{
  description = "Experimental event-driven AirPods Pro 2 handoff for NixOS";
  inputs.nixpkgs.url = "github:nixos/nixpkgs/718f670e845328e9c2cecdd832835712b2cbd065";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      packageFor = system: (import nixpkgs { inherit system; }).callPackage ./nix/package.nix {};
      moduleConfiguration = system: (nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [ ./nix/module.nix {
          system.stateVersion = "26.05";
          services.airpodsHandoff = { enable = true; user = "alice"; device = "AA:BB:CC:DD:EE:FF"; spoofAppleDeviceId = true; };
        } ];
      }).config;
    in {
      nixosModules.default = import ./nix/module.nix;
      nixosModules.airpodsHandoff = self.nixosModules.default;
      packages = eachSystem (system: let app = packageFor system; in {
        default = app;
        airpods-handoff = app;
        airpodsctl = app.controller;
      });
      checks = eachSystem (system:
        let
          pkgs = import nixpkgs { inherit system; };
          cfg = moduleConfiguration system;
          contract = pkgs.writeText "handoff-module-contract.json" (builtins.toJSON {
            user = cfg.systemd.user.services.airpodsctl.unitConfig.ConditionUser;
            device = cfg.systemd.user.services.airpods-auto-switch.environment.AIRPODS_DEVICE;
            controller = cfg.systemd.user.services.airpodsctl.serviceConfig.ExecStart;
            handoff = cfg.systemd.user.services.airpods-auto-switch.serviceConfig.ExecStart;
            deviceId = cfg.hardware.bluetooth.settings.General.DeviceID;
          });
        in {
          unit = self.packages.${system}.default;
          protocol = self.packages.${system}.airpodsctl;
          cli = pkgs.runCommand "airpods-handoff-cli-check" {} ''
            ${self.packages.${system}.default}/bin/airpods-handoff --help > /dev/null
            ${self.packages.${system}.default}/bin/airpods-handoffctl --help > /dev/null
            if AIRPODS_DEVICE=invalid ${self.packages.${system}.default}/bin/airpods-handoff > /dev/null 2>&1; then
              exit 1
            fi
            test -f ${self.packages.${system}.default}/share/airpods-handoff/noctalia/plugin.toml
            test -f ${self.packages.${system}.default}/share/airpods-handoff/noctalia/panel.luau
            touch "$out"
          '';
          module = pkgs.runCommand "airpods-handoff-module-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
            python3 - <<'PY'
            import json
            d=json.load(open('${contract}'))
            assert d['user']=='alice'
            assert d['device']=='AA:BB:CC:DD:EE:FF'
            assert '--device AA:BB:CC:DD:EE:FF' in d['controller']
            assert 'serve --auto-switch=external' in d['controller']
            assert d['handoff'].endswith('/bin/airpods-handoff')
            assert d['deviceId']=='bluetooth:004C:0000:0000'
            PY
            touch "$out"
          '';
        });
      devShells = eachSystem (system: let pkgs = import nixpkgs { inherit system; }; app = packageFor system; in {
        default = pkgs.mkShell {
          packages = [ app.python pkgs.zig_0_16 pkgs.pkg-config pkgs.bluez pkgs.systemd pkgs.luau ];
          shellHook = ''export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"'';
        };
      });
    };
}
