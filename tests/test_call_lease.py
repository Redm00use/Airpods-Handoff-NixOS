"""Call lifetime, independent loss episodes and sustained transport evidence."""
import unittest,asyncio
from unittest.mock import AsyncMock
from airpods_handoff_policy import Policy
from airpods_handoff import Adapter

class PersistentCall(unittest.TestCase):
    def local(self):
        p=Policy(connected=True,ready=True,healthy=True,call_healthy=True,owner='linux',source='linux',source_kind='media',remote='idle',generation=1)
        p.calls(True,now=0);p.decide(0)
        return p
    def route(self,p,t,owner='remote',source='remote',kind='media',remote='active',generation=1):
        p.route(t,dict(connected=True,ready=True,owner=owner,source=source,source_kind=kind,remote_activity=remote),generation)
    def restored(self,p,t):
        self.route(p,t,'linux','linux','media','idle',p.generation)
        p.observe_call_audio(t,True);self.assertFalse(p.call_lease.audio_confirmed)
        p.observe_call_audio(t+1.01,True);p.decide(t+1.01)
        self.assertTrue(p.call_lease.audio_confirmed)
    def test_twelve_separate_media_interruptions_do_not_exhaust_call_lifetime(self):
        p=self.local()
        for i in range(12):
            t=10*i+1;self.route(p,t);p.decide(t)
            self.assertEqual(p.decide(t+.31),'recover-call')
            p.result(t+.4,'recover-call',True,p.inflight_token)
            self.restored(p,t+1)
            self.assertEqual(p.call_lease.attempts,0)
        self.assertEqual(p.call_recoveries,12)
    def test_owner_ack_without_audio_does_not_renew_budget(self):
        p=self.local()
        for i in range(3):
            t=10*i+1;self.route(p,t);p.decide(t);p.decide(t+.31)
            p.result(t+.4,'recover-call',True,p.inflight_token)
            self.route(p,t+.5,'linux','none','idle','idle')
            p.observe_call_audio(t+2,False)
        self.route(p,40);self.assertIsNone(p.decide(40));self.assertEqual(p.state,'CALL_CONTESTED')
        self.assertEqual(p.call_lease.attempts,3)
    def test_short_audio_blips_do_not_reset_an_unrecovered_episode(self):
        p=self.local();p.call_lease.attempts=3
        p.observe_call_audio(1,True);self.assertEqual(p.deadline(1),2)
        p.observe_call_audio(1.2,False);p.observe_call_audio(2,True)
        p.observe_call_audio(2.9,True);self.assertEqual(p.call_lease.attempts,3)
        p.observe_call_audio(3,True);self.assertEqual(p.call_lease.attempts,0)
        self.assertIsNone(p.call_lease.deadline(3))
    def test_reconnect_or_repeated_remote_events_cannot_rearm_without_audio(self):
        p=self.local();p.call_lease.attempts=3
        for generation in range(2,20):
            self.route(p,generation,generation=generation)
            p.observe_call_audio(generation,False);self.assertIsNone(p.decide(generation))
        self.assertEqual(p.call_lease.attempts,3)
    def test_manual_selection_wins_after_many_successful_recoveries(self):
        p=self.local();p.call_recoveries=100;p.manual_peer_request(1)
        self.route(p,2)
        for now in (2,10,1000):
            p.observe_call_audio(now,True);self.assertIsNone(p.decide(now))
            self.assertEqual(p.state,'REMOTE_MANUAL');self.assertFalse(p.call_lease.audio_confirmed)
    def test_stale_audio_confirmation_is_ignored(self):
        p=self.local();old=p.context();p.invalidate();p.call_lease.attempts=3
        p.observe_call_audio(1,True,old);p.observe_call_audio(5,True,old)
        self.assertEqual(p.call_lease.attempts,3);self.assertIsNone(p.call_lease.stable_since)
    def test_reservation_throttles_even_when_route_change_invalidates_ack(self):
        p=self.local();self.route(p,1);p.decide(1);p.decide(1.31)
        old=p.inflight_token;self.route(p,1.4,generation=2)
        self.assertFalse(p.result(1.5,'recover-call',True,old))
        for now in (1.5,2,4):self.assertIsNone(p.decide(now))
        self.assertEqual(p.decide(4.32),'recover-call')
    def test_phone_call_and_unknown_do_not_spend_recovery_budget(self):
        p=self.local()
        for kind in ('call','unknown'):
            self.route(p,1,kind=kind)
            for now in (1,2,100):self.assertIsNone(p.decide(now))
        self.assertEqual(p.call_lease.attempts,0)
    def test_hangup_and_sleep_destroy_lease_and_audio_evidence(self):
        for sleep in (False,True):
            p=self.local();p.call_lease.attempts=2;p.observe_call_audio(1,True)
            if sleep:p.sleep(2,True)
            else:p.calls(False)
            self.assertEqual(p.call_lease.attempts,0);self.assertIsNone(p.call_lease.stable_since)
            self.assertFalse(p.call_proven)

