import os
os.environ.setdefault('AIRPODS_DEVICE','AA:BB:CC:DD:EE:FF')
import asyncio, unittest
from unittest.mock import AsyncMock
from airpods_audio_sessions import PlaybackTracker,candidates
from airpods_call_detection import call_sessions
from airpods_handoff import Adapter
from airpods_handoff_policy import Policy

def node(state='running',name='Zen',role=None,serial=100):
    return {'type':'PipeWire:Interface:Node','info':{'state':state,'props':{'media.class':'Stream/Output/Audio','application.name':name,'media.role':role,'object.serial':serial}}}

class Classifier(unittest.TestCase):
    def test_tagged_unknown_media_allowed(self):self.assertTrue(candidates({1:node(name='Custom player',role='Music')},set()))
    def test_untagged_unknown_not_guessed(self):self.assertFalse(candidates({1:node(name='Custom sound')},set()))
    def test_mpris_pause_cannot_be_bypassed(self):self.assertFalse(candidates({1:node()}, {1}))
    def test_notification_and_dsp_and_captures_excluded(self):
        x={1:node(role='Notification'),2:node(name='EasyEffects',role='DSP'),3:node()}
        x[3]['info']['props']['media.class']='Stream/Input/Audio'
        self.assertFalse(candidates(x,set()))
    def test_muted_stream_not_intent(self):
        x=node();x['info']['params']={'Props':[{'mute':True}]};self.assertFalse(candidates({1:x},set()))
    def test_serial_separates_reused_node_id(self):self.assertNotEqual(set(candidates({1:node(serial=1)},set())),set(candidates({1:node(serial=2)},set())))
    def test_explicit_communication_without_duplex(self):
        self.assertTrue(call_sessions({1:node(role='Communication')}))
    def test_string_monitor_capture_excluded(self):
        x=node(role='Communication');x['info']['props']['stream.capture.sink']='true'
        self.assertFalse(call_sessions({1:x}))

class Fallback(unittest.TestCase):
    def test_initial_baseline_does_not_claim(self):
        t=PlaybackTracker();t.observe(0,{'a':True});self.assertEqual(t.observe(1.01,{'a':True}),{'a'});self.assertIn('a',t.baseline)
    def test_short_sound_ignored(self):
        t=PlaybackTracker();t.observe(0,{});t.observe(1,{'a':True});self.assertFalse(t.observe(1.3,{}));self.assertIsNone(t.deadline(2))
    def test_resume_is_new_edge(self):
        t=PlaybackTracker();t.observe(0,{'a':True});t.observe(1.01,{'a':True});t.observe(2,{'a':False});t.observe(2.3,{'a':False})
        t.observe(3,{'a':True});self.assertEqual(t.observe(4.01,{'a':True}),{'a'});self.assertNotIn('a',t.baseline)
    def test_stop_has_bounded_grace(self):
        t=PlaybackTracker();t.observe(0,{'a':True});t.observe(1.01,{'a':True})
        self.assertEqual(t.observe(2,{}),{'a'});self.assertFalse(t.observe(2.26,{}))
    def test_reset_discards_pre_sleep_intents(self):
        t=PlaybackTracker();t.observe(0,{});t.observe(1,{'a':True});t.reset();t.observe(2,{'a':True});self.assertIn('a',t.baseline)

