#!/usr/bin/env python3
"""Event adapters for the existing airpodsctl controller; no Bluetooth Connect/Disconnect."""
import time, re
import asyncio, json, os, socket, struct, logging, argparse, signal, fcntl, codecs, shutil
from pathlib import Path
from dbus_next import Message, MessageType, BusType
from dbus_next.aio import MessageBus
from airpods_handoff_policy import Policy
from airpods_call_detection import CallTracker, app_family
from airpods_audio_sessions import PlaybackTracker, candidates, stream_props, muted
from airpods_handoff_control import ControlServer

MAC=os.environ.get('AIRPODS_DEVICE','').upper().replace(':','_')
CTL=os.environ.get('AIRPODS_CTL',shutil.which('airpodsctl') or 'airpodsctl')
PACTL=os.environ.get('AIRPODS_PACTL',shutil.which('pactl') or 'pactl')
PW_LINK=os.environ.get('AIRPODS_PW_LINK',shutil.which('pw-link') or 'pw-link')
log=logging.getLogger('handoff')

def family(s):
    s=s.lower()
    if 'zen' in s: return 'firefox'
    for key in ('cider','chrome','chromium','firefox','vlc','mpv','spotify'):
        if key in s: return 'chrome' if key=='chromium' else key
    return ''

class Adapter:
    def __init__(self, shadow):
        self.control=None; self.last_command_error=None; self.baseline_call_keys=None; self.playback_tracker=PlaybackTracker(); self.fallback_streams=set(); self.call_tracker=CallTracker(); self.call_timer=None; self.policy=Policy(); self.shadow=shadow; self.nodes={}; self.clients={}; self.identities={}
        self.owners={}; self.tasks=set(); self.timer=None; self.seq={}; self.pw_ready=False; self.mpris_ready=False
        self.graph_revision=0; self.relinked=set(); self.audio_check=None; self.last_state=None; self.number=0; self.transport='unknown'; self.running=True; self.fatal=asyncio.Event()
        self.lock=asyncio.Lock(); self.ipc_lock=asyncio.Lock(); self.snapshot_lock=asyncio.Lock(); self.recovery=None; self.audio_lock=asyncio.Lock(); self.graph_changed=asyncio.Event(); self.transport_changed=self.graph_changed; self.last_audio_repair=-1e9; self.pause_tasks=set(); self.pause_armed=False; self.player_versions={}; self.uncertain_players=set()

    def spawn(self, coro):
        task=asyncio.create_task(coro); self.tasks.add(task); task.add_done_callback(self.tasks.discard)
        def done(t):
            if not t.cancelled() and t.exception():
                log.error('adapter task failed: %s',t.exception()); self.policy.healthy=False; self.evaluate('adapter-failure'); self.fatal.set()
        task.add_done_callback(done); return task

    def evaluate(self, reason):
        now=asyncio.get_running_loop().time(); self.policy.healthy=self.pw_ready and self.mpris_ready and not self.uncertain_players
        if self.policy.owner=='linux' and self.policy.source=='linux' and self.policy.media():self.pause_armed=True
        action=self.policy.decide(now)
        if self.last_state != self.policy.state or action:
            self.number+=1
            log.info('event=%s reason=%s state=%s->%s owner=%s source=%s kind=%s remote=%s media=%s action=%s shadow=%s generation=%s cooldown_ms=%s',
                self.number,reason,self.last_state,self.policy.state,self.policy.owner,self.policy.source,self.policy.source_kind,self.policy.remote,self.policy.media(),action,self.shadow,self.policy.generation,max(0,int((self.policy.cooldown-now)*1000)))
            self.last_state=self.policy.state
        if self.timer: self.timer.cancel(); self.timer=None
        deadline=self.policy.deadline(now)
        if deadline is not None: self.timer=asyncio.get_running_loop().call_at(deadline,self.evaluate,'deadline')
        if action: self.spawn(self.command(action,self.policy.inflight_token))
        if self.control:self.control.publish()
        if self.audio_eligible(self.policy.context()) and any(edge[0] not in self.relinked for edge in self.stalled_output_links()) and (self.audio_check is None or self.audio_check.done()):
            self.audio_check=self.spawn(self.ensure_audio(self.policy.context(),now))

    async def cli(self, *args):
        async with self.ipc_lock:
            return await self._cli(*args)

    async def _cli(self, *args):
        proc=await asyncio.create_subprocess_exec(CTL,'--session',*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try: out,err=await asyncio.wait_for(proc.communicate(),6)
        except asyncio.TimeoutError:
            proc.kill(); await proc.wait(); return False,''
        return proc.returncode==0,out.decode(errors='replace')

    async def command(self, action, token):
        async with self.lock:
            if not self.policy.valid(token):return
            started=asyncio.get_running_loop().time()
            if self.shadow:
                log.info('shadow decision=%s; no ownership command sent',action)
                self.policy.result(started,action,False,token); self.evaluate('shadow-result'); return
            async with self.ipc_lock:
                # Validate *after* waiting for the IPC lock. New call/pause/route events fence queued work.
                safe=self.command_eligible(action,token)
                args=('switching','take-media') if action in ('restore','claim') else ('switching',action)
                ok,out=await self._cli(*args) if safe else (False,'')
            confirmed=ok and ('owner linux' if action in ('take','restore','claim') else 'owner remote') in out
            now=asyncio.get_running_loop().time()
            applied=self.policy.result(now,action,confirmed,token)
            if applied:self.last_command_error=None if confirmed else 'Не удалось подтвердить переключение. Можно повторить вручную.'
            log.info('command=%s confirmed=%s applied=%s command_ms=%d play_to_ack_ms=%s reason=%s',action,confirmed,applied,int((now-started)*1000),int((now-self.policy.play_started)*1000) if self.policy.play_started is not None else None,'acknowledged' if confirmed else 'precondition-or-ack-failed; no retry')
            self.evaluate('command-result')
            if applied and confirmed and action in ('take','restore','claim'):self.spawn(self.ensure_audio(self.policy.context(),now))
            if confirmed and action=='release' and self.policy.peer_requested and self.policy.owner=='remote':self.spawn(self.pause_for_remote(self.policy.context()))

    def command_eligible(self,action,token):
        p=self.policy
        if not (p.valid(token) and p.connected and p.ready and p.healthy and not p.suspended):return False
        if action=='release':return p.owner=='linux' and not p.protected()
        if p.remote_call:return False
        if action=='restore':return p.local_focus and p.protected()
        if action=='claim':return (p.protected() or p.inflight_manual) and p.remote=='active' and p.source_kind=='media'
        return action=='take' and p.remote=='idle' and (p.protected() or p.inflight_manual)

    def bluez_node(self):
        for key,obj in self.nodes.items():
            info=obj.get('info') or {};props=info.get('props') or {}
            if obj.get('type')=='PipeWire:Interface:Node' and props.get('media.class')=='Audio/Sink' and str(props.get('node.name','')).startswith('bluez_output.'+MAC+'.'):
                return key,info
        return None,None

    async def transport_state(self):
        try:
            objects=(await self.call(self.system,'org.bluez','/','org.freedesktop.DBus.ObjectManager','GetManagedObjects'))[0]
            states=[interfaces['org.bluez.MediaTransport1']['State'].value for path,interfaces in objects.items() if MAC in path and 'org.bluez.MediaTransport1' in interfaces]
            self.transport='active' if 'active' in states else states[0] if states else 'unknown'
        except (RuntimeError,KeyError,asyncio.TimeoutError):self.transport='unknown'
        return self.transport

    def audio_eligible(self,context):
        return context==self.policy.context() and self.policy.connected and self.policy.owner=='linux' and not self.policy.remote_call and not self.policy.suspended and self.policy.healthy and self.policy.protected()

    async def pulse(self,*args):
        proc=await asyncio.create_subprocess_exec(PACTL,*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:out,err=await asyncio.wait_for(proc.communicate(),3)
        except asyncio.TimeoutError:
            proc.kill();await proc.wait();return False
        return proc.returncode==0

    async def wait_audio(self,predicate,timeout):
        deadline=asyncio.get_running_loop().time()+timeout
        while not predicate():
            remaining=deadline-asyncio.get_running_loop().time()
            if remaining<=0:return False
            self.transport_changed.clear()
            if predicate():return True
            try:await asyncio.wait_for(self.transport_changed.wait(),remaining)
            except asyncio.TimeoutError:return False
        return True

    def stalled_output_links(self):
        sink,_=self.bluez_node()
        result=[]
        for key,obj in self.nodes.items():
            info=obj.get('info') or {}; props=info.get('props') or {}
            source=(self.nodes.get(info.get('output-node-id'),{}).get('info') or {})
            sp=source.get('props') or {}
            identity=(key,props.get('object.serial'))
            if (obj.get('type')=='PipeWire:Interface:Link' and sink is not None and info.get('input-node-id')==sink
                    and info.get('state') in ('paused','init') and source.get('state')=='running'
                    and sp.get('media.role') not in ('Notification','Event')
                    and (sp.get('media.class')=='Stream/Output/Audio' or sp.get('application.id')=='com.github.wwmm.easyeffects')
                    ):
                result.append((identity,info.get('output-port-id'),info.get('input-port-id')))
        return result

    async def link_command(self,*args):
        proc=await asyncio.create_subprocess_exec(PW_LINK,*map(str,args),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        try:await asyncio.wait_for(proc.wait(),3)
        except asyncio.TimeoutError:proc.kill();await proc.wait();return False
        return proc.returncode==0

    async def repair_output_links(self,context):
        if self.shadow or not self.audio_eligible(context) or self.policy.source!='linux':return
        repaired=0
        for identity,output,input_ in self.stalled_output_links():
            if identity in self.relinked:continue
            if not self.audio_eligible(context) or self.policy.source!='linux':return
            if (identity,output,input_) not in self.stalled_output_links():continue
            if output is None or input_ is None:continue
            if len(self.relinked)>=128:
                log.warning('output-link repair budget exhausted; no further mutations');return
            self.relinked.add(identity)
            # Re-create only a proven stalled edge into this A2DP sink, leaving mic/effect chain intact.
            removed=await self.link_command('-d',output,input_)
            if not removed:continue
            # Undo the temporary disconnection even if ownership changes during the command.
            restored=await self.link_command(output,input_)
            if not restored:restored=await self.link_command(output,input_)
            repaired+=int(restored)
            log.log(logging.INFO if restored else logging.ERROR,'stalled A2DP output-link repaired=%s edge=%s; one attempt per link generation',restored,identity)
        return repaired

    def audio_active(self):
        _,info=self.bluez_node()
        return bool(self.policy.source=='linux' and self.transport=='active' and info
                    and info.get('state')=='running' and not self.stalled_output_links())

    def audio_sink_failed(self):
        _,info=self.bluez_node()
        return bool(info and info.get('state')=='error')

    def pending_audio_links(self):
        return (self.policy.source=='linux' and len(self.relinked)<128
                and any(edge[0] not in self.relinked for edge in self.stalled_output_links()))

    async def wait_audio_flow(self,context,timeout,stop_on_error=False):
        """Repair newly arriving graph edges in this attempt, not a later queued check."""
        deadline=asyncio.get_running_loop().time()+timeout
        while self.audio_eligible(context):
            if self.audio_active():return True
            if self.pending_audio_links():await self.repair_output_links(context)
            if not self.audio_eligible(context):return False
            if self.audio_active():return True
            if stop_on_error and self.audio_sink_failed():return False
            remaining=deadline-asyncio.get_running_loop().time()
            if remaining<=0:return False
            def progress():
                return (self.audio_active() or not self.audio_eligible(context) or self.pending_audio_links()
                        or (stop_on_error and self.audio_sink_failed()))
            if not await self.wait_audio(progress,remaining):return False
        return False

    async def ensure_audio(self,context,ack_at):
        if self.shadow:return
        async with self.audio_lock:
            if not self.audio_eligible(context):return
            if self.audio_active():
                log.info('audio-active ack_to_active_ms=%d source=linux path=already-ready',int((asyncio.get_running_loop().time()-ack_at)*1000));return
            # Error and stalled-edge events end the grace immediately. Only an
            # unremarkable handoff still gets the natural-transition timeout.
            def progress():
                return self.audio_active() or self.audio_sink_failed() or self.pending_audio_links() or not self.audio_eligible(context)
            await self.wait_audio(progress,.8)
            if not self.audio_eligible(context):return
            if self.pending_audio_links():
                if await self.wait_audio_flow(context,.4,stop_on_error=True):
                    log.info('audio-active ack_to_active_ms=%d source=linux path=graph-only',int((asyncio.get_running_loop().time()-ack_at)*1000));return
            if self.audio_active():
                log.info('audio-active ack_to_active_ms=%d source=linux path=natural',int((asyncio.get_running_loop().time()-ack_at)*1000));return
            # A known PipeWire error is already sufficient evidence to repair.
            # A fresh BlueZ read is a fallback for a missing transport event only.
            if not self.audio_sink_failed():
                await self.transport_state()
                if not self.audio_eligible(context):return
                if self.audio_active():
                    log.info('audio-active ack_to_active_ms=%d source=linux path=transport-snapshot',int((asyncio.get_running_loop().time()-ack_at)*1000));return
            now=asyncio.get_running_loop().time()
            if now-self.last_audio_repair<10:
                log.warning('audio recovery suppressed: cooldown; no reconnect/profile reset');return
            _,info=self.bluez_node()
            if not info:
                log.warning('audio recovery unavailable: no matching A2DP sink; no reconnect');return
            sink=info['props']['node.name']
            self.last_audio_repair=now
            log.warning('audio recovery: one suspend/resume of existing sink; source=%s transport=%s node=%s first_repair_ms=%d',self.policy.source,self.transport,info.get('state'),int((now-ack_at)*1000))
            attempted=False
            try:
                attempted=True
                suspended=await self.pulse('suspend-sink',sink,'1')
                if not suspended:return
                def suspended_state():
                    _,node=self.bluez_node()
                    return self.transport=='idle' or (node and node.get('state')=='suspended') or not self.audio_eligible(context)
                await self.wait_audio(suspended_state,.3)
            finally:
                # Always undo our own suspension, including a lost suspend ACK
                # or a phone call which arrived while the request was in flight.
                if attempted:
                    resumed=await self.pulse('suspend-sink',sink,'0')
                    if not resumed:resumed=await self.pulse('suspend-sink',sink,'0')
                    log.log(logging.INFO if resumed else logging.ERROR,'audio recovery resume=%s context_current=%s',resumed,context==self.policy.context())
            if not self.audio_eligible(context):return
            # AACP events already carry the authoritative source for this
            # generation. Do not block graph repair on a redundant CLI snapshot.
            ready=await self.wait_audio_flow(context,1.5)
            if not self.audio_eligible(context):return
            if not ready:
                await self.transport_state()
                if not self.audio_eligible(context):return
                ready=self.audio_active()
            log.info('audio recovery result ready=%s transport=%s source=%s ack_to_check_ms=%d; no further retries',ready,self.transport,self.policy.source,int((asyncio.get_running_loop().time()-ack_at)*1000))
            if ready:log.info('audio-active ack_to_active_ms=%d source=linux path=recovered',int((asyncio.get_running_loop().time()-ack_at)*1000))

    async def verify_local_play(self,context):
        # A stream/route event may be ready immediately; there is no fixed sleep.
        def progress():
            return self.audio_eligible(context) or context!=self.policy.context() or self.policy.remote_call or not self.policy.connected or self.policy.suspended
        await self.wait_audio(progress,.7)
        if self.audio_eligible(context):await self.ensure_audio(context,asyncio.get_running_loop().time())

    async def pause_for_remote(self,context):
        # Yield only currently tracked media. Never auto-resume after the peer takes over.
        if self.shadow or self.policy.protected():return
        for name in list(self.policy.streams):
            if context!=self.policy.context() or self.policy.owner!='remote' or self.policy.protected():return
            if self.policy.players.get(name) and name in self.identities:
                try:
                    await self.call(self.session,name,'/org/mpris/MediaPlayer2','org.mpris.MediaPlayer2.Player','Pause')
                    log.info('remote takeover: requested Pause for matched player; no automatic resume')
                except (RuntimeError,asyncio.TimeoutError):log.warning('remote takeover: player Pause unavailable')

    def schedule_recovery(self):
        if self.recovery is None or self.recovery.done():
            self.recovery=self.spawn(self.recover())

    async def recover(self):
        for delay in (0,1,3,8):
            if delay:await asyncio.sleep(delay)
            if self.policy.connected and self.policy.ready and self.policy.generation is not None:return
            try:
                reply=await self.call(self.system,'org.bluez','/org/bluez/hci0/dev_'+MAC,'org.freedesktop.DBus.Properties','Get','ss',['org.bluez.Device1','Connected'])
                if not reply[0].value:return
            except (RuntimeError,asyncio.TimeoutError):return
            await self.snapshot()
            if self.policy.connected and self.policy.ready and self.policy.generation is not None:return
        if not self.policy.connected:log.warning('bounded AACP recovery ended; waiting for next BlueZ event')

    async def snapshot(self):
        async with self.snapshot_lock:
            ok,out=await self.cli('switching','status')
            if not ok: return
            values=dict(line.split(' ',1) for line in out.splitlines() if ' ' in line)
            if self.policy.generation is None:
                self.policy.route(asyncio.get_running_loop().time(),{
                    'connected':True,'ready':values.get('multipoint')=='ready',
                    'owner':values.get('owner','unknown'),'remote_activity':values.get('remote-activity','unknown')},'snapshot')
                self.evaluate('initial-aacp-snapshot')

    def routing_socket(self):
        self.guard=open(Path(os.environ['XDG_RUNTIME_DIR'])/'airpods-handoff.lock','a')
        fcntl.flock(self.guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.path=Path(os.environ['XDG_RUNTIME_DIR'])/'airpods-handoff.events'
        if self.path.exists(): self.path.unlink()
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1)
        self.sock.bind(str(self.path)); os.chmod(self.path,0o600); self.sock.setblocking(False)
        asyncio.get_running_loop().add_reader(self.sock.fileno(),self.routing_event)

    def routing_event(self):
        try:
            data,anc,flags,_=self.sock.recvmsg(1024,socket.CMSG_SPACE(12))
            creds=[struct.unpack('3i',c) for level,kind,c in anc if level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS]
            if flags & socket.MSG_TRUNC or not creds or creds[0][1]!=os.getuid(): return
            pid=creds[0][0]
            if Path('/proc',str(pid),'exe').resolve()!=Path(CTL).resolve(): return
            e=json.loads(data)
            if e.get('version') not in (1,2) or type(e.get('sequence')) is not int: return
            prev=self.seq.get(pid,0)
            if e['sequence']<=prev: return
            if prev and e['sequence']!=prev+1:
                self.policy.invalidate(); log.warning('AACP event gap; asynchronous decisions invalidated')
            self.seq[pid]=e['sequence']
            self.observe_route(e,(pid,e['generation']))
        except (ValueError,KeyError,OSError): log.warning('invalid routing event ignored')

    def observe_route(self,e,generation):
        if self.policy.generation!=generation:self.pause_armed=False
        self.policy.route(asyncio.get_running_loop().time(),e,generation)
        if not e.get('connected'):self.pause_armed=False
        if e.get('release_request') is True:
            self.policy.peer_request(asyncio.get_running_loop().time());log.info('peer ownership request protected=%s; defer while local audio session is active',self.policy.protected())
        self.transport_changed.set()
        if self.pause_armed and not self.policy.protected() and self.policy.owner=='remote' and self.policy.remote=='active':
            self.pause_armed=False
            self.spawn(self.pause_for_remote(self.policy.context()))
        self.evaluate('aacp-routing')
        if not e.get('connected'):self.schedule_recovery()

    async def call(self,bus,destination,path,interface,member,signature='',body=None):
        reply=await asyncio.wait_for(bus.call(Message(destination=destination,path=path,interface=interface,member=member,signature=signature,body=body or [])),3)
        if reply.message_type==MessageType.ERROR: raise RuntimeError(reply.error_name)
        return reply.body

    async def add_player(self,name,baseline=True):
        version=self.player_versions.get(name,0)
        try:
            owner=(await self.call(self.session,'org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','s',[name]))[0]
            self.owners[owner]=name
            pid=(await self.call(self.session,'org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID','s',[owner]))[0]
            self.identities[name]=(pid,family(name))
            props=(await self.call(self.session,name,'/org/mpris/MediaPlayer2','org.freedesktop.DBus.Properties','GetAll','s',['org.mpris.MediaPlayer2.Player']))[0]
            if version!=self.player_versions.get(name,0) or self.owners.get(owner)!=name:return
            self.uncertain_players.discard(name)
            self.policy.player(asyncio.get_running_loop().time(),name,props['PlaybackStatus'].value=='Playing',baseline)
            self.correlate(); self.evaluate('mpris-initial-snapshot')
            return True
        except (RuntimeError,KeyError,asyncio.TimeoutError):
            log.warning('MPRIS snapshot unavailable; no playback edge inferred')
            return False

    def correlate(self):
        streams=set(); covered=set(); communication=False
        clients={key:(obj.get('info') or {}).get('props',{}) for key,obj in self.nodes.items() if obj.get('type')=='PipeWire:Interface:Client'}
        for key,obj in self.nodes.items():
            info=obj.get('info') or {}; props=stream_props(self.nodes,obj)
            if props.get('media.class')!='Stream/Output/Audio' or info.get('state') not in ('running','idle','error'): continue
            role=str(props.get('media.role','')).lower()
            # Communication uses the lifecycle tracker, including its stop grace.
            if role in ('notification','event','communication','production','filter','dsp'): continue
            if app_family(props) and role not in ('music','movie','video','game'):continue
            p=str(props.get('application.process.id',''))
            f=family(str(props.get('application.name',''))+' '+str(props.get('application.process.binary','')))
            params=info.get('params',{}).get('Props',[])
            if any(x.get('mute') is True or x.get('softMute') is True or x.get('channelVolumes') and max(x['channelVolumes'])<=0 for x in params): continue
            for name,(pid,app) in self.identities.items():
                if p==str(pid) or (app and app==f):
                    covered.add(key)
                    if info.get('state')=='running' or name in self.policy.streams and self.policy.players.get(name):streams.add(name)
        old_streams=self.policy.streams
        now=time.monotonic()
        fallback=self.playback_tracker.observe(now,candidates(self.nodes,covered)) if self.pw_ready else set()
        for key in self.fallback_streams-fallback:
            self.policy.player(now,key,False);self.policy.players.pop(key,None)
        for key in fallback-self.fallback_streams:
            self.policy.player(now,key,True,baseline=key in self.playback_tracker.baseline)
            log.info('PipeWire fallback playback started; baseline=%s source=%s',key in self.playback_tracker.baseline,key)
        self.fallback_streams=fallback
        self.policy.streams=streams|fallback
        if self.policy.streams != old_streams:
            log.info('media-stream-match mpris=%s fallback=%s; notifications/captures/muted excluded',len(streams),len(fallback))
        active=self.call_tracker.observe(now,self.nodes)
        if self.policy.local_call != (communication or active):
            log.info('local communication protected=%s evidence=%s; duplex lifecycle with silence grace',communication or active,self.call_tracker.evidence)
        if self.baseline_call_keys is None and self.pw_ready:self.baseline_call_keys=set(self.call_tracker.candidates)
        baseline=self.baseline_call_keys is None or all(key in self.baseline_call_keys for key in self.call_tracker.candidates)
        self.policy.calls(communication or active,now=None if baseline else now)
        if self.baseline_call_keys is not None:self.baseline_call_keys.intersection_update(self.call_tracker.candidates)
        if self.call_timer:self.call_timer.cancel();self.call_timer=None
        deadline=min((d for d in (self.call_tracker.deadline(now),self.playback_tracker.deadline(now)) if d is not None),default=None)
        if deadline is not None:self.call_timer=asyncio.get_running_loop().call_at(deadline,self.call_tick)

    def call_tick(self):
        self.correlate();self.evaluate('communication-session-debounce')

    def session_signal(self,msg):
        if msg.message_type!=MessageType.SIGNAL:return
        if msg.interface=='org.freedesktop.DBus' and msg.member=='NameOwnerChanged':
            name,old,new=msg.body
            if name.startswith('org.mpris.MediaPlayer2.'):
                self.player_versions[name]=self.player_versions.get(name,0)+1
                self.uncertain_players.discard(name)
                if old:
                    self.owners.pop(old,None); self.identities.pop(name,None)
                    self.policy.player(asyncio.get_running_loop().time(),name,False)
                if new:self.spawn(self.add_player(name,not self.mpris_ready))
                self.correlate(); self.evaluate('mpris-owner-change')
            return
        name=self.owners.get(msg.sender)
        if name and msg.interface=='org.freedesktop.DBus.Properties' and msg.member=='PropertiesChanged':
            interface,changes,invalidated=msg.body
            if interface=='org.mpris.MediaPlayer2.Player':
                if 'PlaybackStatus' in changes:
                    self.uncertain_players.discard(name)
                    log.info('MPRIS playback=%s source=%s baseline=%s',changes['PlaybackStatus'].value,self.identities.get(name,(None,''))[1],not self.mpris_ready)
                    self.policy.player(asyncio.get_running_loop().time(),name,changes['PlaybackStatus'].value=='Playing',not self.mpris_ready)
                    self.correlate(); self.evaluate('mpris-playback-edge')
                    if changes['PlaybackStatus'].value=='Playing':
                        if self.policy.remote!='idle' or not self.policy.ready:self.spawn(self.snapshot())
                        self.spawn(self.verify_local_play(self.policy.context()))
                elif 'PlaybackStatus' in invalidated:
                    self.uncertain_players.add(name);self.policy.invalidate(clear_lease=False);self.evaluate('mpris-status-unknown');self.spawn(self.refresh_player(name))

    async def refresh_player(self,name):
        for delay in (0,.25,1):
            if delay:await asyncio.sleep(delay)
            if name not in self.uncertain_players:return
            if await self.add_player(name,True):return
        log.warning('MPRIS refresh exhausted; waiting for status/owner event, no playback inferred')

    def system_signal(self,msg):
        if msg.message_type!=MessageType.SIGNAL:return
        if msg.interface=='org.freedesktop.login1.Manager' and msg.member=='PrepareForSleep':
            sleeping=msg.body[0]
            if sleeping:self.reset_session_tracking()
            self.policy.sleep(asyncio.get_running_loop().time(),sleeping);self.evaluate('sleep' if sleeping else 'resume')
            if not sleeping:self.spawn(self.resume_baseline())
            return
        if msg.interface=='org.freedesktop.DBus.Properties' and msg.member=='PropertiesChanged':
            interface,changes,_=msg.body
            if MAC in (msg.path or ''):
                if interface=='org.bluez.MediaTransport1' and 'State' in changes:
                    self.transport=changes['State'].value;self.transport_changed.set(); self.evaluate('bluez-transport')
                if interface=='org.bluez.Device1' and 'Connected' in changes:
                    if changes['Connected'].value:
                        self.policy.generation=None; self.schedule_recovery()
                    else:
                        self.policy.route(asyncio.get_running_loop().time(),{'connected':False},None)
                        self.evaluate('bluez-disconnected')
        elif msg.interface=='org.freedesktop.DBus.ObjectManager' and msg.member=='InterfacesAdded':
            path,interfaces=msg.body
            if MAC in path and 'org.bluez.MediaTransport1' in interfaces:
                value=interfaces['org.bluez.MediaTransport1'].get('State')
                if value:self.transport=value.value;self.transport_changed.set();self.evaluate('bluez-transport-created')
            if MAC in path and 'org.bluez.Device1' in interfaces and interfaces['org.bluez.Device1'].get('Connected') and interfaces['org.bluez.Device1']['Connected'].value:self.schedule_recovery()
        elif msg.interface=='org.freedesktop.DBus.ObjectManager' and msg.member=='InterfacesRemoved':
            if MAC in msg.body[0] and 'org.bluez.MediaTransport1' in msg.body[1]:self.transport='unknown';self.transport_changed.set()
            if MAC in msg.body[0] and 'org.bluez.Device1' in msg.body[1]:
                self.policy.route(asyncio.get_running_loop().time(),{'connected':False},None);self.evaluate('bluez-device-removed')
        elif msg.interface=='org.freedesktop.DBus' and msg.member=='NameOwnerChanged':
            if msg.body[0]=='org.bluez' and not msg.body[2]:
                self.policy.route(asyncio.get_running_loop().time(),{'connected':False},None);self.evaluate('bluez-restarted')
            elif msg.body[0]=='org.bluez' and msg.body[2]:self.schedule_recovery()

    def reset_session_tracking(self):
        self.call_tracker=CallTracker()
        self.baseline_call_keys=None
        self.policy.calls(False)
        self.playback_tracker.reset()
        for key in self.fallback_streams:self.policy.players.pop(key,None)
        self.fallback_streams.clear()
        self.policy.streams.clear()
        if self.call_timer:self.call_timer.cancel();self.call_timer=None

    async def refresh_graph(self):
        revision=self.graph_revision
        proc=await asyncio.create_subprocess_exec(os.environ.get('AIRPODS_PW_DUMP','/run/current-system/sw/bin/pw-dump'),'--no-colors',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        try:out,_=await asyncio.wait_for(proc.communicate(),4)
        except asyncio.TimeoutError:
            proc.kill();await proc.wait();log.warning('resume graph snapshot timed out');return False
        if proc.returncode or len(out)>8_000_000:return False
        try:objects=json.loads(out)
        except (ValueError,UnicodeError):return False
        if revision==self.graph_revision:
            self.nodes={obj['id']:obj for obj in objects if obj.get('info') is not None}
            self.graph_revision+=1
        self.graph_changed.set()
        return True

    async def resume_baseline(self):
        self.mpris_ready=False
        await asyncio.gather(*(self.add_player(name,True) for name in list(self.identities)))
        refreshed=await self.refresh_graph()
        self.mpris_ready=True
        if not refreshed:
            log.warning('resume graph baseline unavailable; stopping adapter for fresh initialization')
            self.fatal.set();return
        self.correlate();self.schedule_recovery();self.evaluate('resume-baseline')

    async def pipewire(self):
        proc=await asyncio.create_subprocess_exec(os.environ.get('AIRPODS_PW_DUMP','/run/current-system/sw/bin/pw-dump'),'--monitor','--no-colors',stdout=asyncio.subprocess.PIPE)
        self.pwproc=proc; buffer=''; decoder=json.JSONDecoder(); utf8=codecs.getincrementaldecoder('utf-8')()
        try:
            while chunk:=await proc.stdout.read(65536):
                buffer+=utf8.decode(chunk)
                if len(buffer)>8_000_000:raise RuntimeError('PipeWire monitor buffer exceeded')
                while buffer.strip():
                    buffer=buffer.lstrip()
                    try:batch,end=decoder.raw_decode(buffer)
                    except json.JSONDecodeError:break
                    buffer=buffer[end:]
                    for obj in batch:
                        key=obj['id']
                        if len(obj)==1 or obj.get('info',{}) is None:self.nodes.pop(key,None);continue
                        old=self.nodes.setdefault(key,{})
                        if 'type' in obj:old['type']=obj['type']
                        if 'info' in obj:
                            info=old.setdefault('info',{})
                            for k,v in obj['info'].items():
                                if k in ('props','params') and isinstance(v,dict):info.setdefault(k,{}).update(v)
                                else:info[k]=v
                    self.graph_revision+=1
                    self.pw_ready=True;self.correlate();self.graph_changed.set();self.evaluate('pipewire-graph')
            raise RuntimeError('PipeWire event monitor exited')
        finally:
            self.pw_ready=False;self.policy.local_focus=False;self.policy.invalidate();self.evaluate('pipewire-unavailable')
            if proc.returncode is None:proc.terminate();await proc.wait()

    async def main(self):
        self.routing_socket()
        self.control=ControlServer(self)
        await self.control.start()
        self.session=await MessageBus().connect(); self.system=await MessageBus(bus_type=BusType.SYSTEM).connect()
        self.session.add_message_handler(self.session_signal);self.system.add_message_handler(self.system_signal)
        for bus,matches in ((self.session,["type='signal',interface='org.freedesktop.DBus.Properties'","type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged'"]),
                            (self.system,["type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'","type='signal',sender='org.bluez'","type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.bluez'"])):
            for match in matches:await self.call(bus,'org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','AddMatch','s',[match])
        names=(await self.call(self.session,'org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames'))[0]
        await asyncio.gather(*(self.add_player(name,True) for name in names if name.startswith('org.mpris.MediaPlayer2.')))
        self.mpris_ready=True
        try:
            objects=(await self.call(self.system,'org.bluez','/','org.freedesktop.DBus.ObjectManager','GetManagedObjects'))[0]
            for path,interfaces in objects.items():
                if MAC in path and 'org.bluez.MediaTransport1' in interfaces:
                    self.transport=interfaces['org.bluez.MediaTransport1']['State'].value
        except (RuntimeError,KeyError,asyncio.TimeoutError):log.warning('Initial BlueZ transport snapshot unavailable')
        self.schedule_recovery(); self.spawn(self.pipewire())
        log.info('event adapters ready shadow=%s; no Bluetooth reconnection or profile reset policy',self.shadow)
        await asyncio.wait([asyncio.create_task(self.session.wait_for_disconnect()),asyncio.create_task(self.system.wait_for_disconnect()),asyncio.create_task(self.fatal.wait())],return_when=asyncio.FIRST_COMPLETED)
        raise RuntimeError('Event adapter disconnected; restart from fresh baselines')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Event-driven AirPods media handoff (experimental)')
    parser.add_argument('--shadow',action='store_true',help='Log decisions without switching or changing audio')
    parser.add_argument('--device',default=os.environ.get('AIRPODS_DEVICE',''),help='Paired AirPods Bluetooth address, or AIRPODS_DEVICE')
    args=parser.parse_args()
    if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',args.device):parser.error('--device or AIRPODS_DEVICE must be a Bluetooth address (AA:BB:CC:DD:EE:FF)')
    MAC=args.device.upper().replace(':','_')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    def terminate(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    try:asyncio.run(Adapter(args.shadow).main())
    except KeyboardInterrupt:pass
