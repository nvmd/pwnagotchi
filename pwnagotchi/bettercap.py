import logging
import requests
import websockets
import asyncio
import random

from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from time import sleep

import pwnagotchi


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
            logging.error("error while decoding json: error='%s' resp='%s'" % (e, r.text))
        else:
            err = "error %d: %s" % (r.status_code, r.text.strip())
            if verbose_errors:
                logging.info(err)
            raise Exception(err)
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

        auth = HTTPBasicAuth(username, password)
        retry = Retry(total=5, backoff_factor=min_sleep, backoff_jitter=0.5, backoff_max=max_sleep)
        adapter = HTTPAdapter(max_retries=retry)
        self.http = requests.Session(auth=auth)
        self.http.mount('http://', adapter)
        self.http.mount('https://', adapter)

    # session takes optional argument to pull a sub-dictionary
    #  ex.: "session/wifi", "session/ble"
    def session(self, sess="session"):
        try:
            r = self.http.get("%s/%s" % (self.url, sess))
            return decode(r)
        except Exception as e:
            raise BettercapException("Error getting session %s", sess) from e

    async def start_websocket(self, consumer):
        s = "%s/events" % self.websocket

        # More modern version of the approach below
        # logging.info("Creating new websocket...")
        # async for ws in websockets.connect(s):
        #     try:
        #         async for msg in ws:
        #             try:
        #                 await consumer(msg)
        #             except Exception as ex:
        #                     logging.debug("Error while parsing event (%s)", ex)
        #     except websockets.exceptions.ConnectionClosedError:
        #         sleep_time = max_sleep*random.random()
        #         logging.warning('Retrying websocket connection in {} sec'.format(sleep_time))
        #         await asyncio.sleep(sleep_time)
        #         continue

        # restarted every time the connection fails
        while True:
            try:
                logging.info("[bettercap] creating new websocket...")
                async for ws in websockets.connect(s, ping_interval=ping_interval, ping_timeout=ping_timeout,
                                                max_queue=max_queue):
                    try:
                        async for msg in ws:
                            try:
                                await consumer(msg)
                            except Exception as ex:
                                logging.debug("[bettercap] error while parsing event (%s)", ex)
                    except websockets.ConnectionClosedError:
                        continue
            except ConnectionRefusedError:
                sleep_time = min_sleep + max_sleep*random.random()
                logging.warning('[bettercap] nobody seems to be listening at the bettercap endpoint...')
                logging.warning('[bettercap] retrying connection in {} sec'.format(sleep_time))
                await asyncio.sleep(sleep_time)
                continue
            except OSError:
                logging.warning('connection to the bettercap endpoint failed...')
                pwnagotchi.restart("AUTO")
                # os.system("service bettercap restart")
                # time.sleep(1)

    def run(self, command, verbose_errors=True):
        try:
            r = self.http.post("%s/session" % self.url, json={'cmd': command})
            return decode(r, verbose_errors=verbose_errors)
        except Exception as e:
            raise BettercapException("Error while executing command %s", command) from e

class BettercapException(Exception):
    pass
