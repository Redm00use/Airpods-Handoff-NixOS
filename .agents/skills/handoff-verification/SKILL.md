---
name: handoff-verification
description: Validate AirPods Handoff source changes using targeted Python, Zig and Nix checks and report which guarantees remain untested on actual AirPods.
---
1. Inspect affected modules and available tests; select the narrowest useful checks first.
2. Where available run `python3 -m unittest discover -s tests -p 'test_*.py' -v`; `(cd vendor/airpodsctl && zig build core-check --summary all)`; `nix flake check --print-build-logs`; `nix build` as scope and environment allow.
3. Report commands, exit status, exact failing cases and environment/toolchain blockers. Never fabricate results.
4. Explicitly distinguish unit/emulator simulation, integration and acoustic on-device validation.
5. Flag regressions affecting call protection, late ACK, failed sink recovery or indefinite retries.
