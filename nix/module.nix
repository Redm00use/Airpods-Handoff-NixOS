{ config, lib, pkgs, ... }:
let
  cfg = config.services.airpodsHandoff;
  inherit (lib) mkOption mkEnableOption types mkIf mkDefault;
in {
  options.services.airpodsHandoff = {
    enable = mkEnableOption "experimental AirPods audio ownership handoff";
    user = mkOption { type = types.strMatching "[A-Za-z0-9_.-]+"; description = "Desktop user whose session runs the services."; example = "alice"; };
    device = mkOption { type = types.strMatching "([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"; description = "Already paired AirPods Bluetooth address."; example = "AA:BB:CC:DD:EE:FF"; };
    package = mkOption { type = types.package; default = pkgs.callPackage ./package.nix {}; description = "Handoff package, including its matching AACP controller."; };
    spoofAppleDeviceId = mkOption { type = types.bool; default = false; description = "Advertise an Apple Bluetooth DeviceID to enable experimental multipoint. Applies to the adapter, not just this pair."; };
    shadow = mkOption { type = types.bool; default = false; description = "Observe and log decisions without ownership, pause or audio commands."; };
  };
  config = mkIf cfg.enable {
    hardware.bluetooth.enable = mkDefault true;
    hardware.bluetooth.settings = mkIf cfg.spoofAppleDeviceId {
      General.DeviceID = mkDefault "bluetooth:004C:0000:0000";
    };
    services.pipewire = {
      enable = mkDefault true;
      pulse.enable = mkDefault true;
      wireplumber.enable = mkDefault true;
    };
    security.rtkit.enable = mkDefault true;
    environment.systemPackages = [ cfg.package cfg.package.controller ];
    systemd.user.services.airpodsctl = {
      description = "AirPods AACP controller (external ownership policy)";
      wantedBy = [ "graphical-session.target" ];
      after = [ "graphical-session-pre.target" ];
      partOf = [ "graphical-session.target" ];
      unitConfig.ConditionUser = cfg.user;
      serviceConfig = {
        ExecStart = "${cfg.package.controller}/bin/airpodsctl -v --device ${cfg.device} serve --auto-switch=external";
        Restart = "on-failure";
        RestartSec = 5;
        UMask = "0077";
      };
    };
    systemd.user.services.airpods-auto-switch = {
      description = "AirPods event-driven audio ownership handoff";
      wantedBy = [ "graphical-session.target" ];
      requires = [ "airpodsctl.service" ];
      after = [ "airpodsctl.service" "wireplumber.service" ];
      wants = [ "wireplumber.service" ];
      partOf = [ "graphical-session.target" ];
      unitConfig.ConditionUser = cfg.user;
      environment.AIRPODS_DEVICE = lib.toUpper cfg.device;
      serviceConfig = {
        ExecStart = "${cfg.package}/bin/airpods-handoff${lib.optionalString cfg.shadow " --shadow"}";
        Restart = "on-failure";
        RestartSec = 5;
        KillMode = "control-group";
        UMask = "0077";
        NoNewPrivileges = true;
      };
    };
  };
}
