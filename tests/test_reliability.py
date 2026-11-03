"""Races and lifecycle regressions; no Bluetooth hardware required."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault('AIRPODS_DEVICE', 'AA:BB:CC:DD:EE:FF')
from dbus_next import Message, Variant
from airpods_handoff import Adapter
from airpods_handoff_control import status_for, ControlServer
from airpods_handoff_policy import Policy
from airpods_audio_sessions import media_mode, stream_props
from airpods_call_detection import call_sessions


def route(kind='media', source='remote', activity='active', owner='remote'):
    return dict(connected=True, ready=True, owner=owner, source=source,
                source_kind=kind, remote_activity=activity)


class CallReturn(unittest.TestCase):
    def local(self):
        p=Policy(connected=True, ready=True, healthy=True, generation=1,
                 owner='linux', source='linux', remote='idle', local_call=True)
        p.decide(0)
        return p

    def test_phone_call_then_idle_returns_continuing_discord_once(self):
        p=self.local()
        p.route(1,route('call'),1)
        self.assertIsNone(p.decide(1))
        self.assertEqual(p.state,'REMOTE_CALL')
        p.route(2,route('unknown',activity='unknown'),1)
        self.assertIsNone(p.decide(2))
        p.route(4,route('idle','none','idle'),1)
        self.assertIsNone(p.decide(4))
        self.assertEqual(p.decide(4.7),'take')
        token=p.inflight_token
        self.assertTrue(p.result(4.8,'take',True,token))
        self.assertIsNone(p.decide(20))
        self.assertFalse(p.interrupted_call)

    def test_no_return_for_baseline_hangup_sleep_disconnect_or_remote_media(self):
        for ending in ('baseline','hangup','sleep','disconnect','media'):
            with self.subTest(ending=ending):
                p=self.local()
                if ending=='baseline':p.local_focus=False
                p.route(1,route('call'),1)
                if ending=='hangup':p.calls(False)
                if ending=='sleep':p.sleep(2,True);p.sleep(3,False)
                if ending=='disconnect':p.route(2,{'connected':False},1)
                event=route() if ending=='media' else route('idle','none','idle')
                p.route(4,event,1)
                # Continuing local focus may restore typed remote music, but
                # an interrupted phone call must not manufacture new play intent.
                if ending=='media':self.assertIsNone(p.intent)
                else:
                    self.assertIsNone(p.decide(4))
                    self.assertIsNone(p.decide(20))

    def test_new_phone_call_invalidates_return_ack(self):
        p=self.local();p.route(1,route('call'),1)
        p.route(4,route('idle','none','idle'),1);p.decide(4);p.decide(4.7)
        token=p.inflight_token
        p.route(4.8,route('call'),1)
        self.assertFalse(p.result(5,'take',True,token))
        self.assertEqual(p.owner,'remote')


class AdapterRaces(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.a=Adapter(False)
        self.a.session=object();self.a.system=object()
        self.a.evaluate=lambda _:None

    async def asyncTearDown(self):
        a=self.a
        for handle in (a.timer,a.call_timer):
            if handle:handle.cancel()
        for task in list(a.tasks):task.cancel()
        await asyncio.gather(*a.tasks,return_exceptions=True)

    def playback(self,value):
        msg=Message.new_signal('/org/mpris/MediaPlayer2','org.freedesktop.DBus.Properties',
            'PropertiesChanged','sa{sv}as',['org.mpris.MediaPlayer2.Player',{'PlaybackStatus':Variant('s',value)},[]])
        msg.sender=':1.10'
        self.a.session_signal(msg)

    async def test_old_mpris_snapshot_cannot_undo_new_pause(self):
        a=self.a;a.mpris_ready=True
        async def call(*args):
            if args[4]=='GetNameOwner':return [':1.10']
            if args[4]=='GetConnectionUnixProcessID':return [10]
            self.playback('Paused')
            return [{'PlaybackStatus':Variant('s','Playing')}]
        a.call=AsyncMock(side_effect=call)
        self.assertTrue(await a.add_player('org.mpris.MediaPlayer2.cider'))
        self.assertFalse(a.policy.players['org.mpris.MediaPlayer2.cider'])
        self.assertIsNone(a.policy.intent)
        self.assertEqual(a.call.await_args.args[1],':1.10')

    async def test_departed_mpris_owner_cannot_reinsert_identity(self):
        a=self.a;name='org.mpris.MediaPlayer2.cider'
        async def call(*args):
            if args[4]=='GetNameOwner':return [':1.10']
            a.session_signal(Message.new_signal('/org/freedesktop/DBus','org.freedesktop.DBus',
                'NameOwnerChanged','sss',[name,':1.10','']))
            return [10]
        a.call=AsyncMock(side_effect=call)
        self.assertFalse(await a.add_player(name))
        self.assertNotIn(name,a.identities)
        self.assertNotIn(name,a.policy.players)
        self.assertNotIn(':1.10',a.owners)

    async def test_late_status_reply_after_sleep_does_not_mark_connected(self):
        a=self.a
        async def cli(*args):
            a.sleep_revision+=1;a.policy.sleep(1,True)
            return True,'multipoint ready\nowner linux\nremote-activity idle'
        a.cli=AsyncMock(side_effect=cli)
        await a.snapshot()
        self.assertFalse(a.policy.ready)
        self.assertIsNone(a.policy.generation)

    async def test_sleep_graph_and_mpris_events_do_not_create_intent(self):
        a=self.a;a.pw_ready=True;a.resuming=True;a.policy.suspended=True
        a.owners={':1.10':'org.mpris.MediaPlayer2.cider'}
        a.nodes={1:{'info':{'state':'running','props':{'media.class':'Stream/Output/Audio','application.name':'Cider'}}}}
        a.correlate();self.playback('Playing')
        self.assertIsNone(a.policy.intent)
        self.assertFalse(a.playback_tracker.seen_baseline)

    async def test_fatal_error_cannot_be_overwritten_by_readiness(self):
        a=Adapter(False);a.pw_ready=a.mpris_ready=True;a.fatal.set()
        a.policy=Policy(connected=True,ready=True,healthy=True,owner='linux',generation=1)
        a.policy.peer_request(0)
        a.evaluate('failure')
        self.assertFalse(a.policy.healthy)
        self.assertFalse(a.tasks)

    async def test_recovery_ignores_other_connected_bluetooth_device(self):
        a=self.a
        a.call=AsyncMock(return_value=[{'/org/bluez/hci1/dev_00_11_22_33_44_55':
            {'org.bluez.Device1':{'Connected':Variant('b',True)}}}])
        a.snapshot=AsyncMock();await a.recover();a.snapshot.assert_not_awaited()

    async def test_helper_cancellation_kills_and_reaps_process(self):
        proc=Mock(returncode=None)
        started=asyncio.Event()
        async def communicate():started.set();await asyncio.Future()
        proc.communicate=communicate;proc.wait=AsyncMock()
        with patch('airpods_handoff.asyncio.create_subprocess_exec',AsyncMock(return_value=proc)):
            task=asyncio.create_task(self.a.run_process('helper'))
            await started.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        proc.kill.assert_called_once();proc.wait.assert_awaited_once()

    async def test_invalid_graph_snapshot_rejected(self):
        for data in ({'id':1},[None],[{'info':{}}]):
            self.a.run_process=AsyncMock(return_value=(True,json.dumps(data).encode()))
            self.assertFalse(await self.a.refresh_graph())

    async def test_late_sink_error_repairs_without_another_ownership_command(self):
        a=self.a;a.evaluate=Adapter.evaluate.__get__(a);a.pw_ready=a.mpris_ready=True
        a.policy=Policy(connected=True,ready=True,healthy=True,owner='linux',source='linux',local_call=True,generation=1)
        a.nodes={8:{'type':'PipeWire:Interface:Node','info':{'state':'error','props':{
            'media.class':'Audio/Sink','node.name':'bluez_output.AA_BB_CC_DD_EE_FF.1'}}}}
        a.ensure_audio=AsyncMock();a.command=AsyncMock()
        a.evaluate('late-pipewire-error');await asyncio.gather(*list(a.tasks))
        a.ensure_audio.assert_awaited_once();a.command.assert_not_awaited()

    async def test_shutdown_cancels_workers_and_closes_control_service(self):
        a=self.a;a.control=Mock();a.control.close=AsyncMock()
        a.session=Mock();a.system=Mock()
        stopped=asyncio.Event()
        async def worker():
            try:await asyncio.Future()
            finally:stopped.set()
        async def run():
            a.spawn(worker());await asyncio.sleep(0)
            raise RuntimeError('bus disconnected')
        a.run=run
        with self.assertRaisesRegex(RuntimeError,'bus disconnected'):await a.main()
        self.assertTrue(stopped.is_set());self.assertTrue(a.policy.suspended)
        a.control.close.assert_awaited_once();a.session.disconnect.assert_called_once()

    async def test_duplicate_bluez_connected_preserves_current_generation(self):
        a=self.a;a.policy.generation=(42,2);a.schedule_recovery=Mock()
        a.system_signal(Message.new_signal('/org/bluez/hci1/dev_AA_BB_CC_DD_EE_FF',
            'org.freedesktop.DBus.Properties','PropertiesChanged','sa{sv}as',
            ['org.bluez.Device1',{'Connected':Variant('b',True)},[]]))
        self.assertEqual(a.policy.generation,(42,2))


class Classifications(unittest.TestCase):
    def test_modes_use_roles_and_do_not_guess_browser_content(self):
        for role,expected in [('Communication','media'),('Music','music'),('Movie','video'),('Video','video'),('Game','game'),(None,'media')]:
            self.assertEqual(media_mode({'media.role':role,'application.name':'Firefox'}),expected)
        self.assertEqual(media_mode({'application.name':'Cider'}),'music')

    def test_string_client_ids_supply_call_identity(self):
        objects={3:{'type':'PipeWire:Interface:Client','info':{'props':{'application.name':'Discord','application.process.id':10}}}}
        for key,cls in [(1,'Stream/Input/Audio'),(2,'Stream/Output/Audio')]:
            objects[key]={'info':{'state':'running','props':{'media.class':cls,'client.id':'3'}}}
        self.assertEqual(stream_props(objects,objects[1])['application.name'],'Discord')
        self.assertTrue(call_sessions(objects))

    def test_status_exposes_modes_and_shadow_without_false_return_button(self):
        a=Adapter(True);a.policy=Policy(connected=True,ready=True,healthy=True,remote='idle')
        a.policy.players={'music':True};a.policy.streams={'music'};a.media_modes={'music','video'}
        self.assertEqual(status_for(a)['local_mode'],'mixed')
        a.policy.local_call=True
        self.assertEqual(status_for(a)['local_mode'],'call')
        self.assertFalse(status_for(a)['can_return'])
        self.assertTrue(status_for(a)['shadow'])

    def test_xdg_preferences_location(self):
        with patch.dict(os.environ,{'XDG_CONFIG_HOME':'/tmp/custom-config'}):
            server=ControlServer(Adapter(True),runtime='/tmp')
            self.assertEqual(str(server.preferences),'/tmp/custom-config/airpods-handoff/preferences.json')

    def test_malformed_routing_events_fail_closed(self):
        valid=dict(version=2,sequence=1,generation=1,**route())
        self.assertTrue(Adapter.valid_routing_event(valid))
        for event in ([],None,dict(valid,ready='yes'),dict(valid,sequence=True),dict(valid,generation=[]),dict(valid,source_kind='phone'),dict(valid,owner=[])):
            self.assertFalse(Adapter.valid_routing_event(event))
