# Persistent local-call lease with bounded interruption recovery

Status: final mechanism deployed after the real call ended. 242 system / 245 portable Python tests and 57 protocol tests passed. Discord start is hearing-confirmed; quiet TikTok validation is pending.

## Problem and required behavior

The old policy spends three recoveries over the entire local call. Multiple iPhone Play presses or separate videos can exhaust that total even when each earlier recovery successfully restored the PC audio path. Conversely, an ownership ACK can leave source=none and a failed transport without consuming further recovery logic because the PC is still marked owner.

Preserve local-call priority across independent media interruptions, with manual iPhone selection as explicit override. Unknown remote state and an actual remote call must not authorize an automatic take. Do not add an unlimited timer-driven reconnect/take loop or infer audible success from an ACK.

## New model

`src/airpods_call_lease.py` owns an interruption budget and transport evidence. The existing total recovery count remains diagnostic only.

- One continuous interruption permits up to three attempts. Dispatch reserves the cooldown immediately, even if later events invalidate the command ACK.
- Recovery is confirmed from the existing AACP source + BlueZ transport + PipeWire node/link evidence. One continuous second of qualified local audio renews the interruption budget. Brief activity and ownership ACKs cannot renew it. This is transport evidence, not proof of audible audio.
- A subsequent fresh loss after confirmed recovery is another interruption, even in a long call with many past recoveries.
- A fresh explicit PC call also retains durable call intent across cold connection and expired short command windows. Only a fresh guarded command is recreated after readiness. Baseline calls, completed calls and manual iPhone choices cannot revive old intent.
- A failed transport repair marks the interruption unresolved even when owner=Linux. It re-enters the same bounded recovery mechanism. After exhaustion, automatic audio repair is blocked too; an explicit Return can re-authorize a fresh attempt series.
- A real phone call pauses automatic PC recovery. The continuing PC-call lease is remembered; typed idle/media after the phone call may permit return. Unknown state waits without spending the budget.
- ManualRoute invalidates queued work and suspends the PC lease. New actual PC intent or explicit Return can select PC again. Hangup and sleep destroy the old lease and its transport evidence.
- Native controller increments a manual-choice revision. If ManualRoute arrives during the fresh routing query, a pending take/take-media/take-call/call-start is rejected before writing further routing frames. Status, release and call-end remain allowed.
- Fresh native call recovery also rejects an actual remote call; it may recover typed local-call, media or idle state.

This preserves the on-demand A2DP background design and external microphone. AAC remains selected. No competing daemon, HFP switch, pairing changes or polling battery service is introduced. The earlier unsuccessful 1.5-second settling experiment is absent.

## External implementations inspected

- [EarPort](https://github.com/Anoryth/earport): useful separation of host-list, media handoff and delayed audio recovery. Its timing-only approach was tested locally and rejected after failing the scenario.
- [LibrePods Rust branch](https://github.com/librepods-org/librepods/tree/linux%2Frust/linux-rust): AACP/OPACK and media-controller references; the inspected branch is a general media handoff implementation, not demonstrated quiet-PC-call priority.
- [Tether protocol notes](https://github.com/zackb/tether/blob/main/docs/BLUETOOTH.md): distinguishes host media reports, actual source and ownership; relevant to avoiding false confirmation.
- [AirTux](https://github.com/watchmypizza/AirTux): generic Bluetooth/MPRIS/notification handling rather than a ready AACP call-priority mechanism.
- PodHop and xatuke/handoff were also inspected as explicit-take/basic-source-handoff references. They do not establish the requested end-to-end behavior.

No reviewed source establishes a drop-in implementation identical to Apple for this hardware and user policy. Source inspection is not hardware verification. No external GPL application code is copied into this MIT tree.

## Acceptance tests

242 Python tests passed in the final system staging tree (239 in the first deployed lease build). New scenarios include twelve successful independent interruptions, three failures without audio confirmation, short audio blips, stale audio observations, reconnect generations, manual choice, phone/unknown guards, hangup/sleep, dispatch cooldown despite stale ACK, and owner=Linux with failed transport. Native emulator tests cover manual choice during fresh query and rejection of a remote source reported as a phone call. 57 native tests and all six x86_64 Nix flake checks passed. The portable Python suite contains three additional packaging/fixture tests.

Remaining hardware acceptance: silent muted Discord plus a continuing iPhone/TikTok feed; no lifetime-three cutoff; explicit manual iPhone routing still wins; real audio recovers and remains usable. This policy cannot itself prevent proprietary firmware from briefly transferring ownership. Zero audible interruptions and complete MacBook parity are not established by these tests.

## Deployment boundary

The main lease build was applied without a call. AirPods were not responding to the PC during the subsequent observation, so no TikTok/Discord acoustic success was established. The user then reported an actual phone conversation. Do not restart services or conduct device experiments until the user says the call is over. The final refinement is built but intentionally not activated during that conversation.
