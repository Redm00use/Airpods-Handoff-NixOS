"""Local user-only controls and event-driven status stream for desktop panels."""
import asyncio,json,os,socket,struct,time
from pathlib import Path

def status_for(adapter):
    p=adapter.policy
    _,node=adapter.bluez_node()
    audio=bool(p.source=='linux' and adapter.transport=='active' and node and node.get('state')=='running' and not adapter.stalled_output_links())
    conflict=p.state=='LOCAL_CONTESTED'
    if not p.connected:title,detail='AirPods не подключены','Подключите наушники к ПК вручную.'
    elif not p.ready or not p.healthy:title,detail='Состояние уточняется','Жду актуальные данные наушников и аудиосистемы.'
    elif p.remote_call:title,detail='Звонок на iPhone','Возврат на ПК доступен после завершения звонка.'
    elif conflict:title,detail='Конфликт переключения','Автовозврат остановлен. Нажмите «Вернуть на ПК» для одной новой попытки.'
    elif p.inflight or p.state=='LOCAL_RESTORE_DEBOUNCE':title,detail='Возвращаю звук на ПК','Проверяю наушники и запускаю аудиоканал.'
    elif p.owner=='linux' and p.local_call and audio:title,detail='Звонок на ПК','Приоритет звонка защищён, в том числе при тишине и выключенном микрофоне.'
    elif p.source=='linux' and audio and p.media():title,detail='Звук с ПК','Музыка или видео на ПК удерживают приоритет до паузы.'
    elif p.owner=='linux' and p.pinned:title,detail='Закреплено за ПК','ПК удерживает приоритет даже на паузе. Снимите закрепление для обычного переключения.'
    elif p.owner=='linux' and p.protected():title,detail='ПК выбран · запускаю звук','Аудиоканал ещё не подтвердил готовность.'
    elif p.source=='remote':title,detail='Звук с iPhone','ПК готов принять звук при новом воспроизведении или звонке.'
    elif p.owner=='linux':title,detail='ПК готов к звуку','Сейчас активного воспроизведения на ПК нет.'
    else:title,detail='Автоматическое переключение','Сейчас нет активного звука на ПК.'
    if p.pinned and p.source=='remote' and not conflict and not p.remote_call and not p.inflight:
        detail='Закрепление включено, но канал у iPhone. Нажмите «Вернуть на ПК».'
    if adapter.last_command_error:detail=adapter.last_command_error
    return dict(version=1,available=True,state=p.state,title=title,detail=detail,pinned=p.pinned,
                conflict=conflict,connected=p.connected,ready=p.ready,owner=p.owner,source=p.source,
                audio_active=audio,local_call=p.local_call,remote_call=p.remote_call,
                can_return=bool(p.connected and p.ready and p.healthy and not p.suspended and not p.remote_call
                                and (p.remote=='idle' or p.source_kind=='media')),pending=bool(p.inflight))

class ControlServer:
    def __init__(self,adapter,runtime=None,preferences=None):
        self.adapter=adapter
        self.path=Path(runtime or os.environ['XDG_RUNTIME_DIR'])/'airpods-handoff.control'
        self.preferences=Path(preferences or Path.home()/'.config/airpods-handoff/preferences.json')
        self.watchers=set();self.last_payload=None;self.server=None
    async def start(self):
        try:
            if self.preferences.stat().st_size<=1024:
                value=json.loads(self.preferences.read_text()).get('pinned')
                if type(value) is bool:self.adapter.policy.pinned=value
        except (OSError,ValueError,AttributeError):pass
        if self.path.exists():self.path.unlink()
        self.server=await asyncio.start_unix_server(self.handle,path=str(self.path),limit=2048)
        self.path.chmod(0o600)
        self.publish()
    def snapshot(self):return status_for(self.adapter)
    def publish(self):
        payload=json.dumps(self.snapshot(),ensure_ascii=False,separators=(',',':')).encode()+b'\n'
        if payload==self.last_payload:return
        self.last_payload=payload
        for writer in tuple(self.watchers):
            transport=writer.transport
            if writer.is_closing() or transport.get_write_buffer_size()>65536:
                self.watchers.discard(writer);writer.close()
            else:writer.write(payload)
    def persist_pin(self,value):
        self.preferences.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        tmp=self.preferences.with_suffix('.tmp')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as output:json.dump({'pinned':value},output)
        tmp.replace(self.preferences)
    def action(self,action):
        p=self.adapter.policy;now=asyncio.get_running_loop().time()
        if action not in ('pin','auto','return'):raise ValueError('Неизвестное действие')
        if action=='return' and not self.snapshot()['can_return']:
            raise ValueError('Возврат сейчас недоступен: проверьте подключение или завершите звонок iPhone.')
        if action in ('pin','auto'):
            self.persist_pin(action=='pin');p.set_pin(now,action=='pin')
        else:p.manual_request(now)
        self.adapter.last_command_error=None
        self.adapter.evaluate('panel-'+action)
        if p.owner=='linux' and p.source=='linux' and p.protected():
            self.adapter.spawn(self.adapter.ensure_audio(p.context(),now))
        return self.snapshot()
    async def handle(self,reader,writer):
        try:
            peer=writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12)
            if struct.unpack('3i',peer)[1]!=os.getuid():return
            raw=await asyncio.wait_for(reader.readline(),2)
            if len(raw)>1024:raise ValueError('Слишком большой запрос')
            request=json.loads(raw);action=request.get('action','status')
            if action=='watch':
                self.watchers.add(writer)
                writer.write(json.dumps(self.snapshot(),ensure_ascii=False).encode()+b'\n');await writer.drain()
                await reader.read(1)
            else:
                result=self.snapshot() if action=='status' else self.action(action)
                writer.write(json.dumps({'ok':True,**result},ensure_ascii=False).encode()+b'\n');await writer.drain()
        except (ValueError,TypeError,AttributeError,asyncio.TimeoutError,OSError) as error:
            if not writer.is_closing():
                writer.write(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False).encode()+b'\n')
                try:await writer.drain()
                except (OSError,ConnectionError):pass
        finally:
            self.watchers.discard(writer);writer.close()
            try:await writer.wait_closed()
            except (OSError,ConnectionError):pass
