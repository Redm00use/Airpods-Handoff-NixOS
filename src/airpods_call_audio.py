"""Keep an already-owned call's A2DP stream clocked during silence/mute.

Zero PCM only, never microphone capture. Not a call detector or ownership command.
"""
import asyncio
import json
import logging

log = logging.getLogger('handoff.call-audio')

class CallAudioGuard:
    def __init__(self, binary, changed=lambda: None):
        self.binary = binary
        self.changed = changed
        self.process = None
        self.target = None
        self.desired = None
        self.session = None
        self.starts = 0
        self.task = None
        self.watchers = set()

    @property
    def active(self):
        return self.process is not None and self.process.returncode is None

    def update(self, enabled, target=None, session=None):
        if self.session != session:
            self.session = session
            self.starts = 0
        self.desired = target if enabled else None
        if self.active and self.target == self.desired:
            return
        if self.process is None and (self.task is None or self.task.done()) and (not self.desired or self.starts >= 3):
            return
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.reconcile())

    async def watch(self, proc):
        await proc.wait()
        if self.process is proc:
            self.process = None
            self.target = None
            self.changed()

    async def reconcile(self):
        if self.process is not None and (not self.active or self.target != self.desired):
            proc = self.process
            if proc.returncode is None:
                proc.terminate()
                try:await asyncio.wait_for(proc.wait(), 2)
                except asyncio.TimeoutError:proc.kill(); await proc.wait()
            if self.process is proc:self.process = None
            self.target = None
        if self.desired and self.process is None and self.starts < 3:
            self.starts += 1
            target = self.desired
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.binary, '--playback', '--raw', '--format', 'f32',
                    '--rate', '48000', '--channels', '2', '--target', target,
                    '--media-role', 'Notification', '--properties',
                    json.dumps({'application.name':'AirPods Call Guard',
                                'node.name':'airpods-call-guard', 'node.dont-reconnect':True}),
                    '/dev/zero', stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                self.process, self.target = proc, target
                task = asyncio.create_task(self.watch(proc))
                self.watchers.add(task); task.add_done_callback(self.watchers.discard)
                log.info('call audio guard started target=%s session=%s; zero PCM only',target,self.session)
            except OSError as error:
                log.warning('call audio guard unavailable: %s',error)
        if self.process is not None and self.desired != self.target:
            await self.reconcile()
        self.changed()

    async def close(self):
        self.desired = None
        if self.task and not self.task.done():await self.task
        await self.reconcile()
        if self.watchers:await asyncio.gather(*tuple(self.watchers),return_exceptions=True)
