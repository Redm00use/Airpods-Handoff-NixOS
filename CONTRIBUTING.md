# Contributing

Run `nix flake check -L` before proposing changes. Use virtual-clock tests for FSM changes and controller emulation for protocol changes. Include a regression test for each ownership race or recovery fix.

For hardware reports provide AirPods model/firmware, iOS version, adapter, NixOS/BlueZ/PipeWire/WirePlumber versions, steps, whether sound was heard and relevant service logs. Separate ownership ACK, active transport and acoustic success. Do not publish pairing keys, raw plist exports, personal profiles or unreviewed diagnostics.

Do not introduce unconditional force takeover, automatic pairing deletion or unbounded Bluetooth reconnect loops. Preserve the single AACP reader and connection/revision fencing. Check both a remote call arriving during takeover and a stale ACK arriving after remote ownership.
