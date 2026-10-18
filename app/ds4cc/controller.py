"""Controller discovery and live input via Linux evdev.

Design notes
* A DualShock 4 shows up as up to three input nodes: the gamepad, a touchpad
  and motion sensors. Detection reads /sys/class/input (world readable), so
  permission problems can be reported instead of silently skipping the device.
* Event-code -> button mapping uses the stable kernel ABI numbers, so all of the
  mapping logic is plain Python and testable without hardware or python-evdev.
* One reader thread multiplexes every node with select(); all file descriptors
  are closed when the controller disappears or the app shuts down.
"""
from __future__ import annotations

import errno
import math
import os
import select
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .diagnostics import EventLog, RateMeter
from .power import BatteryHistory

SYS_INPUT = Path('/sys/class/input')
SYS_POWER = Path('/sys/class/power_supply')
DEV_INPUT = Path('/dev/input')
SONY_VID = 0x054C
BUS_NAMES = {0x03: 'USB', 0x05: 'Bluetooth'}
DRIVER_NAMES = {'playstation': 'hid-playstation', 'sony': 'hid-sony', 'hid-generic': 'hid-generic'}

EV_KEY, EV_ABS = 0x01, 0x03
BTN_LEFT, BTN_SOUTH = 0x110, 0x130

BUTTON_CODES = {
    0x130: 'cross', 0x131: 'circle', 0x133: 'triangle', 0x134: 'square',
    0x136: 'l1', 0x137: 'r1', 0x138: 'l2', 0x139: 'r2',
    0x13A: 'share', 0x13B: 'options', 0x13C: 'ps', 0x13D: 'l3', 0x13E: 'r3',
    0x220: 'dpad-up', 0x221: 'dpad-down', 0x222: 'dpad-left', 0x223: 'dpad-right',
}
BUTTONS = ['cross', 'circle', 'square', 'triangle', 'dpad-up', 'dpad-down', 'dpad-left', 'dpad-right',
           'l1', 'r1', 'l2', 'r2', 'l3', 'r3', 'share', 'options', 'ps', 'touchpad']
LABELS = {'cross': 'Cross', 'circle': 'Circle', 'square': 'Square', 'triangle': 'Triangle',
          'dpad-up': 'D-pad up', 'dpad-down': 'D-pad down', 'dpad-left': 'D-pad left', 'dpad-right': 'D-pad right',
          'l1': 'L1', 'r1': 'R1', 'l2': 'L2', 'r2': 'R2', 'l3': 'L3 (stick click)', 'r3': 'R3 (stick click)',
          'share': 'Share', 'options': 'Options', 'ps': 'PS button', 'touchpad': 'Touchpad click'}

ABS_STICKS = {0x00: 'lx', 0x01: 'ly', 0x03: 'rx', 0x04: 'ry'}
ABS_TRIGGERS = {0x02: 'l2', 0x05: 'r2', 0x0A: 'l2', 0x09: 'r2'}  # Z/RZ, BRAKE/GAS
ABS_HAT = {0x10: 'x', 0x11: 'y'}
ABS_MOTION = {0x00: 'ax', 0x01: 'ay', 0x02: 'az', 0x03: 'gx', 0x04: 'gy', 0x05: 'gz'}
ABS_MT_SLOT, ABS_MT_TRACKING_ID, ABS_MT_X, ABS_MT_Y = 0x2F, 0x39, 0x35, 0x36


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------
def norm_stick(value: int, lo: int, hi: int) -> float:
    """Map a raw stick value to -1..1 with the integer centre at exactly 0."""
    center = (lo + hi + 1) / 2.0
    if value >= center:
        span = max(1.0, hi - center)
    else:
        span = max(1.0, center - lo)
    return round(max(-1.0, min(1.0, (value - center) / span)), 3)


def norm_unit(value: int, lo: int, hi: int) -> float:
    return round(max(0.0, min(1.0, (value - lo) / float(max(1, hi - lo)))), 3)


def parse_caps(text: str) -> set:
    """Parse a sysfs capability bitmap (space-separated hex words, MSW first)."""
    wsize = struct.calcsize('L') * 8
    bits = set()
    for i, word in enumerate(reversed(text.split())):
        try:
            v = int(word, 16)
        except ValueError:
            continue
        for b in range(wsize):
            if (v >> b) & 1:
                bits.add(i * wsize + b)
    return bits


