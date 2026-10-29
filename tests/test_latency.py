import os
os.environ.setdefault('AIRPODS_DEVICE','AA:BB:CC:DD:EE:FF')
import asyncio,time,unittest
from unittest.mock import AsyncMock,patch
from airpods_handoff import Adapter

class Latency(unittest.IsolatedAsyncioTestCase):
    def adapter(self):
        a=Adapter(False);p=a.policy;p.connected=p.ready=p.healthy=True;p.owner='linux';p.source='none';p.generation=1
        p.players={'music':True};p.streams={'music'};a.transport='idle'
        a.nodes={8:{'type':'PipeWire:Interface:Node','info':{'state':'error','props':{'media.class':'Audio/Sink','node.name':'bluez_output.AA_BB_CC_DD_EE_FF.1'}}}}
        a.snapshot=AsyncMock();a.transport_state=AsyncMock()
        return a
    def ready(self,a):
        a.policy.source='linux';a.transport='active';a.nodes[8]['info']['state']='running';a.graph_changed.set()
    def edges(self,a):
        a.nodes[9]={'type':'PipeWire:Interface:Node','info':{'state':'running','props':{'application.id':'com.github.wwmm.easyeffects'}}}
        a.nodes[10]={'type':'PipeWire:Interface:Link','info':{'state':'init','input-node-id':8,'output-node-id':9,'output-port-id':20,'input-port-id':21,'props':{'object.serial':100}}}
    def repair(self,a):
        async def command(*args):
            if args[0]!='-d':
                a.nodes[10]['info']['state']='active';self.ready(a)
            return True
        a.link_command=AsyncMock(side_effect=command)
    async def test_known_error_skips_blind_grace_and_status_roundtrips(self):
        a=self.adapter();trace=[]
        original=a.wait_audio
        async def wait(predicate,timeout):
            trace.append(('wait',bool(predicate())))
            return await original(predicate,timeout)
        a.wait_audio=wait
        async def pulse(*args):
            trace.append(('pulse',args[-1]))
            if args[-1]=='0':self.ready(a)
            return True
        a.pulse=AsyncMock(side_effect=pulse)
        await asyncio.wait_for(a.ensure_audio(a.policy.context(),time.monotonic()),.4)
        self.assertEqual(trace[0],('wait',True));self.assertEqual(a.pulse.await_count,2)
        a.snapshot.assert_not_awaited();a.transport_state.assert_not_awaited()
    async def test_error_event_during_grace_starts_repair_immediately(self):
        a=self.adapter();a.nodes[8]['info']['state']='suspended'
        def error():a.nodes[8]['info']['state']='error';a.graph_changed.set()
        asyncio.get_running_loop().call_soon(error)
        async def pulse(*args):
            if args[-1]=='0':self.ready(a)
            return True
        a.pulse=AsyncMock(side_effect=pulse)
        await asyncio.wait_for(a.ensure_audio(a.policy.context(),time.monotonic()),.4)
        self.assertEqual(a.pulse.await_count,2)
    async def test_late_init_edges_repaired_in_same_recovery_attempt(self):
        a=self.adapter();self.repair(a)
        def graph():
            self.edges(a);self.ready(a)
        async def pulse(*args):
            if args[-1]=='0':asyncio.get_running_loop().call_soon(graph)
            return True
        a.pulse=AsyncMock(side_effect=pulse)
        await asyncio.wait_for(a.ensure_audio(a.policy.context(),time.monotonic()),.4)
        self.assertEqual(a.link_command.await_count,2);self.assertTrue(a.audio_active())
        a.snapshot.assert_not_awaited()
    async def test_graph_only_repair_does_not_reset_transport(self):
        a=self.adapter();a.policy.source='linux';a.nodes[8]['info']['state']='suspended';self.edges(a);self.repair(a)
        a.pulse=AsyncMock()
        await asyncio.wait_for(a.ensure_audio(a.policy.context(),time.monotonic()),.4)
        self.assertTrue(a.audio_active());a.pulse.assert_not_awaited();a.transport_state.assert_not_awaited()
    async def test_natural_success_does_not_read_status_or_repair(self):
        a=self.adapter();a.nodes[8]['info']['state']='running';a.pulse=AsyncMock()
        asyncio.get_running_loop().call_soon(self.ready,a)
        await asyncio.wait_for(a.ensure_audio(a.policy.context(),time.monotonic()),.4)
        self.assertTrue(a.audio_active());a.pulse.assert_not_awaited();a.transport_state.assert_not_awaited()
    async def test_context_change_aborts_wait_without_touching_audio(self):
        a=self.adapter();a.nodes[8]['info']['state']='running';a.pulse=AsyncMock();context=a.policy.context()
        def cancel():a.policy.invalidate();a.graph_changed.set()
        asyncio.get_running_loop().call_soon(cancel)
        await asyncio.wait_for(a.ensure_audio(context,time.monotonic()),.4)
        a.pulse.assert_not_awaited()
    async def test_exhausted_link_budget_does_not_busy_loop(self):
        a=self.adapter();a.policy.source='linux';self.edges(a);a.relinked={(x,x) for x in range(128)}
        self.assertFalse(a.pending_audio_links())
        self.assertFalse(await a.wait_audio_flow(a.policy.context(),.01))
    async def test_local_play_ready_does_not_sleep(self):
        a=self.adapter();a.ensure_audio=AsyncMock()
        with patch('airpods_handoff.asyncio.sleep',side_effect=AssertionError('fixed sleep')):
            await a.verify_local_play(a.policy.context())
        a.ensure_audio.assert_awaited_once()

class RestoreIntentLatency(unittest.TestCase):
    def local(self):
        from airpods_handoff_policy import Policy
        p=Policy(connected=True,ready=True,healthy=True,owner='linux',source='linux',remote='idle',generation=1)
        p.players={'music':True};p.streams={'music'};p.decide(0);return p
    def test_proven_session_restores_on_media_event_without_extra_deadline(self):
        p=self.local();e=dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active')
        p.route(1,e,1);self.assertEqual(p.decide(1),'restore')
        for t in (1,1.01,1.1):p.route(t,e,1);self.assertIsNone(p.decide(t))
    def test_unknown_then_media_waits_for_evidence_without_spending_budget(self):
        p=self.local();e=dict(connected=True,ready=True,owner='remote',source='remote',source_kind='unknown',remote_activity='active')
        p.route(1,e,1);self.assertIsNone(p.decide(1));self.assertFalse(p.restore_attempted)
        e['source_kind']='media';p.route(2,e,1);self.assertEqual(p.decide(2),'restore')
