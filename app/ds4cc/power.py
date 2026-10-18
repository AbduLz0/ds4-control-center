"""Battery history, low-battery alerts and idle-disconnect decisions.

Everything here is plain logic with no I/O so it can be tested without hardware.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional


class BatteryHistory:
    """Ring buffer of (time, percent, charging) samples. Cleared on every new connection."""

    def __init__(self, maxlen: int = 720, min_gap: float = 15.0):
        self._items = deque(maxlen=maxlen)  # 720 samples at 20 s is four hours
        self._lock = threading.Lock()
        self._min_gap = min_gap

    def add(self, battery: Optional[dict], now: Optional[float] = None) -> bool:
        if not battery or not isinstance(battery.get('percent'), int):
            return False
        now = time.time() if now is None else now
        with self._lock:
            if self._items and now - self._items[-1][0] < self._min_gap:
                return False
            self._items.append((now, battery['percent'], battery.get('charging')))
            return True

    def clear(self):
        with self._lock:
            self._items.clear()

    def samples(self) -> list:
        with self._lock:
            return [{'t': t, 'pct': p, 'charging': c} for t, p, c in self._items]

    def drain_rate(self) -> Optional[float]:
        """Percent lost per hour over the current discharge run, or None when it cannot be known honestly."""
        with self._lock:
            run = []
            for t, p, c in reversed(self._items):
                if c is not False:  # stop at the most recent charging/unknown sample
                    break
                run.append((t, p))
        if len(run) < 2:
            return None
        (t1, p1), (t0, p0) = run[0], run[-1]  # newest, oldest
        hours = (t1 - t0) / 3600.0
        if hours < 0.25 or p0 - p1 < 2:  # too short or too little change to extrapolate
            return None
        return round((p0 - p1) / hours, 1)


class LowBatteryAlert:
    """One alert per discharge. Re-arms after charging or after recovering above the threshold."""

    def __init__(self):
        self.armed = True

    def check(self, battery: Optional[dict], threshold: int) -> Optional[str]:
        if not battery or threshold <= 0 or not isinstance(battery.get('percent'), int):
            return None
        pct = battery['percent']
        if battery.get('charging') is True or battery.get('full'):
            self.armed = True
            return None
        if pct > threshold + 5:
            self.armed = True
        if battery.get('charging') is False and pct <= threshold and self.armed:
            self.armed = False
            return 'Controller battery is at %d%%. Plug it in soon.' % pct
        return None


def idle_seconds(last_active: Optional[float], connected_since: Optional[float], now: float) -> float:
    base = max(last_active or 0.0, connected_since or 0.0)
    return max(0.0, now - base) if base else 0.0


def should_idle_disconnect(idle_s: float, minutes: int, bus: Optional[str], mac: Optional[str]) -> bool:
    """Only an enabled setting, a Bluetooth link and a known address allow software disconnect."""
    return bool(minutes and minutes > 0 and bus == 'Bluetooth' and mac and idle_s >= minutes * 60)
