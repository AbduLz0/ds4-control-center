"""Event log, input-rate meter and log export."""
from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

STATE_DIR = Path.home() / '.local' / 'state' / 'ds4-control-center'


class EventLog:
    """Thread-safe ring buffer with monotonically increasing ids."""

    def __init__(self, maxlen: int = 500):
        self._items = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0
        self.enabled = True

    def add(self, kind: str, message: str, force: bool = False):
        """kind: 'button' | 'system' | 'bluetooth'. Input events obey the logging setting."""
        if not self.enabled and kind == 'button' and not force:
            return
        t = time.time()
        with self._lock:
            self._seq += 1
            self._items.append({'id': self._seq, 't': t, 'kind': kind, 'msg': message,
                                'ts': time.strftime('%H:%M:%S', time.localtime(t)) + '.%03d' % int((t % 1) * 1000)})

    def since(self, seq: int, limit: int = 120) -> list:
        with self._lock:
            items = [e for e in self._items if e['id'] > seq]
        return items[-limit:]

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._seq

    def clear(self):
        with self._lock:
            self._items.clear()

    def export(self, directory: Path = STATE_DIR) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / time.strftime('events-%Y%m%d-%H%M%S.log')
        with self._lock:
            lines = ['%s  %-9s %s' % (e['ts'], e['kind'], e['msg']) for e in self._items]
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return path


class RateMeter:
    """Counts raw input events per second without storing individual timestamps."""

    def __init__(self):
        self._sec = 0
        self._count = 0
        self._last = 0
        self._lock = threading.Lock()

    def tick(self, n: int = 1):
        sec = int(time.time())
        with self._lock:
            if sec != self._sec:
                self._last = self._count if sec - self._sec == 1 else 0
                self._sec, self._count = sec, 0
            self._count += n

    def value(self) -> int:
        with self._lock:
            return self._last if int(time.time()) - self._sec <= 1 else 0
