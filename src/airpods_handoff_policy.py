"""Pure event-driven ownership policy. Tokens fence asynchronous work across state changes."""
from dataclasses import dataclass, field

@dataclass
class Policy:
    owner: str = 'unknown'
    source: str = 'unknown'
    source_kind: str = 'unknown'
    ready: bool = False
    remote: str = 'unknown'
    connected: bool = False
    healthy: bool = False
    suspended: bool = False
    local_call: bool = False
    allow_remote_media: bool = True
    remote_call: bool = False
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

    def invalidate(self, clear_lease=True):
        self.revision += 1
        self.intent = self.stable_at = self.idle_at = None
        self.inflight = self.inflight_token = None
        if clear_lease: self.leased = False

    def context(self):
        return self.generation, self.revision

    def valid(self, token):
        return token is not None and token[:2] == self.context() and token == self.inflight_token

    def request(self, action):
        self.serial += 1
        self.inflight = action
        self.inflight_token = (*self.context(), self.serial)
        self.state = action.upper() + '_PENDING'
        return action

    def sleep(self, now, sleeping):
        self.invalidate()
        self.suspended = sleeping
        self.ready = False
        self.source = self.source_kind = 'unknown'
        self.cooldown = now + 2.5
        if not sleeping: self.generation = None

    def calls(self, active):
        if active and not self.local_call: self.invalidate(clear_lease=False)
        self.local_call = active

    def peer_request(self, now):
        if not self.peer_requested:
            self.invalidate()
            self.peer_release_attempted = False
        self.peer_requested = True
        self.cooldown = now + 2.5

    def route(self, now, event, generation):
        if self.generation != generation:
            self.invalidate()
            self.generation = generation
            self.peer_requested = self.peer_release_attempted = False
        old, old_remote, old_call = self.owner, self.remote, self.remote_call
        self.connected = event.get('connected', False)
        self.ready = event.get('ready', False)
        self.owner = event.get('owner', 'unknown')
        self.remote = event.get('remote_activity', 'unknown')
        self.source = event.get('source', 'unknown')
        self.source_kind = event.get('source_kind', 'unknown')
        self.remote_call = self.source != 'linux' and self.source_kind == 'call'
        if (not self.connected or (self.remote == 'active' and old_remote != 'active')
                or (old == 'linux' and self.owner == 'remote') or (self.remote_call and not old_call)):
            self.invalidate()
            self.cooldown = now + 2.5

    def player(self, now, key, playing, baseline=False):
        old = self.players.get(key, False)
        self.players[key] = playing
        if playing and not old and not baseline:
            self.invalidate(clear_lease=False)
            self.peer_requested = self.peer_release_attempted = False
            self.play_started = now
            self.intent = (key, now + 6.0)
        if not playing and self.intent and self.intent[0] == key:
            self.intent = self.stable_at = None
        if not playing and self.inflight == 'take' and not self.media():
            self.invalidate(clear_lease=False)

    def can_take(self):
        return self.remote=='idle' or (self.allow_remote_media and self.remote=='active' and self.source=='remote' and self.source_kind=='media')

    def media(self):
        return any(on and key in self.streams for key, on in self.players.items())

    def decide(self, now):
        if self.intent and now >= self.intent[1]: self.intent = self.stable_at = None
        if self.suspended: self.state = 'SUSPENDED'; return None
        if not self.connected: self.state = 'DISCONNECTED'; return None
        if not self.healthy or not self.ready: self.state = 'DEGRADED'; return None
        if self.peer_requested and not self.peer_release_attempted and self.owner=='linux' and not self.inflight:
            self.peer_release_attempted=True
            return self.request('release')
        if self.remote_call: self.state = 'REMOTE_CALL'; return None
        if self.local_call: self.state = 'LOCAL_CALL' if self.owner == 'linux' else 'CALL_GUARD'; return None
        if self.inflight: self.state = self.inflight.upper() + '_PENDING'; return None
        if self.owner == 'remote' and self.remote == 'active' and not self.can_take(): self.state = 'REMOTE_OVERRIDE'; return None
        if self.media(): self.idle_at = None
        elif self.leased and self.owner == 'linux':
            if self.idle_at is None: self.idle_at = now
            if now >= self.idle_at + 4 and now >= self.cooldown: return self.request('release')
        if self.intent:
            key = self.intent[0]
            eligible = self.players.get(key, False) and key in self.streams
            if not eligible: self.stable_at = None
            elif not self.can_take(): self.intent = self.stable_at = None
            else:
                if self.stable_at is None: self.stable_at = now
                if now >= self.stable_at + .65 and now >= self.cooldown:
                    self.intent = self.stable_at = None
                    if self.owner == 'linux': self.leased = True
                    else: return self.request('take')
        self.state = ('LOCAL_OWNED' if self.source == 'linux' else 'LOCAL_CLAIMED') if self.owner == 'linux' else 'REMOTE_OWNED' if self.owner == 'remote' else 'READY_IDLE'
        return None

    def result(self, now, action, success, token=None):
        token = self.inflight_token if token is None else token
        if not self.valid(token): return False
        self.inflight = self.inflight_token = None
        self.cooldown = now + 2.5
        self.intent = None
        if not success and action == 'release': self.leased = False
        if success:
            self.leased = action == 'take'
            self.owner = 'linux' if self.leased else 'remote'
            # Ownership ACK intentionally does not change self.source.
            self.idle_at = None
        return True

    def deadline(self, now):
        due = []
        if self.intent:
            due.append(self.intent[1])
            if self.stable_at is not None: due.append(max(self.stable_at + .65, self.cooldown))
        if self.idle_at is not None and self.leased: due.append(max(self.idle_at + 4, self.cooldown))
        return min((x for x in due if x > now), default=None)
