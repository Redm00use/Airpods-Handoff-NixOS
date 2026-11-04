"""Bound recovery per interrupted audio path, rather than per call lifetime."""
from dataclasses import dataclass

@dataclass
class CallLease:
    attempts: int = 0
    transport_failed: bool = False
    stable_since: float | None = None
    audio_confirmed: bool = False

    def reset(self):
        self.attempts = 0
        self.transport_failed = False
        self.stable_since = None
        self.audio_confirmed = False

    def observe_audio(self, now, active):
        if not active:
            self.stable_since = None
            self.audio_confirmed = False
            return
        self.transport_failed = False
        if self.stable_since is None:self.stable_since = now
        if now >= self.stable_since + 1.0:
            self.audio_confirmed = True
            self.attempts = 0

    def reserve(self):
        if self.attempts >= 3:return False
        self.attempts += 1
        self.transport_failed = False  # This attempt is now in progress, not confirmed restored.
        return True

    def deadline(self, now):
        due = self.stable_since + 1.0 if self.stable_since is not None and not self.audio_confirmed else None
        return due if due is not None and due > now else None
