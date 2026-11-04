"""Manual connection regression tests; all BlueZ operations are simulated."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from dbus_next import MessageType, Variant
from airpods_connection import ManualConnection, DEVICE, ADAPTER, TRANSPORT, A2DP_SINK

MAC = 'AA:BB:CC:DD:EE:FF'
PATH = '/org/bluez/hci2/dev_AA_BB_CC_DD_EE_FF'


def objects(connected=False, profile=False, powered=True, paired=True, blocked=False):
    result = {
        '/org/bluez/hci2': {ADAPTER: {'Powered': Variant('b', powered)}},
        PATH: {DEVICE: {'Address': Variant('s', MAC), 'Connected': Variant('b', connected),
                       'Paired': Variant('b', paired), 'Blocked': Variant('b', blocked),
                       'Adapter': Variant('o', '/org/bluez/hci2')}}}
    if profile:
        result[PATH + '/sep2/fd0'] = {TRANSPORT: {'State': Variant('s', 'idle')}}
    return result


class Connections(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tree = objects()
        self.calls = []
        self.connect_gate = asyncio.Event()
        self.connect_gate.set()
        self.error = None
        self.profile_after = True
        self.after_snapshot = None
        self.tasks = []
        self.a = SimpleNamespace(policy=SimpleNamespace(remote_call=False, suspended=False),
                                 shadow=False, resuming=False, fatal=asyncio.Event(), control=SimpleNamespace(publish=Mock()))
        self.a.system = SimpleNamespace(call=self.bus_call)
        def spawn(coro):
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task
        self.a.spawn = spawn
        self.c = ManualConnection(self.a, MAC)

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def bus_call(self, message):
        self.calls.append(message)
        if message.member == 'GetManagedObjects':
            if self.after_snapshot:self.after_snapshot()
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[self.tree])
        self.assertEqual(message.member, 'ConnectProfile')
        self.assertEqual(message.path, PATH)  # Discover actual adapter, not hci0.
        self.assertEqual(message.body, [A2DP_SINK])
        await self.connect_gate.wait()
        if self.error:
            return SimpleNamespace(message_type=MessageType.ERROR,
                                   error_name='org.bluez.Error.Failed', body=[self.error])
        self.tree = objects(True, self.profile_after)
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[])

    async def complete(self):
        self.c.request()
        await self.tasks[-1]

    def connects(self):
        return [m for m in self.calls if m.member == 'ConnectProfile']

    async def test_five_clicks_share_one_connection(self):
        self.connect_gate.clear()
        for _ in range(5):self.c.request()
        self.assertEqual(len(self.tasks), 1)
        self.assertTrue(self.c.snapshot()['connecting'])
        self.connect_gate.set()
        await self.tasks[0]
        self.assertEqual(len(self.connects()), 1)
        self.assertFalse(self.c.snapshot()['connecting'])
        self.assertTrue(self.c.snapshot()['a2dp_connected'])

    async def test_already_connected_is_noop(self):
        self.tree = objects(True, True)
        await self.complete()
        self.assertEqual(self.connects(), [])
        self.assertEqual(self.c.phase, 'connected')

    async def test_acl_without_audio_profile_connects_only_a2dp(self):
        self.tree = objects(True, False)
        await self.complete()
        self.assertEqual(len(self.connects()), 1)

    async def test_timeout_preserves_exact_cause_and_does_not_retry(self):
        self.error = 'br-connection-page-timeout'
        await self.complete()
        self.assertEqual(self.c.error, 'not-responding')
        self.assertIn(self.error, self.c.raw_error)
        self.assertIn('Сопряжение сохранено', self.c.detail)
        self.assertEqual(len(self.connects()), 1)

    async def test_key_error_is_distinct_from_timeout(self):
        self.error = 'br-connection-key-missing'
        await self.complete()
        self.assertEqual(self.c.error, 'authentication')

    async def test_bluez_busy_does_not_start_retry_loop(self):
        self.error = 'org.bluez.Error.InProgress'
        await self.complete()
        self.assertEqual(self.c.error, 'busy')
        self.assertEqual(len(self.connects()), 1)

    async def test_known_call_sleep_and_shadow_block_request(self):
        for field in ['remote_call', 'suspended']:
            setattr(self.a.policy, field, True)
            with self.assertRaises(ValueError):self.c.request()
            setattr(self.a.policy, field, False)
        self.a.shadow = True
        with self.assertRaises(ValueError):self.c.request()
        self.assertEqual(self.calls, [])

    async def test_call_appearing_during_snapshot_blocks_connect(self):
        self.after_snapshot = lambda: setattr(self.a.policy, 'remote_call', True)
        await self.complete()
        self.assertEqual(self.connects(), [])

    async def test_off_adapter_and_unpaired_and_blocked_are_not_repaired(self):
        for kwargs in [dict(powered=False), dict(paired=False), dict(blocked=True)]:
            self.tree = objects(**kwargs)
            self.c = ManualConnection(self.a, MAC)
            await self.complete()
            self.assertEqual(self.connects(), [])
            self.assertEqual(self.c.phase, 'failed')

    async def test_method_reply_without_transport_does_not_claim_ready(self):
        self.profile_after = False
        await self.complete()
        self.assertEqual(self.c.phase, 'waiting-profile')
        self.assertFalse(self.c.profile)

    async def test_bluez_restart_cancels_pending_request(self):
        self.connect_gate.clear()
        self.c.request()
        for _ in range(6):await asyncio.sleep(0)
        self.c.signal(SimpleNamespace(message_type=MessageType.SIGNAL,
            interface='org.freedesktop.DBus', member='NameOwnerChanged',
            body=['org.bluez', ':1.2', '']))
        await asyncio.gather(self.tasks[0], return_exceptions=True)
        self.assertFalse(self.c.snapshot()['connecting'])
        self.assertEqual(self.c.phase, 'unavailable')
        self.assertIsNone(self.c.connected)

    async def test_later_success_clears_previous_error(self):
        self.error = 'br-connection-page-timeout'
        await self.complete()
        self.error = None
        await self.complete()
        self.assertIsNone(self.c.error)
        self.assertEqual(self.c.phase, 'connected')
