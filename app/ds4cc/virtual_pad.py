"""A virtual Xbox 360 pad, so games that only look for XInput-style controllers
still see the DualShock 4.

Modern Linux games use SDL and normally see a DS4 directly. Older titles, some
Wine/Proton builds and a number of games that only ship XInput support do not.
This module presents a standard ``Microsoft X-Box 360 pad`` through uinput and
mirrors the physical controller into it. When the feature is on, the app also
grabs the physical pad (see ``ControllerMonitor.set_grab``) so a game does not
receive the same press twice.

``XboxState`` is pure: it produces a list of uinput-shaped events, so the whole
mapping is testable without hardware. ``VirtualPad`` owns the actual device.
"""
from __future__ import annotations

import math
import threading
from typing import Dict, List, Tuple

from .input_map import MappingUnavailable, uinput_reason

XBOX_NAME = 'Microsoft X-Box 360 pad'
XBOX_VENDOR = 0x045E
XBOX_PRODUCT = 0x028E
XBOX_VERSION = 0x0114
TRIGGER_THRESHOLD = 0.5
DEADZONE = 0.10

BUTTON_OUTPUTS = {
    'cross': 'BTN_A', 'circle': 'BTN_B', 'square': 'BTN_X', 'triangle': 'BTN_Y',
    'l1': 'BTN_TL', 'r1': 'BTN_TR', 'l3': 'BTN_THUMBL', 'r3': 'BTN_THUMBR',
    'share': 'BTN_SELECT', 'options': 'BTN_START', 'ps': 'BTN_MODE', 'touchpad': 'BTN_MODE',
}
TRIGGER_BUTTONS = {'l2': 'BTN_TL2', 'r2': 'BTN_TR2'}
STICK_AXES = {'lx': 'ABS_X', 'ly': 'ABS_Y', 'rx': 'ABS_RX', 'ry': 'ABS_RY'}
TRIGGER_AXES = {'l2': 'ABS_Z', 'r2': 'ABS_RZ'}
DPAD_DIRECTIONS = {'dpad-up': (0, -1), 'dpad-down': (0, 1), 'dpad-left': (-1, 0), 'dpad-right': (1, 0)}
OUTPUT_BUTTONS = sorted(set(BUTTON_OUTPUTS.values()) | set(TRIGGER_BUTTONS.values()))
ALL_STICKS = ('ABS_X', 'ABS_Y', 'ABS_RX', 'ABS_RY')


def scale_stick(x: float, y: float, deadzone: float = DEADZONE) -> Tuple[float, float]:
    """Radial dead zone with full range beyond it. Returns -1..1 on both axes."""
    magnitude = math.hypot(x, y)
    if magnitude <= deadzone or magnitude <= 1e-9:
        return 0.0, 0.0
    scale = min(1.0, (magnitude - deadzone) / max(1e-6, 1.0 - deadzone))
    return (x / magnitude) * scale, (y / magnitude) * scale


def _axis_value(value: float) -> int:
    return max(-32768, min(32767, int(round(value * 32767.0))))


def _trigger_value(value: float) -> int:
    return max(0, min(255, int(round(max(0.0, min(1.0, value)) * 255.0))))


