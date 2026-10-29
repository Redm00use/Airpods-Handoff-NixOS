import os
os.environ['AIRPODS_DEVICE']='AA:BB:CC:DD:EE:FF'
import asyncio, unittest
from unittest.mock import AsyncMock, patch
from airpods_handoff import Adapter

async def timeout_immediately(awaitable,*args,**kwargs):
    if hasattr(awaitable,'close'):awaitable.close()
    raise asyncio.TimeoutError

class AsyncTests(unittest.IsolatedAsyncioTestCase):
    def setup_audio(self):
        a=Adapter(False);p=a.policy;p.connected=p.ready=p.healthy=True;p.owner='linux';p.source='remote';p.generation=1
        p.players={'music':True};p.streams={'music'}
        a.nodes={8:{'type':'PipeWire:Interface:Node','info':{'state':'error','props':{'media.class':'Audio/Sink','node.name':'bluez_output.AA_BB_CC_DD_EE_FF.1'}}}}
        a.snapshot=AsyncMock();a.transport_state=AsyncMock(return_value='idle');a.pulse=AsyncMock(return_value=True)
        return a
    async def test_resume_connected_but_unsynced_still_requests_snapshot(self):
        from dbus_next import Variant
        a=self.setup_audio();a.system=object();a.policy.ready=False;a.policy.generation=None
        a.call=AsyncMock(return_value=[Variant('b',True)])
        async def snapshot():a.policy.ready=True;a.policy.generation=2
        a.snapshot=AsyncMock(side_effect=snapshot)
        await a.recover();a.snapshot.assert_awaited_once()
    async def test_shadow_never_changes_audio(self):
        a=self.setup_audio();a.shadow=True
        await a.ensure_audio(a.policy.context(),0);a.pulse.assert_not_awaited()
    async def test_one_suspend_resume_no_retry_loop(self):
        a=self.setup_audio()
        with patch('airpods_handoff.asyncio.wait_for',timeout_immediately):
            await a.ensure_audio(a.policy.context(),0)
            await a.ensure_audio(a.policy.context(),0)
        self.assertEqual([x.args for x in a.pulse.await_args_list],[('suspend-sink','bluez_output.AA_BB_CC_DD_EE_FF.1','1'),('suspend-sink','bluez_output.AA_BB_CC_DD_EE_FF.1','0')])
    async def test_remote_takeover_always_undoes_our_suspend(self):
        a=self.setup_audio()
        async def pulse(*args):
            if args[-1]=='1':
                a.policy.route(2,dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote',source_kind='call'),1)
            return True
        a.pulse=AsyncMock(side_effect=pulse)
        with patch('airpods_handoff.asyncio.wait_for',timeout_immediately):await a.ensure_audio(a.policy.context(),0)
        self.assertEqual(a.pulse.await_count,2);self.assertEqual(a.policy.owner,'remote');a.snapshot.assert_not_awaited()
    async def test_failed_suspend_still_undoes_possible_lost_ack(self):
        a=self.setup_audio();a.pulse=AsyncMock(side_effect=[False,True])
        with patch('airpods_handoff.asyncio.wait_for',timeout_immediately):await a.ensure_audio(a.policy.context(),0)
        self.assertEqual(a.pulse.await_count,2)
        self.assertEqual(a.pulse.await_args_list[-1].args[-1],'0')
    async def test_command_with_stale_token_sends_nothing(self):
        a=self.setup_audio();a.policy.owner='remote';a.policy.player(1,'new',True);a.policy.streams.add('new');a.policy.remote='idle'
        a.policy.decide(1);action=a.policy.decide(1.7);token=a.policy.inflight_token
        a.policy.invalidate();a._cli=AsyncMock()
        await a.command(action,token);a._cli.assert_not_awaited()
    async def test_late_ack_after_remote_call_cannot_retake(self):
        a=self.setup_audio();p=a.policy;p.owner='remote';p.remote='idle';p.player(1,'new',True);p.streams.add('new');p.decide(1);p.decide(1.7);token=p.inflight_token
        async def cli(*args):
            if args[-1] in ('take','take-media'):p.route(2,dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote',source_kind='call'),1)
            return True,'multipoint ready\nowner linux\nremote-activity idle'
        a._cli=AsyncMock(side_effect=cli);a.evaluate=lambda _:None
        await a.command('take',token);self.assertEqual(p.owner,'remote');self.assertFalse(p.leased)


class RemotePauseSequence(unittest.IsolatedAsyncioTestCase):
    async def test_ownership_idle_then_remote_media_pauses_owned_player(self):
        a=Adapter(False);a.session=object();a.pw_ready=a.mpris_ready=True;a.pause_armed=True
        a.policy.generation=1;a.policy.owner='linux';a.policy.players={'cider':True};a.policy.streams={'cider'};a.identities={'cider':(10,'cider')}
        a.call=AsyncMock(return_value=[])
        a.observe_route(dict(connected=True,ready=True,owner='remote',remote_activity='idle',source='linux',source_kind='media'),1)
        a.call.assert_not_awaited()
        a.observe_route(dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote',source_kind='media'),1)
        await asyncio.gather(*list(a.tasks))
        self.assertEqual(a.call.await_count,1);self.assertEqual(a.call.await_args.args[4],'Pause')
        a.observe_route(dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote',source_kind='media'),1)
        self.assertFalse(a.tasks)
    async def test_remote_baseline_never_pauses_unowned_player(self):
        a=Adapter(False);a.pw_ready=a.mpris_ready=True;a.call=AsyncMock()
        a.observe_route(dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote',source_kind='media'),1)
        a.call.assert_not_awaited();self.assertFalse(a.tasks)
