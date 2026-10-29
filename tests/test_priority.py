import os
os.environ.setdefault('AIRPODS_DEVICE','AA:BB:CC:DD:EE:FF')
import asyncio
import unittest
from unittest.mock import AsyncMock
from airpods_call_detection import CallTracker,call_sessions
from airpods_handoff import Adapter
from airpods_handoff_policy import Policy

def node(cls,pid=10,state='running',binary='DiscordCanary',**props):
    return {'type':'PipeWire:Interface:Node','info':{'state':state,'props':{'media.class':cls,'application.process.binary':binary,'application.process.id':pid,**props}}}

class Calls(unittest.TestCase):
    def pair(self,state='running'):
        return {1:node('Stream/Input/Audio',state=state),2:node('Stream/Output/Audio',state=state)}
    def test_discord_without_role_and_muted_silence(self):
        t=CallTracker();self.assertFalse(t.observe(0,self.pair()));self.assertTrue(t.tick(.21))
        self.assertTrue(t.observe(10,self.pair('idle')))
        self.assertTrue(t.observe(20,{}));self.assertFalse(t.tick(21.26))
    def test_only_capture_or_different_processes_not_call(self):
        self.assertFalse(call_sessions({1:node('Stream/Input/Audio')}))
        self.assertFalse(call_sessions({1:node('Stream/Input/Audio'),2:node('Stream/Output/Audio',pid=11)}))
    def test_monitor_and_notification_excluded(self):
        x=self.pair();x[1]['info']['props']['stream.capture.sink']=True
        self.assertFalse(call_sessions(x))
        x=self.pair();x[2]['info']['props']['media.role']='Notification'
        self.assertFalse(call_sessions(x))
    def test_client_identity_and_telegram(self):
        x={1:node('Stream/Input/Audio',binary=''),2:node('Stream/Output/Audio',binary=''),3:{'type':'PipeWire:Interface:Client','info':{'props':{'application.process.binary':'telegram-desktop','application.process.id':10}}}}
        for k in (1,2):x[k]['info']['props']={'media.class':x[k]['info']['props']['media.class'],'client.id':3}
        self.assertTrue(call_sessions(x))
    def test_short_graph_gap_does_not_end_call(self):
        t=CallTracker();t.observe(0,self.pair());t.tick(.21);t.observe(1,{})
        self.assertTrue(t.observe(2,self.pair()));self.assertTrue(t.tick(5))

class Priority(unittest.TestCase):
    def ready(self):return Policy(connected=True,ready=True,healthy=True,owner='linux',generation=1)
    def test_call_defers_peer_until_hangup(self):
        p=self.ready();p.calls(True);p.peer_request(1)
        for t in (1,5,100):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'LOCAL_CALL_PROTECTED')
        p.calls(False);self.assertEqual(p.decide(101),'release')
    def test_notification_does_not_protect(self):
        p=self.ready();p.peer_request(1);self.assertEqual(p.decide(1),'release')
    def test_no_ownership_fabrication_after_remote_takeover(self):
        p=self.ready();p.calls(True);p.route(2,dict(connected=True,ready=True,owner='remote',source='remote',remote_activity='active'),1)
        self.assertIsNone(p.decide(3));self.assertEqual(p.owner,'remote');self.assertEqual(p.source,'remote')

class Dispatch(unittest.IsolatedAsyncioTestCase):
    async def test_queued_release_cannot_bypass_new_call(self):
        a=Adapter(False);a.policy=Policy(connected=True,ready=True,healthy=True,owner='linux',generation=1)
        a.policy.peer_request(0);a.policy.decide(0);token=a.policy.inflight_token
        a.policy.calls(True);a._cli=AsyncMock();a.evaluate=lambda _:None
        await a.command('release',token);a._cli.assert_not_awaited()
    async def test_live_detector_debounces_and_logs_state(self):
        a=Adapter(True);a.nodes={1:node('Stream/Input/Audio'),2:node('Stream/Output/Audio')}
        a.correlate();self.assertFalse(a.policy.local_call)
        a.call_tracker.onset-=1;a.correlate();self.assertTrue(a.policy.local_call)
        if a.call_timer:a.call_timer.cancel()

class LockRace(unittest.IsolatedAsyncioTestCase):
    async def test_stream_appears_while_release_waits_for_ipc(self):
        a=Adapter(False);p=a.policy
        p.connected=p.ready=p.healthy=True;p.owner='linux';p.generation=1
        p.peer_request(0);p.decide(0);token=p.inflight_token
        a._cli=AsyncMock();a.evaluate=lambda _:None
        await a.ipc_lock.acquire()
        task=asyncio.create_task(a.command('release',token))
        await asyncio.sleep(0)
        p.players['browser']=True;p.streams={'browser'}
        a.ipc_lock.release();await task
        a._cli.assert_not_awaited()

