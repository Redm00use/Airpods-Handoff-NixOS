# Experimental native call-score lifecycle announcements

Status: built and deployed; hardware effect unknown.

## Evidence

AACP capture from the quiet-call failure contains score-only peer dictionaries (`audioRoutingScore=301`) and subsequent ownership changes. It contains no incoming automatic yield request with `Hijackv2` or `RoutedToBluetooth`. Therefore the existing conditional score reply is not reached in this scenario. The meaning of peer score-only reports is not established; they are not treated as requests.

Other reviewed implementations did not establish a drop-in solution for silent AAC call retention. EarPort's delayed audio restart was tested and rejected separately. Its host-list maintenance is not clearly the missing piece: observed connected-host flags already carry both hosts in the list.

## Hypothesis and minimal change

Announce the local score independently of peer request shape, once when an explicitly reported/proven local call becomes active, then withdraw it on call end. Use the existing native score dictionary shape already used for replies: 501 for call, 100 for idle.

`Controller.reportCall` sends the score only when the advertised score changes. Repeated call-start and recover-call reports do not repeat it. A new control session starts with no remembered announcement. A call-end still sends idle once even if no prior announcement is remembered, allowing conservative withdrawal. Score state is updated only after sending succeeds.

ManualRoute continues to disable automatic negotiation immediately. The Python lifecycle withdraws the call report after manual choice. Incoming score-only frames remain informational; no score-response loop is added. The new score frame contains no ownership command or yield flag. Existing call report/yield behavior is otherwise unchanged.

This is an experiment based on observed packet shape and the missing lifecycle announcement. It is not proof that iPhone will honor the score or that Apple call arbitration has been reproduced. No undocumented opcode 0x44 values are introduced.

## Software acceptance

- Exact native OPACK dictionary for 501 and 100, with no ownership field.
- Emulator expects the extra score frame on first call-start/end.
- Repeated start/end omits the score frame while preserving ordinary call-report handling.
- Score-only announcements do not alter the observed owner.
- Existing manual-route and automatic-request tests remain required.

## Hardware acceptance

With stereo AAC, a silent muted Discord call remains audible after ordinary iPhone Play, without repeated recoveries or a stalled transport. A manual iPhone route still succeeds. Phone-call/unknown protections, background connection and passive battery monitoring remain preserved. Failed hardware validation requires reconsidering or reverting this change, not adding an endless takeover loop.

## Software results

56 protocol tests passed. All six x86_64 portable Nix checks and the system build passed. Controller/handler were restarted without an active call; WirePlumber and passive battery services were not restarted. Background control reconnected and observed owner/source=iPhone; no score announcement was logged on passive startup. Acoustic validation of the new call behavior is requested, not assumed.

## First hardware attempt

After score 501 was logged, the PC recovered three times and then yielded in CALL_CONTESTED. The user confirmed iPhone playback, and clarified that they pressed Play 3–4 times. This tests repeated remote playback intents and exhaustion of the per-call recovery budget; it does not establish behavior for one isolated Play followed by no further input. Stable retention against repeated Play was not achieved. A controlled single-Play test is pending. Do not reclassify earlier captures as single-Play or manual-route tests without evidence.