class Claims(unittest.TestCase):
    def remote(self,kind='media'):
        p=Policy();p.route(0,dict(connected=True,ready=True,owner='remote',source='remote',source_kind=kind,remote_activity='active'),1);p.healthy=True;p.cooldown=0
        return p
    def play(self,p):p.player(1,'music',True);p.streams={'music'};p.decide(1)
    def test_explicit_media_can_claim_remote_music_once(self):
        p=self.remote();self.play(p);self.assertEqual(p.decide(1.7),'claim');token=p.inflight_token
        p.result(1.8,'claim',True,token);p.route(2,dict(connected=True,ready=True,owner='linux',source='linux',source_kind='media',remote_activity='idle'),1);p.decide(2)
        p.route(3,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),1)
        self.assertEqual(p.decide(3),'restore')
        p.result(3.4,'restore',True,p.inflight_token)
        p.route(4,dict(connected=True,ready=True,owner='linux',source='linux',source_kind='media',remote_activity='idle'),1);p.decide(4)
        p.route(5,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),1)
        self.assertIsNone(p.decide(6));self.assertEqual(p.state,'LOCAL_CONTESTED')
    def test_no_claim_on_phone_call_or_unknown_source(self):
        for kind in ('call','unknown'):
            p=self.remote(kind);self.play(p);self.assertIsNone(p.decide(2));self.assertFalse(p.restore_attempted)
    def test_startup_playing_is_not_user_edge(self):
        p=self.remote();p.player(1,'music',True,baseline=True);p.streams={'music'}
        self.assertIsNone(p.decide(2));self.assertIsNone(p.decide(100))
    def test_new_remote_edge_does_not_erase_user_play(self):
        p=self.remote();p.remote='idle';self.play(p)
        p.route(1.2,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),1)
        p.decide(1.2);self.assertEqual(p.decide(3.8),'claim')
    def test_pause_invalidates_claim(self):
        p=self.remote();self.play(p);p.decide(1.7);token=p.inflight_token;p.player(1.8,'music',False)
        self.assertFalse(p.valid(token))

class AdapterFallback(unittest.IsolatedAsyncioTestCase):
    async def test_baseline_then_resume_creates_one_qualified_edge(self):
        a=Adapter(True);a.pw_ready=True;a.nodes={1:node()};a.correlate()
        for key in a.playback_tracker.pending:a.playback_tracker.pending[key]-=2
        a.correlate();self.assertTrue(a.policy.media());self.assertIsNone(a.policy.intent)
        a.nodes[1]['info']['state']='idle';a.correlate()
        for key in a.playback_tracker.stopping:a.playback_tracker.stopping[key]-=2
        a.correlate();self.assertFalse(a.policy.media())
        a.nodes[1]['info']['state']='running';a.correlate()
        for key in a.playback_tracker.pending:a.playback_tracker.pending[key]-=2
        a.correlate();self.assertTrue(a.policy.media());self.assertIsNotNone(a.policy.intent)
        if a.call_timer:a.call_timer.cancel()
    async def test_claim_dispatch_uses_controller_guarded_media_take(self):
        a=Adapter(False);a.policy=Claims().remote();Claims().play(a.policy);a.policy.decide(1.7);token=a.policy.inflight_token
        a._cli=AsyncMock(return_value=(True,'owner linux'));a.evaluate=lambda _:None;a.ensure_audio=AsyncMock()
        await a.command('claim',token);a._cli.assert_awaited_once_with('switching','take-media')
        if a.tasks:await asyncio.gather(*list(a.tasks))
    async def test_call_arriving_while_waiting_for_ipc_blocks_claim(self):
        a=Adapter(False);a.policy=Claims().remote();Claims().play(a.policy);a.policy.decide(1.7);token=a.policy.inflight_token
        a._cli=AsyncMock();a.evaluate=lambda _:None
        await a.ipc_lock.acquire();task=asyncio.create_task(a.command('claim',token));await asyncio.sleep(0)
        a.policy.remote_call=True;a.ipc_lock.release();await task;a._cli.assert_not_awaited()

class Recovery(unittest.IsolatedAsyncioTestCase):
    async def test_sleep_clears_fallback_and_call_without_force(self):
        from dbus_next import Message, MessageType
        a=Adapter(True);a.pw_ready=a.mpris_ready=True;a.policy.connected=a.policy.ready=True;a.policy.owner=a.policy.source='linux'
        a.policy.local_focus=True;a.policy.local_call=True;a.fallback_streams={'pw:1:1'};a.policy.players={'pw:1:1':True};a.policy.streams={'pw:1:1'}
        message=Message.new_signal('/org/freedesktop/login1','org.freedesktop.login1.Manager','PrepareForSleep','b',[True])
        a.system_signal(message)
        self.assertTrue(a.policy.suspended);self.assertFalse(a.policy.local_focus);self.assertFalse(a.policy.local_call);self.assertFalse(a.fallback_streams)
        if a.timer:a.timer.cancel()
    async def test_resume_failure_restarts_from_baseline(self):
        a=Adapter(True);a.refresh_graph=AsyncMock(return_value=False)
        await a.resume_baseline();self.assertTrue(a.fatal.is_set())
    async def test_successful_resume_is_not_a_play_edge(self):
        a=Adapter(True);a.pw_ready=True;a.nodes={1:node()};a.refresh_graph=AsyncMock(return_value=True);a.schedule_recovery=lambda:None
        await a.resume_baseline();self.assertTrue(a.mpris_ready);self.assertIsNone(a.policy.intent);self.assertTrue(a.playback_tracker.baseline)
        if a.call_timer:a.call_timer.cancel()
    async def test_invalidated_player_refresh_is_bounded(self):
        from unittest.mock import patch
        a=Adapter(True);a.uncertain_players={'player'};a.add_player=AsyncMock(return_value=False)
        with patch('airpods_handoff.asyncio.sleep',new=AsyncMock()):await a.refresh_player('player')
        self.assertEqual(a.add_player.await_count,3)
    async def test_ack_after_expected_release_event_is_applied(self):
        p=Policy(connected=True,ready=True,healthy=True,owner='linux',remote='idle',source='linux',generation=1)
        p.peer_request(0);self.assertEqual(p.decide(0),'release');token=p.inflight_token
        p.route(.1,dict(connected=True,ready=True,owner='remote',remote_activity='idle',source='linux'),1)
        self.assertTrue(p.valid(token));self.assertTrue(p.result(.2,'release',True,token));self.assertEqual(p.owner,'remote')

