{
  description = "";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, flake-utils, nixpkgs, ... }@inputs:

     flake-utils.lib.eachDefaultSystem (system: let
      pkgs = import nixpkgs {
        inherit system;
        overlays = [
          (self: super: {

            pythonPackagesExtensions = super.pythonPackagesExtensions ++ [
              (python-self: python-super: {

                stable-baselines3 = python-super.stable-baselines3.overridePythonAttrs (oldAttrs: {
                  disabledTestPaths = oldAttrs.disabledTestPaths ++ super.lib.optional super.stdenv.isDarwin [
                      "tests/test_logger.py"  # darwin: Trace/BPT trap: 5
                  ];
                  # disabledTests = [
                  #   # Upstream
                  #   # Tests that attempt to access the filesystem
                  #   "test_make_atari_env"
                  #   "test_vec_env_monitor_kwargs"
                  # ];
                });

                # needed by stable-baselines3, shimmy
                ale-py = python-super.ale-py.overridePythonAttrs (oldAttrs: {

                  # To propagate `cmakeFlags`
                  # inject `CMAKE_ARGS` into setuptools' invocation of cmake
                  # Shell expansions won't be performed, use `preConfigure` to 
                  # prepare flags that rely on it
                  patchPhase = ''
                    substituteInPlace setup.py \
                      --replace-fail "cmake_args = [" \
                      "cmake_args = os.environ.get(\"CMAKE_ARGS\", \"\").split() + ["
                  '';

                  preConfigure = ''
                    export CMAKE_ARGS=$cmakeFlags "''${cmakeFlagsArray[@]}"
                  '';

                  cmakeFlags = super.lib.optional super.stdenv.isDarwin [
                    "-DCMAKE_CXX_COMPILER_AR=${super.stdenv.cc}/bin/ar"
                    "-DCMAKE_CXX_COMPILER_RANLIB=${super.stdenv.cc}/bin/ranlib"
                  ];

                  meta.broken = false;
                });
              })
            ];

          })
        ];
      };
      forPython = pkgs.python311;
      pythonWithPackages = forPython.withPackages(ps: with ps; [
            pip
            pytest

            dbus-python
            file-read-backwards
            flask
            flask-cors
            flask-wtf
            gast
            # gpiozero  # macos!
            # inky  # https://pypi.org/project/inky/  # macos!
            pillow # Pillow
            pycryptodome
            pydrive2
            python-dateutil
            # python-prctl
            pyyaml # PyYAML
            requests
            # rpi_hardware_pwm  # https://pypi.org/project/rpi-hardware-pwm/  # macos!
            # rpi_lgpio # rpi.lgpio # https://pypi.org/project/rpi-lgpio/  # macos!
            scapy
            # shimmy  # python311Packages.ale-py broken on darwin
            smbus2
            # spidev  # macos!
            # stable-baselines3 # https://pypi.org/project/stable-baselines3/  # python311Packages.ale-py broken on darwin
            toml
            torch
            torchvision
            tweepy
            websockets

            # pythonRuntimeDepsCheck
            gym
            # rpi-gpio  # macos!
            # smbus
          ]);
    in {
      devShells.default = pkgs.mkShell {
        name = "pwnagotchi";
        nativeBuildInputs = with pkgs; [
          nil # lsp language server for nix
          nixpkgs-fmt
          nix-output-monitor
          bash-language-server
          shellcheck
        ];
        buildInputs = with pkgs; [
          forPython.pkgs.venvShellHook
          pythonWithPackages
          forPython.pkgs.dbus-python
        ];
        venvDir = ".venv";

        # These commands are run once after the venv was created
        postVenvCreation = ''
          unset SOURCE_DATE_EPOCH
          # pip install -r requirements.txt
          pip install --editable .
        '';
        # Now we can execute any commands within the virtual environment.
        # This is optional and can be left out to run pip manually.
        postShellHook = ''
          echo running postShellHook
          # allow pip to install wheels
          unset SOURCE_DATE_EPOCH
        '';
      };
    });

}
