# Shared state — AirPods Handoff

Updated: 2026-11-04 (Europe/Kyiv). Experimental; full MacBook parity is not established.

## Repository and deployment

Current work combines upstream main through `59a936c` with the November 4 persistent-call, background-connection and manual-routing implementation. Consult `git log` for publication history. The user requested publication to Redm00use/Airpods-Handoff-NixOS main.

This portable checkout and the machine's deployed NixOS configuration are separate source trees. Editing or pulling this repository does not deploy it. The latest local implementation was deployed before the publication merge; upstream integration itself has not been deployed.

## User decisions

- Preserve stereo AAC, the selected external USB microphone, pairing and passive battery monitoring. HFP testing was declined; active Bluetooth/HID battery polling previously correlated with audio gaps.
- Explicit iPhone AirPods selection is allowed even during a PC call. `manual_remote` cancels autonomous reclaim until fresh authorized PC intent.
- Background connection must not start A2DP or interrupt iPhone. Prefer PC only when both hosts are confirmed idle.
- No extra applications; use existing services and Noctalia.

## Current implementation

- Control-only background AACP, bounded backoff and independent on-demand A2DP.
- Persistent call lease: three attempts per unresolved interruption; renew only after one sustained second of qualified local source, active BlueZ transport and healthy running PipeWire graph. ACK alone is insufficient.
- Typed remote calls and unknown sources block call claims. Preserve continuing PC intent without reviving completed or baseline calls.
- Explicit phone selection cancels queued claims, withdraws native call reports and survives control reconnects. Native manual-route revision fences in-flight requests.
- Scoped native Discord fallback retains only previously proven calls using matching VoiceEngine clients, process identity and process-owned UDP sockets. Client presence alone was rejected because clients survive hangup. See `docs/decisions/2026-11-04-quiet-discord-lifetime.md`.
- Explicit PC return repairs typed local idle/no-source audio; stale peer-release work is cleared when manual mode ends at confirmed both-idle.
- Upstream MPRIS revision/owner fences, string client IDs, resume barriers, input validation, helper/socket cleanup, late sink errors, panel modes and optional adapter identity retained.
- Zero-PCM guard remains disabled by default. Score announcements alone did not prove prevention of automatic switching; no echo loop or unbounded reclaim.

## Verification and limitations

Before publication merge: 251 system Python tests, 254 portable Python tests and 57 native tests; x86_64 flake checks and system build passed. Publication merge: 254 Python tests and x86_64 flake checks passed, including native controller, CLI and module contracts. ARM untested.

Hardware confirmed quiet background reconnect without iPhone music pauses; Discord start audible in AAC; ordinary TikTok scrolling left Discord in AirPods and TikTok on phone speaker after one initial roughly one-second interruption. This initial gap remains unresolved.

Manual iPhone selection held during a detected Discord call. Re-enabling Discord sound did not steal it back; disconnect cleared the call flag. Missing-node fallback was unit-tested and replayed with real kernel metadata, but that specific branch was not observed in the running daemon's sampled graph. The final stale-release idle fix has automated coverage, without a new acoustic idle test.

Earlier lifetime-three-attempt recovery and the temporary settling-delay experiment failed hardware tests; they were superseded/reverted. Do not treat old test failures as the current design, or claim all call apps, firmware, sleep cycles and browser lifecycles were tested. Ownership ACK, source, transport, graph readiness and heard sound remain distinct evidence.

## Next action and shared-account workflow

Investigate bounded native arbitration to avoid the initial transfer gap; increasing retries is not proof of seamless switching. Keep raw captures, personal device identifiers and credentials outside shared files.

Both desktop accounts must open this same checkout to share Skills and this state. Files do not synchronize chat history or authentication. Avoid simultaneous edits to the same files; update this small index after meaningful work.
