"""Single-flight BlueZ connection with quiet, backoff-limited background retries.

Background connection opens only AACP. A2DP is connected explicitly/on local use.
"""
import asyncio
import logging
from dbus_next import Message, MessageType

log = logging.getLogger('handoff.connection')
DEVICE = 'org.bluez.Device1'
ADAPTER = 'org.bluez.Adapter1'
TRANSPORT = 'org.bluez.MediaTransport1'
A2DP_SINK = '0000110b-0000-1000-8000-00805f9b34fb'


def explain_error(raw):
    text = raw.lower()
    if 'page-timeout' in text or 'host is down' in text:
        return 'not-responding', 'AirPods не отвечают ПК. Закройте кейс на 10 секунд, затем откройте рядом с ПК. Сопряжение сохранено.'
    if 'authentication' in text or 'auth-failed' in text or 'key-missing' in text:
        return 'authentication', 'Наушники отклонили проверку сопряжения. Нужна диагностика ключа; сопряжение автоматически не удаляется.'
    if 'inprogress' in text or 'busy' in text:
        return 'busy', 'BlueZ уже подключает устройство. Дождитесь завершения текущей попытки.'
    if 'notready' in text:
        return 'adapter-off', 'Bluetooth-адаптер не готов. Проверьте, включён ли Bluetooth.'
    if 'notavailable' in text or 'profile-unavailable' in text:
        return 'profile-unavailable', 'Аудиопрофиль недоступен. Проверьте состояние PipeWire и WirePlumber.'
    if 'timeout' in text or 'timed out' in text or 'noreply' in text:
        return 'timeout', 'Подключение не завершилось вовремя. Проверьте доступность наушников; сопряжение сохранено.'
    return 'failed', 'Не удалось подключить AirPods. Причина BlueZ сохранена в журнале и диагностике.'


