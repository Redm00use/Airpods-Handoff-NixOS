# Third-party notices

## Bundled code

`vendor/airpodsctl` is a locally modified copy of [hacel/airpodsctl](https://github.com/hacel/airpodsctl), copyright (c) 2026 hacel, MIT licensed. Its original notice is retained in `vendor/airpodsctl/LICENSE`. `UPSTREAM` records the exact base revision. Local extensions include external policy mode, authenticated routing snapshots, call/media classification, guarded media takeover and peer-yield handling. The controller is bundled so incompatible upstream IPC/protocol updates are not silently pulled at runtime.

The new Python adapter, FSM, Nix packaging, module, tests and documentation are covered by the root MIT license.

## Technical references (not bundled or launched)

- [airpods-tui](https://github.com/annoyedmilk/airpods-tui), reviewed at `8af4eb20cbc39c33983d70c0518753db13f0bbfa`: distinction between ownership ACK and audio source; sink-level stream restart.
- [earport-handoff](https://github.com/pika-02-03/earport-handoff), reviewed at `1d55f5cf51fa44f3a139e1df4ca2b5a2a6ace436`: sticky remote yield across transient NONE; framed peer release marker.
- [LibrePods](https://github.com/librepods-org/librepods): public reverse-engineering context and DeviceID/multipoint findings.
- [MPRIS specification](https://specifications.freedesktop.org/mpris/latest/Player_Interface.html).
- [PipeWire pw-dump documentation](https://docs.pipewire.org/page_man_pw-dump_1.html).

No source trees from the above GPL reference projects are included in this repository. Protocol-level observations and behavioral references are documented separately from bundled MIT code.

Apple, AirPods and iPhone are trademarks of Apple Inc. This project is independent and is not endorsed by Apple.
