"""Local user-only controls and event-driven status stream for desktop panels."""
import asyncio,json,os,socket,struct,time
from pathlib import Path

def status_for(adapter):
    p=adapter.policy
    connection=adapter.connection.snapshot()
    _,node=adapter.bluez_node()
    audio=bool(p.source=='linux' and adapter.transport=='active' and node and node.get('state')=='running' and not adapter.stalled_output_links())
    conflict=p.state in ('LOCAL_CONTESTED','CALL_CONTESTED')
    if not p.connected:title,detail='AirPods не подключены',('Фоновое подключение включено. Активный звук iPhone не перехватывается.' if connection.get('auto_connect') else 'Подключите наушники к ПК вручную.')
    elif not p.ready or not (p.healthy or p.local_call and p.call_healthy is True):title,detail='Состояние уточняется','Жду актуальные данные наушников и аудиосистемы.'
    elif conflict:title,detail='Конфликт переключения','Аудиоканал не восстановился после ограниченной серии попыток. Нажмите «Вернуть на ПК».'
    elif p.remote_call:title,detail='Звонок на iPhone','Автоматический захват приостановлен на время звонка телефона.'
    elif p.state=='CALL_SOURCE_UNKNOWN':title,detail='Уточняю источник звука','Звонок ПК активен, но источник наушников пока неизвестен. Принудительного захвата нет.'
    elif p.manual_remote:title,detail='iPhone выбран вручную','Удержание звука ПК приостановлено. Для возврата нажмите «Вернуть звук на ПК».'
    elif p.inflight or p.state in ('LOCAL_RESTORE_DEBOUNCE','CALL_RECOVERY_WAIT'):title,detail='Возвращаю звук на ПК','Проверяю наушники и запускаю аудиоканал.'
    elif p.owner=='linux' and p.local_call and audio:title,detail='Звонок на ПК','Звонок распознан; активен аудиоканал ПК.'
    elif p.source=='linux' and audio and p.media():title,detail='Звук с ПК','Музыка или видео на ПК удерживают приоритет до паузы.'
    elif p.owner=='linux' and p.pinned:title,detail='Закреплено за ПК','ПК удерживает приоритет даже на паузе. Снимите закрепление для обычного переключения.'
    elif p.owner=='linux' and p.protected():title,detail='ПК выбран · запускаю звук','Аудиоканал ещё не подтвердил готовность.'
    elif p.source=='remote':title,detail='Звук с iPhone','ПК готов принять звук при новом воспроизведении или звонке.'
    elif p.owner=='linux':title,detail='ПК готов к звуку','Сейчас активного воспроизведения на ПК нет.'
    else:title,detail='Автоматическое переключение','Сейчас нет активного звука на ПК.'
    if p.pinned and not p.manual_remote and p.source=='remote' and not conflict and not p.remote_call and not p.inflight:
        detail='Закрепление включено, но канал у iPhone. Нажмите «Вернуть на ПК».'
    if adapter.last_command_error:detail=adapter.last_command_error
    if connection['connecting']:
        title,detail='Подключаю AirPods',('Подключение в фоне без запроса приоритета звука.' if connection.get('connection_background') else 'Одна попытка подключения. Повторные нажатия объединяются.')
    elif not p.connected and connection['connection_error']:
        title,detail='Подключение не удалось',connection['connection_detail']
    elif not p.connected and connection['bluetooth_connected']:
        title,detail='Bluetooth подключён','Жду аудиопрофиль и готовность управления AirPods.'
    elif p.connected and p.ready and p.source=='linux' and p.media() and not audio and not p.remote_call:
        title,detail='Аудиоканал не готов','ПК выбран, но поток звука ещё не работает. Нажмите «Вернуть звук на ПК».'
    if connection.get('auto_connect_paused') and not connection['connecting']:
        title,detail='Автоподключение приостановлено','Вы отключили AirPods вручную. Нажмите «Подключить», чтобы возобновить фоновое подключение.'
    if p.suspended:title,detail='ПК в режиме сна','Автоматическое переключение приостановлено.'
    elif adapter.shadow:title,detail='Режим наблюдения','Решения записываются в журнал; переключение и восстановление звука отключены.'
    return dict(version=1,available=True,shadow=adapter.shadow,local_mode=adapter.local_mode(),media_modes=sorted(adapter.media_modes),state=p.state,title=title,detail=detail,pinned=p.pinned,
                conflict=conflict,connected=p.connected,ready=p.ready,owner=p.owner,source=p.source,
                audio_active=audio,manual_remote=p.manual_remote,local_call=p.local_call,remote_call=p.remote_call,call_proven=p.call_proven,call_pending_intent=p.call_intent,call_recovery_attempts=p.call_recoveries,call_incident_attempts=p.call_lease.attempts,call_transport_confirmed=p.call_lease.audio_confirmed,call_transport_failed=p.call_lease.transport_failed,call_evidence=list(adapter.call_tracker.evidence),call_audio_guard=adapter.call_audio.active,
                can_return=bool(not adapter.shadow and p.connected and p.ready and (p.healthy or p.local_call and p.call_healthy is True) and not p.suspended and not p.remote_call
                                and ((p.local_call and p.call_proven and p.source_kind in ('idle','media') and p.remote!='unknown') or not p.remote_call and (p.remote=='idle' or p.source_kind=='media'))),pending=bool(p.inflight or connection['connecting']),**connection)

class ControlServer:
    def __init__(self,adapter,runtime=None,preferences=None):
        self.adapter=adapter
        self.path=Path(runtime or os.environ['XDG_RUNTIME_DIR'])/'airpods-handoff.control'
        self.preferences=Path(preferences) if preferences is not None else Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'airpods-handoff/preferences.json'
        self.watchers=set();self.connections=set();self.last_payload=None;self.server=None
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
    async def close(self):
        if self.server:
            self.server.close();await self.server.wait_closed()
            for writer in tuple(self.connections):writer.close()
            await asyncio.gather(*(writer.wait_closed() for writer in tuple(self.connections)),return_exceptions=True)
            self.path.unlink(missing_ok=True)
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
        if action=='connect':
            self.adapter.connection.request()
            return self.snapshot()
        if action=='disconnect':
            self.adapter.connection.request_disconnect()
            return self.snapshot()
        if action not in ('pin','auto','return'):raise ValueError('Неизвестное действие')
        if action=='return' and not self.snapshot()['can_return']:
            raise ValueError('Возврат сейчас недоступен: проверьте подключение или завершите звонок iPhone.')
        if action in ('pin','auto'):
            self.persist_pin(action=='pin');p.set_pin(now,action=='pin')
        else:p.manual_request(now)
        self.adapter.last_command_error=None
        self.adapter.evaluate('panel-'+action)
        # AACP ownership can remain local after a failed transport restart.
        # An explicit return must also repair that known idle/no-source state.
        local_audio=(p.source=='linux' or action=='return' and p.source=='none'
                     and p.source_kind=='idle' and p.remote=='idle' and not p.remote_call)
        if p.owner=='linux' and local_audio and p.protected():
            self.adapter.spawn(self.adapter.ensure_audio(p.context(),now))
        return self.snapshot()
    async def handle(self,reader,writer):
        self.connections.add(writer)
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
            self.connections.discard(writer)
            self.watchers.discard(writer);writer.close()
            try:await writer.wait_closed()
            except (OSError,ConnectionError):pass
