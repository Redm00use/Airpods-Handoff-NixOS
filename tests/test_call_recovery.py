import asyncio
import unittest
from unittest.mock import AsyncMock
from airpods_call_detection import CallTracker,call_sessions
from airpods_handoff_policy import Policy
from airpods_handoff import Adapter


def node(cls,app='zen',pid=123,state='running',**props):
    return {'type':'PipeWire:Interface:Node','info':{'state':state,'props':{
        'media.class':cls,'application.process.id':pid,'application.process.binary':app,
        'application.name':app,'node.name':app+'.audio',**props}}}


class Detection(unittest.TestCase):
    def pair(self,app='zen',state='running'):
        return {1:node('Stream/Input/Audio',app,state=state),2:node('Stream/Output/Audio',app,state=state)}
    def test_unmarked_browser_duplex_is_call(self):
        for app in ('zen-beta','firefox','chromium','brave','vivaldi','google-chrome'):
            t=CallTracker();t.observe(0,self.pair(app));self.assertTrue(t.observe(.21,self.pair(app)),app)
    def test_browser_capture_only_or_unrelated_pids_not_call(self):
        self.assertFalse(call_sessions({1:node('Stream/Input/Audio')}))
        self.assertFalse(call_sessions({1:node('Stream/Input/Audio'),2:node('Stream/Output/Audio',pid=456)}))
    def test_unrelated_name_containing_zen_is_not_browser(self):
        self.assertFalse(call_sessions(self.pair('frozen-player')))
    def test_unknown_application_requires_explicit_role(self):
        self.assertFalse(call_sessions(self.pair('unknown-app')))
        self.assertTrue(call_sessions({1:node('Stream/Input/Audio','unknown-app',**{'media.role':'Communication'})}))
    def test_browser_silence_and_mute_hold_then_removed_streams_release(self):
        t=CallTracker();t.observe(0,self.pair());self.assertTrue(t.observe(.21,self.pair()))
        pair=self.pair(state='idle');pair[1]['info']['params']={'Props':[{'mute':True}]}
        self.assertTrue(t.observe(5,pair));self.assertTrue(t.observe(6,{}));self.assertFalse(t.tick(7.26))
    def test_notification_and_monitor_are_not_browser_call(self):
        pair=self.pair();pair[2]['info']['props']['media.role']='Notification';self.assertFalse(call_sessions(pair))
        pair=self.pair();pair[1]['info']['props']['stream.capture.sink']=True;self.assertFalse(call_sessions(pair))
    def test_matching_client_process_identity_is_used(self):
        pair=self.pair()
        for item in pair.values():
            item['info']['props']={'media.class':item['info']['props']['media.class'],'client.id':9}
        pair[9]={'type':'PipeWire:Interface:Client','info':{'props':{'application.process.id':123,'application.process.binary':'zen'}}}
        self.assertTrue(call_sessions(pair))


