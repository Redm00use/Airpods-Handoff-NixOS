#!/usr/bin/env python3
"""Event adapters for the existing airpodsctl controller; no Bluetooth Connect/Disconnect."""
import asyncio, json, os, socket, struct, logging, argparse, signal, fcntl, codecs, shutil, re
from pathlib import Path
from dbus_next import Message, MessageType, BusType
from dbus_next.aio import MessageBus
from airpods_handoff_policy import Policy

MAC=os.environ.get('AIRPODS_DEVICE','').upper().replace(':','_')
CTL=os.environ.get('AIRPODS_CTL',shutil.which('airpodsctl') or 'airpodsctl')
PACTL=os.environ.get('AIRPODS_PACTL',shutil.which('pactl') or 'pactl')
log=logging.getLogger('handoff')

def family(s):
    s=s.lower()
    for key in ('cider','chrome','chromium','firefox','vlc','mpv','spotify'):
        if key in s: return 'chrome' if key=='chromium' else key
    return ''

class Adapter:
    def __init__(self, shadow):
        self.policy=Policy(); self.shadow=shadow; self.nodes={}; self.clients={}; self.identities={}
        self.owners={}; self.tasks=set(); self.timer=None; self.seq={}; self.pw_ready=False; self.mpris_ready=False
        self.last_state=None; self.number=0; self.transport='unknown'; self.running=True; self.fatal=asyncio.Event()
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

    async def cli(self, *args):
        async with self.ipc_lock:
            return await self._cli(*args)

    async def _cli(self, *args):
        proc=await asyncio.create_subprocess_exec(CTL,'--session','--device',MAC.replace('_',':'),*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
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
            # The controller refreshes routing and validates remote-idle inside the same command.
            # Do not add a separate status round trip, nor trust a token queued before another event.
            safe=self.policy.valid(token) and not self.policy.suspended and self.policy.connected
            safe=safe and (action=='release' or (not self.policy.remote_call and self.policy.can_take() and self.policy.ready and self.policy.media() and not self.policy.local_call))
            if action=='release' and (self.policy.owner!='linux' or ((self.policy.media() or self.policy.local_call) and not self.policy.peer_requested)):safe=False
            async with self.ipc_lock:
                operation='take-media' if action=='take' and self.policy.allow_remote_media else action
                ok,out=await self._cli('switching',operation) if safe and self.policy.valid(token) and self.policy.healthy and (action!='take' or self.policy.media()) else (False,'')
            confirmed=ok and ('owner linux' if action=='take' else 'owner remote') in out
            now=asyncio.get_running_loop().time()
            applied=self.policy.result(now,action,confirmed,token)
            log.info('command=%s confirmed=%s applied=%s command_ms=%d play_to_ack_ms=%s reason=%s',action,confirmed,applied,int((now-started)*1000),int((now-self.policy.play_started)*1000) if self.policy.play_started is not None else None,'acknowledged' if confirmed else 'precondition-or-ack-failed; no retry')
            self.evaluate('command-result')
            if applied and confirmed and action=='take':self.spawn(self.ensure_audio(self.policy.context(),now))
            if confirmed and action=='release' and self.policy.peer_requested and self.policy.owner=='remote':self.spawn(self.pause_for_remote(self.policy.context()))

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
        return context==self.policy.context() and self.policy.connected and self.policy.owner=='linux' and not self.policy.remote_call and not self.policy.suspended and self.policy.healthy and self.policy.media()

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

    async def ensure_audio(self,context,ack_at):
        # Wait for the actual source/transport events, not an ownership ACK alone.
        if self.shadow:return
        async with self.audio_lock:
            if not self.audio_eligible(context):return
            def active():
                _,info=self.bluez_node()
                return self.policy.source=='linux' and self.transport=='active' and info and info.get('state')=='running'
            await self.wait_audio(active,.8)
            if not self.audio_eligible(context):return
            await self.transport_state()
            if not self.audio_eligible(context):return
            _,info=self.bluez_node()
            if active():
                log.info('audio-active ack_to_active_ms=%d source=linux',int((asyncio.get_running_loop().time()-ack_at)*1000));return
            now=asyncio.get_running_loop().time()
            if now-self.last_audio_repair<10:
                log.warning('audio recovery suppressed: cooldown; no reconnect/profile reset');return
            if not info:
                log.warning('audio recovery unavailable: no matching A2DP sink; no reconnect');return
            sink=info['props']['node.name']
            self.last_audio_repair=now
            log.warning('audio recovery: one suspend/resume of existing sink; source=%s transport=%s node=%s',self.policy.source,self.transport,info.get('state'))
            suspended=False
            attempted=False
            try:
                attempted=True
                suspended=await self.pulse('suspend-sink',sink,'1')
                if not suspended:return
                def suspended_state():
                    _,node=self.bluez_node()
                    return self.transport=='idle' or (node and node.get('state')=='suspended')
                await self.wait_audio(suspended_state,.3)
            finally:
                # Always undo our suspension, even if a call or a new generation superseded this operation.
                if attempted:
                    resumed=await self.pulse('suspend-sink',sink,'0')
                    if not resumed:resumed=await self.pulse('suspend-sink',sink,'0')
                    log.log(logging.INFO if resumed else logging.ERROR,'audio recovery resume=%s context_current=%s',resumed,context==self.policy.context())
            if not self.audio_eligible(context):return
            await self.snapshot();await self.transport_state()
            await self.wait_audio(active,1.5)
            if not self.audio_eligible(context):return
            log.info('audio recovery result transport=%s source=%s ack_to_check_ms=%d; no further retries',self.transport,self.policy.source,int((asyncio.get_running_loop().time()-ack_at)*1000))

    async def verify_local_play(self,context):
        await asyncio.sleep(.7)
        if self.audio_eligible(context):await self.ensure_audio(context,asyncio.get_running_loop().time())

    async def pause_for_remote(self,context):
        # Yield only currently tracked media. Never auto-resume after the peer takes over.
        if self.shadow:return
        for name in list(self.policy.streams):
            if context!=self.policy.context() or self.policy.owner!='remote':return
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
            self.policy.peer_request(asyncio.get_running_loop().time());log.info('explicit peer ownership request; yielding once')
        self.transport_changed.set()
        if self.pause_armed and self.policy.owner=='remote' and self.policy.remote=='active':
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
        except (RuntimeError,KeyError,asyncio.TimeoutError):
            log.warning('MPRIS snapshot unavailable; no playback edge inferred')

    def correlate(self):
        streams=set(); communication=False
        for obj in self.nodes.values():
            info=obj.get('info',{}); props=info.get('props',{})
            if props.get('media.class')!='Stream/Output/Audio' or info.get('state')!='running': continue
            role=str(props.get('media.role','')).lower()
            if role=='communication':communication=True
            if role in ('notification','event','communication','production','filter','dsp'): continue
            p=str(props.get('application.process.id',''))
            f=family(str(props.get('application.name',''))+' '+str(props.get('application.process.binary','')))
            params=info.get('params',{}).get('Props',[])
            if any(x.get('mute') is True or x.get('softMute') is True or x.get('channelVolumes') and max(x['channelVolumes'])<=0 for x in params): continue
            for name,(pid,app) in self.identities.items():
                if p==str(pid) or (app and app==f): streams.add(name)
        if streams != self.policy.streams:
            log.info('media-stream-match count=%s; notification/capture/idle/muted streams excluded',len(streams))
        self.policy.streams=streams
        self.policy.calls(communication)

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
                    self.uncertain_players.add(name);self.policy.invalidate(clear_lease=False);self.evaluate('mpris-status-unknown');self.spawn(self.add_player(name,True))

    def system_signal(self,msg):
        if msg.message_type!=MessageType.SIGNAL:return
        if msg.interface=='org.freedesktop.login1.Manager' and msg.member=='PrepareForSleep':
            sleeping=msg.body[0];self.policy.sleep(asyncio.get_running_loop().time(),sleeping);self.evaluate('sleep' if sleeping else 'resume')
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

    async def resume_baseline(self):
        self.mpris_ready=False
        await asyncio.gather(*(self.add_player(name,True) for name in list(self.identities)))
        self.mpris_ready=True;self.schedule_recovery();self.evaluate('resume-baseline')

    async def pipewire(self):
        proc=await asyncio.create_subprocess_exec(os.environ.get('AIRPODS_PW_DUMP',shutil.which('pw-dump') or 'pw-dump'),'--monitor','--no-colors',stdout=asyncio.subprocess.PIPE)
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
                    self.pw_ready=True;self.correlate();self.graph_changed.set();self.evaluate('pipewire-graph')
            raise RuntimeError('PipeWire event monitor exited')
        finally:
            self.pw_ready=False;self.policy.invalidate();self.evaluate('pipewire-unavailable')
            if proc.returncode is None:proc.terminate();await proc.wait()

    async def main(self):
        self.routing_socket()
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
