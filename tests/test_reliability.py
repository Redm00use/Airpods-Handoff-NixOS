"""Races and lifecycle regressions; no Bluetooth hardware required."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault('AIRPODS_DEVICE', 'AA:BB:CC:DD:EE:FF')
from dbus_next import Message, Variant
from airpods_handoff import Adapter, MAC
from airpods_handoff_control import status_for, ControlServer
from airpods_handoff_policy import Policy
from airpods_audio_sessions import media_mode, stream_props
from airpods_call_detection import call_sessions


def route(kind='media', source='remote', activity='active', owner='remote'):
    return dict(connected=True, ready=True, owner=owner, source=source,
                source_kind=kind, remote_activity=activity)




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
            'media.class':'Audio/Sink','node.name':'bluez_output.'+MAC+'.1'}}}}
        a.ensure_audio=AsyncMock();a.command=AsyncMock();a.sync_call_report=Mock()
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
        a.system_signal(Message.new_signal('/org/bluez/hci1/dev_'+MAC,
            'org.freedesktop.DBus.Properties','PropertiesChanged','sa{sv}as',
            ['org.bluez.Device1',{'Connected':Variant('b',True)},[]]))
        self.assertEqual(a.policy.generation,(42,2))

    async def test_cancelled_link_delete_restores_possible_removed_edge(self):
        a=self.a;a.policy=Policy(connected=True,ready=True,healthy=True,
            owner='linux',source='linux',local_call=True,generation=1)
        a.stalled_output_links=lambda:[((10,100),20,21)]
        a.link_command=AsyncMock(side_effect=[asyncio.CancelledError(),True])
        with self.assertRaises(asyncio.CancelledError):await a.repair_output_links(a.policy.context())
        self.assertEqual([call.args for call in a.link_command.await_args_list],[('-d',20,21),(20,21)])


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

class MergeContracts(unittest.IsolatedAsyncioTestCase):
    async def test_resume_blocks_call_health_and_reports(self):
        a=Adapter(False);a.pw_ready=a.mpris_ready=True;a.resuming=True
        p=a.policy;p.connected=p.ready=p.local_call=p.call_proven=True;p.generation=1
        p.owner=p.source='linux';p.remote='idle'
        a.evaluate('resume-barrier')
        self.assertFalse(p.healthy);self.assertFalse(p.call_healthy)
        self.assertIsNone(a.call_report_task)
        self.assertFalse(a.tasks)

    async def test_manual_request_validation_keeps_boolean_contract(self):
        event=dict(version=2,sequence=1,generation=1,manual_request=True,**route())
        self.assertTrue(Adapter.valid_routing_event(event))
        for value in ('true',1,[],None):
            self.assertFalse(Adapter.valid_routing_event(dict(event,manual_request=value)))

    async def test_background_connection_waits_for_resume_baseline(self):
        a=Adapter(False);a.resuming=True
        a.connection.auto_enabled=True;a.connection.request=Mock()
        try:
            a.connection.auto_tick()
            a.connection.request.assert_not_called()
            self.assertIsNotNone(a.connection.auto_timer)
        finally:
            if a.connection.auto_timer:a.connection.auto_timer.cancel()