class XboxState:
    """Pure DS4 -> Xbox 360 state machine.

    ``feed_button`` and ``feed_axis`` return a list of ``(kind, name, value)``
    tuples, where kind is ``'key'`` or ``'abs'``. The runtime turns those into
    evdev writes; tests inspect them directly.
    """

    def __init__(self, deadzone: float = DEADZONE):
        self.deadzone = deadzone
        self._down = set()
        self._counts: Dict[str, int] = {}
        self._dpad = set()
        self._sticks = {'lx': 0.0, 'ly': 0.0, 'rx': 0.0, 'ry': 0.0}
        self._triggers = {'l2': 0.0, 'r2': 0.0}
        self._trigger_down = {'l2': False, 'r2': False}
        self._analog_seen = {'l2': False, 'r2': False}
        self._hat = (0, 0)

    # -- outputs ----------------------------------------------------------
    def _key(self, output: str, down: bool) -> List[Tuple[str, str, int]]:
        count = self._counts.get(output, 0)
        if down:
            self._counts[output] = count + 1
            return [('key', output, 1)] if count == 0 else []
        if count <= 0:
            return []
        if count == 1:
            self._counts.pop(output, None)
            return [('key', output, 0)]
        self._counts[output] = count - 1
        return []

    def _hat_events(self) -> List[Tuple[str, str, int]]:
        x = y = 0
        if 'dpad-left' in self._dpad:
            x -= 1
        if 'dpad-right' in self._dpad:
            x += 1
        if 'dpad-up' in self._dpad:
            y -= 1
        if 'dpad-down' in self._dpad:
            y += 1
        events = []
        if (x, y) != self._hat:
            self._hat = (x, y)
            events.append(('abs', 'ABS_HAT0X', x))
            events.append(('abs', 'ABS_HAT0Y', y))
        return events

    def _stick_events(self, which: str) -> List[Tuple[str, str, int]]:
        if which == 'left':
            x, y = scale_stick(self._sticks['lx'], self._sticks['ly'], self.deadzone)
            return [('abs', 'ABS_X', _axis_value(x)), ('abs', 'ABS_Y', _axis_value(-y))]
        x, y = scale_stick(self._sticks['rx'], self._sticks['ry'], self.deadzone)
        return [('abs', 'ABS_RX', _axis_value(x)), ('abs', 'ABS_RY', _axis_value(-y))]

    def _trigger_events(self, which: str) -> List[Tuple[str, str, int]]:
        # If the driver only reports triggers as buttons, give the virtual pad a
        # full analog axis too; many Xbox-era games read only ABS_Z/ABS_RZ.
        if self._analog_seen[which]:
            value = self._triggers[which]
        else:
            value = 1.0 if self._trigger_down[which] else 0.0
        pressed = self._trigger_down[which] or value >= TRIGGER_THRESHOLD
        events = [('abs', TRIGGER_AXES[which], _trigger_value(value))]
        # Pressure updates are state changes, not additional owners of the key.
        output = TRIGGER_BUTTONS[which]
        if pressed != bool(self._counts.get(output, 0)):
            events += self._key(output, pressed)
        return events

    # -- input ------------------------------------------------------------
    def feed_button(self, name: str, pressed: bool) -> List[Tuple[str, str, int]]:
        pressed = bool(pressed)
        if pressed == (name in self._down):
            return []
        if pressed:
            self._down.add(name)
        else:
            self._down.discard(name)
        if name in DPAD_DIRECTIONS:
            if pressed:
                self._dpad.add(name)
            else:
                self._dpad.discard(name)
            return self._hat_events()
        if name in TRIGGER_BUTTONS:
            self._trigger_down[name] = pressed
            return self._trigger_events(name)
        output = BUTTON_OUTPUTS.get(name)
        return self._key(output, pressed) if output else []

    def feed_axis(self, name: str, value) -> List[Tuple[str, str, int]]:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return []
        if not math.isfinite(number):
            return []
        if name in ('lx', 'ly'):
            self._sticks[name] = max(-1.0, min(1.0, number))
            return self._stick_events('left')
        if name in ('rx', 'ry'):
            self._sticks[name] = max(-1.0, min(1.0, number))
            return self._stick_events('right')
        if name in ('l2', 'r2'):
            self._analog_seen[name] = True
            self._triggers[name] = max(0.0, min(1.0, number))
            return self._trigger_events(name)
        return []

    def reset(self) -> List[Tuple[str, str, int]]:
        events = []
        for output in list(self._counts):
            if self._counts.get(output, 0) > 0:
                events.append(('key', output, 0))
        self._counts.clear()
        self._down.clear()
        self._dpad.clear()
        self._trigger_down = {'l2': False, 'r2': False}
        self._analog_seen = {'l2': False, 'r2': False}
        self._sticks = {'lx': 0.0, 'ly': 0.0, 'rx': 0.0, 'ry': 0.0}
        self._triggers = {'l2': 0.0, 'r2': 0.0}
        self._hat = (0, 0)
        events += [('abs', name, 0) for name in ALL_STICKS]
        events += [('abs', 'ABS_Z', 0), ('abs', 'ABS_RZ', 0)]
        events += [('abs', 'ABS_HAT0X', 0), ('abs', 'ABS_HAT0Y', 0)]
        return events

    def snapshot(self) -> dict:
        return {
            'buttons': sorted(self._down),
            'hat': {'x': self._hat[0], 'y': self._hat[1]},
            'sticks': dict(self._sticks),
            'triggers': dict(self._triggers),
        }