def classify(name: str, keys: set, abses: set) -> str:
    lname = name.lower()
    if 'touchpad' in lname and (ABS_MT_X in abses or BTN_LEFT in keys):
        return 'touchpad'
    if 'motion sensors' in lname or ({0, 1, 2, 3, 4, 5} <= abses and not keys):
        return 'motion'
    if BTN_SOUTH in keys:  # BTN_SOUTH == BTN_GAMEPAD
        return 'gamepad'
    return 'other'


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return ''


def _hex(path: Path) -> int:
    try:
        return int(_read(path) or '0', 16)
    except ValueError:
        return 0


@dataclass
class Node:
    event: str
    path: str
    name: str
    vendor: int
    product: int
    bus: int
    uniq: str
    phys: str
    virtual: bool
    role: str
    readable: bool
    devdir: str
    writable: bool = False

    @property
    def number(self) -> int:
        try:
            return int(self.event[5:])
        except ValueError:
            return 0

    @property
    def group(self):
        return (self.vendor, self.product, self.uniq or self.phys.split('/')[0])

    @property
    def bus_name(self) -> str:
        return BUS_NAMES.get(self.bus, 'Unknown')

    def public(self) -> dict:
        return {'role': self.role, 'name': self.name, 'event': self.event, 'readable': self.readable,
                'writable': self.writable, 'virtual': self.virtual}


def scan_nodes(root: Path = SYS_INPUT, dev_root: Path = DEV_INPUT) -> list:
    nodes = []
    try:
        entries = [p for p in root.iterdir() if p.name.startswith('event')]
    except OSError:
        return nodes
    entries.sort(key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 0)
    for ev in entries:
        dev = ev / 'device'
        name = _read(dev / 'name')
        if not name:
            continue
        keys = parse_caps(_read(dev / 'capabilities' / 'key'))
        abses = parse_caps(_read(dev / 'capabilities' / 'abs'))
        role = classify(name, keys, abses)
        if role == 'other':
            continue
        real = os.path.realpath(str(ev))
        path = str(dev_root / ev.name)
        nodes.append(Node(
            event=ev.name, path=path, name=name,
            vendor=_hex(dev / 'id' / 'vendor'), product=_hex(dev / 'id' / 'product'),
            bus=_hex(dev / 'id' / 'bustype'), uniq=_read(dev / 'uniq').lower(), phys=_read(dev / 'phys'),
            virtual='/virtual/' in real, role=role,
            readable=os.access(path, os.R_OK), writable=os.access(path, os.W_OK), devdir=str(dev)))
    return nodes


def pick_controller(nodes: list):
    """Return (primary_gamepad, [touchpad/motion companions]) or None."""
    pads = [n for n in nodes if n.role == 'gamepad']
    if not pads:
        return None
    pads.sort(key=lambda n: (n.virtual, n.vendor != SONY_VID, n.number))
    primary = pads[0]
    companions = [n for n in nodes if n is not primary and n.role in ('touchpad', 'motion')
                  and n.group == primary.group]
    return primary, companions


def kernel_driver(devdir: str) -> Optional[str]:
    try:
        link = Path(devdir).resolve().parent / 'driver'
        if link.exists():
            name = os.path.basename(os.path.realpath(str(link)))
            return DRIVER_NAMES.get(name, name)
    except OSError:
        pass
    return None


def read_battery(node: Node, power_root: Path = SYS_POWER) -> Optional[dict]:
    """Best-effort battery lookup. Returns None when the kernel does not expose one."""
    candidates = []
    try:  # the power supply hangs off the HID device, a level or two above the input node
        here = Path(node.devdir).resolve()
        for parent in (here.parent, here.parent.parent):
            candidates += list(parent.glob('power_supply/*'))
    except OSError:
        pass
    mac = node.uniq
    try:
        for p in power_root.iterdir():
            n = p.name.lower()
            if (mac and mac in n) or ('controller' in n and 'battery' in n and not mac):
                candidates.append(p)
    except OSError:
        pass
    for p in candidates:
        cap = _read(p / 'capacity')
        if cap.isdigit():
            status = _read(p / 'status') or 'Unknown'
            return {'percent': max(0, min(100, int(cap))), 'status': status,
                    'charging': True if status.lower() == 'charging' else
                    (False if status.lower() in ('discharging', 'not charging') else None),
                    'full': status.lower() == 'full'}
    return None


