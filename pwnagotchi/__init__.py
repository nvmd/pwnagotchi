import os
import logging
import time
import re
from enum import Enum

from pwnagotchi._version import __version__

_name = None
config = None
_cpu_stats = {}

class Mode(Enum):
    AUTO = 1
    MANUAL = 2

def set_name(new_name):
    if new_name is None:
        return

    new_name = new_name.strip()
    if new_name == '':
        return

    if not re.match(r'^[a-zA-Z0-9\-]{2,25}$', new_name):
        logging.warning("name '%s' is invalid: min length is 2, max length 25, only a-zA-Z0-9- allowed", new_name)
        return

    current = name()
    if new_name != current:
        global _name

        logging.info("setting unit hostname '%s' -> '%s'", current, new_name)
        with open('/etc/hostname', 'wt') as fp:
            fp.write(new_name)

        with open('/etc/hosts', 'rt') as fp:
            prev = fp.read()
            logging.debug("old hosts:\n%s\n", prev)

        with open('/etc/hosts', 'wt') as fp:
            patched = prev.replace(current, new_name, -1)
            logging.debug("new hosts:\n%s\n", patched)
            fp.write(patched)

        os.system("hostname '%s'" % new_name)
        reboot(reason_msg="Setting name")


def name():
    global _name
    if _name is None:
        with open('/etc/hostname', 'rt') as fp:
            _name = fp.read().strip()
    return _name


def uptime():
    with open('/proc/uptime') as fp:
        return int(fp.read().split('.')[0])


def mem_usage():
    with open('/proc/meminfo') as fp:
        for line in fp:
            line = line.strip()
            if line.startswith("MemTotal:"):
                kb_mem_total = int(line.split()[1])
            if line.startswith("MemFree:"):
                kb_mem_free = int(line.split()[1])
            if line.startswith("Buffers:"):
                kb_main_buffers = int(line.split()[1])
            if line.startswith("Cached:"):
                kb_main_cached = int(line.split()[1])
        kb_mem_used = kb_mem_total - kb_mem_free - kb_main_cached - kb_main_buffers
        return round(kb_mem_used / kb_mem_total, 1)


def _cpu_stat():
    """
    Returns the split first line of the /proc/stat file
    """
    with open('/proc/stat', 'rt') as fp:
        return list(map(int, fp.readline().split()[1:]))


def cpu_load(tag=None):
    """
    Returns the current cpuload
    """
    if tag and tag in _cpu_stats.keys():
        parts0 = _cpu_stats[tag]
    else:
        parts0 = _cpu_stat()
        time.sleep(0.1)     # only need to sleep when no tag
    parts1 = _cpu_stat()
    if tag:
        _cpu_stats[tag] = parts1

    parts_diff = [p1 - p0 for (p0, p1) in zip(parts0, parts1)]
    user, nice, sys, idle, iowait, irq, softirq, steal, _guest, _guest_nice = parts_diff
    idle_sum = idle + iowait
    non_idle_sum = user + nice + sys + irq + softirq + steal
    total = idle_sum + non_idle_sum
    return non_idle_sum / total


def temperature(celsius=True):
    with open('/sys/class/thermal/thermal_zone0/temp', 'rt') as fp:
        temp = int(fp.read().strip())
    c = int(temp / 1000)
    return c if celsius else ((c * (9 / 5)) + 32)


def shutdown(reason_msg=None, requested_by=None):
    logging.warning(f"shutting down, reason={reason_msg}, by={requested_by}...")

    from pwnagotchi.ui import view
    if view.ROOT:
        view.ROOT.on_shutdown()
        # give it some time to refresh the ui
        time.sleep(10)

    logging.warning("syncing...")

    from pwnagotchi import fs
    for m in fs.mounts:
        m.sync()
 
    os.system("sync")
    os.system("halt")


def restart(mode: Mode|None, reason_msg=None, requested_by=None):
    logging.warning(f"restarting: mode={mode}, reason={reason_msg}, by={requested_by}...")

    match mode:
        case Mode.AUTO:
            os.system("touch /root/.pwnagotchi-auto")
        case Mode.MANUAL:
            os.system("touch /root/.pwnagotchi-manual")

    os.system("service bettercap restart")
    time.sleep(1)
    # rely on a service manager (like systemd)
    # to restart us according to restart policy
    logging.critical("Exiting to be restarted...")
    os._exit(2) # kill all threads


def reboot(mode: Mode|None = None, reason_msg=None, requested_by=None):
    logging.warning(f"rebooting: mode={mode}, reason={reason_msg}, by={requested_by}...")

    from pwnagotchi.ui import view
    if view.ROOT:
        view.ROOT.on_rebooting(reason_msg=reason_msg)
        # give it some time to refresh the ui
        time.sleep(10)

    match mode:
        case Mode.AUTO:
            os.system("touch /root/.pwnagotchi-auto")
        case Mode.MANUAL:
            os.system("touch /root/.pwnagotchi-manual")

    logging.warning("syncing...")

    from pwnagotchi import fs
    for m in fs.mounts:
        m.sync()

    os.system("sync")
    os.system("shutdown -r now")
