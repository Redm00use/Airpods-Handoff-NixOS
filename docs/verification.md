# Verification

## 2026-11-03, 0.4.0

- 135 pure/async tests passed locally on Python 3.12. The complete 142-test suite
  passed in GitHub Actions on Python 3.11 and 3.13 for runtime commit
  `c7baf05fb78f1ec851aa98e2e82863039c61813a`.

- New regressions cover interrupted-call return/cancellation, stale MPRIS replies,
  owner removal, resume barriers, late snapshots, fatal health, multi-adapter
  discovery, cancelled helpers, invalid inputs, late sink errors and shutdown.
- The editing environment can run pure/async tests but denies AF_UNIX socket
  creation. Socket integration tests are retained unchanged and run in GitHub
  Actions; they are not replaced by mocks or silently skipped in CI.
- Python 3.11/3.13 CI runs the complete suite. Nix checks build the controller,
  run its protocol tests, compile the panel, and validate packaged CLI/module
  contracts including optional Bluetooth Name/Class/DeviceID.
- No new AirPods/iPhone acoustic test, physical suspend/resume test or Apple
  Account enrollment has been performed. Mac-like identity changes Bluetooth
  metadata only; it does not prove Apple relay participation.

## Historical evidence — 2026-10-29, 0.3.0

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


## 2026-11-04 — persistent call lease and publication integration

The portable tree combines upstream `59a936c` with control-only background connection, bounded per-interruption call recovery, native manual-route fencing and scoped Discord voice-transport evidence. The former per-call lifetime recovery cap and unsuccessful settling-delay experiment were superseded/reverted.

Hardware evidence: the user heard uninterrupted iPhone music during background reconnect, Discord in stereo AAC, and Discord retained/recovered while scrolling TikTok (TikTok on the phone speaker). One initial roughly one-second interruption remained. Manual iPhone route held during the detected call and after re-enabling Discord sound; explicit hangup cleared call detection. No full macOS equivalence is claimed.

The missing-audio-node Discord fallback has unit coverage and a replay using real process/socket metadata; the sampled daemon graph still had audio nodes, so that branch is not independently hardware-proven. The final stale peer-release cleanup has regression coverage without another acoustic idle-selection test. No ARM or complete sleep/call-app matrix was run. Publication integration does not deploy the portable tree.

Publication merge validation: 254 Python tests passed (`unittest discover`), and `nix flake check --no-write-lock-file` passed on x86_64-linux, including package, native protocol, paired-control selection, CLI and NixOS module contracts. ARM was omitted as incompatible with the local builder. No services were restarted for publication.
