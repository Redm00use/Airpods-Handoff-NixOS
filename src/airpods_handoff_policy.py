"""Pure event-driven ownership policy. Tokens fence asynchronous work across state changes."""
from dataclasses import dataclass, field
from airpods_call_lease import CallLease

@dataclass
class Policy:
    owner: str = 'unknown'
    source: str = 'unknown'
    source_kind: str = 'unknown'
    ready: bool = False
    remote: str = 'unknown'
    connected: bool = False
    healthy: bool = False
    call_healthy: bool | None = None
    suspended: bool = False
    pinned: bool = False
    manual_pending: bool = False
    inflight_manual: bool = False
    local_focus: bool = False
    restore_attempted: bool = False
    restore_at: float | None = None
    local_call: bool = False
    call_proven: bool = False
    call_intent: bool = False
    call_serial: int = 0
    call_recoveries: int = 0
    call_lease: CallLease = field(default_factory=CallLease)
    call_cooldown: float = 0
    call_recovery_at: float | None = None
    remote_call: bool = False
    manual_remote: bool = False
    peer_requested: bool = False
    peer_release_attempted: bool = False
    players: dict = field(default_factory=dict)
    streams: set = field(default_factory=set)
    intent: tuple | None = None
    stable_at: float | None = None
    idle_at: float | None = None
    cooldown: float = 0
    leased: bool = False
    inflight: str | None = None
    inflight_token: tuple | None = None
    generation: object = None
    revision: int = 0
    serial: int = 0
    play_started: float | None = None
    state: str = 'DISCONNECTED'
    prefer_idle_pc: bool = True
    idle_preference_at: float | None = None
    idle_preference_attempted: bool = False

    def both_idle(self):
        # Unknown routing is never evidence of silence on the phone.
        return (not self.protected() and self.remote == 'idle' and
                (self.source_kind == 'idle' or
                 self.source == 'linux' and self.source_kind == 'media') and
                not self.remote_call)

    def invalidate(self, clear_lease=True):
        self.revision += 1
        self.manual_pending = self.inflight_manual = False
        self.intent = self.stable_at = self.idle_at = None
        self.inflight = self.inflight_token = None
        self.idle_preference_at = None
        self.idle_preference_attempted = False
        if clear_lease: self.leased = False

    def context(self):
        return self.generation, self.revision

    def valid(self, token):
        return token is not None and token[:2] == self.context() and token == self.inflight_token

    def request(self, action):
        self.serial += 1
        self.inflight = action
        self.inflight_manual = self.manual_pending
        self.manual_pending = False
        self.inflight_token = (*self.context(), self.serial)
        self.state = action.upper() + '_PENDING'
        return action

    def sleep(self, now, sleeping):
        if sleeping:self.calls(False)
        self.invalidate()
        self.local_focus = self.restore_attempted = False
        self.restore_at = None
        self.suspended = sleeping
        self.ready = False
        self.source = self.source_kind = 'unknown'
        self.remote = 'unknown'
        self.remote_call = False  # A pre-suspend call report cannot block reconnection forever.
        self.cooldown = now + 2.5
        if not sleeping: self.generation = None

    def calls(self, active, now=None):
        if active and not self.local_call:
            if now is not None:self.manual_remote = False
            self.call_intent = now is not None
            self.call_serial += 1
            self.call_proven = self.owner == 'linux' and self.source == 'linux'
            self.call_recoveries = 0
            self.call_lease.reset()
            self.call_cooldown = 0
            self.call_recovery_at = None
            self.invalidate(clear_lease=False)
            if now is not None:
                self.intent = ('@call',now+6)
                self.play_started = now
                self.peer_requested = self.peer_release_attempted = False
        self.local_call = active
        if not active:
            self.call_intent = False
            self.call_proven = False
            self.call_recoveries = 0
            self.call_lease.reset()
            self.call_cooldown = 0
            self.call_recovery_at = None
            if self.inflight == 'recover-call': self.invalidate(clear_lease=False)
            if self.intent and self.intent[0]=='@call':self.intent=self.stable_at=None
            if self.inflight in ('take','claim','restore') and not self.protected() and not self.inflight_manual:self.invalidate(clear_lease=False)

    def observe_call_audio(self, now, active, context=None):
        if context is not None and context!=self.context():return
        qualified=(active and self.local_call and self.call_proven and self.connected
                   and self.ready and not self.suspended and not self.manual_remote
                   and not self.remote_call and self.owner=='linux' and self.source=='linux'
                   and (self.healthy or self.call_healthy is True))
        self.call_lease.observe_audio(now, qualified)

    def protected(self):
        return not self.manual_remote and (self.pinned or self.local_call or self.media())

    def set_pin(self,now,pinned):
        self.invalidate(clear_lease=False)
        self.pinned=pinned
        if pinned:self.manual_request(now)

    def manual_request(self,now):
        self.manual_remote = False
        self.invalidate(clear_lease=False)
        self.restore_attempted=False
        if self.local_call:
            self.call_proven = True  # Explicit user return may authorize this call.
            self.call_recoveries = 0
            self.call_lease.reset()
            self.call_cooldown = 0
            self.call_recovery_at = None
        self.peer_requested=self.peer_release_attempted=False
        self.manual_pending=True
        self.intent=('@manual',now+6)
        self.play_started=now


    def manual_peer_request(self, now):
        # Explicit peer choice outranks the current call/media lease, including mute.
        self.invalidate()
        self.manual_remote = True
        self.call_intent = False
        self.call_lease.reset()
        self.local_focus = self.restore_attempted = False
        self.restore_at = self.call_recovery_at = None
        self.peer_requested = True
        self.peer_release_attempted = False

    def peer_request(self, now):
        if self.protected() or self.manual_pending or self.inflight_manual:
            self.peer_requested = True
            self.peer_release_attempted = False
            return
        if not self.peer_requested:
            self.invalidate()
            self.peer_release_attempted = False
        self.peer_requested = True
        self.cooldown = now + 2.5

    def route(self, now, event, generation):
        if self.generation != generation:
            self.call_lease.observe_audio(now, False)
            self.invalidate()
            self.local_focus = self.restore_attempted = False
            self.restore_at = None
            self.generation = generation
            self.peer_requested = self.peer_release_attempted = False
        old, old_remote, old_call = self.owner, self.remote, self.remote_call
        pending_intent = self.intent
        pending_started = self.play_started
        self.connected = event.get('connected', False)
        if not self.connected:
            self.local_focus = self.restore_attempted = False
            self.restore_at = None
        self.ready = event.get('ready', False)
        self.owner = event.get('owner', 'unknown')
        self.remote = event.get('remote_activity', 'unknown')
        self.source = event.get('source', 'unknown')
        self.source_kind = event.get('source_kind', 'unknown')
        self.remote_call = self.source != 'linux' and self.source_kind == 'call'
        if not self.connected or self.owner!='linux' or self.source!='linux':
            self.call_lease.observe_audio(now, False)
        expected_release = (self.inflight == 'release' and self.owner == 'remote'
                            and self.remote == 'idle' and not self.protected())
        if (not self.connected or (self.remote == 'active' and old_remote != 'active')
                or (old == 'linux' and self.owner == 'remote' and not expected_release) or (self.remote_call and not old_call)):
            self.invalidate()
            self.cooldown = now + 2.5
            if self.connected and not self.remote_call and pending_intent and pending_intent[1] > now:
                self.intent = pending_intent
                self.play_started = pending_started
                self.manual_pending = pending_intent[0]=='@manual'

    def player(self, now, key, playing, baseline=False):
        old = self.players.get(key, False)
        self.players[key] = playing
        if playing and not old and not baseline:
            self.manual_remote = False
            self.invalidate(clear_lease=False)
            self.peer_requested = self.peer_release_attempted = False
            self.play_started = now
            self.intent = (key, now + 6.0)
        if not playing and self.intent and self.intent[0] == key:
            self.intent = self.stable_at = None
        if not playing and self.inflight in ('take','restore','claim') and not self.protected() and not self.inflight_manual:
            self.invalidate(clear_lease=False)

    def media(self):
        return any(on and key in self.streams for key, on in self.players.items())

    def decide(self, now):
        if self.intent and now >= self.intent[1]:
            self.intent = self.stable_at = None
            self.manual_pending=False
        if self.suspended: self.state = 'SUSPENDED'; return None
        if not self.connected: self.state = 'DISCONNECTED'; return None
        if not self.ready or not (self.healthy or self.local_call and self.call_healthy is True): self.state = 'DEGRADED'; return None
        if self.manual_remote:
            if not self.local_call and not self.media() and self.both_idle():
                self.invalidate(clear_lease=False)
                self.manual_remote = False
                self.peer_requested = self.peer_release_attempted = False
            else:
                self.call_recovery_at = None
                if self.inflight:return None
                if self.owner == 'linux' and not self.peer_release_attempted:
                    self.peer_release_attempted = True
                    return self.request('release')
                self.state = 'REMOTE_MANUAL'
                return None
        if not self.protected():
            self.local_focus = self.restore_attempted = False
            self.restore_at = None
        elif self.owner == 'linux' and self.source == 'linux':
            self.local_focus = True
            self.restore_at = None
        if self.local_call and self.owner == 'linux' and self.source == 'linux' and not self.call_lease.transport_failed:
            self.call_proven = True
            self.call_intent = False
            self.call_recovery_at = None
        if self.remote_call:
            self.call_recovery_at = None
            self.state = 'REMOTE_CALL'
            return None
        # Keep a proven local call lease across AACP generations, not old command
        # tokens. Bounded reacquisition is distinct from starting a new call while
        # the phone already owns a conversation.
        call_lost = (self.owner != 'linux' or self.source == 'remote' and self.remote == 'active'
                     or self.call_lease.transport_failed)
        if self.local_call and self.call_proven and call_lost:
            if self.inflight:return None
            if (self.source_kind not in ('idle','media') and not (self.source=='linux' and self.source_kind=='call')) or self.remote == 'unknown':
                self.call_recovery_at = None
                self.state = 'CALL_SOURCE_UNKNOWN'
                return None
            if self.call_lease.attempts >= 3:
                self.call_recovery_at = None
                self.state = 'CALL_CONTESTED'
                return None
            if self.call_recovery_at is None:self.call_recovery_at = now + .3
            if now < max(self.call_recovery_at,self.call_cooldown):
                self.state = 'CALL_RECOVERY_WAIT'
                return None
            if not self.call_lease.reserve():return None
            self.call_recoveries += 1  # Lifetime diagnostic only; not a permission budget.
            self.call_cooldown = now + 3
            self.call_recovery_at = None
            return self.request('recover-call')
        if not self.local_call and self.local_focus and self.protected() and self.source == 'remote' and self.source_kind == 'media' and not self.remote_call:
            if self.inflight:return None
            if self.restore_attempted:
                self.state = 'LOCAL_CONTESTED'
                return None
            # A proven continuing local session and a typed remote-media event
            # already establish intent. The controller re-checks call safety;
            # do not add another blind 300 ms before the one allowed restore.
            self.restore_attempted = True
            self.restore_at = None
            return self.request('restore')
        if self.protected() and self.owner == 'linux' and not (self.manual_pending and self.source=='remote'):
            self.state = 'LOCAL_CALL_PROTECTED' if self.local_call else 'LOCAL_PINNED' if self.pinned else 'LOCAL_MEDIA_PROTECTED'
            self.idle_at = None
            self.leased = True
            self.intent = self.stable_at = None
            self.manual_pending=False
            return None
        if self.peer_requested and not self.peer_release_attempted and self.owner=='linux' and not self.inflight:
            self.peer_release_attempted=True
            return self.request('release')
        if self.remote_call: self.state = 'REMOTE_CALL'; return None
        if self.local_call and self.call_intent and not self.call_proven and not self.intent:
            # A continuing explicit call is durable intent. Rebuild only a fresh
            # short command window after reconnection, never stale command tokens.
            self.intent = ('@call',now+6)
        if self.local_call and not self.intent:
            self.state = 'LOCAL_CALL' if self.owner == 'linux' else 'CALL_GUARD'; return None
        if self.inflight: self.state = self.inflight.upper() + '_PENDING'; return None
        if self.owner == 'remote' and self.remote == 'active' and not self.intent:
            self.state = 'REMOTE_OVERRIDE'; return None
        if self.media(): self.idle_at = None
        elif self.leased and self.owner == 'linux' and not self.manual_pending and not (self.prefer_idle_pc and self.remote == 'idle'):
            if self.idle_at is None: self.idle_at = now
            if now >= self.idle_at + 4 and now >= self.cooldown: return self.request('release')
        if self.intent:
            key = self.intent[0]
            eligible = True if key=='@manual' else self.local_call if key=='@call' else self.players.get(key, False) and key in self.streams
            if not eligible: self.stable_at = None
            elif self.remote == 'active' and self.source_kind != 'media':
                self.stable_at = None
            else:
                if self.stable_at is None: self.stable_at = now
                if now >= self.stable_at + .65 and now >= self.cooldown:
                    self.intent = self.stable_at = None
                    if self.owner == 'linux' and self.source != 'remote':
                        self.leased = True
                        self.idle_at = None
                        self.manual_pending = False
                    elif self.remote == 'active':
                        return self.request('claim')
                    elif self.remote == 'idle': return self.request('take')
        # Connecting Bluetooth does not express playback intent. Only a typed,
        # settled idle report from AACP may select the idle default host.
        idle_candidate = (self.prefer_idle_pc and self.both_idle() and not self.intent
                          and self.owner in ('remote', 'none'))
        if idle_candidate:
            if self.idle_preference_at is None: self.idle_preference_at = now
            if (not self.idle_preference_attempted and
                    now >= max(self.idle_preference_at + 1, self.cooldown)):
                self.idle_preference_attempted = True
                return self.request('take-idle')
        else:
            self.idle_preference_at = None
            self.idle_preference_attempted = False
        self.state = ('LOCAL_OWNED' if self.source == 'linux' else 'LOCAL_CLAIMED') if self.owner == 'linux' else 'REMOTE_OWNED' if self.owner == 'remote' else 'READY_IDLE'
        return None

    def result(self, now, action, success, token=None):
        token = self.inflight_token if token is None else token
        if not self.valid(token): return False
        self.inflight = self.inflight_token = None
        self.inflight_manual=False
        self.cooldown = now + 2.5
        if action == 'recover-call':self.call_cooldown = now + 3
        self.intent = None
        if not success and action == 'release': self.leased = False
        if success:
            self.leased = action in ('take','restore','claim','take-idle','recover-call')
            self.owner = 'linux' if self.leased else 'remote'
            # Ownership ACK intentionally does not change self.source.
            self.idle_at = None
        return True

    def deadline(self, now):
        due = []
        call_audio_deadline=self.call_lease.deadline(now)
        if call_audio_deadline is not None:due.append(call_audio_deadline)
        if self.restore_at is not None:due.append(self.restore_at)
        if self.call_recovery_at is not None:due.append(max(self.call_recovery_at,self.call_cooldown))
        if self.intent:
            due.append(self.intent[1])
            if self.stable_at is not None: due.append(max(self.stable_at + .65, self.cooldown))
        if self.idle_at is not None and self.leased: due.append(max(self.idle_at + 4, self.cooldown))
        if self.idle_preference_at is not None and not self.idle_preference_attempted:
            due.append(max(self.idle_preference_at + 1, self.cooldown))
        return min((x for x in due if x > now), default=None)
