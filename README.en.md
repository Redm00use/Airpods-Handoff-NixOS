# AirPods Handoff for NixOS

Experimental event-driven audio ownership handoff for AirPods Pro 2 USB-C, iPhone and Linux. [Detailed installation and status matrix (Russian)](README.md).

This reuses a locally extended MIT-licensed `hacel/airpodsctl` controller. A Python FSM consumes BlueZ D-Bus, MPRIS, PipeWire and authenticated AACP routing events. It does not loop Bluetooth disconnect/connect, modify pairing keys, or implement Apple-account/iCloud Automatic Switching.

## Status

Version 0.3 protects active Linux calls/media rather than auto-pausing a local player when iPhone requests ownership. Duplex Discord/Telegram streams and explicitly tagged communication sessions are tracked, including silence/mute grace. A conservative PipeWire fallback covers known media applications and Music/Movie/Video/Game streams without MPRIS; notifications and startup baselines do not create takeover intent.

New playback/call intent can request one controller-guarded `take-media` over remote music. A proven local session can also request one bounded recovery after an autonomous iPhone takeover; repeated contention stops at `LOCAL_CONTESTED`. The automatic path does not use unconditional `take --force`. The controller refreshes status and rejects calls/unknown types before changing ownership.

A2DP transport state is insufficient evidence of working audio. Paused/init output links into the matching AirPods sink are repaired once per link generation, without rebuilding the microphone/effect chain or disconnecting Bluetooth. Old intents/focus are discarded on sleep; resume refreshes the graph. There are 120 Python regression tests plus controller core tests.

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