class FailedTransport(unittest.TestCase):
    def test_owned_but_failed_audio_enters_bounded_recovery(self):
        p=PersistentCall().local();p.source='none';p.source_kind='idle'
        p.call_lease.transport_failed=True
        p.decide(1);self.assertEqual(p.decide(1.31),'recover-call')
        self.assertEqual(p.call_lease.attempts,1)
        token=p.inflight_token;p.result(1.4,'recover-call',True,token)
        self.assertFalse(p.call_lease.audio_confirmed)
        self.assertEqual(p.call_lease.attempts,1)
        p.call_lease.transport_failed=True;p.call_lease.attempts=3
        self.assertIsNone(p.decide(10));self.assertEqual(p.state,'CALL_CONTESTED')

    def test_local_source_hint_does_not_push_the_failure_deadline_forever(self):
        p=PersistentCall().local();p.call_lease.transport_failed=True
        p.decide(1);self.assertEqual(p.decide(1.31),'recover-call')

    def test_exhausted_transport_episode_cannot_mutate_audio_until_explicit_return(self):
        a=Adapter(False);p=PersistentCall().local();a.policy=p
        p.call_lease.attempts=3;p.call_lease.transport_failed=True
        self.assertFalse(a.audio_eligible(p.context()))
        p.manual_request(10);self.assertTrue(a.audio_eligible(p.context()))

    def test_real_audio_clears_failed_transport_without_immediate_budget_rearm(self):
        p=PersistentCall().local();p.call_lease.transport_failed=True;p.call_lease.attempts=2
        p.observe_call_audio(1,True)
        self.assertFalse(p.call_lease.transport_failed);self.assertEqual(p.call_lease.attempts,2)
        p.observe_call_audio(2,True);self.assertEqual(p.call_lease.attempts,0)

class QueuedCall(unittest.IsolatedAsyncioTestCase):
    async def test_actual_phone_call_arriving_in_ipc_queue_stops_mutation(self):
        p=PersistentCall().local();a=Adapter(False);a.policy=p;a.evaluate=lambda _:None
        PersistentCall().route(p,1);p.decide(1);p.decide(1.31)
        a._cli=AsyncMock();await a.ipc_lock.acquire()
        task=asyncio.create_task(a.command('recover-call',p.inflight_token));await asyncio.sleep(0)
        p.remote_call=True;p.source_kind='call';a.ipc_lock.release();await task
        a._cli.assert_not_awaited()


class DurableCallIntent(unittest.TestCase):
    def test_explicit_call_waits_for_cold_connection_then_uses_fresh_command(self):
        p=Policy();p.calls(True,now=0)
        self.assertIsNone(p.decide(20));self.assertTrue(p.call_intent)
        p.route(21,dict(connected=True,ready=True,owner='remote',source='none',source_kind='idle',remote_activity='idle'),7)
        p.healthy=True;p.decide(21)
        self.assertEqual(p.decide(21.7),'take')
    def test_baseline_call_and_manual_phone_choice_do_not_gain_durable_intent(self):
        p=Policy();p.calls(True)
        self.assertFalse(p.call_intent)
        p=Policy();p.calls(True,now=0);p.manual_peer_request(1)
        self.assertFalse(p.call_intent)
        p.route(21,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),7)
        p.healthy=True
        for now in (21,30,100):self.assertIsNone(p.decide(now))
    def test_call_ending_before_connection_never_replays_old_intent(self):
        p=Policy();p.calls(True,now=0);p.calls(False)
        p.route(21,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),7)
        p.healthy=True
        for now in (21,30,100):self.assertIsNone(p.decide(now))
        self.assertFalse(p.call_intent)
