# AirPods Handoff for NixOS

Experimental event-driven audio ownership handoff for AirPods Pro 2 USB-C, iPhone and Linux. [Detailed installation and status matrix (Russian)](README.md).

This reuses a locally extended MIT-licensed `hacel/airpodsctl` controller. A Python FSM consumes BlueZ D-Bus, MPRIS, PipeWire and authenticated AACP routing events. It does not loop Bluetooth disconnect/connect, modify pairing keys, or implement Apple-account/iCloud Automatic Switching.

## Status

Confirmed on one setup: paused iPhone → Cider playback on Linux, return to iPhone, and automatic Cider pause. Existing iPhone calls were correctly reported and guarded. Notification exclusion, race handling, sleep/resume and recovery have automated coverage, not a complete hardware matrix.

**Taking over ongoing iPhone music is implemented with a guarded `take-media` operation, but is not yet hearing-tested.** Calls and unknown source types are rejected by the controller after a fresh status exchange. No unconditional `--force` is used.

A bounded suspend/resume of the existing A2DP sink can recover a stalled transport without disconnecting Bluetooth or cycling profiles. Transport errors and delayed starts have occurred; this is not a stable-release claim. Other AirPods models, adapters, firmware and ARM hardware remain unverified.

## Install

Add this local checkout as a flake input, or use `github:OWNER/airpods-handoff-nixos` **after the repository has been published**:

```nix
inputs.airpods-handoff.url = "path:/home/alice/Documents/airpods-handoff-nixos";
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
