# Changelog

## Local merge — 2026-11-04

- Incorporate upstream MPRIS revision/owner fences and string PipeWire client IDs.
- Fence resume baselines, preserve authenticated generations on duplicate BlueZ signals, validate routing/graph input.
- Reap helpers, restore interrupted edge deletions, close service resources and detect late sink errors.
- Report evidence-based media modes and shadow status in the existing panel; honor XDG_CONFIG_HOME.
- Preserve the newer control-only background connection, native call reports, manual iPhone selection and bounded call recovery.
- 223 Python tests passed; no new acoustic call-stability claim.

## Unreleased — continuing call priority

- Preserve proven PC call recovery rights across AACP generations, with fresh commands and a three-attempt budget.
- Typed take-call command revalidates source and rejects unknown; queued commands are cancelled on hangup.
- Broader browser duplex detection; call evidence/conflict status exposed to the panel.
- Suspend clears old call rights; no blanket claim of full Apple behavior.


## Unreleased — background connection

- Control-only background AACP connection with backoff; no audio-profile/ownership command on connect.
- WirePlumber automatic profile connection disabled only for the selected device.
- A2DP opened on demand after local ownership; initial background-profile design rejected by hardware test.
- Prefer PC when both hosts are explicitly idle; revalidate before non-forced take.
- Cancel stale connection work and prevent stale phone-call state from blocking resume.
- Connection status and error diagnostics included in the panel protocol.
- Hardware validation in progress; no claim of complete Apple Automatic Switching.


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
