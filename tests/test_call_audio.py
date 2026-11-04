import os
os.environ.setdefault('AIRPODS_DEVICE','AA:BB:CC:DD:EE:FF')
import asyncio
import unittest
from unittest.mock import AsyncMock,Mock,patch
from airpods_call_audio import CallAudioGuard
from airpods_call_detection import call_sessions
from airpods_audio_sessions import candidates
import test_priority as fixtures

class Process:
    def __init__(self):self.returncode=None;self.ended=asyncio.Event();self.terminate=Mock(side_effect=self.end)
    def end(self):self.returncode=0;self.ended.set()
    async def wait(self):await self.ended.wait();return self.returncode
    def kill(self):self.end()

class Guard(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.processes=[]
        async def spawn(*args,**kwargs):
            p=Process();self.processes.append(p);return p
        self.spawn=AsyncMock(side_effect=spawn);self.patch=patch('airpods_call_audio.asyncio.create_subprocess_exec',self.spawn);self.patch.start()
        self.guard=CallAudioGuard('/fake/pw-cat')
    async def asyncTearDown(self):await self.guard.close();self.patch.stop()
    async def start(self,session=1):
        self.guard.update(True,'bluez_output.TEST.1',session)
        if self.guard.task:await self.guard.task
    async def test_only_zero_pcm_targeted_to_headphones_no_microphone(self):
        await self.start();args=self.spawn.await_args.args
        self.assertIn('--playback',args);self.assertNotIn('--record',args);self.assertEqual(args[-1],'/dev/zero')
        self.assertEqual(args[args.index('--target')+1],'bluez_output.TEST.1')
        self.assertEqual(args[args.index('--media-role')+1],'Notification')
    async def test_updates_do_not_duplicate_process_and_hangup_stops_it(self):
        await self.start()
        for _ in range(10):await self.start()
        self.assertEqual(self.spawn.await_count,1);self.guard.update(False,session=1);await self.guard.task
        self.assertFalse(self.guard.active);self.processes[0].terminate.assert_called_once()
    async def test_restart_budget_is_per_call_not_graph_event(self):
        for _ in range(3):
            await self.start();self.processes[-1].end();await asyncio.sleep(0);await asyncio.sleep(0)
        for _ in range(5):await self.start()
        self.assertEqual(self.spawn.await_count,3)
        await self.start(2);self.assertEqual(self.spawn.await_count,4)
    async def test_hangup_during_process_creation_still_closes_child(self):
        gate=asyncio.Event();proc=Process()
        async def delayed(*args,**kwargs):await gate.wait();return proc
        self.spawn.side_effect=delayed;self.guard.update(True,'bluez_output.TEST.1',1)
        await asyncio.sleep(0);self.guard.update(False,session=1);gate.set();await self.guard.task
        proc.terminate.assert_called_once();self.assertFalse(self.guard.active)
    async def test_disabled_shadow_or_idle_never_starts_process(self):
        self.guard.update(False,session=0);await asyncio.sleep(0);self.spawn.assert_not_awaited()

class Exclusions(unittest.TestCase):
    def test_silent_guard_does_not_create_call_or_media_lease(self):
        n={'type':'PipeWire:Interface:Node','info':{'state':'running','props':{'media.class':'Stream/Output/Audio','application.name':'AirPods Call Guard','node.name':'airpods-call-guard','media.role':'Notification'}}}
        self.assertFalse(call_sessions({1:n}));self.assertFalse(candidates({1:n},set()))

class StableEdge(unittest.IsolatedAsyncioTestCase):
    async def test_recreated_link_cannot_reset_repair_budget(self):
        a=fixtures.OutputLinkRepair.setup_graph(self);ctx=a.policy.context()
        await a.repair_output_links(ctx)
        for serial in range(101,110):
            a.nodes[10]['info']['props']['object.serial']=serial
            await a.repair_output_links(ctx)
        self.assertEqual(a.link_command.await_count,2)
        self.assertFalse(a.pending_audio_links());self.assertFalse(a.audio_active())
    async def test_new_port_generation_can_be_repaired(self):
        a=fixtures.OutputLinkRepair.setup_graph(self);ctx=a.policy.context();await a.repair_output_links(ctx)
        a.nodes[10]['info']['props']['object.serial']=102
        a.nodes[20]={'info':{'props':{'object.serial':999}}}
        await a.repair_output_links(ctx);self.assertEqual(a.link_command.await_count,4)
