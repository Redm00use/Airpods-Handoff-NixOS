# Verification — 2026-10-29, 0.3.0

## Automated checks

- 120 Python tests pass against the sanitized standalone sources: 117 runtime regressions and 3 portable CLI/socket integration checks.
- The vendored controller has 40 core tests, including fresh remote-media authorization and rejection of call/unknown states through an emulated exchange.
- Luau panel compilation is included in the Nix package check.
- NixOS module contract checks username, device, controller/adapter executables and optional Apple DeviceID wiring. CLI smoke checks verify entry points, invalid device rejection and packaged panel files.
- GitHub Actions is included; local execution is reported separately from actual hosted CI results.
- Personal home paths, original device addresses, pairing keys, bytecode caches and access tokens are excluded from the exported tree.

## Hardware evidence and limits

Test setup: one AirPods Pro 2 USB-C pair, iPhone and NixOS x86_64-linux. This is not a hardware certification matrix.

- User hearing-confirmed Cider starting over ongoing iPhone music after the init-link fix. The phone paused and PC audio became audible.
- User hearing-confirmed recovery of a Discord call after iPhone music took the channel. The local call was detected with media=false; one bounded restore was sent. Brief interruption remained possible.
- On Discord hangup, the local call guard cleared and one idle release was confirmed.
- Manual pin preference persistence, event-stream delivery and Auto restoration were verified while AirPods were disconnected. No ownership command was needed for that preference check.
- Initial faster recovery sample: ownership loss→typed remote source 252ms; old restore debounce 301ms; ownership command 184ms; ACK→observed graph readiness 264ms. Previously recorded recovery checks were commonly around 1s after ACK, with some unsuccessful 2.4s checks. These are software observations, not acoustic latency measurements.
- User initially perceived little improvement. The final extra 300ms debounce removal is not yet hearing-confirmed.
- A subsequent repeated iPhone takeover entered LOCAL_CONTESTED and required manual return. This is an acknowledged limitation, not a solved seamless-switching claim.
- Telegram-specific hardware calls, physical sleep/resume, long repeated acoustic tests, ARM and other adapters/models/firmware remain unverified.

See [manual tests](manual-tests.ru.md). `owner=linux`, an ownership ACK, or a running transport alone does not prove audible sound. The implementation also checks observed source and final PipeWire graph state; hearing verification is still separate.
