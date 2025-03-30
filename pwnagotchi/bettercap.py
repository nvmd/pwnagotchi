import logging
import requests
import websockets
import asyncio
import random
import re

from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

import pwnagotchi

logger = logging.getLogger(__name__)

ping_timeout = 180
ping_interval = 15
max_queue = 10000

min_sleep = 0.5
max_sleep = 5.0

websockets.connect.BACKOFF_INITIAL_DELAY = min_sleep
websockets.connect.BACKOFF_MIN_DELAY = min_sleep
websockets.connect.BACKOFF_MAX_DELAY = max_sleep


def decode(resp, verbose_errors=True):
    try:
        return resp.json()
    except Exception as e:
        error_text = resp.text.strip()
        error_msg = f"error {resp.status_code}: {error_text}"

        match resp.status_code:
            case 200:
                logger.error("error while decoding json: error='%s' resp='%s'" % (e, resp.text))
                return resp.text
            case 400:
                if 'is an unknown BSSID' in error_text:
                    # 50:c7:de:ee:d3:47 is an unknown BSSID or it is in the association skip list.
                    bssid = None
                    try:
                        bssid = extract_error_info_bssid(error_text)
                    except Exception as e:
                        logger.error(f"{e}")
                    raise BettercapUnknownBSSIDError(bssid)
                elif 'could not find interface' in error_text:
                    # error_text = "could not find interface wlan0mon: no interface matching 'wlan0mon' found.

                    # NOTE: we still need this (error_msg) particular log line, 
                    # so that fix_services can pick it up
                    # This obviously should be handled in a less roundabout way
                    logger.critical(error_msg)

                    interface = None
                    reason = None
                    try:
                        (interface, reason) = extract_error_info_interface(error_text)
                    except Exception as e:
                        logger.error(f"{e}")

                    # TODO:
                    # * run the monstart command to restart wlan0mon
                    # * restart bettercap?
                    raise BettercapInterfaceNotFoundError(interface, reason)
                elif 'is not running' in error_text:
                    # module wifi is not running
                    logger.critical(error_msg)

                    module_name = None
                    try:
                        module_name = extract_error_info_module(error_text)
                    except Exception as e:
                        logger.error(f"{e}")

                    raise BettercapModuleNotRunningError(module_name)

        if verbose_errors:
            logger.info(error_msg)
        raise BettercapError(error_msg)

def extract_error_info_bssid(error_text: str) -> str:
    error_text_cleared = error_text.strip()
    bssid = None

    idx = error_text_cleared.find("is an unknown BSSID")
    if idx == -1:
        print(f"idx = {idx}")
        raise ValueError(f"error message '{error_text}' is malformed")

    bssid = error_text_cleared[0:idx].strip()
    if len(bssid) != 17:
        if bssid == '':
            raise ValueError("no BSSID")
        raise ValueError(f"invalid BSSID {bssid}")

    return bssid

def extract_error_info_module(error_text: str) -> str:
    error_text_cleared = error_text.strip()
    # most probably one of the precomputed values will suffice
    match error_text_cleared:
        case "module wifi is not running":
            return "wifi"

    module_name = None
    try:
        pattern = re.compile(r'module (?P<module>[^\s]*) is not running')
        match = pattern.search(error_text_cleared)
        module_name = match.group('module').strip()
    except Exception as e:
        raise ValueError(f"error message '{error_text}' is malformed") from e
    return module_name

def extract_error_info_interface(error_text: str) -> tuple[str, str]:
    error_text_cleared = error_text.strip()
    # most probably one of the precomputed values will suffice
    match error_text_cleared:
        case "could not find interface wlan0mon: no interface matching 'wlan0mon' found.":
            return ("wlan0mon", "no interface matching 'wlan0mon' found.")

    interface = None
    reason = None
    try:
        # assuming <interface> is mandatory and <reason> is optional
        pattern = re.compile(r'could not find interface (?P<interface>[^:\s]+)(: (?P<reason>.*))*')
        match = pattern.search(error_text_cleared)
        interface = match.group('interface').strip()
        reason_match = match.group('reason')
        reason = None
        if reason_match:
            reason = reason_match.strip()
    except Exception as e:
        raise ValueError(f"error message '{error_text}' is malformed") from e
    return (interface, reason)

class Client(object):
    def __init__(self, hostname='localhost', scheme='http', port=8081,
                 username='user', password='pass'):
        self.url = "%s://%s:%d/api" % (scheme, hostname, port)
        self.websocket = "ws://%s:%s@%s:%d/api" % (username, password,
                                                   hostname, port)

        retry = Retry(total=5, backoff_factor=min_sleep, backoff_max=max_sleep,
                      backoff_jitter=0.5)
        adapter = HTTPAdapter(max_retries=retry)

        self.http = requests.Session()
        self.http.auth = HTTPBasicAuth(username, password)
        self.http.mount('http://', adapter)
        self.http.mount('https://', adapter)

    # session takes optional argument to pull a sub-dictionary
    #  ex.: "session/wifi", "session/ble"
    def session(self, sess="session"):
        try:
            r = self.http.get("%s/%s" % (self.url, sess))
            return decode(r)
        except Exception as e:
            raise BettercapConnectionError(f"Error getting session {sess}") from e

    async def start_websocket(self, consumer):
        s = "%s/events" % self.websocket

        # restarted every time the connection fails
        # do we need this outer loop to manage the initial connection?
        while True:
            try:
                logger.debug("creating new websocket...")
                async for ws in websockets.connect(s, ping_interval=ping_interval, ping_timeout=ping_timeout,
                                                max_queue=max_queue):
                    logger.info("connected to websocket")
                    try:
                        async for msg in ws:
                            try:
                                await consumer(msg)
                            except Exception as ex:
                                logger.debug("error while parsing event (%s)", ex)
                    except websockets.ConnectionClosedError:
                        continue
            except ConnectionRefusedError:
                sleep_time = min_sleep + max_sleep*random.random()
                logger.warning('nobody seems to be listening at the bettercap endpoint')
                logger.warning('retrying connection in {} sec'.format(sleep_time))
                await asyncio.sleep(sleep_time)
                continue
            except Exception as e:
                logger.error('connection to the websocket endpoint failed')
                logger.error('hoping that the error will be detected via `session` fail and bettercap will be restarted')
                # TODO: recovery procedure.
                # can't just reraise an exception because we're not in the main thread

    def run(self, command, verbose_errors=True):
        try:
            r = self.http.post("%s/session" % self.url, json={'cmd': command})
            return decode(r, verbose_errors=verbose_errors)
        except BettercapError as e:
            raise e
        except Exception as e:
            raise BettercapConnectionError(f"Error while executing command '{command}'") from e

class BettercapConnectionError(Exception):
    pass
class BettercapError(Exception):
    pass
class BettercapUnknownBSSIDError(BettercapError):
    pass
class BettercapInterfaceNotFoundError(BettercapError):
    pass
class BettercapModuleNotRunningError(BettercapError):
    pass