class BoundedRestore(unittest.TestCase):
    def local(self):
        p=Policy(connected=True,ready=True,healthy=True,owner='linux',source='linux',generation=1)
        p.players={'music':True};p.streams={'music'};p.decide(0)
        return p
    def steal(self,p,t=1):
        p.route(t,dict(connected=True,ready=True,owner='remote',source='remote',remote_activity='active',source_kind='media'),1)
    def test_restore_once_then_contested_without_loop(self):
        p=self.local();self.steal(p);self.assertEqual(p.decide(1),'restore');token=p.inflight_token
        self.assertTrue(p.result(1.4,'restore',True,token))
        p.route(2,dict(connected=True,ready=True,owner='linux',source='linux',remote_activity='idle'),1);p.decide(2)
        self.steal(p,3)
        for t in (3,4,100):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'LOCAL_CONTESTED')
    def test_no_force_for_remote_baseline(self):
        p=self.local();p.local_focus=False;self.steal(p)
        self.assertIsNone(p.decide(1));self.assertIsNone(p.decide(10))
    def test_pause_cancels_pending_restore_ack(self):
        p=self.local();self.steal(p);p.decide(1);p.decide(1.31);token=p.inflight_token
        p.player(1.32,'music',False);self.assertFalse(p.valid(token));self.assertFalse(p.result(2,'restore',True,token))
    def test_remote_call_is_not_forced(self):
        p=self.local();self.steal(p);p.remote_call=True
        for t in (1,2,100):self.assertIsNone(p.decide(t));self.assertFalse(p.restore_attempted)
    def test_disconnect_clears_proven_focus(self):
        p=self.local();p.route(1,{'connected':False},1)
        self.assertFalse(p.local_focus);self.assertIsNone(p.decide(2))
    def test_sleep_clears_focus(self):
        p=self.local();p.sleep(1,True);self.assertFalse(p.local_focus)

class OutputLinkRepair(unittest.IsolatedAsyncioTestCase):
    def setup_graph(self):
        a=Adapter(False);p=a.policy;p.connected=p.ready=p.healthy=True;p.owner=p.source='linux';p.generation=1
        p.players={'cider':True};p.streams={'cider'}
        a.nodes={8:{'type':'PipeWire:Interface:Node','info':{'state':'running','props':{'media.class':'Audio/Sink','node.name':'bluez_output.AA_BB_CC_DD_EE_FF.1'}}},9:{'type':'PipeWire:Interface:Node','info':{'state':'running','props':{'application.id':'com.github.wwmm.easyeffects'}}},10:{'type':'PipeWire:Interface:Link','info':{'state':'paused','input-node-id':8,'output-node-id':9,'output-port-id':20,'input-port-id':21,'props':{'object.serial':100}}}}
        a.link_command=AsyncMock(return_value=True);return a
    async def test_paused_effect_output_repaired_once(self):
        a=self.setup_graph();ctx=a.policy.context()
        await a.repair_output_links(ctx);await a.repair_output_links(ctx)
        self.assertEqual([x.args for x in a.link_command.await_args_list],[('-d',20,21),(20,21)])
        self.assertTrue(a.stalled_output_links()) # Command ACK cannot invent a graph state.
    async def test_active_or_remote_or_shadow_does_not_relink(self):
        for mode in ('active','remote','shadow'):
            a=self.setup_graph()
            if mode=='active':a.nodes[10]['info']['state']='active'
            if mode=='remote':a.policy.source='remote'
            if mode=='shadow':a.shadow=True
            await a.repair_output_links(a.policy.context());a.link_command.assert_not_awaited()
    async def test_microphone_and_other_sinks_untouched(self):
        a=self.setup_graph();a.nodes[10]['info']['input-node-id']=66
        await a.repair_output_links(a.policy.context());a.link_command.assert_not_awaited()
    async def test_ownership_change_still_restores_removed_edge(self):
        a=self.setup_graph()
        async def command(*args):
            if args[0]=='-d':a.policy.owner='remote'
            return True
        a.link_command=AsyncMock(side_effect=command)
        await a.repair_output_links(a.policy.context());self.assertEqual(a.link_command.await_count,2)

class InitLinkRegression(unittest.IsolatedAsyncioTestCase):
    setup_graph=OutputLinkRepair.setup_graph
    async def test_init_link_into_suspended_sink_is_repaired(self):
        a=self.setup_graph();a.nodes[8]['info']['state']='suspended';a.nodes[10]['info']['state']='init'
        await a.repair_output_links(a.policy.context())
        self.assertEqual(a.link_command.await_count,2)
    async def test_init_link_without_running_upstream_is_untouched(self):
        a=self.setup_graph();a.nodes[9]['info']['state']='idle';a.nodes[10]['info']['state']='init'
        await a.repair_output_links(a.policy.context());a.link_command.assert_not_awaited()
