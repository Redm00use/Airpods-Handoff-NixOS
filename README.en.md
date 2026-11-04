# AirPods Handoff for NixOS

## 0.4.0 base with November 4 improvements

- A continuing PC call can make bounded guarded returns after an interrupting iPhone
  call reports idle. Baseline calls, hangup, sleep, disconnect and unknown remote
  states do not authorize that return.
- Status/panel report call, music, video, game, mixed, media or idle from observed
  stream roles and identities. Untagged browser content remains generic media.
- MPRIS replies are fenced against newer playback/owner events; suspend/resume
  suppresses decisions until fresh baselines are ready. Recovery discovers the
  configured device across BlueZ adapters instead of assuming hci0.
- Helper processes are reaped on cancellation/timeout; late sink errors trigger
  bounded audio recovery. Microphone selection and A2DP/HFP remain WirePlumber's
  responsibility.
- Optional `services.airpodsHandoff.macLikeIdentity.enable = true` advertises
  Apple DeviceID, laptop class and a configurable default name (`name = "Mac"`).
  This is Bluetooth identification, **not Apple Account enrollment**, and cannot
  guarantee that iPhone treats Linux as an authenticated Mac. Saved adapter Alias
  can override the default Name.


Experimental event-driven audio ownership handoff for AirPods Pro 2 USB-C, iPhone and Linux. [Detailed installation and status matrix (Russian)](README.md).

This reuses a locally extended MIT-licensed `hacel/airpodsctl` controller. A Python FSM consumes BlueZ D-Bus, MPRIS, PipeWire and authenticated AACP routing events. It does not loop Bluetooth disconnect/connect, modify pairing keys, or implement Apple-account/iCloud Automatic Switching.

## Status

Version 0.4 protects active Linux calls/media rather than auto-pausing a local player when iPhone requests ownership. Duplex Discord/Telegram streams and explicitly tagged communication sessions are tracked, including silence/mute grace. A conservative PipeWire fallback covers known media applications and Music/Movie/Video/Game streams without MPRIS; notifications and startup baselines do not create takeover intent.

New playback/call intent can request one controller-guarded `take-media` over remote music. A proven media session can request one bounded recovery after an autonomous iPhone takeover; repeated contention stops at `LOCAL_CONTESTED`. Continuing calls use a separate lease with three attempts per interruption, renewed only by verified source, transport and audio graph health. The automatic path does not use unconditional `take --force`. The controller refreshes status and rejects calls/unknown types before changing ownership.

A2DP transport state is insufficient evidence of working audio. Paused/init output links into the matching AirPods sink are repaired once per link generation, without rebuilding the microphone/effect chain or disconnecting Bluetooth. Old intents/focus are discarded on sleep; resume refreshes the graph. There are 254 portable Python regression tests plus 57 native controller tests.

Manual repair of the specific stalled output links was hearing-confirmed on one setup; the automatic repair was observed in logs. Full repeated hardware cycles, PC calls, sleep/resume, other models/adapters and ARM remain unverified. This does not implement Apple's closed cross-device arbiter or guarantee interruption-free ownership. It is an experimental project, not a stable-release claim.

## Install

Use the published repository as a flake input:

```nix
inputs.airpods-handoff.url = "github:Redm00use/Airpods-Handoff-NixOS";
```

Add `inputs.airpods-handoff.nixosModules.default` to your existing NixOS module list and configure:

```nix
services.airpodsHandoff = {
  enable = true;
  user = "alice";
  device = "AA:BB:CC:DD:EE:FF"; # replace with your paired AirPods address
  spoofAppleDeviceId = true;
  shadow = false;
};
```

Apply using your usual `nixos-rebuild switch`. Without flakes, import `./nix/module.nix` from a copy of the full repository under `/etc/nixos/`.

Requires PipeWire/WirePlumber/pipewire-pulse, BlueZ, a desktop session D-Bus and MPRIS players. Tested build environment: NixOS 26.05 x86_64-linux, Zig 0.16. Apple DeviceID spoofing applies to the whole adapter; changing it may require re-pairing and may restart Bluetooth. Initial pairing and Bluetooth connection remain the user's responsibility.

Services run only for the configured user and are wanted by `graphical-session.target`:

```bash
systemctl --user start airpodsctl airpods-auto-switch
airpodsctl --session switching status
journalctl --user -u airpods-auto-switch -u airpodsctl -f
airpods-handoff-diagnose
```