# --------------------------------------------------------------------------
# input state
# --------------------------------------------------------------------------
class InputState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.down = set()
        self.counts = dict.fromkeys(BUTTONS, 0)
        self.axes = {k: 0.0 for k in ('lx', 'ly', 'rx', 'ry', 'l2', 'r2')}
        self.analog = {'l2': False, 'r2': False}
        self.touch = [{'active': False, 'x': 0.0, 'y': 0.0} for _ in range(2)]
        self._slot = 0
        self.touch_seen = False
        self.motion = None
        self.units = {'accel': 'raw', 'gyro': 'raw'}

    def is_active(self) -> bool:
        """True while the player is holding something: a button, a finger, a trigger or a stick away from centre.
        Resting stick noise stays well below the 0.25 threshold, so it does not count."""
        if self.down or any(f['active'] for f in self.touch):
            return True
        if self.axes['l2'] > 0.05 or self.axes['r2'] > 0.05:
            return True
        return (math.hypot(self.axes['lx'], self.axes['ly']) > 0.25
                or math.hypot(self.axes['rx'], self.axes['ry']) > 0.25)

    def _button(self, name: str, value: int):
        if value == 2:  # key auto-repeat
            return False, None
        pressed = bool(value)
        if pressed == (name in self.down):
            return False, None
        if pressed:
            self.down.add(name)
            self.counts[name] += 1
        else:
            self.down.discard(name)
        verb = 'pressed' if pressed else 'released'
        return True, '%s %s' % (LABELS[name], verb)

    def apply(self, role: str, etype: int, code: int, value: int, ai=None):
        """Apply one kernel event. Returns (state_changed, log_message_or_None).
        `ai` is an object with .min/.max/.resolution for ABS events."""
        lo = getattr(ai, 'min', 0)
        hi = getattr(ai, 'max', 255)
        if etype == EV_KEY:
            if role == 'touchpad':
                return self._button('touchpad', value) if code == BTN_LEFT else (False, None)
            name = BUTTON_CODES.get(code) if role == 'gamepad' else None
            return self._button(name, value) if name else (False, None)
        if etype != EV_ABS:
            return False, None
        if role == 'gamepad':
            if code in ABS_STICKS:
                key = ABS_STICKS[code]
                new = norm_stick(value, lo, hi)
            elif code in ABS_TRIGGERS:
                key = ABS_TRIGGERS[code]
                self.analog[key] = True
                new = norm_unit(value, lo, hi)
            elif code in ABS_HAT:
                neg, pos = (('dpad-left', 'dpad-right') if ABS_HAT[code] == 'x' else ('dpad-up', 'dpad-down'))
                msgs = []
                for name, active in ((neg, value < 0), (pos, value > 0)):
                    changed, msg = self._button(name, 1 if active else 0)
                    if changed:
                        msgs.append(msg)
                return (bool(msgs), '; '.join(msgs) or None)
            else:
                return False, None
            if self.axes.get(key) == new:
                return False, None
            self.axes[key] = new
            return True, None
        if role == 'touchpad':
            if code == ABS_MT_SLOT:
                self._slot = max(0, min(1, value))
                return False, None
            f = self.touch[self._slot]
            if code == ABS_MT_TRACKING_ID:
                self.touch_seen = True
                f['active'] = value >= 0
                return True, ('Touchpad: finger %s' % ('down' if value >= 0 else 'up'))
            if code == ABS_MT_X:
                f['x'] = norm_unit(value, lo, hi)
                return True, None
            if code == ABS_MT_Y:
                f['y'] = norm_unit(value, lo, hi)
                return True, None
            return False, None
        if role == 'motion' and code in ABS_MOTION:
            key = ABS_MOTION[code]
            res = getattr(ai, 'resolution', 0) or 0
            if self.motion is None:
                self.motion = dict.fromkeys(ABS_MOTION.values(), 0.0)
            if res > 0:
                v = value / float(res)
                if key[0] == 'g':
                    v *= 57.29578  # rad/s -> deg/s
                self.units['gyro' if key[0] == 'g' else 'accel'] = 'deg/s' if key[0] == 'g' else 'g'
            else:
                v = value / float(max(1, (hi - lo) / 2.0))
            self.motion[key] = round(v, 3)
            return True, None
        return False, None


