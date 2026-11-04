"""Background connection and idle arbitration without hardware or real delays."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from dbus_next import MessageType
from airpods_handoff import Adapter
from airpods_handoff_policy import Policy
import test_connection as fixtures
from test_connection import objects


class IdlePreference(unittest.TestCase):
    def ready(self, remote='idle', kind='idle'):
        return Policy(connected=True, ready=True, healthy=True, owner='remote',
                      source='remote', remote=remote, source_kind=kind, generation=1)

    def test_connection_without_idle_evidence_never_takes(self):
        for remote, kind in [('active','media'), ('active','call'), ('unknown','unknown'), ('idle','unknown')]:
            p=self.ready(remote,kind)
            for now in (0,1,10,100):self.assertIsNone(p.decide(now))

    def test_both_idle_selects_pc_after_settling_once(self):
        p=self.ready();self.assertIsNone(p.decide(0));self.assertEqual(p.deadline(0),1)
        self.assertIsNone(p.decide(.99));self.assertEqual(p.decide(1),'take-idle')
        token=p.inflight_token;self.assertTrue(p.result(1.1,'take-idle',True,token))
        for now in (2,10,100):self.assertIsNone(p.decide(now));self.assertEqual(p.owner,'linux')
        self.assertEqual(p.source,'remote')  # No fabricated audio confirmation.

    def test_local_service_audio_does_not_defeat_idle_default(self):
        p=self.ready();p.source='linux';p.source_kind='media'
        p.decide(0);self.assertEqual(p.decide(1),'take-idle')
        p=self.ready();p.source='remote';p.source_kind='media'
        for now in (0,1,100):self.assertIsNone(p.decide(now))

    def test_failed_idle_claim_is_not_retried_on_every_status(self):
        p=self.ready();p.decide(0);p.decide(1);p.result(1.1,'take-idle',False)
        for now in (4,10,100):self.assertIsNone(p.decide(now))

    def test_idle_preference_does_not_override_new_phone_play(self):
        p=self.ready();p.decide(0)
        p.route(.5,dict(connected=True,ready=True,owner='remote',source='remote',
                        source_kind='media',remote_activity='active'),1)
        for now in (1,5,20):self.assertIsNone(p.decide(now))
        p.route(21,dict(connected=True,ready=True,owner='remote',source='remote',
                        source_kind='idle',remote_activity='idle'),1)
        p.decide(21);self.assertEqual(p.decide(22),'take-idle')

    def test_sleep_unhealthy_and_call_block_idle_default(self):
        for field,value in [('suspended',True),('healthy',False),('ready',False),('remote_call',True),('local_call',True)]:
            p=self.ready();setattr(p,field,value)
            for now in (0,5,100):self.assertIsNone(p.decide(now))

    def test_media_without_new_play_is_not_treated_as_idle(self):
        p=self.ready();p.players={'music':True};p.streams={'music'}
        for now in (0,10,100):self.assertIsNone(p.decide(now))

    def test_idle_selection_can_be_disabled(self):
        p=self.ready();p.prefer_idle_pc=False
        for now in (0,10,100):self.assertIsNone(p.decide(now))

    def test_stale_phone_call_does_not_deadlock_reconnect_after_sleep(self):
        p=self.ready('active','call');p.remote_call=True
        p.sleep(1,True);p.sleep(2,False)
        self.assertFalse(p.remote_call);self.assertEqual(p.remote,'unknown')
        self.assertFalse(p.ready);self.assertIsNone(p.decide(100))

    def test_typed_idle_is_rechecked_after_ipc_lock(self):
        a=Adapter(False);a.policy=self.ready();p=a.policy
        p.decide(0);p.decide(1);token=p.inflight_token
        self.assertTrue(a.command_eligible('take-idle',token))
        p.source_kind='call';p.remote='active'
        self.assertFalse(a.command_eligible('take-idle',token))


class BackgroundConnection(unittest.IsolatedAsyncioTestCase):
    # Reuse only the fake peer, without duplicating the manual regression tests.
    async def asyncSetUp(self):
        await fixtures.Connections.asyncSetUp(self)
        async def control(*args):
            await self.connect_gate.wait()
            if self.error:raise RuntimeError(self.error)
            self.tree=objects(True,False);self.a.policy.ready=True
            return True, 'owner remote'
        self.a.cli=AsyncMock(side_effect=control)
    bus_call = fixtures.Connections.bus_call
    complete = fixtures.Connections.complete
    connects = fixtures.Connections.connects
    async def asyncTearDown(self):
        if self.c.auto_timer:self.c.auto_timer.cancel()
        await fixtures.Connections.asyncTearDown(self)

    async def test_auto_connection_opens_only_control_not_audio(self):
        self.a.policy.owner='remote';self.a.policy.remote='active'
        self.c.auto_enabled=True;self.c.auto_tick();await self.tasks[-1]
        self.assertEqual(len(self.connects()),0)
        self.a.cli.assert_awaited_once_with('switching','status')
        self.assertEqual(self.a.policy.owner,'remote');self.assertTrue(self.c.background)
        self.assertFalse(self.c.profile);self.assertEqual(self.c.phase,'control-ready')

    async def test_control_timeout_keeps_actual_error_and_classifies_it(self):
        diagnostic='airpodsctl: ERROR The requested operation failed; cause: AirPods control connection timed out'
        self.a.cli=AsyncMock(return_value=(False,diagnostic))
        self.c.auto_enabled=True;self.c.auto_tick();await self.tasks[-1]
        self.assertEqual(self.c.raw_error,diagnostic)
        self.assertEqual(self.c.error,'timeout')
        self.assertEqual(self.connects(),[])
        self.assertIsNotNone(self.c.auto_timer)

    async def test_background_and_manual_join_one_flight(self):
        self.connect_gate.clear();self.c.auto_enabled=True;self.c.auto_tick()
        self.c.request();self.c.auto_tick();self.assertEqual(len(self.tasks),1)
        self.connect_gate.set();await self.tasks[0];self.assertEqual(len(self.connects()),0);self.assertEqual(self.a.cli.await_count,1)

    async def test_background_failure_backs_off_and_stops_for_auth(self):
        self.error='br-connection-page-timeout';self.c.auto_enabled=True
        for expected in (5,15,30,60,60):
            self.c.auto_tick();await self.tasks[-1]
            delay=self.c.auto_timer.when()-asyncio.get_running_loop().time()
            self.assertAlmostEqual(delay,expected,delta=.1)
        self.error='br-connection-key-missing';self.c.auto_tick();await self.tasks[-1]
        count=self.a.cli.await_count;self.c.auto_tick();await asyncio.sleep(0)
        self.assertEqual(self.a.cli.await_count,count);self.assertTrue(self.c.blocked_error)

    async def test_background_already_connected_does_not_connect_again(self):
        self.c.load(objects(True,True));self.c.auto_enabled=True;self.c.auto_tick()
        await asyncio.sleep(0);self.assertEqual(self.calls,[])

    async def test_background_never_connects_during_call_sleep_or_shadow(self):
        self.c.auto_enabled=True
        for field in ('remote_call','suspended'):
            setattr(self.a.policy,field,True);self.c.auto_tick();await asyncio.sleep(0)
            setattr(self.a.policy,field,False)
        self.a.shadow=True;self.c.start_auto(True)
        self.assertEqual(self.calls,[]);self.assertIsNone(self.c.auto_timer)

    async def test_invalidated_snapshot_cannot_restore_stale_state(self):
        self.after_snapshot=self.c.invalidate
        self.c.request()
        await asyncio.gather(self.tasks[-1], return_exceptions=True)
        self.assertEqual(self.connects(),[]);self.assertIsNone(self.c.connected)
        self.assertEqual(self.c.phase,'unavailable')

    async def test_failed_control_channel_can_recover_without_reconnecting_audio(self):
        self.c.load(objects(True,True));self.a.policy.ready=False
        self.a.schedule_recovery=Mock();self.c.auto_enabled=True;self.c.auto_tick()
        self.a.schedule_recovery.assert_called_once();self.assertEqual(self.calls,[])

    async def test_late_control_ready_clears_transient_cli_timeout_without_audio(self):
        self.c.error='failed';self.c.raw_error='control-channel-unavailable';self.c.phase='failed'
        self.c.control_ready()
        self.assertTrue(self.c.connected);self.assertFalse(self.c.profile)
        self.assertIsNone(self.c.error);self.assertIsNone(self.c.raw_error)
        self.assertEqual(self.c.phase,'control-ready');self.assertEqual(self.connects(),[])

    async def test_manual_disconnect_pauses_autoconnect_until_manual_connect(self):
        self.a.policy.invalidate=Mock()
        self.tree=objects(True,True)
        original=self.bus_call
        async def bus_call(message):
            if message.member=='Disconnect':
                self.calls.append(message);self.tree=objects(False,False)
                return SimpleNamespace(message_type=MessageType.METHOD_RETURN,body=[])
            return await original(message)
        self.a.system.call=bus_call
        self.c.auto_enabled=True;self.c.request_disconnect();await self.tasks[-1]
        self.assertTrue(self.c.auto_paused);self.assertIsNone(self.c.auto_timer)
        self.c.auto_tick();await asyncio.sleep(0);self.assertEqual(len(self.connects()),0)
        self.a.policy.invalidate.assert_called_once()
        self.c.request();await self.tasks[-1]
        self.assertFalse(self.c.auto_paused);self.assertEqual(len(self.connects()),1)


class IdleDispatch(unittest.IsolatedAsyncioTestCase):
    async def test_phone_play_while_command_waits_prevents_take(self):
        a=Adapter(False);p=a.policy
        p.connected=p.ready=p.healthy=True;p.owner='remote';p.remote='idle';p.source_kind='idle'
        p.decide(0);p.decide(1);token=p.inflight_token
        a._cli=AsyncMock();a.evaluate=lambda _:None
        await a.ipc_lock.acquire();task=asyncio.create_task(a.command('take-idle',token))
        await asyncio.sleep(0);p.remote='active';p.source_kind='media'
        a.ipc_lock.release();await task;a._cli.assert_not_awaited()

    async def test_idle_uses_non_forced_take_and_does_not_repair_or_pause_audio(self):
        a=Adapter(False);p=a.policy
        p.connected=p.ready=p.healthy=True;p.owner='remote';p.remote='idle';p.source_kind='idle'
        p.decide(0);p.decide(1);a._cli=AsyncMock(return_value=(True,'owner linux'))
        a.evaluate=lambda _:None;a.ensure_audio=AsyncMock();a.pause_for_remote=AsyncMock()
        await a.command('take-idle',p.inflight_token)
        a._cli.assert_awaited_once_with('switching','take')
        a.ensure_audio.assert_not_awaited();a.pause_for_remote.assert_not_awaited()


class OnDemandProfile(unittest.IsolatedAsyncioTestCase):
    def adapter(self, success=True):
        a=Adapter(False);p=a.policy
        p.connected=p.ready=p.healthy=True;p.owner='linux';p.source='none';p.remote='idle'
        p.players={'media':True};p.streams={'media'};a.connection.device_path='/org/bluez/hci2/dev_test'
        async def connect():a.connection.profile=success
        def request():a.connection.task=asyncio.create_task(connect())
        a.connection.request=Mock(side_effect=request)
        a.audio_active=Mock(return_value=success);a.wait_audio=AsyncMock(return_value=False)
        a.transport_state=AsyncMock()
        return a

    async def test_local_audio_opens_profile_after_ownership_only(self):
        a=self.adapter();await a.ensure_audio(a.policy.context(),0)
        a.connection.request.assert_called_once();self.assertTrue(a.connection.profile)

    async def test_idle_and_phone_call_never_open_audio(self):
        for mode in ('idle','call','remote'):
            a=self.adapter()
            if mode=='idle':a.policy.players.clear()
            if mode=='call':a.policy.remote_call=True
            if mode=='remote':a.policy.owner='remote'
            await a.ensure_audio(a.policy.context(),0);a.connection.request.assert_not_called()

    async def test_failed_profile_has_one_attempt_per_local_intent(self):
        a=self.adapter(False);context=a.policy.context()
        await a.ensure_audio(context,0);await a.ensure_audio(context,0)
        a.connection.request.assert_called_once()
        a.policy.invalidate();await a.ensure_audio(a.policy.context(),0)
        self.assertEqual(a.connection.request.call_count,2)

    async def test_call_while_control_request_pending_blocks_audio(self):
        a=self.adapter();gate=asyncio.Event();a.connection.task=asyncio.create_task(gate.wait())
        task=asyncio.create_task(a.ensure_audio(a.policy.context(),0));await asyncio.sleep(0)
        a.policy.remote_call=True;gate.set();await task
        a.connection.request.assert_not_called()