class VirtualPad:
    """Owns the uinput Xbox 360 device and mirrors controller events into it."""

    def __init__(self, log=None):
        self._log = log
        self._lock = threading.RLock()
        self._ui = None
        self._evdev = None
        self._state = XboxState()
        self._enabled = False
        self._message = ''
        self._error = ''

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled and self._ui is not None

    def enable(self) -> dict:
        with self._lock:
            if self._ui is not None:
                self._enabled = True
                return {'ok': True, 'message': 'The virtual Xbox pad is already on.', 'status': self.status()}
            reason = uinput_reason()
            if reason:
                self._message = reason
                return {'ok': False, 'message': reason, 'status': self.status()}
            try:
                import evdev
                from evdev import AbsInfo, UInput, ecodes
            except ImportError as exc:
                self._message = 'python-evdev is not installed. Run ./install.sh.'
                return {'ok': False, 'message': self._message, 'status': self.status()}
            self._evdev = evdev
            axis = AbsInfo(0, -32768, 32767, 0, 0, 0)
            trigger = AbsInfo(0, 0, 255, 0, 0, 0)
            hat = AbsInfo(0, -1, 1, 0, 0, 0)
            events = {
                ecodes.EV_KEY: [ecodes.ecodes[name] for name in OUTPUT_BUTTONS],
                ecodes.EV_ABS: [(ecodes.ABS_X, axis), (ecodes.ABS_Y, axis),
                                (ecodes.ABS_RX, axis), (ecodes.ABS_RY, axis),
                                (ecodes.ABS_Z, trigger), (ecodes.ABS_RZ, trigger),
                                (ecodes.ABS_HAT0X, hat), (ecodes.ABS_HAT0Y, hat)],
            }
            try:
                self._ui = UInput(events, name=XBOX_NAME, phys='ds4cc-vpad',
                                  vendor=XBOX_VENDOR, product=XBOX_PRODUCT,
                                  version=XBOX_VERSION, bustype=ecodes.BUS_USB)
            except Exception as exc:  # UInputError is not an OSError
                self._message = ('Could not create the virtual Xbox pad: %s. '
                                 'See the uinput check on the Troubleshooting page.' % exc)
                self._ui = None
                return {'ok': False, 'message': self._message, 'status': self.status()}
            self._state.reset()
            self._enabled = True
            self._message = 'The virtual Xbox pad is on. Games will see it as a standard controller.'
            self._error = ''
            if self._log:
                self._log.add('system', 'Virtual Xbox 360 pad created (games that only accept XInput can use it).')
            return {'ok': True, 'message': self._message, 'status': self.status()}

    def disable(self) -> dict:
        with self._lock:
            ui = self._ui
            was = self._enabled
            self._ui = None
            self._enabled = False
            self._state.reset()
            if ui is not None:
                try:
                    ui.close()
                except Exception:
                    pass
        if was:
            self._message = 'The virtual Xbox pad is off.'
            if self._log:
                self._log.add('system', 'Virtual Xbox pad removed.')
        return {'ok': True, 'message': 'The virtual Xbox pad is off.', 'status': self.status()}

    def _write(self, events) -> None:
        if not events or self._ui is None:
            return
        codes = self._evdev.ecodes
        try:
            for kind, name, value in events:
                code = codes.ecodes.get(name)
                if code is None:
                    continue
                self._ui.write(codes.EV_KEY if kind == 'key' else codes.EV_ABS, code, int(value))
            self._ui.syn()
        except Exception as exc:
            self._error = str(exc)
            self._message = 'The virtual pad stopped working: %s' % exc
            if self._log:
                self._log.add('system', self._message)

    def feed_button(self, name: str, pressed: bool):
        with self._lock:
            if self._ui is not None:
                self._write(self._state.feed_button(name, pressed))

    def feed_axis(self, name: str, value):
        with self._lock:
            if self._ui is not None:
                self._write(self._state.feed_axis(name, value))

    def reset(self):
        with self._lock:
            if self._ui is not None:
                self._write(self._state.reset())

    def shutdown(self):
        self.disable()

    def status(self) -> dict:
        with self._lock:
            return {
                'enabled': self._enabled and self._ui is not None,
                'available': uinput_reason() == '',
                'reason': uinput_reason(),
                'state': 'on' if (self._enabled and self._ui is not None) else ('blocked' if uinput_reason() else 'off'),
                'message': self._message,
                'error': self._error,
                'name': XBOX_NAME,
                'snapshot': self._state.snapshot() if self._ui is not None else None,
            }
