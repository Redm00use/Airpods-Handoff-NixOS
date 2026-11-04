import asyncio,unittest
from unittest.mock import AsyncMock
from airpods_handoff import Adapter
from airpods_handoff_policy import Policy

class ManualRoute(unittest.TestCase):
 def local(self):
  p=Policy(connected=True,ready=True,healthy=True,owner='linux',source='linux',source_kind='media',remote='idle',generation=1)
  p.calls(True,0);p.decide(0);return p
 def remote(self,p,t=1,generation=1,kind='media'):
  p.route(t,dict(connected=True,ready=True,owner='remote',source='remote',source_kind=kind,remote_activity='idle' if kind=='idle' else 'active'),generation)
 def test_manual_phone_choice_yields_ongoing_call_once_and_does_not_reclaim(self):
  p=self.local();p.manual_peer_request(1)
  self.assertFalse(p.protected());self.assertEqual(p.decide(1),'release')
  token=p.inflight_token;self.assertTrue(p.result(1.1,'release',True,token));self.remote(p,1.2)
  for t in (2,5,50,500):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'REMOTE_MANUAL')
  self.assertTrue(p.local_call);self.assertTrue(p.call_proven);self.assertEqual(p.call_recoveries,0)
 def test_manual_choice_invalidates_queued_call_recovery(self):
  p=self.local();self.remote(p,1);p.decide(1);self.assertEqual(p.decide(1.31),'recover-call');token=p.inflight_token
  p.manual_peer_request(1.4);self.assertFalse(p.valid(token));self.assertIsNone(p.decide(10))
 def test_manual_choice_survives_control_reconnect_during_same_call(self):
  p=self.local();p.manual_peer_request(1);p.route(2,{'connected':False},2);self.remote(p,3,3)
  self.assertIsNone(p.decide(10));self.assertEqual(p.state,'REMOTE_MANUAL')
 def test_explicit_pc_return_clears_phone_override(self):
  p=self.local();p.manual_peer_request(1);self.remote(p,2);p.manual_request(3)
  self.assertFalse(p.manual_remote);p.decide(3);self.assertEqual(p.decide(3.31),'recover-call')
 def test_new_local_play_clears_override_but_existing_play_does_not(self):
  p=self.local();p.players={'music':True};p.streams={'music'};p.manual_peer_request(1);self.remote(p,2)
  p.player(3,'music',True);self.assertTrue(p.manual_remote)
  p.player(4,'music',False);p.player(5,'music',True);self.assertFalse(p.manual_remote)
 def test_new_call_clears_override_but_resume_baseline_does_not(self):
  p=self.local();p.manual_peer_request(1);p.calls(False);p.calls(True,None);self.assertTrue(p.manual_remote)
  p.calls(False);p.calls(True,5);self.assertFalse(p.manual_remote)
 def test_both_idle_after_hangup_restore_pc_preference(self):
  p=self.local();p.manual_peer_request(1);self.remote(p,2);p.calls(False);self.remote(p,20,kind='idle')
  self.assertIsNone(p.decide(20));self.assertFalse(p.manual_remote);self.assertEqual(p.decide(21),'take-idle')
 def test_automatic_peer_request_does_not_cancel_call_protection(self):
  p=self.local();p.peer_request(1);self.assertTrue(p.protected());self.assertFalse(p.manual_remote)
  self.remote(p,2);p.decide(2);self.assertEqual(p.decide(2.31),'recover-call')

class ManualAdapter(unittest.IsolatedAsyncioTestCase):
 async def test_call_report_withdrawn_and_stale_recovery_rejected_after_manual_choice(self):
  a=Adapter(False);p=a.policy;p.connected=p.ready=p.healthy=True;p.owner=p.source='linux';p.remote='idle';p.source_kind='media';p.generation=1;p.calls(True,0)
  a._cli=AsyncMock(return_value=(True,''));a.sync_call_report();await a.call_report_task
  p.manual_peer_request(1);a.sync_call_report();await a.call_report_task
  self.assertEqual([c.args[-1] for c in a._cli.await_args_list],['call-start','call-end'])
  self.assertFalse(a.call_report_sent)
  token=p.request('recover-call');self.assertFalse(a.command_eligible('recover-call',p.inflight_token))


class IdleAfterManual(unittest.TestCase):
 def test_finished_call_idle_default_does_not_replay_old_phone_release(self):
  p=Policy(connected=True,ready=True,healthy=True,owner='remote',source='none',
           source_kind='idle',remote='idle',generation=1,manual_remote=True,
           peer_requested=True)
  p.decide(0)
  self.assertEqual(p.decide(1),'take-idle')
  p.result(1.1,'take-idle',True,p.inflight_token)
  self.assertIsNone(p.decide(1.2))
  self.assertFalse(p.peer_requested)
  self.assertEqual(p.owner,'linux')

 def test_idle_transition_cancels_queued_old_manual_release(self):
  p=Policy(connected=True,ready=True,healthy=True,owner='linux',source='none',
           source_kind='idle',remote='idle',generation=1,manual_remote=True,
           peer_requested=True)
  p.request('release');old=p.inflight_token
  p.decide(0)
  self.assertFalse(p.valid(old))
  self.assertFalse(p.result(1,'release',True,old))
  self.assertEqual(p.owner,'linux')
