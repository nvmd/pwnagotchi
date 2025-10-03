import logging
import time
import signal
import sys
import os

import pwnagotchi
from pwnagotchi import Mode
from pwnagotchi.agent import Agent
from pwnagotchi.agent import StaleReconError
from pwnagotchi.ui.display import Display

class Pwnagotchi:
    def __init__(self, args, config):
        from pwnagotchi.identity import KeyPair
        from pwnagotchi.ui import fonts
        from pwnagotchi import plugins

        self.args = args
        self.config = config

        # make config globally available in the package
        pwnagotchi.config = self.config

        plugins.load(self.config)

        fonts.init(self.config)
        self.display = Display(config=self.config, state={'name': '%s>' % pwnagotchi.name()})

        keypair = KeyPair(path=self.config['main']['state-dir'], view=self.display)

        self.agent = Agent(view=self.display, config=self.config, keypair=keypair)

    def run(self, mode):
        if mode == Mode.MANUAL:
            self.do_manual_mode()
        else:
            self.do_auto_mode()

    def restart(self, mode, reason):
        self.agent._restart(mode, reason_msg=reason)

    def do_manual_mode(self):
        logging.info("entering manual mode ...")

        self.agent.mode = Mode.MANUAL
        self.agent.start_webui()
        self.agent.last_session.parse(self.agent.view(), self.args.skip_session)
        if not self.args.skip_session:
            logging.info(
                "the last session lasted %s (%d completed epochs, trained for %d), average reward:%s (min:%s max:%s)" % (
                    self.agent.last_session.duration_human,
                    self.agent.last_session.epochs,
                    self.agent.last_session.train_epochs,
                    self.agent.last_session.avg_reward,
                    self.agent.last_session.min_reward,
                    self.agent.last_session.max_reward))

        from pwnagotchi import grid, plugins

        while True:
            self.display.on_manual_mode(self.agent.last_session)
            time.sleep(5)
            if grid.is_connected():
                plugins.on('internet_available', self.agent)

    def do_auto_mode(self):
        from pwnagotchi.agent import BettercapConnectionError
        from pwnagotchi import grid, plugins

        logging.info("entering auto mode ...")

        self.agent.mode = Mode.AUTO
        self.agent.last_session.parse(self.agent.view(), self.args.skip_session)  # show stats in AUTO
        self.agent.start()

        while True:
            try:
                # recon on all channels
                self.agent.recon()
                # get nearby access points grouped by channel
                channels = self.agent.get_access_points_by_channel()
                # for each channel
                try:
                    for ch, aps in channels:
                        time.sleep(1)
                        self.agent.set_channel(ch)

                        # for each ap on this channel
                        for ap in aps:
                            # send an association frame in order to get for a PMKID
                            self.agent.associate(ap)
                            # deauth all client stations in order to get a full handshake
                            for sta in ap['clients']:
                                self.agent.deauth(ap, sta)

                        self.agent.observe_current_channel()
                except StaleReconError as e:
                    # don't observe_current_channel() even though some 
                    # assocs/deauths may have been sent
                    # we most probably won't get any replies for assocs/deuths
                    # we've made earlier than recon got stale
                    # if the latter are gone, then the former has even greater
                    # chance of being "gone" by now
                    logging.warning("recon is stale -> end epoch")

                # An interesting effect of this:
                #
                # From Pwnagotchi's perspective, the more new access points
                # and / or client stations nearby, the longer one epoch of
                # its relative time will take ... basically, in Pwnagotchi's universe,
                # Wi-Fi electromagnetic fields affect time like gravitational fields
                # affect ours ... neat ^_^
                self.agent.next_epoch()

                if grid.is_connected():
                    plugins.on('internet_available', self.agent)

            except BettercapConnectionError as e:
                logging.exception(f"Unrecovered bettercap exception: {e}")
                
                # agent._view.sleep(5) # this does time.sleep(5)
                import pwnagotchi.ui.faces as faces
                self.agent._view.update(force=True, new_data={"status": "Restarting bettercap",
                                                              "face": faces.DEBUG})
                logging.warning("Attempting to restart bettercap")

                os.system("service bettercap restart")
                time.sleep(5)
                try:
                    self.agent.setup_monitor_bettercap()
                    logging.warning("Bettercap seems to have recovered")
                except:
                    logging.critical("Bettercap didn't recover")

            except Exception as e:
                if str(e).find("wifi.interface not set") > 0:
                    logging.exception("main loop exception due to unavailable wifi device, likely programmatically disabled (%s)", e)
                    logging.info("sleeping 60 seconds then advancing to next epoch to allow for cleanup code to trigger")
                    time.sleep(60)
                    self.agent.next_epoch()
                else:
                    logging.exception("main loop exception (%s)", e)