class ManualConnection:
    def __init__(self, adapter, mac):
        self.adapter = adapter
        self.mac = mac.replace('_', ':').upper()
        self.device_path = None
        self.adapter_path = None
        self.connected = None
        self.profile = False
        self.powered = None
        self.task = None
        self.phase = 'idle'
        self.error = None
        self.detail = None
        self.raw_error = None
        self.duration_ms = None
        self.epoch = 0
        self.auto_enabled = False
        self.auto_paused = False
        self.auto_timer = None
        self.retry_index = 0
        self.retry_delays = (5, 15, 30, 60)
        self.blocked_error = False
        self.background = False

    def start_auto(self, enabled=True):
        self.auto_enabled = enabled
        self.schedule_auto(0)

    def schedule_auto(self, delay):
        if self.auto_timer:
            self.auto_timer.cancel()
            self.auto_timer = None
        if self.auto_enabled and not self.auto_paused and not self.adapter.shadow:
            self.auto_timer = asyncio.get_running_loop().call_later(delay, self.auto_tick)

    def auto_tick(self):
        self.auto_timer = None
        p = self.adapter.policy
        if self.auto_paused:
            return
        if p.suspended or getattr(self.adapter,'resuming',False) or self.adapter.fatal.is_set() or p.remote_call or self.powered is False or self.blocked_error:
            self.schedule_auto(60)
            return
        if self.task and not self.task.done():
            return  # The running single flight schedules the next wakeup.
        if self.connected and (self.profile or getattr(p, 'ready', False)):
            # Recover the control channel independently of Bluetooth/audio ownership.
            if not getattr(p, 'ready', True) and hasattr(self.adapter, 'schedule_recovery'):
                self.adapter.schedule_recovery()
            self.retry_index = 0
            self.schedule_auto(60)
            return
        self.request(automatic=True)

    def publish(self):
        if self.adapter.control:
            self.adapter.control.publish()

    def snapshot(self):
        p = self.adapter.policy
        call_owned = (getattr(p,'local_call',False) and getattr(p,'call_proven',False)
                      and getattr(p,'owner',None)=='linux' and getattr(p,'remote',None)=='idle')
        return dict(connecting=bool(self.task and not self.task.done()),
                    bluetooth_connected=self.connected, a2dp_connected=self.profile,
                    connection_phase=self.phase, connection_error=self.error,
                    connection_detail=self.detail, connection_raw_error=self.raw_error,
                    connection_ms=self.duration_ms,
                    auto_connect=self.auto_enabled and not self.auto_paused,
                    auto_connect_paused=self.auto_paused, connection_background=self.background,
                    can_connect=not (p.remote_call and not call_owned or p.suspended or self.adapter.shadow
                                     or self.powered is False))

    def control_ready(self):
        # The control socket can complete after the requesting CLI timed out.
        # Fresh AACP readiness supersedes that transient connection error.
        self.connected = True
        self.error = self.detail = self.raw_error = None
        self.blocked_error = False
        self.phase = 'connected' if self.profile else 'control-ready'
        self.retry_index = 0
        self.publish()

    def request(self, automatic=False):
        if self.task and not self.task.done():
            if not automatic and self.phase == 'disconnecting':
                self.auto_paused = False  # Resume once the requested disconnect finishes.
            return  # All clicks join the same operation.
        if not self.snapshot()['can_connect']:
            raise ValueError('Подключение недоступно во время звонка iPhone, сна или при выключенном Bluetooth.')
        if self.auto_timer:
            self.auto_timer.cancel()
            self.auto_timer = None
        if not automatic:
            self.adapter.policy.manual_remote = False
            self.auto_paused = False
            self.retry_index = 0
            self.blocked_error = False
        self.background = automatic
        self.error = self.detail = self.raw_error = self.duration_ms = None
        self.phase = 'checking'
        self.task = self.adapter.spawn(self.run(self.epoch))
        self.publish()

    def request_disconnect(self):
        if self.adapter.shadow:
            raise ValueError('Отключение недоступно в режиме наблюдения.')
        self.auto_paused = True
        self.adapter.policy.invalidate()
        self.invalidate()
        self.phase = 'disconnecting'
        self.task = self.adapter.spawn(self.disconnect(self.epoch))
        self.publish()

    async def disconnect(self, epoch):
        try:
            await self.refresh(epoch)
            if epoch != self.epoch:return
            if self.device_path and self.connected:
                await self.call(self.device_path, DEVICE, 'Disconnect', timeout=10)
                await self.refresh(epoch)
            if epoch == self.epoch:self.phase = 'idle'
        except (RuntimeError, OSError, asyncio.TimeoutError) as error:
            if epoch == self.epoch:
                self.raw_error = str(error)[:300] or 'timeout'
                self.error, self.detail = explain_error(self.raw_error)
                self.phase = 'failed'
        finally:
            if epoch == self.epoch:
                self.task = None
                self.schedule_auto(3)
                self.publish()

    async def call(self, path, interface, member, signature='', body=None, timeout=3):
        reply = await asyncio.wait_for(self.adapter.system.call(Message(
            destination='org.bluez', path=path, interface=interface,
            member=member, signature=signature, body=body or [])), timeout)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f'{reply.error_name}: {reply.body}')
        return reply.body

    def load(self, objects):
        self.connected = False
        self.profile = False
        self.device_path = self.adapter_path = None
        props = {}
        for path, interfaces in objects.items():
            candidate = interfaces.get(DEVICE, {})
            address = candidate.get('Address')
            if address and address.value.upper() == self.mac:
                self.device_path = path
                props = candidate
                self.adapter_path = candidate['Adapter'].value if 'Adapter' in candidate else path.rsplit('/', 1)[0]
                self.connected = bool(candidate.get('Connected') and candidate['Connected'].value)
                break
        powered = objects.get(self.adapter_path, {}).get(ADAPTER, {}).get('Powered')
        self.powered = powered.value if powered is not None else None
        if self.device_path:
            self.profile = self.connected and any(
                path.startswith(self.device_path + '/') and TRANSPORT in interfaces
                for path, interfaces in objects.items())
        if self.profile:
            self.error = self.detail = self.raw_error = None
        return props

    async def refresh(self, epoch=None):
        objects = (await self.call('/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects'))[0]
        if epoch is not None and epoch != self.epoch:
            return {}
        return self.load(objects)

    async def run(self, epoch):
        started = asyncio.get_running_loop().time()
        try:
            props = await self.refresh(epoch)
            if epoch != self.epoch:
                return
            if not self.snapshot()['can_connect']:
                self.error = 'adapter-off' if self.powered is False else 'deferred'
                self.detail = ('Bluetooth выключен.' if self.powered is False else
                               'Подключение отложено: звонок iPhone или переход в сон.')
                self.phase = 'failed'
                return
            if self.connected and self.profile:
                self.phase = 'connected'
                log.info('manual-connect skipped: A2DP already connected')
                return
            if not self.device_path or not props.get('Paired') or not props['Paired'].value:
                self.error, self.detail = 'not-paired', 'AirPods не сопряжены с этим ПК. Добавьте их через настройки Bluetooth.'
                self.phase = 'failed'
                return
            if props.get('Blocked') and props['Blocked'].value:
                self.error, self.detail = 'blocked', 'AirPods заблокированы в настройках Bluetooth.'
                self.phase = 'failed'
                return
            self.phase = 'connecting'
            self.publish()
            if self.background:
                self.phase = 'control-connecting'
                log.info('background-connect control-only; no A2DP/ownership request')
                ok, diagnostic = await self.adapter.cli('switching', 'status')
                if not ok:
                    raise RuntimeError(diagnostic.strip()[-300:] or 'control-channel-unavailable')
            else:
                log.info('connect begin background=False profile=A2DP; explicit/local audio request')
                await self.call(self.device_path, DEVICE, 'ConnectProfile', 's', [A2DP_SINK], timeout=25)
            if epoch != self.epoch:
                return
            # A successful method reply is not proof of an audible channel.
            await self.refresh(epoch)
            if epoch == self.epoch:
                self.phase = 'connected' if self.profile else 'control-ready' if getattr(self.adapter.policy, 'ready', False) else 'waiting-profile'
        except asyncio.CancelledError:
            raise
        except (RuntimeError, OSError, asyncio.TimeoutError, ValueError, AttributeError) as error:
            if epoch == self.epoch:
                self.raw_error = str(error)[:300] or 'timeout'
                self.error, self.detail = explain_error(self.raw_error)
                self.phase = 'failed'
                log.warning('manual-connect failed code=%s bluez=%s', self.error, self.raw_error)
        finally:
            if epoch == self.epoch:
                self.duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
                self.task = None
                self.blocked_error = self.error in ('authentication', 'not-paired', 'blocked')
                if self.profile or self.connected and getattr(self.adapter.policy, 'ready', False):
                    self.retry_index = 0
                    delay = 60
                else:
                    delay = self.retry_delays[min(self.retry_index, len(self.retry_delays)-1)]
                    self.retry_index += 1
                self.schedule_auto(delay)
                self.publish()
                log.info('connect completed phase=%s background=%s elapsed_ms=%s next_retry_s=%s',
                         self.phase, self.background, self.duration_ms,
                         delay if self.auto_enabled and not self.blocked_error else None)

    def invalidate(self):
        self.epoch += 1
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = None
        self.connected = None
        self.powered = None
        self.profile = False
        self.error = self.detail = self.raw_error = None
        self.phase = 'unavailable'
        self.schedule_auto(5)

    def signal(self, msg):
        if msg.message_type != MessageType.SIGNAL:
            return
        if msg.interface == 'org.freedesktop.DBus' and msg.member == 'NameOwnerChanged' and msg.body[0] == 'org.bluez':
            self.invalidate()
        elif msg.interface == 'org.freedesktop.login1.Manager' and msg.member == 'PrepareForSleep':
            if msg.body[0]:
                self.invalidate()
            else:
                self.blocked_error = False
                self.retry_index = 0
                self.schedule_auto(3)
        elif msg.interface == 'org.freedesktop.DBus.Properties' and msg.member == 'PropertiesChanged':
            interface, values, _ = msg.body
            if msg.path == self.device_path and interface == DEVICE and 'Connected' in values:
                self.connected = values['Connected'].value
                if not self.connected:
                    self.profile = False
                    self.retry_index = 0
                    self.schedule_auto(5)
                else:
                    self.error = self.detail = self.raw_error = None
            elif msg.path == self.adapter_path and interface == ADAPTER and 'Powered' in values:
                self.powered = values['Powered'].value
                if not self.powered:
                    self.invalidate()
                    self.powered = False
                else:
                    self.schedule_auto(3)
            if msg.path == self.device_path and interface == DEVICE and 'Paired' in values:
                self.blocked_error = not values['Paired'].value
                self.schedule_auto(3)
        elif msg.interface == 'org.freedesktop.DBus.ObjectManager' and msg.member == 'InterfacesAdded':
            path, interfaces = msg.body
            if self.device_path and path.startswith(self.device_path + '/') and TRANSPORT in interfaces:
                self.profile = True
                self.error = self.detail = self.raw_error = None
                self.phase = 'connected'
                self.retry_index = 0
        elif msg.interface == 'org.freedesktop.DBus.ObjectManager' and msg.member == 'InterfacesRemoved':
            path, interfaces = msg.body
            if path == self.device_path and DEVICE in interfaces:
                self.invalidate()
            elif self.device_path and path.startswith(self.device_path + '/') and TRANSPORT in interfaces:
                self.profile = False
                self.schedule_auto(5)
        self.publish()
