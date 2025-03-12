import logging
import requests
import websockets
import asyncio
import random

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


def decode(r, verbose_errors=True):
    try:
        return r.json()
    except Exception as e:
        if r.status_code == 200:
            logger.error("error while decoding json: error='%s' resp='%s'" % (e, r.text))
        else:
            err = "error %d: %s" % (r.status_code, r.text.strip())
            if verbose_errors:
                logger.info(err)
            raise BettercapError(err)
        return r.text


class Client(object):
    def __init__(self, hostname='localhost', scheme='http', port=8081, username='user', password='pass'):
        self.hostname = hostname
        self.scheme = scheme
        self.port = port
        self.username = username
        self.password = password
        self.url = "%s://%s:%d/api" % (scheme, hostname, port)
        self.websocket = "ws://%s:%s@%s:%d/api" % (username, password, hostname, port)

        retry = Retry(total=5, backoff_factor=min_sleep, backoff_max=max_sleep, backoff_jitter=0.5)
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
