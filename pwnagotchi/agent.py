import time
import json
import os
import re
import logging
import asyncio
#import _thread
import threading
import subprocess

import pwnagotchi
import pwnagotchi.utils as utils
import pwnagotchi.plugins as plugins
from pwnagotchi.ui.view import View
from pwnagotchi.identity import KeyPair
from pwnagotchi.ui.web.server import Server
from pwnagotchi.automata import Automata
from pwnagotchi.log import LastSession
from pwnagotchi.bettercap import Client, BettercapConnectionError, BettercapError, BettercapUnknownBSSIDError, BettercapInterfaceNotFoundError
from pwnagotchi.mesh.utils import AsyncAdvertiser
from pwnagotchi.ai.train import AsyncTrainer

logger = logging.getLogger(__name__)

class StaleReconError(Exception):
    pass

class Agent(Client, Automata, AsyncAdvertiser, AsyncTrainer):
    def __init__(self, view: View, config: dict, keypair: KeyPair):
        Client.__init__(self,
                        "127.0.0.1" if "hostname" not in config['bettercap'] else config['bettercap']['hostname'],
                        "http" if "scheme" not in config['bettercap'] else config['bettercap']['scheme'],
                        8081 if "port" not in config['bettercap'] else config['bettercap']['port'],
                        "pwnagotchi" if "username" not in config['bettercap'] else config['bettercap']['username'],
                        "pwnagotchi" if "password" not in config['bettercap'] else config['bettercap']['password'])
        Automata.__init__(self, config, view)
        AsyncAdvertiser.__init__(self, config, view, keypair)
        AsyncTrainer.__init__(self, config)

        self.recovery_file = self._config['main']['state-dir'] + "/" + "recovery.json"

        self._started_at = time.time()

        self._supported_channels = utils.iface_channels(config['main']['iface'])
        self._view = view
        self._view.set_agent(self)
        self._web_ui = Server(self, config['ui'])

        self._current_channel = None
        # APs from the last recon
        self._access_points = []
        # cache computed values from the latest AP recon and channel hop
        self._access_points_by_channel = {}
        self._reset_recon_caches()

        self._history = {}  # MAC addr -> number of interactions
        self._handshakes = {}
        self._last_pwnd = None

        self.last_session = LastSession(self._config)
        self.mode = 'auto'

        if not os.path.exists(config['bettercap']['handshakes']):
            os.makedirs(config['bettercap']['handshakes'])

        logger.info("%s@%s (v%s)", pwnagotchi.name(), self.fingerprint(), pwnagotchi.__version__)
        for _, plugin in plugins.loaded.items():
            logger.debug("plugin '%s' v%s", plugin.__class__.__name__, plugin.__version__)

    def config(self):
        return self._config

    def view(self):
        return self._view

    def supported_channels(self):
        return self._supported_channels

    def setup_events(self):
        for tag in self._config['bettercap']['silence']:
            try:
                self.run('events.ignore %s' % tag, verbose_errors=False)
            except Exception:
                pass

    def _reset_wifi_settings(self):
        mon_iface = self._config['main']['iface']
        self.run('set wifi.interface %s' % mon_iface)
        self.run('set wifi.ap.ttl %d' % self._config['personality']['ap_ttl'])
        self.run('set wifi.sta.ttl %d' % self._config['personality']['sta_ttl'])
        self.run('set wifi.rssi.min %d' % self._config['personality']['min_rssi'])
        self.run('set wifi.handshakes.file %s' % self._config['bettercap']['handshakes'])
        self.run('set wifi.handshakes.aggregate false')

    def start_monitor_mode(self):
        mon_iface = self._config['main']['iface']
        mon_start_cmd = self._config['main']['mon_start_cmd']
        restart = not self._config['main']['no_restart']
        has_mon = False

        while has_mon is False:
            for iface in self.session()['interfaces']:
                if iface['name'] == mon_iface:
                    logger.info("found monitor interface: %s", iface['name'])
                    has_mon = True
                    break

            if has_mon is False:
                if mon_start_cmd is not None and mon_start_cmd != '':
                    logger.info("starting monitor interface ...")
                    self.run('!%s' % mon_start_cmd)
                else:
                    logger.info("waiting for monitor interface %s ...", mon_iface)
                    time.sleep(1)

        logger.info("supported channels: %s", self._supported_channels)
        logger.info("handshakes will be collected inside %s", self._config['bettercap']['handshakes'])

        self._reset_wifi_settings()

        wifi_running = self.is_module_running('wifi')
        if wifi_running and restart:
            logger.debug("restarting wifi module ...")
            self.restart_module('wifi.recon')
            self.run('wifi.clear')
        elif not wifi_running:
            logger.debug("starting wifi module ...")
            self.start_module('wifi.recon')

    def _wait_bettercap(self):
        while True:
            try:
                logger.info(f"connected to bettercap session started at: {self.session('started-at')}")
                return
            except Exception:
                logger.info("waiting for bettercap API to become available ...")
                time.sleep(1)

    def start(self):
        self.set_starting()

        self._maybe_start(self._config['ai']['enabled'], 'ai', self.start_ai)

        self._wait_bettercap()
        self.setup_events()
        self.start_monitor_mode()
        self.start_event_polling()
        self.start_session_fetcher()
        self._maybe_start(self._config['personality']['advertise'], 'advertising',
                          self.start_advertising)

        # print initial stats
        self.next_epoch()
        self.set_ready()

    def recon(self):
        recon_time = self._config['personality']['recon_time']
        max_inactive = self._config['personality']['max_inactive_scale']
        recon_mul = self._config['personality']['recon_inactive_multiplier']
        channels = self._config['personality']['channels']

        if self._epoch.inactive_for >= max_inactive:
            recon_time *= recon_mul

        self._current_channel = None

        if not channels:
            logger.info("RECON %ds", recon_time)
            # Enable channel hopping on all supported channels.
            self.run('wifi.recon.channel clear')
        else:
            # Comma separated list of channels to hop on
            channel_list = ','.join(map(str, channels))
            logger.info("RECON %ds on channels %s", recon_time, channel_list)
            self.run('wifi.recon.channel %s' % channel_list)

        self.set_conducting_recon(recon_time)

    def _set_access_points(self, aps):
        self._access_points = aps

        # Group APs by channel
        channels = self._config['personality']['channels']
        grouped = {}
        for ap in aps:
            ch = ap['channel']
            # if we're sticking to a channel, skip anything
            # which is not on that channel
            if channels and ch not in channels:
                continue
            if ch not in grouped:
                grouped[ch] = [ap]
            else:
                grouped[ch].append(ap)
        self._access_points_by_channel = grouped

        # reset caches
        self._reset_recon_caches()

        # call event subscribers
        self._view_update_aps_stas(self.get_current_channel())
        plugins.on('wifi_update', self, aps)

        self._epoch.observe(aps, list(self._peers.values()))
        return self._access_points

    def _filter_aps(self, unfiltered_aps):
        whitelist = self._config['main']['whitelist']
        aps = []
        for ap in unfiltered_aps:
            if ap['encryption'] == '' or ap['encryption'] == 'OPEN':
                continue
            elif ap['hostname'] in whitelist or ap['mac'][:13].lower() in whitelist or ap['mac'].lower() in whitelist:
                continue
            else:
                aps.append(ap)
        return aps

    def _fetch_access_points(self):
        aps = []
        try:
            all_aps = self.session('wifi')['aps']
            plugins.on("unfiltered_ap_list", self, all_aps)
            aps = self._filter_aps(all_aps)
        except BettercapConnectionError as e:
            raise e
        except Exception as e:
            # consider exceptions other than from bettercap safe to ignore
            logger.exception("Error while getting access points (%s)", e)

        aps.sort(key=lambda ap: ap['channel'])
        return self._set_access_points(aps)

    def _reset_recon_caches(self):
        self._tot_aps = None
        self._tot_stas = None
        self._aps_stas_on_channel = {}

    def get_total_aps_stas(self) -> tuple[int,int]:
        if not self._tot_aps or not self._tot_stas:
            aps = self._access_points
            total_aps = len(aps)
            total_stas = sum(len(ap['clients']) for ap in aps)
            self._tot_aps = total_aps
            self._tot_stas = total_stas

        return (self._tot_aps, self._tot_stas)

    def get_total_aps_stas_on_channel(self, channel: int) -> tuple[int,int] | None:
        if channel not in self._access_points_by_channel:
            return None

        if channel not in self._aps_stas_on_channel:
            aps = self._access_points
            # FIXME: reuse already computed _access_points_by_channel
            # aps_ch = len(self._access_points_by_channel[channel])
            aps_ch = len([ap for ap in aps if ap['channel'] == channel])
            stas_ch = sum(
                [len(ap['clients']) for ap in aps if ap['channel'] == channel])
            self._aps_stas_on_channel[channel] = (aps_ch, stas_ch)

        return self._aps_stas_on_channel[channel]

    def get_current_channel(self) -> int | None:
        return self._current_channel

    def get_access_points_by_channel(self):
        self._fetch_access_points()

        # sort by more populated channels(dict -> list[(ch,aps)])
        return sorted(self._access_points_by_channel.items(),
                      key=lambda kv: len(kv[1]),
                      reverse=True)

    def _resolve_sta_in_ap(self, ap_mac: str, station_mac: str) -> tuple[dict,dict] | None:
        for ap in self.session('wifi')['aps']:
            if ap['mac'] == ap_mac:
                for sta in ap['clients']:
                    if sta['mac'] == station_mac:
                        return ap, sta
                return ap, {'mac': station_mac, 'vendor': ''}
        return None

    def _view_update_aps_stas(self, channel: int | None):
        (total_aps, total_stas) = self.get_total_aps_stas()
        # when called with `current_channel`, it is None during recon,
        # so no per-channel stats available
        if channel:
            (aps_ch, stas_ch) = self.get_total_aps_stas_on_channel(channel)
            self._view.set('aps', '%d (%d)' % (aps_ch, total_aps))
            self._view.set('sta', '%d (%d)' % (stas_ch, total_stas))
        else:
            logger.info(f"Wi-Fi observation: {total_aps} APs, {total_stas} STAs")
            self._view.set('aps', '%d' % total_aps)
            self._view.set('sta', '%d' % total_stas)

    def _view_update_handshakes(self, new, ap_mac_or_name=None):
        num_session = len(self._handshakes)
        num_total = utils.total_unique_handshakes(self._config['bettercap']['handshakes'])

        self._update_advertisement(adv_data = {
            'pwnd_run': num_session,
            'pwnd_tot': num_total,
        })

        self._view.on_handshakes(new, ap_mac_or_name=ap_mac_or_name,
                                 session=num_session, total=num_total)

    def _update_peers(self):
        self._view.set_closest_peer(self._closest_peer, len(self._peers))

    def _reboot(self, reason_msg=None, requested_by=None):
        self.set_rebooting()
        self._save_recovery_data()
        pwnagotchi.reboot(reason_msg=reason_msg, requested_by=requested_by)

    def _restart(self, mode='AUTO', reason_msg=None, requested_by=None):
        self._save_recovery_data()
        pwnagotchi.restart(mode, reason_msg=reason_msg, requested_by=requested_by)

    def _save_recovery_data(self):
        logger.info("writing recovery data to %s ...", self.recovery_file)
        with open(self.recovery_file, 'w') as fp:
            data = {
                'started_at': self._started_at,
                'epoch': self._epoch.epoch,
                'history': self._history,
                'handshakes': self._handshakes,
                'last_pwnd': self._last_pwnd
            }
            json.dump(data, fp)

    def _load_recovery_data(self, delete=True, no_exceptions=True):
        try:
            with open(self.recovery_file, 'rt') as fp:
                data = json.load(fp)
                logger.info("found recovery data: %s", data)
                self._started_at = data['started_at']
                self._epoch.epoch = data['epoch']
                self._handshakes = data['handshakes']
                self._history = data['history']
                self._last_pwnd = data['last_pwnd']

                if delete:
                    logger.info("deleting %s", self.recovery_file)
                    os.unlink(self.recovery_file)
        except:
            if not no_exceptions:
                raise

    def start_session_fetcher(self):
        #_thread.start_new_thread(self._fetch_stats, ())
        threading.Thread(target=self._fetch_stats, args=(), name="Session Fetcher", daemon=True).start()

    def _fetch_stats(self):
        while True:
            uptime_secs = pwnagotchi.uptime()
            self._view.set('uptime', utils.secs_to_hhmmss(uptime_secs))

            self._update_advertisement(adv_data = {
                'uptime': uptime_secs,
                'epoch': self._epoch.epoch, # .next_epoch() is in Automata
            })

            try:
                # self._update_peers()  ################
                self._view.set_closest_peer(self._closest_peer, len(self._peers))
            except Exception as err:
                logger.error("[agent:_fetch_stats] self.update_peers: %s" % repr(err))

            # FIXME:
            # this is really only needed on the first run, to populate historical data
            # view is getting updated on every handshake in `track_handshake`
            # there's no way the number can change outside of that, unless
            # pwnagotchi is running in MANU
            self._view_update_handshakes(0, self._last_pwnd)

            time.sleep(5)

    async def _on_event(self, msg):
        found_handshake = False
        jmsg = json.loads(msg)

        # give plugins access to the events
        try:
            plugins.on('bcap_%s' % re.sub(r"[^a-z0-9_]+", "_", jmsg['tag'].lower()), self, jmsg)
        except Exception as err:
            logger.error("Processing event: %s" % err)

        if jmsg['tag'] == 'wifi.client.handshake':
            filename = jmsg['data']['file']
            sta_mac = jmsg['data']['station']
            ap_mac = jmsg['data']['ap']
            key = "%s -> %s" % (sta_mac, ap_mac)
            
            # check if it's new/unique for this session
            if key in self._handshakes:
                # don't provide ap_mac_or_name – view tracks only the last new
                # and save name lookup with self._find_ap_sta_in
                self.track_handshake(new=0)
                return

            self._handshakes[key] = jmsg
            pwnd_ap = None  # name or mac addr
            ap_and_station = self._resolve_sta_in_ap(ap_mac, sta_mac)
            if ap_and_station is None:
                pwnd_ap = ap_mac

                logger.warning("!!! captured new handshake: %s !!!", key)
                plugins.on('handshake', self, filename, ap_mac, sta_mac)
            else:
                (ap, sta) = ap_and_station
                pwnd_ap = ap['hostname'] if ap['hostname'] != '' and ap[
                    'hostname'] != '<hidden>' else ap_mac

                logger.warning(f"CH {ap['channel']}: "\
                            f"!!! captured new handshake, {ap['rssi']} dBm: "\
                            f"{sta['mac']} ({utils.get_vendor(sta)}) -> "\
                            f"{ap['hostname']} [{ap['mac']} ({utils.get_vendor(ap)})] !!!")
                plugins.on('handshake', self, filename, ap, sta)

            self.track_handshake(new=1, ap_mac_or_name=pwnd_ap)

    def _event_poller(self, loop):
        self._load_recovery_data()
        self.run('events.clear')

        while True:
            logger.debug("[agent:_event_poller] polling events ...")
            try:
                loop.create_task(self.start_websocket(self._on_event))
                loop.run_forever()
                logger.info("[agent:_event_poller] loop loop loop")
            except Exception as ex:
                logger.error("[agent:_event_poller] Error while polling via websocket (%s)", ex)

    def start_event_polling(self):
        # start a thread and pass in the mainloop
        #_thread.start_new_thread(self._event_poller, (asyncio.get_event_loop(),))
        threading.Thread(target=self._event_poller, args=(asyncio.get_event_loop(),), name="Event Polling", daemon=True).start()

    def is_module_running(self, module):
        modules = self.session('modules')
        for m in modules:
            if m['name'] == module:
                return m['running']
        return False

    def start_module(self, module):
        self.run('%s on' % module)

    def restart_module(self, module):
        self.run('%s off; %s on' % (module, module))

    def _has_handshake(self, bssid):
        for key in self._handshakes:
            if bssid.lower() in key:
                return True
        return False
    
    def _is_recon_channel_hopping(self):
        return self._current_channel is None

    def _should_interact(self, who):
        if self._has_handshake(who):
            return False
        if who not in self._history:
            return True
        return self._history[who] < self._config['personality']['max_interactions']
    
    def _should_assoc(self, who):
        return self._config['personality']['associate'] and self._should_interact(who)
    
    def _should_deauth(self, who):
        return self._config['personality']['deauth'] and self._should_interact(who)
    
    def _throttle_if_needed(self, throttle_type):
        if throttle_type not in self._config['personality']:
            logger.warning(f"Unknown throttle_type '{throttle_type}")
            return 0

        throttle = self._config['personality'][throttle_type]
        if throttle > 1:
            # will track sleep time in epoch, we probably don't need that, 
            # and it'll also call the plugins
            # self.sleep_for(throttle)
            # Preserve old semantics for now, just update the view
            self._view.sleep(throttle)
        else:
            time.sleep(throttle)
            self._view.on_normal()
        return throttle

    def track_interaction(self, who):
        if who not in self._history:
            self._history[who] = 1
        else:
            self._history[who] += 1

    def track_assoc(self, who):
        self.track_interaction(who)
        self._epoch.track(assoc=True)
        # NOTE: view isn't updated here because only successful assocs
        # are tracked, but the view tracks (is updated) on an attempt
        # to do so! it may fail

    def track_deauth(self, who):
        self.track_interaction(who)
        self._epoch.track(deauth=True)
        # NOTE: why view isn't update here? see `track_assoc`

    def track_handshake(self, new, ap_mac_or_name=None):
        # numbers of _unique_ handshakes everywhere
        self._epoch.track(handshake=True, inc=new)
        # NOTE: maybe save to `self._handshakes` here as well

        # save only if new in this session
        if new > 0:
            self._last_pwnd = ap_mac_or_name

        # view also tracks successful handshakes
        self._view_update_handshakes(new, self._last_pwnd)

    def associate(self, ap):
        if self.is_stale():
            logger.debug("recon is stale, skipping assoc(%s)", ap['mac'])
            raise StaleReconError()

        if not self._should_assoc(ap['mac']):
            logger.info(f"skipping assoc({ap['hostname']} {ap['mac']})")
            return

        self._view.on_assoc(ap)
        try:
            logger.info(f"CH {ap['channel']}: "\
                        f"sending association frame to {ap['hostname']} ({ap['mac']} {utils.get_vendor(ap)}) "\
                        f"[{len(ap['clients'])} clients], "\
                        f"{ap['rssi']} dBm ...")
            self.run('wifi.assoc %s' % ap['mac'])
            self.track_assoc(ap['mac'])
        except BettercapUnknownBSSIDError as e:
            (ap_mac,) = e.args
            self._on_miss(ap_mac)
        except BettercapInterfaceNotFoundError as e:
            logger.critical(e)
        except BettercapError as e:
            logger.error(e)

        plugins.on('association', self, ap)
        self._throttle_if_needed('throttle_a')

    def deauth(self, ap, sta):
        if self.is_stale():
            logger.debug("recon is stale, skipping deauth(%s)", sta['mac'])
            raise StaleReconError()

        if not self._should_deauth(sta['mac']):
            logger.info(f"skipping deauth({sta['mac']})")
            return

        self._view.on_deauth(sta)
        try:
            logger.info(f"CH {ap['channel']}: "\
                        f"deauthing {sta['mac']} ({utils.get_vendor(sta)}) "\
                        f"from {ap['hostname']} ({ap['mac']} {utils.get_vendor(ap)}), "\
                        f"{ap['rssi']} dBm ...")
            self.run('wifi.deauth %s' % sta['mac'])
            self.track_deauth(sta['mac'])
        except BettercapUnknownBSSIDError as e:
            (ap_mac,) = e.args
            self._on_miss(ap_mac)
        except BettercapInterfaceNotFoundError as e:
            logger.critical(e)
        except BettercapError as e:
            logger.error(e)

        plugins.on('deauthentication', self, ap, sta)
        self._throttle_if_needed('throttle_d')

    def observe_current_channel(self, verbose=True):
        if self._is_recon_channel_hopping():
            logger.error("observe_current_channel is called when "\
                          "recon_channel_hopping is in progress")
            return

        # Wait on the current channel if needed
        # if on the current channel no client stations has been deauthenticated
        # and only association frames have been sent, we don't need to wait
        # on it very long (before switching channel) as we don't have to wait for
        # such client stations to reconnect in order to sniff the handshake.
        deauth_recon_time = self._config['personality']['hop_recon_time']
        assoc_recon_time = self._config['personality']['min_recon_time']
        wait = 0
        if self._epoch.did_deauth and self._epoch.did_associate:
            wait = max(deauth_recon_time, assoc_recon_time)
        elif self._epoch.did_deauth:
            wait = deauth_recon_time
        elif self._epoch.did_associate:
            wait = assoc_recon_time

        if wait > 0:
            if verbose:
                logger.info(f"CH {self._current_channel}: observing for {wait}s")
            else:
                logger.debug(f"CH {self._current_channel}: observing for {wait}s")
            self.set_observing_channel(wait)
        else:
            logger.warning(f"not observing channel {self._current_channel} "\
                             "because no successful deauths or assocs have been "\
                             "previously made in this epoch")

    def set_channel(self, channel: int, verbose=True):
        if self.is_stale():
            logger.debug("recon is stale, skipping set_channel(%d)", channel)
            raise StaleReconError()
        if channel == self._current_channel:
            logger.info(f"already on channel {channel}")
            return

        # Hop to the new channel
        try:
            # only one channel to recon on
            self.run('wifi.recon.channel %d' % channel)
            self._current_channel = channel

            stats = self.get_total_aps_stas_on_channel(channel)
            if stats:
                (aps, stas) = stats
                logger.info(f"CHANNEL {channel}: {aps} APs {stas} STAs")
            else:
                logger.info(f"CHANNEL {channel}")

            self._epoch.track(hop=True)
            self._view.set('channel', '%d' % channel)

            self._view_update_aps_stas(channel)
            plugins.on('channel_hop', self, channel)

        except Exception as e:
            logger.error("Error while setting channel (%s)", e)
            raise e

    def set_policy(self, new_params):
        """
        This method is to be called by any policy maker (AI, auto-tune, etc.)
        to apply the policy
        """
        logger.info("setting new policy:")
        for name, value in new_params.items():
            if name in self._config['personality']:
                curr_value = self._config['personality'][name]
                if curr_value != value:
                    logger.info("! %s: %s -> %s" % (name, curr_value, value))
                    self._config['personality'][name] = value
            else:
                logger.error("param %s not in personality configuration!" % name)

        # apply to bettercap
        self.run('set wifi.ap.ttl %d' % self._config['personality']['ap_ttl'])
        self.run('set wifi.sta.ttl %d' % self._config['personality']['sta_ttl'])
        self.run('set wifi.rssi.min %d' % self._config['personality']['min_rssi'])

    def _maybe_start(self, enabled, name, start_what):
        if enabled:
            start_what()
        else:
            logger.info(f"{name} disabled")
