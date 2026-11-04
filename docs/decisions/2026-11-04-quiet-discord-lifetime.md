# Preserve an established Discord call when its audio nodes disappear

Status: implemented and deployed. Acoustic/manual-routing checks are recorded below; missing-node retention has unit coverage plus replay with live kernel metadata.

## Observations

The user confirmed Discord remained voice-connected while the old tracker reported no call. A PipeWire snapshot contained no Discord audio nodes, but the same native `WEBRTC VoiceEngine` clients persisted. Later audio nodes returned with the same clients. Keeping the clients alone is unsafe: they also persisted after the user explicitly disconnected.

The proven VoiceEngine process owned one UDP socket during the connected session and zero after explicit disconnect. This provides a narrow additional liveness observation for this native Discord setup. It does not establish a universal call API for browsers or other applications.

## Implementation

`src/airpods_voice_transport.py` records only a previously detected native Discord duplex call, associated VoiceEngine client object serials, process start identity and process-owned UDP socket inodes. It can retain a running call when audio nodes vanish if that same client/process/socket proof remains. It cannot establish a new call from a running Discord process or UDP socket alone. New unrelated sockets, reused PIDs and replaced client identities do not inherit the old call.

Kernel metadata is read at most once per two seconds while a relevant call is tracked. It reads fd links and inode columns in bounded proc UDP tables; it does not read socket payload/audio or credentials. No Bluetooth, HID or battery polling is added. Probe failure is conservative: retention expires rather than guessing. The normal stop grace remains, so closed voice sockets release the call within a bounded interval. A replacement ICE socket with all audio nodes absent may require fresh audio evidence; this fallback is intentionally narrow.

## Verification

249 system Python tests passed after this fix. Coverage includes missing nodes, client persistence after hangup, reused PID/client identity, replacement UDP socket, no new call from clients alone, browser exclusion and probe failure. All x86_64 Nix checks passed.

A missing-audio-node replay using the actual live process metadata retained the call. This is an integration/replay observation, not proof that the running daemon exercised that exact branch during the subsequent acoustic test.

On hardware after deployment:

- User joined native Discord, muted/deafened without leaving. The handler continued to report local_call=true. Audio nodes were still present in the sampled graph, so that snapshot alone is not evidence of missing-node fallback.
- User manually selected AirPods on iPhone and confirmed its sound held for at least 15 seconds. The handler simultaneously reported local_call=true, manual_remote=true and REMOTE_MANUAL; pending PC recovery was cancelled.
- Re-enabling Discord sound while staying in the channel did not steal the iPhone route; user confirmed it stayed on iPhone.
- After explicit voice disconnect, local_call became false and the observed source was iPhone. No new acoustic proof of uninterrupted post-hangup sound was separately requested.

Earlier TikTok test on the persistent-call mechanism: three videos scrolled, one roughly one-second apparent transfer to AirPods then back; Discord was heard in AirPods and TikTok on iPhone speaker afterward. Repeated interruption on every video was not reported. Zero-gap MacBook equivalence is NOT achieved.

## Follow-up idle cleanup

The hangup journal exposed one stale peer-release request: after manual routing ended and both hosts reported idle, the PC idle preference took ownership then replayed an old release. The policy now invalidates that old work and clears peer-release flags when leaving manual mode for confirmed idle. A regression reproduced the unwanted release before the fix; 251 system tests and all portable Nix checks passed afterward. The small follow-up was deployed without a call. A new acoustic idle-selection test was not performed.
