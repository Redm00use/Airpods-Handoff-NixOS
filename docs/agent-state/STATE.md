# Shared state — AirPods Handoff

Last updated: 2026-11-04 (Europe/Kyiv).
Status: latest fixes deployed; test voice call ended. Main routing scenarios passed with one remaining initial TikTok dropout; full MacBook parity is not established.

## Current objective

Preserve stereo AAC, quiet background AACP connection and intentional manual routing while improving call handoff. Stable retention of a silent PC call against ordinary iPhone Play is NOT achieved.

## Repository baseline

- Local HEAD: `2d7b1f2` (2026-10-29), with substantial uncommitted Python, Zig, Nix and panel changes. Do not reset or replace the working tree.
- GitHub commit reviewed: `59a936c900bb86d42fa2651b2a4a779a1857c1ae` (2026-11-03). Selected fixes were adapted, not merged wholesale: its controller lacks newer local protocol/manual-route work.
- The portable repository and deployed NixOS configuration are separate source trees. Editing this checkout alone does not deploy to the machine. Compare before copying; deployment must preserve device-specific configuration.
- No commit or push performed in this session.

## User decisions

- Preserve stereo AAC and the selected external USB microphone. HFP testing was explicitly declined.
- Manual AirPods selection on iPhone is allowed, including during a PC call. `manual_remote` cancels autonomous PC reclaim until fresh authorized PC intent.
- Background control connection must not start A2DP or interrupt iPhone. When both devices are idle, prefer PC.
- No extra applications. Integrate functions into existing services and Noctalia.
- Preserve passive battery monitoring. Active Bluetooth/HID battery polling previously correlated with audio gaps and was removed.

## Implemented locally

- Control-only background AACP with bounded retries, independent on-demand A2DP and idle-PC preference (`src/airpods_connection.py`, policy).
- Typed manual-route detection and native call reports in vendored controller; fixed relay length; separate cold-connect/operation budgets.
- Call lifetime detection retains muted/quiet duplex sessions; bounded call recovery, manual-route fencing and call-report withdrawal.
- Adapted upstream fixes: MPRIS revision/unique-owner fencing, string PipeWire client IDs, resume barrier, input validation, helper/socket cleanup, duplicate BlueZ generation protection, late sink-error handling, evidence-based panel modes and XDG preferences.
- Explicit Return now invokes bounded audio repair for local ownership with typed idle/no source. Remote/unknown sources were not added to that repair path (`src/airpods_handoff_control.py`).
- Zero-PCM call guard remains disabled by default; it previously failed hardware validation.

## Verification on 2026-11-04

- Final staged system Python suite: 242 passed; the currently deployed first lease build passed 239. The rejected settling experiment passed 229 system/232 portable tests but failed its on-device scenario; those four tests are not part of the active tree. The new regression failed on the previous code.
- Portable x86_64 Nix flake checks and system build passed. ARM was not tested.
- Existing matching controller build has 54 passing protocol tests; controller was not changed during the November 4 merge.
- Background reconnection: source stayed iPhone, PC A2DP off; user confirmed music without pauses.
- Discord start: recognized as a call, AAC selected; user confirmed PC sound.
- Silent muted Discord + ordinary iPhone Play: THREE automatic recoveries, followed by no audible audio from either device. User confirmed silence. This test FAILED stable call retention.
- A direct quiet test WAV stalled. One suspend/resume of the existing AirPods sink restored playback; user heard the repeated signal. This proves repair of that episode, not prevention of future switching.
- Latest explicit-return code was deployed after leaving the test call. Its new idle/no-source button path has automated coverage; hardware confirmation through the updated button is still pending.

## Latest protocol evidence / open hypotheses

- A follow-up AACP-only capture again showed three recoveries and source becoming none. Do not treat owner=Linux as audible success.
- Incoming score-only `audioRoutingScore=301` messages were observed. No incoming `Hijackv2`/`RoutedToBluetooth` reason appeared in that capture, so the current automatic-request score-response trigger did not run.
- The meaning of the score-only messages is not established: they may be reports/replies rather than requests. Do not implement an echo loop or claim a proven negotiation fix from this evidence.
- Observed peer/local connected-device states were ordinary 07/01 and 05/03 pairs; available captures do not establish a transition-state claim race.
- Direct host-state opcode 0x44 is a research lead only. No arbitrary values were sent.
- Raw captures and personal device identifiers are intentionally excluded from shared repository memory.

## Next bounded action

Do not call the implementation identical to Apple. The remaining confirmed issue is a roughly one-second initial transfer/dropout when iPhone/TikTok first requests audio during the PC call. Three videos afterward remained on the phone speaker, and Discord sound was confirmed in AirPods. Investigate native arbitration to prevent the initial transfer; increasing retry counts cannot prove zero-gap behavior.

Persistent-call lease is deployed. Quiet native Discord now has a narrowly scoped fallback tied to previously proven VoiceEngine client/process/UDP socket lifetime; client presence alone was tested and rejected because clients persist after hangup. See `docs/decisions/2026-11-04-quiet-discord-lifetime.md`. This is not a generic browser-call guarantee.

Hardware-confirmed after that fix: manual iPhone route held while local_call=true/manual_remote=true, and re-enabling sound in the same Discord channel did not take it back. After explicit hangup, the call flag cleared. Missing-node retention was unit-tested and replayed with real kernel metadata, but the daemon's sampled deafened graph still contained audio nodes; do not overstate that specific branch's hardware validation.

A final regression fix clears stale peer-release work when returning from manual mode to confirmed both-idle. 251 system Python tests and x86_64 Nix checks passed; 57 native tests remain the matched controller baseline. No new acoustic idle-selection test after the small final fix. No commit/push.

## Shared-account workflow

Both desktop applications must open this SAME checkout to share these files. Skills and STATE.md are repository files, not a shared chat history. Neither desktop application's authentication nor model selection is configured by this kit. Avoid simultaneous edits to the same files; record a short handoff in this state index.

## Current immutable deployment

Active final system: `/nix/store/zaskxhr83rfr1ib7z06scz7dwl04fja9-nixos-system-niri-26.05.20261026.718f670`. Previous persistent-call build: `/nix/store/0f78fh4fh4r80gfa3fmvhhnxd5q9p7ss-nixos-system-niri-26.05.20261026.718f670`. Final updates changed only the Python handler; controller, WirePlumber and passive batteries were not restarted. Preserve AAC/external mic and existing pairing.
