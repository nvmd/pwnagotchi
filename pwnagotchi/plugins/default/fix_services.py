import logging
import re
import subprocess
import time
import random
from io import TextIOWrapper
import os

import pwnagotchi
from pwnagotchi import plugins
from pwnagotchi.agent import Agent
from pwnagotchi.ai.epoch import Epoch
from pwnagotchi.ui.view import View

import pwnagotchi.ui.faces as faces
from pwnagotchi.bettercap import Client

from pwnagotchi.ui.components import Text
from pwnagotchi.ui.view import BLACK
import pwnagotchi.ui.fonts as fonts

logger = logging.getLogger(__name__)


class FixServices(plugins.Plugin):
    __author__ = 'jayofelony'
    __version__ = '1.0'
    __license__ = 'GPL3'
    __description__ = 'Fix blindness, firmware crashes and brain not being loaded'
    __name__ = 'Fix_Services'
    __help__ = """
    Reload brcmfmac module when blindbug is detected, instead of rebooting. Adapted from WATCHDOG.
    """

    def __init__(self):
        self.options = dict()
        self.pattern = re.compile(r'ieee80211 phy0: brcmf_cfg80211_add_iface: iface validation failed: err=-95')
        self.pattern2 = re.compile(r'wifi error while hopping to channel')
        self.pattern3 = re.compile(r'Firmware has halted or crashed')
        self.pattern4 = re.compile(r'error 400: could not find interface wlan0mon')
        self.pattern5 = re.compile(r'fatal error: concurrent map iteration and map write')
        self.pattern6 = re.compile(r'panic: runtime error')
        self.pattern7 = re.compile(r'ieee80211 phy0: _brcmf_set_multicast_list: Setting allmulti failed, -110')
        self.isReloadingMon = False
        self.connection = None
        self.LASTTRY = 0

    def on_loaded(self):
        """
        Gets called when the plugin gets loaded
        """
        logger.info("plugin loaded.")

    def on_ready(self, agent: Agent):
        last_lines = ''.join(list(TextIOWrapper(subprocess.Popen(['journalctl', '-n10', '-k'],
                                                                 stdout=subprocess.PIPE).stdout))[-10:])
        try:
            cmd_output = subprocess.check_output("ip link show wlan0mon", shell=True)
            logger.debug("[ip link show wlan0mon]: %s" % repr(cmd_output))
            if ",UP," in str(cmd_output):
                logger.debug("wlan0mon is up.")

        except Exception as err:
            logger.error("[ip link show wlan0mon]: %s" % repr(err))
            try:
                self._tryTurningItOffAndOnAgain(agent)
            except Exception as err:
                logger.error("[OffNOn]: %s" % repr(err))

    # bettercap sys_log event
    # search syslog events for the brcmf channel fail, and reset when it shows up
    # apparently this only gets messages from bettercap going to syslog, not from syslog
    def on_bcap_sys_log(self, agent: Agent, event):
        if re.search('wifi error while hopping to channel', event['data']['Message']):
            logger.debug("SYSLOG MATCH: %s" % event['data']['Message'])
            logger.debug("**** restarting wifi.recon")
            try:
                result = agent.run("wifi.recon off; wifi.recon on")
                if result["success"]:
                    logger.debug("wifi.recon flip: success!")
                    if hasattr(agent, 'view'):
                        display = agent.view()
                        if display:
                            display.update(force=True, new_data={"status": "Wifi recon flipped!", "face": faces.COOL})
                    else:
                        print("Wifi recon flipped")
                else:
                    logger.warning("wifi.recon flip: FAILED: %s" % repr(result))
                    self._tryTurningItOffAndOnAgain(agent)
            except Exception as err:
                logger.error("SYSLOG wifi.recon flip fail: %s" % err)
                self._tryTurningItOffAndOnAgain(agent)

    def on_epoch(self, agent: Agent, epoch: Epoch, epoch_data):
        last_lines = ''.join(list(TextIOWrapper(subprocess.Popen(['journalctl', '-n10', '-k'],
                                                                 stdout=subprocess.PIPE).stdout))[-10:])
        other_last_lines = ''.join(list(TextIOWrapper(subprocess.Popen(['journalctl', '-n10'],
                                                                       stdout=subprocess.PIPE).stdout))[-10:])
        other_other_last_lines = ''.join(
            list(TextIOWrapper(subprocess.Popen(['tail', '-n10', '/etc/pwnagotchi/log/pwnagotchi.log'],
                                                stdout=subprocess.PIPE).stdout))[-10:])
        # don't check if we ran a reset recently
        logger.debug("**** epoch")
        if time.time() - self.LASTTRY > 180:
            # get last 10 lines
            if hasattr(agent, 'view'):
                display = agent.view()
            else:
                display = None

            logger.debug("**** checking")
            if len(self.pattern.findall(last_lines)) >= 1:
                self.logPrintView("error", "Monitor interface error. Reloading kernel modules, restarting.",
                                    display, {"status": "Monitor interface error. Reloading kernel modules, restarting.",
                                              "face": faces.COOL},
                                    True)
                self._remedy_monstop(display)
                self._remedy_monstart()
                self._remedy_pwnagotchi_restart(agent, display)

            # Look for pattern 2
            elif len(self.pattern2.findall(other_last_lines)) >= 5:
                logger.debug("**** Should trigger a reload of the wlan0mon device:\n%s" % last_lines)
                self.logPrintView("error", "Wifi channel stuck. Restarting recon.",
                                    display, {"status": "Wifi channel stuck. Restarting recon.",
                                              "face": faces.COOL},
                                    True)
                self._remedy_bettercap_recon_off_on(agent, display)

            # Look for pattern 3
            elif len(self.pattern3.findall(other_last_lines)) >= 1:
                self.logPrintView("debug", "Firmware has halted or crashed. Restarting wlan0mon.",
                                    display, {"status": "Firmware has halted or crashed. Restarting wlan0mon.",
                                              "face": faces.COOL},
                                    True)
                self._remedy_monstart()

            # Look for pattern 4
            elif len(self.pattern4.findall(other_other_last_lines)) >= 3:
                self.logPrintView("debug", "wlan0 is down!",
                                  display, {"status": "Restarting wlan0 now!",
                                            "face": faces.COOL},
                                  True)
                self._remedy_monstart()

            # Look for pattern 5
            elif len(self.pattern5.findall(other_other_last_lines)) >= 1:
                logger.debug("Bettercap has crashed!")
                self._remedy_pwnagotchi_restart(agent, display)

            # Look for pattern 6
            elif len(self.pattern6.findall(other_other_last_lines)) >= 1:
                logger.debug("Bettercap has crashed!")
                self._remedy_pwnagotchi_restart(agent, display)

            # Look for pattern 7
            elif len(self.pattern7.findall(other_other_last_lines)) >= 1:
                logger.debug("Monitor mode failed!")
                self._remedy_bettercap_recon_off_on(agent, display)
            else:
                logger.debug("logs look good")

    def _remedy_monstop(self, display: View):
        try:
            cmd_output = subprocess.check_output("monstop", shell=True)
            self.logPrintView("info", "wlan0mon down and deleted: %s" % repr(cmd_output),
                                display, {"status": "wlan0mon d-d-d-down!", "face": faces.BORED})
        except Exception as nope:
            logger.error("[delete wlan0mon] %s" % repr(nope))

    def _remedy_monstart(self):
        try:
            # Run the monstart command to restart wlan0mon
            cmd_output = subprocess.check_output("monstart", shell=True)
            logger.debug("[monstart]: %s" % repr(cmd_output))
        except Exception as err:
            logger.error("[monstart]: %s" % repr(err))

    def _remedy_pwnagotchi_restart(self, agent: Agent, display: View):
        self.logPrintView("error", "restarting bettercap and pwnagotchi",
                                    display, {"status": "Restarting pwnagotchi!",
                                              "face": faces.COOL},
                                    True)
        agent._restart("AUTO")

    def _remedy_bettercap_recon_off_on(self, agent: Client, display: View):
        try:
            result = agent.run("wifi.recon off; wifi.recon on")
            if result["success"]:
                logger.debug("wifi.recon flip: success!")
                self.logPrintView("debug", "wifi.recon flip: success!",
                                    display, {"status": "Wifi recon flipped!",
                                              "face": faces.COOL},
                                    True)
            else:
                logger.warning("wifi.recon flip: FAILED: %s" % repr(result))

        except Exception as err:
            logger.error("[wifi.recon flip] %s" % repr(err))

    def logPrintView(self, level: str, message, ui=None, displayData=None, force=True):
        try:
            lvl = logger.getLevelNamesMapping.get(level.upper())
            if lvl is None:
                lvl = logger.ERROR
            logger.log(lvl, message)

            if ui:
                ui.update(force=force, new_data=displayData)
            elif displayData and "status" in displayData:
                print(displayData["status"])
            else:
                print("[%s] %s" % (level, message))
        except Exception as err:
            logger.error("[logPrintView] ERROR %s" % repr(err))

    def _tryTurningItOffAndOnAgain(self, connection):
        # avoid overlapping restarts, but allow it if it's been a while
        # (in case the last attempt failed before resetting "isReloadingMon")
        if self.isReloadingMon and (time.time() - self.LASTTRY) < 180:
            logger.debug("Duplicate attempt ignored")
        else:
            self.isReloadingMon = True
            self.LASTTRY = time.time()

            if hasattr(connection, 'view'):
                display = connection.view()
                if display:
                    display.update(force=True, new_data={"status": "I'm blind! Try turning it off and on again",
                                                         "face": faces.BORED})
            else:
                display = None

            # main divergence from WATCHDOG starts here
            #
            # instead of rebooting, and losing all that energy loading up the AI
            #    pause wifi.recon, close wlan0mon, reload the brcmfmac kernel module
            #    then recreate wlan0mon, ..., and restart wifi.recon

            # Turn it off

            # attempt a sanity check. does wlan0mon exist?
            # is it up?
            try:
                cmd_output = subprocess.check_output("ip link show wlan0mon", shell=True)
                logger.debug("[ip link show wlan0mon]: %s" % repr(cmd_output))
                if ",UP," in str(cmd_output):
                    logger.debug("wlan0mon is up. Skip reset?")
                    # not reliable, so don't skip just yet
                    # print("wlan0mon is up. Skipping reset.")
                    # self.isReloadingMon = False
                    # return
            except Exception as err:
                logger.error("[ip link show wlan0mon]: %s" % repr(err))

            try:
                result = connection.run("wifi.recon off")
                if "success" in result:
                    self.logPrintView("info", "wifi.recon off: %s!" % repr(result),
                                      display, {"status": "Wifi recon paused!", "face": faces.COOL})
                    time.sleep(2)
                else:
                    self.logPrintView("warning", "wifi.recon off: FAILED: %s" % repr(result),
                                      display, {"status": "Recon was busted (probably)",
                                                "face": random.choice((faces.BROKEN, faces.DEBUG))})
            except Exception as err:
                logger.error("[wifi.recon off] error  %s" % (repr(err)))

            logger.debug("recon paused. Now trying wlan0mon reload")

            self._remedy_monstop(display)

            logger.debug("Now trying modprobe -r")

            # Try this sequence 3 times until it is reloaded
            #
            # Future: while "not fixed yet": blah blah blah. if "max_attemts", then reboot like the old days
            #
            tries = 1
            while tries < 3:
                try:
                    # unload the module
                    cmd_output = subprocess.check_output("sudo modprobe -r brcmfmac", shell=True)
                    self.logPrintView("info", "unloaded brcmfmac", display,
                                      {"status": "Turning it off #%s" % tries, "face": faces.SMART})

                    # reload the module
                    try:
                        # reload the brcmfmac kernel module
                        cmd_output = subprocess.check_output("sudo modprobe brcmfmac", shell=True)

                        self.logPrintView("info", "reloaded brcmfmac")

                        # success! now make the mon0
                        try:
                            cmd_output = subprocess.check_output("monstart", shell=True)
                            self.logPrintView("info", "[interface add wlan0mon worked #%s: %s"
                                              % (tries, cmd_output))
                            try:
                                # try accessing mon0 in bettercap
                                result = connection.run("set wifi.interface wlan0mon")
                                if "success" in result:
                                    logger.debug("[set wifi.interface wlan0mon worked!")
                                    # stop looping and get back to recon
                                    break
                                else:
                                    logger.debug(
                                        "[set wifi.interfaceface wlan0mon] failed? %s" % repr(result))
                            except Exception as err:
                                logger.debug(
                                    "[set wifi.interface wlan0mon] except: %s" % repr(err))
                        except Exception as cerr:  #
                            if not display:
                                print("failed loading wlan0mon attempt #%s: %s" % (tries, repr(cerr)))
                    except Exception as err:  # from modprobe
                        if not display:
                            print("Failed reloading brcmfmac")
                        logger.error("Failed reloading brcmfmac %s" % repr(err))

                except Exception as nope:  # from modprobe -r
                    # fails if already unloaded, so probably fine
                    logger.error("[#%s modprobe -r] %s" % (tries, repr(nope)))
                    if not display:
                        print("[#%s modprobe -r] %s" % (tries, repr(nope)))
                    pass

                tries = tries + 1
                if tries < 3:
                    logger.debug("wlan0mon didn't make it. trying again")
                else:
                    logger.debug("wlan0mon loading failed, no choice but to reboot ..")
                    agent._reboot()

            # exited the loop, so hopefully it loaded
            if tries < 3:
                if display:
                    display.update(force=True, new_data={"status": "And back on again...",
                                                         "face": faces.INTENSE})
                else:
                    print("And back on again...")
                logger.debug("wlan0mon back up")
            else:
                self.LASTTRY = time.time()

            time.sleep(8 + tries * 2)  # give it a bit before restarting recon in bettercap
            self.isReloadingMon = False

            logger.debug("re-enable recon")
            try:
                result = connection.run("wifi.clear; wifi.recon on")

                if "success" in result:  # and result["success"] is True:
                    if display:
                        display.update(force=True, new_data={"status": "I can see again! (probably)",
                                                             "face": faces.HAPPY})
                    else:
                        print("I can see again")
                    logger.debug("wifi.recon on")
                    self.LASTTRY = time.time() + 120  # 2-minute pause until next time.
                else:
                    logger.error("wifi.recon did not start up")
                    self.LASTTRY = time.time() - 300  # failed, so try again ASAP
                    self.isReloadingMon = False

            except Exception as err:
                logger.error("[wifi.recon on] %s" % repr(err))
                agent._reboot()

    # called to setup the ui elements
    def on_ui_setup(self, ui):
        with ui._lock:
            # add custom UI elements
            if "position" in self.options:
                pos = self.options['position'].split(',')
                pos = [int(x.strip()) for x in pos]
            else:
                pos = (ui.width() / 2 + 35, ui.height() - 11)

            logger.debug("on_ui_setup finished")

    # called when the ui is updated
    def on_ui_update(self, ui):
        return

    def on_unload(self, ui):
        return


# run from command line to brute force a reload
if __name__ == "__main__":
    print("Performing brcmfmac reload and restart wlan0mon in 5 seconds...")
    fb = FixServices()

    data = {'Message': "kernel: brcmfmac: brcmf_cfg80211_nexmon_set_channel: Set Channel failed: chspec=1234"}
    event = {'data': data}

    agent = Client('localhost', port=8081, username="pwnagotchi", password="pwnagotchi")

    time.sleep(2)
    print("3 seconds")
    time.sleep(3)
    fb.on_epoch(agent, event, None)
    # fb._tryTurningItOffAndOnAgain(agent)
