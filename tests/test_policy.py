import unittest
from airpods_handoff_policy import Policy

class Tests(unittest.TestCase):
    def ready(self):
        p=Policy();p.route(0,dict(connected=True,ready=True,owner='remote',remote_activity='idle'),1);p.healthy=True
        return p
    def play(self,p,t=1,key='a'):
        p.player(t,key,True);p.streams.add(key);p.decide(t)
    def test_debounce_and_single_take(self):
        p=self.ready();self.play(p)
        self.assertIsNone(p.decide(1.5));self.assertEqual(p.decide(1.66),'take');self.assertIsNone(p.decide(2))
        p.result(2,'take',True);self.assertIsNone(p.decide(40));self.assertTrue(p.leased)
    def test_already_local_new_media_adopts_without_duplicate_take(self):
        p=self.ready();p.owner='linux';self.play(p)
        self.assertIsNone(p.decide(1.7));self.assertTrue(p.leased)
        p.player(2,'a',False);p.decide(2)
        self.assertEqual(p.decide(6.1),'release')
    def test_short_sound_and_no_stream(self):
        p=self.ready();self.play(p);p.player(1.3,'a',False);self.assertIsNone(p.decide(2))
        p.player(3,'a',True);p.streams.clear();self.assertIsNone(p.decide(5))
    def test_remote_cancels_intent(self):
        p=self.ready();self.play(p)
        p.route(1.2,dict(connected=True,ready=True,owner='remote',remote_activity='active'),1)
        p.route(2,dict(connected=True,ready=True,owner='remote',remote_activity='idle'),1)
        self.assertIsNone(p.decide(2.7));self.assertIsNone(p.intent)
    def test_remote_active_request_expires_without_take(self):
        p=self.ready();p.remote='active';self.play(p)
        self.assertIsNone(p.decide(2));self.assertIsNone(p.decide(7.1));self.assertIsNone(p.intent)
    def test_initial_playing_is_baseline(self):
        p=self.ready();p.player(1,'a',True,True);p.streams={'a'};self.assertIsNone(p.decide(5))
    def test_second_player_edge(self):
        p=self.ready();p.player(0,'a',True,True);self.play(p,1,'b');self.assertEqual(p.decide(1.7),'take')
    def test_release_grace_cancelled_between_tracks(self):
        p=self.ready();p.leased=True;p.owner='linux';p.player(1,'a',False)
        p.decide(2);self.assertIsNone(p.decide(5));self.play(p,5.5);self.assertIsNone(p.decide(8))
    def test_failed_release_never_loops(self):
        p=self.ready();p.leased=True;p.owner='linux';p.decide(1)
        self.assertEqual(p.decide(6),'release');p.result(6,'release',False)
        self.assertIsNone(p.decide(30));self.assertIsNone(p.decide(60))
    def test_disconnect_and_new_generation_cancel(self):
        p=self.ready();self.play(p);p.route(1.3,{'connected':False},2)
        self.assertIsNone(p.decide(5));self.assertIsNone(p.intent)
    def test_monitor_loss_not_idle_release(self):
        p=self.ready();p.leased=True;p.owner='linux';p.healthy=False;p.decide(1)
        self.assertIsNone(p.decide(20));self.assertTrue(p.leased)
    def test_delayed_remote_idle_after_phone_pause(self):
        p=self.ready();p.remote='active';self.play(p)
        p.route(2,dict(connected=True,ready=True,owner='remote',remote_activity='active'),1)
        self.assertIsNotNone(p.intent)  # Repeated status is not a new remote takeover.
        p.route(5,dict(connected=True,ready=True,owner='remote',remote_activity='idle'),1)
        self.assertIsNone(p.decide(5));self.assertEqual(p.decide(5.7),'take')
    def test_expired_intent(self):
        p=self.ready();p.player(1,'a',True);p.decide(1);p.streams={'a'};self.assertIsNone(p.decide(8))
    def test_remote_override_no_pingpong(self):
        p=self.ready();self.play(p);p.decide(1.7);p.result(1.8,'take',True)
        p.route(2,dict(connected=True,ready=True,owner='remote',remote_activity='active'),1)
        p.route(8,dict(connected=True,ready=True,owner='remote',remote_activity='idle'),1)
        self.assertIsNone(p.decide(60));self.assertFalse(p.leased)

