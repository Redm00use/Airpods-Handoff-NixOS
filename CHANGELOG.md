# Changelog

## Unreleased — 2026-11-04

- Control-only background connection with bounded backoff and on-demand A2DP; prefer PC only when both hosts are confirmed idle.
- Persistent call lease: at most three attempts per unresolved interruption; renew only after one second of verified source, transport and audio graph health.
- Preserve explicit iPhone routing during a PC call, including across control reconnection; fence queued native claims against newer manual choices.
- Add bounded native Discord voice-transport lifetime evidence for previously proven calls; client presence alone cannot start or retain a call.
- Repair explicit PC return with local ownership and missing audio; clear stale peer-release work after manual mode ends.
- Validate typed OPACK relay requests, native call announcements and source-safe call claims; reject remote calls and unknown sources.
- Incorporate upstream MPRIS revision/owner fences, string client IDs, resume barriers, helper cleanup, late sink error handling and panel statuses.
- Preserve optional Mac-like adapter identity and upstream CI. No official Apple Account integration.
- Hardware: quiet background connection, Discord recovery, and manual iPhone override confirmed. One initial roughly one-second TikTok interruption remains; full macOS parity is not established.

## 0.4.0 — 2026-11-03

- Resume a previously local, continuing call once after confirmed iPhone call end;
  cancel on hangup, suspend, disconnect, or a new remote call.
- Re-arm the single restore budget after 30 seconds of sustained local ownership,
  so an unrelated later interruption does not remain blocked for the entire call.
- Expose evidence-based local session modes and call applications in status/panel.
- Add opt-in Mac-like Bluetooth identity without claiming Apple Account integration.
- Fence stale MPRIS replies and suspend/resume baselines, latch fatal health failures,
  and find the configured AirPods on any BlueZ adapter.
- Reap cancelled helpers, close service sockets/tasks, validate routing and graph
  input, and recover late sink errors independently of ownership command completion.
- Honor XDG_CONFIG_HOME and show shadow mode explicitly.
- Add lifecycle regression coverage and Python 3.11/3.13 CI alongside Nix checks.

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