class Recovery(unittest.TestCase):
    def local(self):
        p=Policy(connected=True,ready=True,healthy=True,owner='linux',source='linux',source_kind='media',remote='idle',generation=1)
        p.calls(True,now=0);p.decide(0);self.assertTrue(p.call_proven)
        return p
    def route(self,p,t,kind='media',generation=1):
        p.route(t,dict(connected=True,ready=True,owner='remote',source='remote' if kind!='idle' else 'none',source_kind=kind,remote_activity='idle' if kind=='idle' else 'active'),generation)
    def test_existing_call_recovers_after_aacp_reconnect(self):
        p=self.local();p.route(1,{'connected':False},2);self.route(p,2,'idle',3)
        self.assertIsNone(p.decide(2));self.assertEqual(p.decide(2.31),'recover-call')
    def test_unrelated_mpris_failure_does_not_block_call_recovery(self):
        p=self.local();p.healthy=False;p.call_healthy=True;self.route(p,1,'idle',2)
        p.decide(1);self.assertEqual(p.decide(1.31),'recover-call')
    def test_pipewire_loss_blocks_call_recovery(self):
        p=self.local();p.healthy=False;p.call_healthy=False;self.route(p,1,'idle',2)
        for t in (1,10,100):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'DEGRADED')
    def test_media_does_not_bypass_unhealthy_mpris(self):
        p=self.local();p.calls(False);p.healthy=False;p.call_healthy=True;p.players={'music':True};p.streams={'music'}
        self.route(p,1,'idle',2)
        for t in (1,10,100):self.assertIsNone(p.decide(t))
    def test_phone_call_blocks_recovery_but_continuing_pc_call_can_return_after_idle(self):
        p=self.local();self.route(p,1,'call')
        for t in (1,1.31,10):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'REMOTE_CALL')
        self.route(p,11,'idle');p.decide(11)
        self.assertEqual(p.decide(11.31),'recover-call')
    def test_fresh_or_baseline_pc_call_does_not_steal_existing_phone_call(self):
        for now in (None,0):
            p=Policy(connected=True,ready=True,healthy=True,owner='remote',source='remote',source_kind='call',remote='active')
            p.remote_call=True;p.calls(True,now=now)
            for t in (0,1,10):self.assertIsNone(p.decide(t));self.assertFalse(p.call_proven)
    def test_unknown_source_waits_for_typed_event_without_spending_budget(self):
        p=self.local();self.route(p,1,'unknown')
        for t in (1,10,100):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'CALL_SOURCE_UNKNOWN')
        self.assertEqual(p.call_recoveries,0);self.route(p,101,'media');p.decide(101)
        self.assertEqual(p.decide(101.31),'recover-call')
    def test_three_attempt_limit_survives_connection_generations(self):
        p=self.local()
        for i in range(3):
            t=10*i+1;self.route(p,t,'media',i+2);p.decide(t)
            self.assertEqual(p.decide(t+.31),'recover-call');token=p.inflight_token
            p.result(t+.4,'recover-call',False,token)
        self.route(p,40,'media',10)
        for t in (40,41,100):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'CALL_CONTESTED')
        self.assertEqual(p.call_recoveries,3)
    def test_cooldown_prevents_repeat_after_failed_recovery(self):
        p=self.local();self.route(p,1);p.decide(1);p.decide(1.31);p.result(1.4,'recover-call',False)
        p.decide(1.5);self.assertIsNone(p.decide(3));self.assertEqual(p.decide(4.41),'recover-call')
    def test_call_ack_does_not_start_legacy_media_restore(self):
        p=self.local();self.route(p,1,'media');p.decide(1);p.decide(1.31)
        p.owner='linux';p.remote='idle' # ACK, source notification not yet arrived.
        p.result(1.4,'recover-call',True,p.inflight_token)
        for t in (1.4,1.5,2):self.assertIsNone(p.decide(t))
        self.assertFalse(p.restore_attempted)
    def test_hangup_cancels_pending_recovery_and_old_ack(self):
        p=self.local();self.route(p,1,'media');p.decide(1);p.decide(1.31);token=p.inflight_token
        p.calls(False);self.assertFalse(p.valid(token));self.assertFalse(p.result(2,'recover-call',True,token))
        self.assertFalse(p.call_proven);self.assertEqual(p.call_recoveries,0)
    def test_sleep_clears_proven_call_before_fresh_baseline(self):
        p=self.local();p.sleep(1,True);self.assertFalse(p.call_proven);self.assertFalse(p.local_call)
        p.sleep(2,False);self.route(p,3,'call',2);p.calls(True)
        for t in (3,10,100):self.assertIsNone(p.decide(t))
    def test_new_call_resets_budget_only_after_real_end(self):
        p=self.local();p.call_recoveries=3;p.calls(True,now=5);self.assertEqual(p.call_recoveries,3)
        p.calls(False);p.calls(True,now=10);self.assertEqual(p.call_recoveries,0)
    def test_generation_change_fences_old_command(self):
        p=self.local();self.route(p,1);p.decide(1);p.decide(1.31);old=p.inflight_token
        self.route(p,2,'idle',2);self.assertFalse(p.valid(old));self.assertFalse(p.result(3,'recover-call',True,old))
    def test_proven_call_lease_not_given_to_unrelated_media(self):
        p=self.local();p.calls(False);p.players={'music':True};p.streams={'music'};self.route(p,1,'call')
        for t in (1,5,100):self.assertIsNone(p.decide(t));self.assertFalse(p.call_proven)


class Dispatch(unittest.IsolatedAsyncioTestCase):
    def adapter(self):
        a=Adapter(False);p=a.policy
        p.connected=p.ready=p.healthy=True;p.owner=p.source='linux';p.remote='idle';p.source_kind='media';p.generation=1
        p.calls(True,now=0);p.decide(0)
        p.route(1,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),1)
        p.decide(1);p.decide(1.31);a.evaluate=lambda _:None;a._cli=AsyncMock(return_value=(True,'owner linux'));a.ensure_audio=AsyncMock()
        return a
    async def test_queued_call_recovery_uses_pipewire_health_not_mpris(self):
        a=self.adapter();a.policy.healthy=False;a.policy.call_healthy=True
        await a.command('recover-call',a.policy.inflight_token)
        a._cli.assert_awaited_once_with('switching','take-call')
        for task in tuple(a.tasks):await task
    async def test_recovery_uses_typed_command_not_force(self):
        a=self.adapter();await a.command('recover-call',a.policy.inflight_token)
        a._cli.assert_awaited_once_with('switching','take-call')
        for task in tuple(a.tasks):await task
    async def test_hangup_while_waiting_for_ipc_never_sends_take(self):
        a=self.adapter();token=a.policy.inflight_token;await a.ipc_lock.acquire()
        task=asyncio.create_task(a.command('recover-call',token));await asyncio.sleep(0)
        a.policy.calls(False);a.ipc_lock.release();await task;a._cli.assert_not_awaited()
    async def test_unknown_source_arriving_in_ipc_queue_is_rejected(self):
        a=self.adapter();token=a.policy.inflight_token;await a.ipc_lock.acquire()
        task=asyncio.create_task(a.command('recover-call',token));await asyncio.sleep(0)
        a.policy.source_kind='unknown';a.ipc_lock.release();await task;a._cli.assert_not_awaited()
    async def test_confirmed_ownership_can_start_a2dp_before_source_event(self):
        a=self.adapter();p=a.policy;p.owner='linux';p.remote='idle'
        self.assertTrue(a.audio_eligible(p.context()));self.assertTrue(a.connection.snapshot()['can_connect'])