class Races(unittest.TestCase):
    ready=Tests.ready
    play=Tests.play
    def pending(self):
        p=self.ready();self.play(p);self.assertEqual(p.decide(1.7),'take');return p,p.inflight_token
    def test_explicit_play_can_take_from_confirmed_remote_media(self):
        p=self.ready();p.remote='active';p.source='remote';p.source_kind='media';self.play(p)
        self.assertEqual(p.decide(1.7),'take')
    def test_remote_media_never_takes_without_a_new_play(self):
        p=self.ready();p.remote='active';p.source='remote';p.source_kind='media'
        p.player(1,'a',True,True);p.streams={'a'};self.assertIsNone(p.decide(5))
    def test_remote_call_never_qualifies_as_remote_media(self):
        p=self.ready();p.route(0,dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote',source_kind='call'),1)
        self.play(p);self.assertIsNone(p.decide(4));self.assertTrue(p.remote_call)
    def test_peer_request_yields_once_while_music_is_playing(self):
        p=self.ready();p.owner='linux';p.leased=True;self.play(p)
        p.peer_request(2);self.assertEqual(p.decide(2),'release');token=p.inflight_token
        p.result(2.1,'release',False,token)
        self.assertIsNone(p.decide(20));self.assertTrue(p.peer_requested)
    def test_new_play_after_peer_yield_is_a_new_intent(self):
        p=self.ready();p.peer_request(1);p.player(2,'a',False);self.play(p,5)
        self.assertFalse(p.peer_requested);self.assertEqual(p.decide(5.7),'take')
    def test_old_take_ack_cannot_clear_new_release_command(self):
        p,old=self.pending();p.owner='linux';p.peer_request(2)
        self.assertEqual(p.decide(2),'release');new=p.inflight_token
        self.assertFalse(p.result(2.1,'take',True,old));self.assertTrue(p.valid(new));self.assertEqual(p.inflight,'release')
    def test_late_ack_after_phone_takeover_is_ignored(self):
        p,token=self.pending()
        p.route(2,dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote',source_kind='media'),1)
        self.assertFalse(p.result(2.1,'take',True,token));self.assertEqual(p.owner,'remote');self.assertFalse(p.leased)
    def test_ack_from_previous_connection_is_ignored(self):
        p,token=self.pending();p.route(2,{'connected':False},2)
        self.assertFalse(p.result(2.1,'take',True,token));self.assertFalse(p.connected)
    def test_incoming_call_cancels_pending_command(self):
        p,token=self.pending()
        p.route(2,dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote',source_kind='call'),1)
        self.assertTrue(p.remote_call);self.assertFalse(p.valid(token));self.assertIsNone(p.decide(20))
    def test_local_call_blocks_music_and_idle_release(self):
        p=self.ready();p.calls(True);self.play(p);self.assertIsNone(p.decide(3))
        p.owner='linux';p.leased=True;p.streams.clear();p.decide(4);self.assertIsNone(p.decide(40))
    def test_suspend_invalidates_then_resume_is_baseline(self):
        p,token=self.pending();p.sleep(2,True);self.assertIsNone(p.decide(3));self.assertEqual(p.state,'SUSPENDED')
        self.assertFalse(p.result(4,'take',True,token));p.sleep(5,False)
        p.route(6,dict(connected=True,ready=True,owner='remote',remote_activity='idle'),2)
        p.player(6,'a',True,True);self.assertIsNone(p.decide(10))
    def test_ownership_ack_is_not_audio_confirmation(self):
        p,token=self.pending();p.source='remote';p.result(2,'take',True,token)
        self.assertEqual(p.owner,'linux');self.assertEqual(p.source,'remote');p.decide(3);self.assertEqual(p.state,'LOCAL_CLAIMED')
    def test_transient_none_never_reclaims_after_remote_takeover(self):
        p=self.ready();p.owner='linux';p.leased=True
        p.route(1,dict(connected=True,ready=True,owner='remote',remote_activity='active',source='remote'),1)
        p.route(2,dict(connected=True,ready=True,owner='remote',remote_activity='idle',source='none'),1)
        self.assertIsNone(p.decide(20));self.assertFalse(p.leased)
    def test_pause_invalidates_pending_take(self):
        p,token=self.pending();p.player(2,'a',False)
        self.assertFalse(p.result(3,'take',True,token))

if __name__=='__main__':unittest.main()
