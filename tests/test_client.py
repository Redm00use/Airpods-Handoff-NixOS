import os
os.environ.setdefault('AIRPODS_DEVICE','AA:BB:CC:DD:EE:FF')
import asyncio,json,sys,tempfile,unittest
from pathlib import Path
from airpods_handoff import Adapter
from airpods_handoff_control import ControlServer

class ClientContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.adapter=Adapter(True);self.adapter.evaluate=lambda _:None
        self.server=ControlServer(self.adapter,self.tmp.name,Path(self.tmp.name)/'prefs.json');await self.server.start()
        self.client=Path(__file__).resolve().parent.parent/'src/handoffctl.py'
    async def asyncTearDown(self):
        for writer in tuple(self.server.watchers):writer.close()
        self.server.server.close();await self.server.server.wait_closed();self.tmp.cleanup()
    async def launch(self,action,runtime=None):
        return await asyncio.create_subprocess_exec(sys.executable,str(self.client),action,env={**os.environ,'XDG_RUNTIME_DIR':runtime or self.tmp.name},stdout=asyncio.subprocess.PIPE)
    async def test_status_and_pin_auto_roundtrip(self):
        for action,pinned in (('status',False),('pin',True),('auto',False)):
            proc=await self.launch(action);out,_=await proc.communicate();self.assertEqual(proc.returncode,0)
            self.assertEqual(json.loads(out)['pinned'],pinned)
    async def test_missing_service_has_json_error_and_nonzero_exit(self):
        proc=await self.launch('status',str(Path(self.tmp.name)/'missing'));out,_=await proc.communicate()
        self.assertEqual(proc.returncode,1);self.assertFalse(json.loads(out)['available'])
    async def test_watch_delivers_changed_state(self):
        proc=await self.launch('watch')
        try:
            self.assertFalse(json.loads(await asyncio.wait_for(proc.stdout.readline(),2))['pinned'])
            self.adapter.policy.pinned=True;self.server.publish()
            self.assertTrue(json.loads(await asyncio.wait_for(proc.stdout.readline(),2))['pinned'])
        finally:proc.terminate();await proc.wait()