Use `shadow = true` to log decisions without ownership, Pause or sink commands. The controller still opens AACP and requests status. Do not run competing AACP daemons or stale local systemd overrides.

## Develop

```bash
nix flake check --print-build-logs
nix build
nix develop
python3 -m unittest discover -s tests -p 'test_*.py'
(cd vendor/airpodsctl && zig build core-check --summary all)
```

Hardware tests and limitations: [manual matrix](docs/manual-tests.ru.md). An ownership ACK or active transport is not an acoustic test.

MIT; vendored controller retains its upstream license. See [notices](THIRD_PARTY_NOTICES.md).

Hardware update: Cider-over-iPhone and a Discord call recovery were hearing-confirmed on one setup; brief switching interruptions remain possible. See [verification](docs/verification.md).

## Manual controls and Noctalia

`airpods-handoffctl status|watch|pin|auto|return` uses a user-only UNIX socket. Pin preferences persist, but pinning is not Apple's firmware-level lock. A repeated autonomous takeover can require manual return rather than starting a command loop.

The optional [Noctalia 5.2 / Luau API 24 panel](integrations/noctalia/README.md) displays source/call/recovery/conflict and exposes the same controls. It does not depend on personal scripts or addresses. Status strings are currently Russian.

Recovery now reacts immediately to a known sink error and repairs late-arriving graph edges within the same attempt. The extra 300ms restore delay was removed only for a proven local session and typed remote media. An initial optimized sample showed 264ms from ownership ACK to observed graph readiness; the user initially perceived little difference. The latest policy change is not an acoustic latency guarantee.

## Background connection (hardware follow-up November 4)

`autoConnect` and `preferIdlePC` default to true. Background connection opens
only the AACP L2CAP channel of the explicitly selected, paired device. It never
calls ConnectProfile or takes ownership. The module disables WirePlumber's
independent bluez5.auto-connect for this device. A2DP is opened on demand after
local ownership and a protected local session. Retries back off 5/15/30/60s;
key errors stop retries. Pairing is never removed. Manual Disconnect pauses
background reconnect until Connect or service restart.

Confirmed idle on both hosts selects Linux using non-forced take after 1 second.
Unknown source/activity never counts as idle. Disable with `autoConnect = false;
preferIdlePC = false;`. The initial background-A2DP implementation failed hardware
validation by pausing iPhone music; the control-only replacement preserved iPhone music in one hardware test. Idle-PC selection was also confirmed. Repeated transitions, calls and sleep still need broader validation.

## Continuing PC calls

A previously proven local call may recover across AACP reconnection with a
fresh-source-checked `take-call` request. Typed remote calls and unknown sources
are rejected. Each unresolved interruption permits at most three attempts; one
second of verified local source, active transport and healthy audio graph renews
the budget. An ACK alone does not. Hangup cancels queued work; suspend clears
the lease. Native Discord has a narrowly scoped lifetime fallback for previously
proven calls, matching VoiceEngine clients, process identity and owned UDP sockets.
This is not a universal browser call-lifecycle API.

## Hardware follow-up (2026-11-02)

The zero-PCM call guard did not reliably prevent iPhone takeovers and defaults
to off. Control-only reconnection preserved iPhone music in a hearing-confirmed
test; paging initially failed twice. Cold connection now has a separate 10s
budget, operations receive a fresh 3s budget, and routing mutations require a
live control session. The paired L2CAP socket explicitly requests medium security.

Call category reports, peer yield messages and first-contact host announcements
are implemented. The generic media-scored yield request still failed a quiet
Discord test after three recoveries. A control-channel-only trace showed call
category 501 followed by media routing score 301. A version using consistent
call scores (501) is being validated; it is a protocol hypothesis, not a claim
of macOS parity. No unlimited takeover loop is enabled.

## Explicit phone selection

The user confirmed that the failing takeover tests included manually selecting
AirPods on the iPhone; the trace contained `ManualRoute`. These tests must not
be described as proof of a purely automatic-switching failure. The selected
policy now lets explicit phone choice override an ongoing PC call or media
lease, matching the intended Apple-like behavior. A bounded OPACK reader requires
a typed true yield request and an exact manual reason. It invalidates pending
returns and withdraws the PC call report without ending the call. A new explicit
PC return/play/call can reselect the PC. Hardware confirmed manual override during
a continuing Discord call. Ordinary TikTok playback left Discord in AirPods and
TikTok on the phone speaker after one initial roughly one-second interruption.
See [verification](docs/verification.md); full macOS parity is not established.
