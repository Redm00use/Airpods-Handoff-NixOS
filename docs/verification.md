# Packaging verification — 2026-10-29

Locally verified on x86_64-linux with the committed nixpkgs lock:

- `nix flake check --print-build-logs`: all native checks passed.
- Python FSM/adapter tests: 42 passed in the Nix build sandbox.
- Vendored controller core tests: 40 passed, including active-media authorization and rejection of call/unknown source through an emulated exchange.
- NixOS module contract: custom username, device address, DeviceID and executable wiring evaluated and checked.
- `nix run . -- --help`: passed.
- `nix develop --command python3 -B -m unittest discover -s tests -p 'test_*.py'`: 42 passed.
- Invalid device address rejected before starting the adapter.
- `switching take-media --force` rejected by the CLI.
- Personal paths and original hardware addresses removed from exported code/tests.

The GitHub Actions workflow has been included but has not run on GitHub yet. ARM outputs are not tested. Full upstream D-Bus integration tests and real hardware tests are not implied by these checks. See the README status matrix for the separate hardware evidence and remaining unverified behavior.
