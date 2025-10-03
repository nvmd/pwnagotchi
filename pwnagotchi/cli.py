import logging
import argparse
import time
import signal
import sys
import toml
import requests
import os
import re

import pwnagotchi
from pwnagotchi import Pwnagotchi
from pwnagotchi import Mode
from pwnagotchi.utils import DottedTomlEncoder
from pwnagotchi import utils
from pwnagotchi import log
from pwnagotchi import fs
from pwnagotchi.google import cmd as google_cmd
from pwnagotchi.plugins import cmd as plugins_cmd

def pwnagotchi_cli():
    def add_parsers(parser):
        """
        Adds the plugins and google subcommands
        """
        subparsers = parser.add_subparsers()

        # Add parsers from plugins_cmd
        plugins_cmd.add_parsers(subparsers)

        # Add parsers from google_cmd
        google_cmd.add_parsers(subparsers)

    parser = argparse.ArgumentParser(prog="pwnagotchi")
    # pwnagotchi --help
    parser.add_argument('-C', '--config', action='store', dest='config', default='/etc/pwnagotchi/default.toml',
                        help='Main configuration file.')
    parser.add_argument('-U', '--user-config', action='store', dest='user_config', default='/etc/pwnagotchi/config.toml',
                        help='If this file exists, configuration will be merged and this will override default values.')

    parser.add_argument('--manual', dest="do_manual", action="store_true", default=False, help="Manual mode.")
    parser.add_argument('--skip-session', dest="skip_session", action="store_true", default=False,
                        help="Skip last session parsing in manual mode.")

    parser.add_argument('--clear', dest="do_clear", action="store_true", default=False,
                        help="Clear the ePaper display and exit.")

    parser.add_argument('--debug', dest="debug", action="store_true", default=False,
                        help="Enable debug logs.")

    parser.add_argument('--version', dest="version", action="store_true", default=False,
                        help="Print the version.")

    parser.add_argument('--print-config', dest="print_config", action="store_true", default=False,
                        help="Print the configuration.")

    # pwnagotchi plugins --help
    add_parsers(parser)
    args = parser.parse_args()

    if plugins_cmd.used_plugin_cmd(args):
        config = utils.load_config(args)
        log.setup_logging(args, config)
        rc = plugins_cmd.handle_cmd(args, config)
        sys.exit(rc)
    if google_cmd.used_google_cmd(args):
        config = utils.load_config(args)
        log.setup_logging(args, config)
        rc = google_cmd.handle_cmd(args)
        sys.exit(rc)

    if args.version:
        print(pwnagotchi.__version__)
        sys.exit(0)

    config = utils.load_config(args)
    log.setup_logging(args, config)

    if args.print_config:
        print(toml.dumps(config, encoder=DottedTomlEncoder()))
        sys.exit(0)

    if args.do_clear:
        from pwnagotchi.ui.display import Display
        display = Display(config=config)
        logging.info("clearing the display ...")
        display.clear()
        sys.exit(0)

    pwnagotchi.set_name(config['main']['name'])
    fs.setup_mounts(config)

    pwn = Pwnagotchi(args, config)

    def usr1_handler(*unused):
        logging.info('Received USR1 signal. Restart process ...')
        pwn.restart(Mode.MANUAL if args.do_manual else Mode.AUTO, reason="USR1 signal")

    signal.signal(signal.SIGUSR1, usr1_handler)
    
    pwn.run(Mode.MANUAL if args.do_manual else Mode.AUTO)


if __name__ == '__main__':
    pwnagotchi_cli()
