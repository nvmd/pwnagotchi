{
  description = "";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, flake-utils, nixpkgs, ... }@inputs:

     flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      devShells.default = pkgs.mkShell {
        name = "pwnagotchi";
        nativeBuildInputs = with pkgs; [
          nil # lsp language server for nix
          nixpkgs-fmt
          nix-output-monitor
          bash-language-server
          shellcheck
          (python311.withPackages(ps: with ps; [ 
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
          ]))
        ];
      };
    });

}
