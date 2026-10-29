{ lib, stdenv, stdenvNoCC, python3, makeWrapper, zig_0_16, pkg-config, bluez, systemd, pulseaudio, pipewire, wireplumber, luau }:
let
  python = python3.withPackages (ps: [ ps.dbus-next ]);
  controller = stdenv.mkDerivation {
    pname = "airpodsctl-handoff";
    version = "0.5.0-handoff.1";
    src = ../vendor/airpodsctl;
    nativeBuildInputs = [ zig_0_16 pkg-config ];
    buildInputs = [ bluez systemd ];
    dontConfigure = true;
    postPatch = ''
      substituteInPlace src/server.zig --replace-fail 'self.ensureTransport();' '// External policy never cycles audio profiles.'
    '';
    buildPhase = ''
      export ZIG_GLOBAL_CACHE_DIR="$TMPDIR/zig-global-cache"
      zig build -Doptimize=ReleaseSafe -Dversion=0.5.0-handoff.1
    '';
    doCheck = true;
    checkPhase = ''
      zig build core-check -Doptimize=ReleaseSafe -Dversion=0.5.0-handoff.1 --summary all
    '';
    installPhase = ''
      zig build install -Doptimize=ReleaseSafe -Dversion=0.5.0-handoff.1 --prefix "$out"
    '';
    meta = { description = "Locally extended airpodsctl AACP controller"; license = lib.licenses.mit; platforms = lib.platforms.linux; mainProgram = "airpodsctl"; };
  };
in stdenvNoCC.mkDerivation {
  pname = "airpods-handoff";
  version = "0.3.0";
  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      (lib.fileset.fileFilter (file: file.hasExt "py") ../src)
      (lib.fileset.fileFilter (file: file.hasExt "py") ../tests)
      ../integrations/noctalia
    ];
  };
  nativeBuildInputs = [ python makeWrapper luau ];
  dontConfigure = true;
  dontBuild = true;
  doCheck = true;
  checkPhase = ''
    PYTHONPATH=src python3 -B -m unittest discover -s tests -p 'test_*.py' -v
    luau-compile --binary integrations/noctalia/panel.luau > "$TMPDIR/airpods-panel.luac"
  '';
  installPhase = ''
    mkdir -p "$out/lib/airpods-handoff" "$out/bin"
    cp src/*.py "$out/lib/airpods-handoff/"
    mkdir -p "$out/share/airpods-handoff/noctalia"
    cp integrations/noctalia/* "$out/share/airpods-handoff/noctalia/"
    makeWrapper ${python}/bin/python3 "$out/bin/airpods-handoffctl" \
      --add-flags "$out/lib/airpods-handoff/handoffctl.py"
    makeWrapper ${python}/bin/python3 "$out/bin/airpods-handoff" \
      --add-flags "$out/lib/airpods-handoff/airpods_handoff.py" \
      --set AIRPODS_CTL ${controller}/bin/airpodsctl \
      --set AIRPODS_PACTL ${pulseaudio}/bin/pactl \
      --set AIRPODS_PW_LINK ${pipewire}/bin/pw-link \
      --set AIRPODS_PW_DUMP ${pipewire}/bin/pw-dump
    makeWrapper ${python}/bin/python3 "$out/bin/airpods-handoff-diagnose" \
      --add-flags "$out/lib/airpods-handoff/diagnose.py" \
      --prefix PATH : ${lib.makeBinPath [ systemd wireplumber pipewire ]}
  '';
  passthru = { inherit controller python; };
  meta = {
    description = "Experimental event-driven AirPods ownership handoff for Linux";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "airpods-handoff";
  };
}