# --------------------------------------------------------------------------
# monitor thread
# --------------------------------------------------------------------------
class ControllerMonitor:
    def __init__(self, log: EventLog, on_event: Optional[Callable[[str, dict], None]] = None):
        self._log = log
        self._on_event = on_event
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = InputState()
        self._rate = RateMeter()
        self._seq = 1
        self._info: Optional[dict] = None
        self._nodes: list = []
        self._unreadable: list = []
        self._battery: Optional[dict] = None
        self._error: Optional[str] = None
        self._last_input: Optional[float] = None
        self._connected_since: Optional[float] = None
        self._primary_dev = None
        self._primary_node: Optional[Node] = None
        self._evdev_ok = True
        self._last_active: Optional[float] = None
        self.battery_history = BatteryHistory()

    # -- lifecycle -----------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name='ds4-input', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def connected(self) -> bool:
        return self._info is not None

    def _bump(self):
        self._seq += 1

    # -- snapshots ------------------------------------------------------
    def frame(self, since: int = 0) -> dict:
        """Hot data polled at the UI refresh rate. Tiny when nothing changed."""
        with self._lock:
            base = {'seq': self._seq, 'rate': self._rate.value(), 'last_input': self._last_input}
            if since == self._seq:
                base['same'] = True
                return base
            st = self._state
            base.update(
                connected=self._info is not None,
                down=sorted(st.down), counts=dict(st.counts), axes=dict(st.axes), analog=dict(st.analog),
                touch=[dict(f) for f in st.touch], touch_seen=st.touch_seen,
                motion=dict(st.motion) if st.motion else None, units=dict(st.units))
            return base

    def status(self) -> dict:
        with self._lock:
            info = dict(self._info) if self._info else None
            return {
                'connected': info is not None, 'info': info, 'battery': self._battery,
                'nodes': [n.public() for n in self._nodes], 'unreadable': list(self._unreadable),
                'error': self._error, 'evdev': self._evdev_ok,
                'connected_since': self._connected_since, 'last_input': self._last_input,
            }

    def last_active(self) -> Optional[float]:
        """Time of the last meaningful input. A held button or stick counts as activity right now."""
        with self._lock:
            if self._info is not None and self._state.is_active():
                self._last_active = time.time()
            return self._last_active

    def primary_node(self) -> Optional[Node]:
        with self._lock:
            return self._primary_node if self._info is not None else None

    def connected_since(self) -> Optional[float]:
        with self._lock:
            return self._connected_since

    def reset_measurements(self):
        with self._lock:
            self._state.counts = dict.fromkeys(BUTTONS, 0)
            self._bump()

    # -- rumble ------------------------------------------------------------
    def rumble(self, strong: float, weak: float, ms: int) -> dict:
        with self._lock:
            dev = self._primary_dev
        if dev is None:
            return {'ok': False, 'message': 'No controller connected.'}
        try:
            from evdev import ecodes, ff
        except ImportError:
            return {'ok': False, 'message': 'python-evdev is not installed.'}
        try:
            if ecodes.EV_FF not in dev.capabilities():
                return {'ok': False, 'message': 'This driver does not expose force feedback (rumble).'}
            ms = max(50, min(2000, int(ms)))
            rumble = ff.Rumble(strong_magnitude=int(max(0, min(1, strong)) * 0xFFFF),
                               weak_magnitude=int(max(0, min(1, weak)) * 0xFFFF))
            effect = ff.Effect(ecodes.FF_RUMBLE, -1, 0, ff.Trigger(0, 0), ff.Replay(ms, 0),
                               ff.EffectType(ff_rumble_effect=rumble))
            eid = dev.upload_effect(effect)
            dev.write(ecodes.EV_FF, eid, 1)
            timer = threading.Timer(ms / 1000.0 + 0.3, self._erase_effect, (dev, eid))
            timer.daemon = True
            timer.start()
            return {'ok': True, 'message': 'Rumble sent for %d ms.' % ms}
        except OSError as e:
            return {'ok': False, 'message': 'Could not send rumble (%s). Rumble needs write access to the device, which your session does not have.' % e.strerror}

    @staticmethod
    def _erase_effect(dev, eid):
        try:
            dev.erase_effect(eid)
        except Exception:  # device may already be gone
            pass

    # -- worker ------------------------------------------------------------
    def _run(self):
        try:
            import evdev  # noqa: F401
        except ImportError:
            with self._lock:
                self._evdev_ok = False
                self._error = 'python-evdev is not installed. Run ./install.sh.'
            self._stop.wait()
            return
        while not self._stop.is_set():
            nodes = scan_nodes()
            pick = pick_controller(nodes)
            with self._lock:
                self._nodes = nodes
                self._unreadable = [n.public() for n in nodes if n.role == 'gamepad' and not n.readable]
            if pick is None or not pick[0].readable:
                if pick is not None:
                    with self._lock:
                        self._error = 'Permission denied for %s. See Troubleshooting.' % pick[0].path
                else:
                    with self._lock:
                        self._error = None
                self._stop.wait(1.0)
                continue
            try:
                self._session(pick[0], pick[1])
            except Exception as e:  # never let the monitor thread die
                with self._lock:
                    self._error = 'Input stopped: %s' % e
                self._log.add('system', 'Input stopped: %s' % e)
            self._stop.wait(0.5)

    def _session(self, primary: Node, companions: list):
        import evdev
        opened = {}  # fd -> (device, role, absinfo-by-code)
        try:
            for node in [primary] + [c for c in companions if c.readable]:
                try:
                    dev = evdev.InputDevice(node.path)
                except OSError as e:
                    if node is primary:
                        raise
                    self._log.add('system', 'Could not open %s: %s' % (node.role, e.strerror))
                    continue
                ai = {code: info for code, info in dev.capabilities().get(EV_ABS, [])}
                opened[dev.fd] = (dev, node.role, ai)
                if node is primary:
                    with self._lock:
                        self._primary_dev = dev
                        self._primary_node = primary
            info = {'name': primary.name, 'path': primary.path, 'bus': primary.bus_name,
                    'vendor': '%04x' % primary.vendor, 'product': '%04x' % primary.product,
                    'mac': primary.uniq or None, 'driver': kernel_driver(primary.devdir),
                    'virtual': primary.virtual, 'sony': primary.vendor == SONY_VID,
                    'roles': sorted({r for _, r, _ in opened.values()})}
            with self._lock:
                self._state.reset()
                self._info = info
                self._error = None
                self._connected_since = time.time()
                self._last_active = self._connected_since
                self._battery = read_battery(primary)
                self.battery_history.clear()
                self.battery_history.add(self._battery)
                self._bump()
            self._log.add('system', 'Connected: %s (%s)' % (primary.name, primary.bus_name))
            if self._on_event:
                self._on_event('connected', info)
            last_battery = time.monotonic()
            while not self._stop.is_set():
                ready, _, _ = select.select(list(opened), [], [], 0.5)
                for fd in ready:
                    dev, role, ai = opened[fd]
                    self._drain(dev, role, ai)
                if time.monotonic() - last_battery > 20:
                    last_battery = time.monotonic()
                    batt = read_battery(primary)
                    with self._lock:
                        self._battery = batt
                    self.battery_history.add(batt)
        except OSError as e:
            if e.errno not in (errno.ENODEV, errno.EIO, errno.ENOENT):
                with self._lock:
                    self._error = 'Controller input ended: %s' % e.strerror
        finally:
            for dev, _, _ in opened.values():
                try:
                    dev.close()
                except Exception:
                    pass
            with self._lock:
                was = self._info
                self._primary_dev = None
                self._primary_node = None
                self._info = None
                self._battery = None
                self._connected_since = None
                self._state.reset()
                self._bump()
            if was is not None:
                self._log.add('system', 'Disconnected: %s' % was['name'])
                if self._on_event:
                    self._on_event('disconnected', was)

    def _drain(self, dev, role: str, ai: dict):
        try:
            for ev in dev.read():
                if ev.type not in (EV_KEY, EV_ABS):
                    continue
                self._rate.tick()
                with self._lock:
                    changed, msg = self._state.apply(role, ev.type, ev.code, ev.value, ai.get(ev.code))
                    if changed:
                        self._bump()
                        if role != 'motion':  # a resting pad still streams gyro noise
                            self._last_input = time.time()
                            if msg or self._state.is_active():
                                self._last_active = self._last_input
                if msg:
                    self._log.add('button', msg)
        except BlockingIOError:
            pass
