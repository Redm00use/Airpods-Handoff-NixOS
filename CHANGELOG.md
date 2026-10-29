# Changelog

## 0.3.0 — 2026-10-29

- Persistent manual pin/auto mode and one explicit return attempt after contention.
- User-only control socket, event-driven status stream, portable handoffctl and optional Noctalia panel.
- Immediate recovery on sink errors, late-link repair within the current attempt, fewer status round trips.
- No extra 300ms restore debounce for a proven local session after typed remote music.
- 120 Python tests, controller protocol checks and Luau compilation in the Nix package check.
- Documented repeat-conflict and closed-protocol limitations; no complete Apple Automatic Switching claim.

## 0.2.0 — 2026-10-29 (local, unreleased)

- Active Linux call/media protection before peer release; no phone-triggered local auto-pause.
- Duplex/explicit-role communication tracking with call lifecycle grace.
- Debounced PipeWire playback fallback when MPRIS is unavailable.
- One guarded media claim per new intent and bounded recovery of a proven local session.
- Paused/init final A2DP link repair, source/transport/graph verification, fencing at IPC dispatch.
- Fresh graph baselines after sleep; bounded refresh of invalidated MPRIS state.
- Expected release-event/ACK ordering regression and expanded Python tests (95).
- Hardware verification remains incomplete; do not claim complete Apple Automatic Switching.