class CallAcquisition(unittest.TestCase):
    def test_new_call_can_take_idle_and_claim_remote_music(self):
        for activity,action in (('idle','take'),('active','claim')):
            p=Claims().remote();p.remote=activity;p.calls(True,now=1);p.decide(1)
            self.assertEqual(p.decide(1.7),action)
    def test_call_baseline_does_not_claim_and_hangup_cancels_ack(self):
        p=Claims().remote();p.calls(True);self.assertIsNone(p.decide(2))
        p.calls(False);p.calls(True,now=3);p.decide(3);p.decide(3.7);token=p.inflight_token
        p.calls(False);self.assertFalse(p.valid(token))
    def test_remote_phone_call_excludes_claim(self):
        p=Claims().remote('call');p.calls(True,now=1);p.decide(1);self.assertIsNone(p.decide(2))

class RepeatedCycles(unittest.TestCase):
    def test_ten_complete_pause_play_cycles_have_bounded_commands(self):
        p=Claims().remote();actions=[]
        for cycle in range(10):
            t=cycle*20+10
            p.player(t-1,'music',False);p.decide(t-1)
            p.route(t,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),1)
            p.player(t,'music',True);p.streams={'music'};p.decide(t)
            action=p.decide(t+3);actions.append(action);self.assertEqual(action,'claim')
            p.result(t+3.1,action,True,p.inflight_token)
            p.route(t+3.2,dict(connected=True,ready=True,owner='linux',source='linux',source_kind='media',remote_activity='idle'),1);p.decide(t+3.2)
            p.route(t+4,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),1)
            action=p.decide(t+4);actions.append(action);self.assertEqual(action,'restore')
            p.result(t+4.4,action,True,p.inflight_token)
            p.route(t+4.5,dict(connected=True,ready=True,owner='linux',source='linux',source_kind='media',remote_activity='idle'),1);p.decide(t+4.5)
            p.route(t+5,dict(connected=True,ready=True,owner='remote',source='remote',source_kind='media',remote_activity='active'),1)
            for extra in (0,1,2,5):self.assertIsNone(p.decide(t+5+extra))
        self.assertEqual(actions.count('claim'),10);self.assertEqual(actions.count('restore'),10)

class ElectronIdentity(unittest.TestCase):
    def test_discord_chromium_helper_is_not_browser_media(self):
        x=node(name='Chromium');x['info']['props']['application.process.binary']='.DiscordCanary-wrapped'
        self.assertFalse(candidates({1:x},set()))
    def test_explicit_telegram_music_is_not_globally_disabled(self):
        x=node(name='Telegram',role='Music');x['info']['props']['application.process.binary']='telegram-desktop'
        self.assertTrue(candidates({1:x},set()))
    def test_discord_helper_does_not_match_chrome_mpris_family(self):
        a=Adapter(True);a.identities={'chrome':(10,'chrome')};x=node(name='Chromium')
        x['info']['props']['application.process.binary']='.DiscordCanary-wrapped';a.nodes={1:x}
        a.correlate();self.assertFalse(a.policy.streams)
