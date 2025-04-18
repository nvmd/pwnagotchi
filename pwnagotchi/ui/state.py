from threading import Lock
from pwnagotchi.ui.components import Widget, Text, LabeledValue

class State(object):
    def __init__(self, state: dict[str, Widget|Text|LabeledValue]={}):
        self._state = state # all ui elements
        self._lock = Lock()
        self._listeners = {}
        self._changes = {}

    def add_element(self, key, elem):
        self._state[key] = elem
        self._changes[key] = True

    def has_element(self, key):
        return key in self._state

    def remove_element(self, key):
        del self._state[key]
        self._changes[key] = True

    def add_listener(self, key, cb):
        with self._lock:
            self._listeners[key] = cb

    def items(self):
        with self._lock:
            return self._state.items()

    def get(self, key):
        with self._lock:
            return self._state[key].value if key in self._state else None

    def reset(self):
        with self._lock:
            self._changes = {}

    def changes(self, ignore=()) -> list[str]:
        with self._lock:
            return self._filter_changes_unsafe(ignore)

    def has_changes(self, ignore=()) -> int:
        with self._lock:
            if ignore != ():
                return len(self._filter_changes_unsafe(ignore)) > 0
            else:
                return len(self._changes) > 0

    def set(self, key, value):
        with self._lock:
            self._set_unsafe(key, value)

    def set_data(self, new_data: dict[str, str]):
        with self._lock:
            for key, val in new_data.items():
                self._set_unsafe(key, val)

    def _set_unsafe(self, key, value):
        if key in self._state:
            prev = self._state[key].value
            self._state[key].value = value

            if prev != value:
                self._changes[key] = True
                if key in self._listeners and self._listeners[key] is not None:
                    self._listeners[key](prev, value)
                    
    def _filter_changes_unsafe(self, ignore=()):
        return list(filter(lambda change: change not in ignore,
                           self._changes.keys()))
