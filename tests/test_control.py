import os
os.environ.setdefault('AIRPODS_DEVICE','AA:BB:CC:DD:EE:FF')
import asyncio,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock
from airpods_handoff import Adapter
from airpods_handoff_control import ControlServer,status_for
from airpods_handoff_policy import Policy

class ManualPolicy(unittest.TestCase):
    def ready(self):return Policy(connected=True,ready=True,healthy=True,owner='linux',source='linux',remote='idle',generation=1)
    def test_pin_holds_while_idle_and_defers_peer(self):
        p=self.ready();p.set_pin(0,True);p.peer_request(1)
        for t in (1,10,100):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'LOCAL_PINNED')
    def test_unpin_allows_normal_idle_release(self):
        p=self.ready();p.set_pin(0,True);p.decide(0);p.set_pin(1,False);p.decide(1)
        self.assertEqual(p.decide(5.1),'release')
    def test_manual_return_rearms_contested_but_is_one_request(self):
        p=self.ready();p.owner=p.source='remote';p.remote='active';p.source_kind='media';p.state='LOCAL_CONTESTED';p.restore_attempted=True
        p.manual_request(1);p.decide(1);self.assertEqual(p.decide(1.7),'claim');self.assertTrue(p.inflight_manual)
        token=p.inflight_token;p.result(2,'claim',True,token);self.assertFalse(p.inflight_manual)
        self.assertIsNone(p.decide(100))
    def test_pin_persisted_baseline_does_not_force_remote(self):
        p=self.ready();p.pinned=True;p.owner=p.source='remote';p.remote='active';p.source_kind='media'
        for t in (0,10,100):self.assertIsNone(p.decide(t))
    def test_phone_call_never_claimed(self):
        p=self.ready();p.owner=p.source='remote';p.remote='active';p.remote_call=True;p.source_kind='call'
        p.set_pin(0,True)
        for t in (0,1,10):self.assertIsNone(p.decide(t))
    def test_manual_return_without_media_expires_then_releases(self):
        p=self.ready();p.leased=True;p.manual_request(0);p.decide(0);self.assertIsNone(p.decide(.7));self.assertFalse(p.manual_pending)
        p.decide(1);self.assertEqual(p.decide(5.1),'release')
    def test_manual_pause_does_not_cancel_user_request(self):
        p=self.ready();p.owner=p.source='remote';p.remote='idle';p.manual_request(0);p.decide(0);p.decide(.7);token=p.inflight_token
        p.player(.8,'music',False);self.assertTrue(p.valid(token))
    def test_pin_recovery_is_bounded(self):
        p=self.ready();p.set_pin(0,True);p.decide(0)
        e=dict(connected=True,ready=True,owner='remote',source='remote',remote_activity='active',source_kind='media')
        p.route(1,e,1);self.assertEqual(p.decide(1),'restore');p.result(1.4,'restore',True,p.inflight_token)
        p.route(2,e,1)
        for t in (2,10,100):self.assertIsNone(p.decide(t));self.assertEqual(p.state,'LOCAL_CONTESTED')

class Controls(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.a=Adapter(True)
        p=self.a.policy;p.connected=p.ready=p.healthy=True;p.owner=p.source='linux';p.remote='idle';p.generation=1
        self.a.evaluate=lambda _:None;self.a.ensure_audio=AsyncMock()
        self.control=ControlServer(self.a,self.tmp.name,Path(self.tmp.name)/'prefs.json');await self.control.start()
    async def asyncTearDown(self):
        for writer in tuple(self.control.watchers):writer.close()
        self.control.server.close();await self.control.server.wait_closed()
        for task in list(self.a.tasks):await task
        self.tmp.cleanup()
    async def request(self,action):
        reader,writer=await asyncio.open_unix_connection(str(self.control.path));writer.write(json.dumps({'action':action}).encode()+b'\n');await writer.drain()
        result=json.loads(await reader.readline());writer.close();await writer.wait_closed();return result
    async def test_mode_persisted_and_socket_private(self):
        result=await self.request('pin');self.assertTrue(result['pinned'])
        self.assertEqual(json.loads(self.control.preferences.read_text()),{'pinned':True})
        self.assertEqual(self.control.path.stat().st_mode&0o777,0o600)
        self.assertFalse((await self.request('auto'))['pinned'])
    async def test_watch_pushes_only_changed_snapshots(self):
        reader,writer=await asyncio.open_unix_connection(str(self.control.path));writer.write(b'{"action":"watch"}\n');await writer.drain()
        first=json.loads(await reader.readline());self.assertTrue(first['available'])
        self.a.policy.pinned=True;self.control.publish();second=json.loads(await asyncio.wait_for(reader.readline(),1));self.assertTrue(second['pinned'])
        self.control.publish()
        with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(reader.readline(),.02)
        writer.close();await writer.wait_closed()
    async def test_errors_are_actionable_and_no_call_override(self):
        self.a.policy.remote_call=True
        result=await self.request('return');self.assertFalse(result['ok']);self.assertIn('звонок',result['error'])
        result=await self.request('arbitrary');self.assertFalse(result['ok'])
    async def test_status_does_not_claim_audible_from_owner_ack(self):
        self.a.policy.local_call=True;self.a.policy.source='remote'
        result=await self.request('status');self.assertFalse(result['audio_active']);self.assertNotEqual(result['title'],'Звонок на ПК')
