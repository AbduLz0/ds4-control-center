"""Turn controller input into keyboard and mouse input, for any game.

The module has two halves on purpose:

* ``MappingEngine`` is pure Python. It takes semantic input ("cross pressed",
  "left stick x is 0.8") and decides which keys and mouse buttons to hold and
  how far the mouse should move. It has no evdev or ``/dev/uinput`` dependency,
  so every rule is testable without hardware.
* ``InputMapper`` owns the virtual keyboard and mouse and a small timing thread
  for mouse look. It only opens ``/dev/uinput`` when the user switches the
  feature on, and it reports a plain-language reason when that is not allowed.

The ready-made presets are ordinary dicts, so the UI and the tests use exactly
the same values the runtime uses.
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Callable, Optional

BUTTONS = ['cross', 'circle', 'square', 'triangle', 'dpad-up', 'dpad-down', 'dpad-left', 'dpad-right',
           'l1', 'r1', 'l2', 'r2', 'l3', 'r3', 'share', 'options', 'ps', 'touchpad']
BUTTON_LABELS = {
    'cross': 'Cross', 'circle': 'Circle', 'square': 'Square', 'triangle': 'Triangle',
    'dpad-up': 'D-pad up', 'dpad-down': 'D-pad down', 'dpad-left': 'D-pad left', 'dpad-right': 'D-pad right',
    'l1': 'L1', 'r1': 'R1', 'l2': 'L2', 'r2': 'R2',
    'l3': 'L3 (left stick click)', 'r3': 'R3 (right stick click)',
    'share': 'Share', 'options': 'Options', 'ps': 'PS button', 'touchpad': 'Touchpad click',
}
STICK_MODES = ('wasd', 'arrows', 'ad', 'mouse', 'none')
LEFT_STICK_MODES = ('wasd', 'arrows', 'ad', 'none')
STICK_MODE_LABELS = {
    'wasd': 'WASD keys', 'arrows': 'Arrow keys', 'ad': 'A / D only',
    'mouse': 'Mouse look', 'none': 'Not mapped',
}
DEFAULT_PRESET = 'shooter'
MOUSE_PX_PER_SEC = 1400.0

# A binding is one of: a Linux key name, a mouse button, or a wheel direction.
MOUSE_BUTTONS = ('BTN_LEFT', 'BTN_RIGHT', 'BTN_MIDDLE')
WHEEL_BINDINGS = ('WHEEL_UP', 'WHEEL_DOWN')


def _binding(value) -> str:
    """Return a safe binding string, or '' when the value is not one we support."""
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if value == '':
        return ''
    if value.startswith('KEY_'):
        body = value[4:]
        if 1 <= len(body) <= 28 and all(ch.isupper() or ch.isdigit() or ch == '_' for ch in body):
            return value
        return ''
    if value in MOUSE_BUTTONS or value in WHEEL_BINDINGS:
        return value
    return ''


PRESETS = {
    'shooter': {
        'label': 'Shooter (WASD + mouse)',
        'description': 'Left stick moves with WASD, right stick looks with the mouse. '
                       'R2 fires, L2 aims, R reloads, Space jumps, Ctrl crouches.',
        'left_stick': 'wasd',
        'right_stick': 'mouse',
        'bindings': {
            'cross': 'KEY_SPACE', 'circle': 'KEY_LEFTCTRL', 'square': 'KEY_R', 'triangle': 'KEY_E',
            'dpad-up': 'KEY_UP', 'dpad-down': 'KEY_DOWN', 'dpad-left': 'KEY_LEFT', 'dpad-right': 'KEY_RIGHT',
            'l1': 'KEY_Q', 'r1': 'KEY_F', 'l2': 'BTN_RIGHT', 'r2': 'BTN_LEFT',
            'l3': 'KEY_LEFTSHIFT', 'r3': 'KEY_V', 'share': 'KEY_TAB', 'options': 'KEY_ESC',
            'ps': 'KEY_ENTER', 'touchpad': 'KEY_M',
        },
    },
    'action': {
        'label': 'Action / platformer (WASD + arrows)',
        'description': 'Left stick moves with WASD, right stick uses the arrow keys, D-pad also uses arrows. '
                       'L2/R2 become right/left mouse buttons for games that use them.',
        'left_stick': 'wasd',
        'right_stick': 'arrows',
        'bindings': {
            'cross': 'KEY_SPACE', 'circle': 'KEY_LEFTCTRL', 'square': 'KEY_J', 'triangle': 'KEY_K',
            'dpad-up': 'KEY_UP', 'dpad-down': 'KEY_DOWN', 'dpad-left': 'KEY_LEFT', 'dpad-right': 'KEY_RIGHT',
            'l1': 'KEY_Q', 'r1': 'KEY_E', 'l2': 'BTN_RIGHT', 'r2': 'BTN_LEFT',
            'l3': 'KEY_LEFTSHIFT', 'r3': 'KEY_L', 'share': 'KEY_TAB', 'options': 'KEY_ESC',
            'ps': 'KEY_ENTER', 'touchpad': 'KEY_M',
        },
    },
    'classic': {
        'label': 'Classic / menus (arrows + mouse)',
        'description': 'Left stick and D-pad use the arrow keys, right stick moves the mouse. '
                       'Cross is Enter, Circle is Escape; L1/R1 scroll the mouse wheel. '
                       'Useful for older games, visual novels and point-and-click titles.',
        'left_stick': 'arrows',
        'right_stick': 'mouse',
        'bindings': {
            'cross': 'KEY_ENTER', 'circle': 'KEY_ESC', 'square': 'KEY_BACKSPACE', 'triangle': 'KEY_TAB',
            'dpad-up': 'KEY_UP', 'dpad-down': 'KEY_DOWN', 'dpad-left': 'KEY_LEFT', 'dpad-right': 'KEY_RIGHT',
            'l1': 'WHEEL_UP', 'r1': 'WHEEL_DOWN', 'l2': 'BTN_RIGHT', 'r2': 'BTN_LEFT',
            'l3': 'KEY_LEFTSHIFT', 'r3': 'KEY_LEFTCTRL', 'share': 'KEY_M', 'options': 'KEY_ESC',
            'ps': 'KEY_ENTER', 'touchpad': 'BTN_LEFT',
        },
    },
    'racing': {
        'label': 'Racing (keyboard)',
        'description': 'Left stick steers with A/D; R2 accelerates with W and L2 brakes with S. '
                       'Space is the handbrake, R resets the car and C changes the camera.',
        'left_stick': 'ad',
        'right_stick': 'none',
        'bindings': {
            'cross': 'KEY_SPACE', 'circle': 'KEY_R', 'square': 'KEY_C', 'triangle': 'KEY_H',
            'dpad-up': 'KEY_UP', 'dpad-down': 'KEY_DOWN', 'dpad-left': 'KEY_LEFT', 'dpad-right': 'KEY_RIGHT',
            'l1': 'KEY_LEFTSHIFT', 'r1': 'KEY_E', 'l2': 'KEY_S', 'r2': 'KEY_W',
            'l3': 'KEY_LEFTCTRL', 'r3': 'KEY_Q', 'share': 'KEY_TAB', 'options': 'KEY_ESC',
            'ps': 'KEY_ENTER', 'touchpad': 'KEY_M',
        },
    },
}
PRESET_ORDER = ('shooter', 'action', 'classic', 'racing')


def default_mapping() -> dict:
    preset = PRESETS[DEFAULT_PRESET]
    return {
        'enabled': False,
        'preset': DEFAULT_PRESET,
        'bindings': {b: preset['bindings'].get(b, '') for b in BUTTONS},
        'left_stick': preset['left_stick'],
        'right_stick': preset['right_stick'],
        'deadzone': 0.18,
        'sensitivity': 1.0,
        'exponent': 1.35,
        'invert_y': False,
        'grab': False,
        'trigger_threshold': 0.35,
    }


def _number(value, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    return round(max(low, min(high, number)), 3)


def _boolean(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def clean_mapping(raw) -> dict:
    """Validate a mapping dict, filling anything missing from its preset.

    Unknown keys, bindings that are not Linux key/mouse names, out-of-range
    numbers and non-boolean booleans are replaced with safe values instead of
    being passed to uinput.
    """
    raw = raw if isinstance(raw, dict) else {}
    preset = raw.get('preset')
    if preset not in PRESETS and preset != 'custom':
        preset = DEFAULT_PRESET
    base = PRESETS[preset]['bindings'] if preset in PRESETS else {}
    raw_bindings = raw.get('bindings') if isinstance(raw.get('bindings'), dict) else {}
    bindings = {}
    for button in BUTTONS:
        value = raw_bindings.get(button, base.get(button, ''))
        bindings[button] = _binding(value)
        if not bindings[button] and value not in ('', None):
            bindings[button] = _binding(base.get(button, ''))
    left = raw.get('left_stick')
    right = raw.get('right_stick')
    if left not in LEFT_STICK_MODES:
        left = PRESETS[preset]['left_stick'] if preset in PRESETS else 'wasd'
    if right not in STICK_MODES:
        right = PRESETS[preset]['right_stick'] if preset in PRESETS else 'mouse'
    return {
        'enabled': _boolean(raw.get('enabled'), False),
        'preset': preset,
        'bindings': bindings,
        'left_stick': left,
        'right_stick': right,
        'deadzone': _number(raw.get('deadzone'), 0.02, 0.6, 0.18),
        'sensitivity': _number(raw.get('sensitivity'), 0.1, 4.0, 1.0),
        'exponent': _number(raw.get('exponent'), 0.5, 3.0, 1.35),
        'invert_y': _boolean(raw.get('invert_y'), False),
        'grab': _boolean(raw.get('grab'), False),
        'trigger_threshold': _number(raw.get('trigger_threshold'), 0.05, 0.9, 0.35),
    }


def public_presets() -> list:
    return [{'id': key, 'label': PRESETS[key]['label'], 'description': PRESETS[key]['description'],
             'left_stick': PRESETS[key]['left_stick'], 'right_stick': PRESETS[key]['right_stick'],
             'bindings': dict(PRESETS[key]['bindings'])} for key in PRESET_ORDER]


def preset_mapping(preset: str) -> dict:
    """A complete mapping for a named preset (with the current defaults for options)."""
    if preset not in PRESETS:
        raise ValueError('Unknown preset.')
    mapping = default_mapping()
    mapping['preset'] = preset
    mapping['bindings'] = {b: PRESETS[preset]['bindings'].get(b, '') for b in BUTTONS}
    mapping['left_stick'] = PRESETS[preset]['left_stick']
    mapping['right_stick'] = PRESETS[preset]['right_stick']
    return mapping


def mouse_delta(x: float, y: float, deadzone: float, sensitivity: float, exponent: float,
                invert_y: bool, dt: float):
    """Relative mouse motion in pixels for one tick. Pure and easy to test."""
    magnitude = math.hypot(x, y)
    if magnitude <= deadzone or dt <= 0:
        return 0.0, 0.0
    direction_x, direction_y = x / magnitude, y / magnitude
    # The curve starts at zero exactly at the dead-zone edge, which gives fine aim.
    curve = ((magnitude - deadzone) / max(1e-6, 1.0 - deadzone)) ** exponent
    speed = MOUSE_PX_PER_SEC * sensitivity * curve
    # The controller's positive Y is up; a mouse's positive REL_Y is down.
    dy = -direction_y * speed * dt
    if invert_y:
        dy = -dy
    return direction_x * speed * dt, dy


# --------------------------------------------------------------------------
# pure engine
# --------------------------------------------------------------------------
class MappingEngine:
    """Turns controller state into key/mouse decisions. No hardware here."""

    def __init__(self, mapping: dict,
                 emit_key: Optional[Callable[[str, bool], None]] = None,
                 emit_mouse_button: Optional[Callable[[str, bool], None]] = None,
                 emit_wheel: Optional[Callable[[int], None]] = None,
                 emit_move: Optional[Callable[[int, int], None]] = None):
        self._emit_key = emit_key or (lambda name, down: None)
        self._emit_mouse_button = emit_mouse_button or (lambda name, down: None)
        self._emit_wheel = emit_wheel or (lambda delta: None)
        self._emit_move = emit_move or (lambda dx, dy: None)
        self._cfg = default_mapping()
        self.bindings = dict(self._cfg['bindings'])
        self._keys = {}
        self._mouse = {}
        self._down = set()
        self._stick_keys = {'left': set(), 'right': set()}
        self._axes = {'lx': 0.0, 'ly': 0.0, 'rx': 0.0, 'ry': 0.0}
        self._analog = {'l2': 0.0, 'r2': 0.0}
        self._analog_seen = {'l2': False, 'r2': False}
        self._digital = {'l2': False, 'r2': False}
        self._acc_x = 0.0
        self._acc_y = 0.0
        self.mouse_moving = False
        self.last_output = ''
        self.set_mapping(mapping)

    # -- configuration ----------------------------------------------------
    def set_mapping(self, mapping: dict):
        was_active = bool(self._keys or self._mouse or self._stick_keys['left'] or self._stick_keys['right'])
        if was_active:
            self.reset()
        self._cfg = clean_mapping(mapping)
        self.bindings = dict(self._cfg['bindings'])
        self._sync_stick('left')
        self._sync_stick('right')
        for trigger in ('l2', 'r2'):
            self._apply_trigger(trigger, force=True)

    @property
    def config(self) -> dict:
        return dict(self._cfg)

    # -- outputs ----------------------------------------------------------
    def _key(self, name: str, down: bool):
        count = self._keys.get(name, 0)
        if down:
            self._keys[name] = count + 1
            if count == 0:
                self._emit_key(name, True)
                self.last_output = name + ' down'
        elif count > 0:
            if count == 1:
                self._keys.pop(name, None)
                self._emit_key(name, False)
                self.last_output = name + ' up'
            else:
                self._keys[name] = count - 1

    def _mouse_button(self, name: str, down: bool):
        count = self._mouse.get(name, 0)
        if down:
            self._mouse[name] = count + 1
            if count == 0:
                self._emit_mouse_button(name, True)
                self.last_output = name + ' down'
        elif count > 0:
            if count == 1:
                self._mouse.pop(name, None)
                self._emit_mouse_button(name, False)
                self.last_output = name + ' up'
            else:
                self._mouse[name] = count - 1

    def _binding_output(self, binding: str, down: bool):
        if not binding:
            return
        if binding.startswith('KEY_'):
            self._key(binding, down)
        elif binding.startswith('BTN_'):
            self._mouse_button(binding, down)
        elif binding == 'WHEEL_UP' and down:
            self._emit_wheel(1)
            self.last_output = 'Wheel up'
        elif binding == 'WHEEL_DOWN' and down:
            self._emit_wheel(-1)
            self.last_output = 'Wheel down'

    def _logical_button(self, name: str, pressed: bool):
        pressed = bool(pressed)
        if pressed == (name in self._down):
            return
        if pressed:
            self._down.add(name)
        else:
            self._down.discard(name)
        self._binding_output(self.bindings.get(name, ''), pressed)

    # -- input ------------------------------------------------------------
    def set_button(self, name: str, pressed: bool):
        if name not in BUTTONS:
            return
        if name in ('l2', 'r2'):
            self._digital[name] = bool(pressed)
            self._apply_trigger(name)
            return
        self._logical_button(name, pressed)

    def set_axis(self, name: str, value):
        try:
            number = max(-1.0, min(1.0, float(value)))
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(number):
            return
        if name in self._axes:
            self._axes[name] = number
            if name[0] == 'l' or name[0] == 'r':
                self._sync_stick('left' if name[0] == 'l' else 'right')
        elif name in ('l2', 'r2'):
            self._analog[name] = max(0.0, min(1.0, number))
            self._analog_seen[name] = True
            self._apply_trigger(name)

    def _apply_trigger(self, name: str, force: bool = False):
        if self._analog_seen[name]:
            pressed = self._analog[name] >= self._cfg['trigger_threshold']
        else:
            pressed = self._digital[name]
        if force or pressed != (name in self._down):
            self._logical_button(name, pressed)

    def _sync_stick(self, which: str):
        mode = self._cfg['left_stick'] if which == 'left' else self._cfg['right_stick']
        old = self._stick_keys[which]
        desired = set()
        if mode in ('wasd', 'arrows', 'ad'):
            x = self._axes['lx' if which == 'left' else 'rx']
            y = self._axes['ly' if which == 'left' else 'ry']
            deadzone = self._cfg['deadzone']
            if mode == 'wasd':
                names = ('KEY_A', 'KEY_D', 'KEY_W', 'KEY_S')
            elif mode == 'ad':
                names = ('KEY_A', 'KEY_D', None, None)
            else:
                names = ('KEY_LEFT', 'KEY_RIGHT', 'KEY_UP', 'KEY_DOWN')
            for value, negative, positive in ((x, names[0], names[1]), (y, names[3], names[2])):
                if positive and value >= (deadzone * 0.72 if positive in old else deadzone):
                    desired.add(positive)
                if negative and value <= -(deadzone * 0.72 if negative in old else deadzone):
                    desired.add(negative)
        for name in old - desired:
            self._key(name, False)
        for name in desired - old:
            self._key(name, True)
        self._stick_keys[which] = desired

    def tick(self, dt: float):
        """Advance mouse look. Called on a timer; pure key output happens on input."""
        if self._cfg['right_stick'] != 'mouse':
            self.mouse_moving = False
            return
        x, y = self._axes['rx'], self._axes['ry']
        self.mouse_moving = math.hypot(x, y) > self._cfg['deadzone']
        if not self.mouse_moving:
            self._acc_x = self._acc_y = 0.0
            return
        dx, dy = mouse_delta(x, y, self._cfg['deadzone'], self._cfg['sensitivity'],
                             self._cfg['exponent'], self._cfg['invert_y'], dt)
        self._acc_x += dx
        self._acc_y += dy
        move_x = int(self._acc_x)
        move_y = int(self._acc_y)
        if move_x or move_y:
            self._acc_x -= move_x
            self._acc_y -= move_y
            self._emit_move(move_x, move_y)

    # -- lifecycle --------------------------------------------------------
    def reset(self):
        """Release every output. Used when the feature stops or the pad disconnects."""
        for name in list(self._keys):
            self._keys[name] = 1
            self._key(name, False)
        for name in list(self._mouse):
            self._mouse[name] = 1
            self._mouse_button(name, False)
        self._keys.clear()
        self._mouse.clear()
        self._down.clear()
        self._stick_keys = {'left': set(), 'right': set()}
        self._axes = {k: 0.0 for k in self._axes}
        self._analog = {'l2': 0.0, 'r2': 0.0}
        self._analog_seen = {'l2': False, 'r2': False}
        self._digital = {'l2': False, 'r2': False}
        self._acc_x = self._acc_y = 0.0
        self.mouse_moving = False
        self.last_output = ''

    def held(self) -> list:
        return sorted(list(self._keys) + list(self._mouse))


# --------------------------------------------------------------------------
# virtual devices
# --------------------------------------------------------------------------
class MappingUnavailable(RuntimeError):
    """Raised when this user cannot create uinput devices."""


def uinput_reason() -> str:
    """Why keyboard/mouse output is unavailable, or '' when it should work."""
    if not os.path.exists('/dev/uinput'):
        return ('The kernel uinput device (/dev/uinput) is missing. Load the module with '
                '"sudo modprobe uinput" and add it to /etc/modules-load.d if it should persist.')
    if not os.access('/dev/uinput', os.W_OK):
        return ('Your user cannot write to /dev/uinput, so the app cannot create a virtual keyboard or mouse. '
                'Run ./scripts/enable-uinput.sh once (it adds a udev rule with your consent), then log out '
                'and back in. This app never changes system permissions by itself.')
    return ''


def uinput_available() -> bool:
    return uinput_reason() == ''


class UinputOutput:
    """Virtual keyboard and mouse. Opens two uinput devices and closes both."""

    def __init__(self):
        self._keyboard = None
        self._mouse = None
        self._evdev = None

    def open(self):
        reason = uinput_reason()
        if reason:
            raise MappingUnavailable(reason)
        try:
            import evdev
            from evdev import UInput, ecodes
        except ImportError as exc:
            raise MappingUnavailable('python-evdev is not installed. Run ./install.sh.') from exc
        self._evdev = evdev
        try:
            # Declare the whole key namespace so a rebind never needs a device restart.
            key_codes = sorted({code for code in ecodes.KEY if 0 < code <= 0x2ef})
            self._keyboard = UInput({ecodes.EV_KEY: key_codes},
                                    name='DS4 Control Center virtual keyboard',
                                    phys='ds4cc-keyboard', vendor=0x1209, product=0x0001,
                                    version=0x0001, bustype=ecodes.BUS_USB)
            self._mouse = UInput({
                ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE,
                                ecodes.BTN_SIDE, ecodes.BTN_EXTRA],
                ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
            }, name='DS4 Control Center virtual mouse', phys='ds4cc-mouse',
                vendor=0x1209, product=0x0002, version=0x0001, bustype=ecodes.BUS_USB)
        except Exception as exc:  # UInputError is not an OSError
            self.close()
            raise MappingUnavailable('Could not create the virtual keyboard or mouse: %s. '
                                     'See Troubleshooting for the uinput check.' % exc) from exc

    @property
    def opened(self) -> bool:
        return self._keyboard is not None and self._mouse is not None

    def _code(self, name: str):
        try:
            return self._evdev.ecodes.ecodes.get(name)
        except AttributeError:
            return None

    def key(self, name: str, down: bool):
        code = self._code(name)
        if code is None:
            return
        self._keyboard.write(self._evdev.ecodes.EV_KEY, code, 1 if down else 0)
        self._keyboard.syn()

    def mouse_button(self, name: str, down: bool):
        code = self._code(name)
        if code is None:
            return
        self._mouse.write(self._evdev.ecodes.EV_KEY, code, 1 if down else 0)
        self._mouse.syn()

    def wheel(self, delta: int):
        self._mouse.write(self._evdev.ecodes.EV_REL, self._evdev.ecodes.REL_WHEEL, int(delta))
        self._mouse.syn()

    def move(self, dx: int, dy: int):
        if dx:
            self._mouse.write(self._evdev.ecodes.EV_REL, self._evdev.ecodes.REL_X, int(dx))
        if dy:
            self._mouse.write(self._evdev.ecodes.EV_REL, self._evdev.ecodes.REL_Y, int(dy))
        if dx or dy:
            self._mouse.syn()

    def close(self):
        for device in (self._keyboard, self._mouse):
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass
        self._keyboard = self._mouse = None


class InputMapper:
    """Owns the virtual keyboard/mouse and feeds it from the controller thread."""

    def __init__(self, log=None):
        self._log = log
        self._lock = threading.RLock()
        self._cfg = default_mapping()
        self._engine: Optional[MappingEngine] = None
        self._output: Optional[UinputOutput] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._enabled = False
        self._message = ''
        self._error = ''
        self._started_at: Optional[float] = None

    # -- configuration ----------------------------------------------------
    def configure(self, mapping: dict) -> dict:
        cleaned = clean_mapping(mapping)
        with self._lock:
            self._cfg = cleaned
            if self._engine is not None:
                self._engine.set_mapping(cleaned)
        return cleaned

    @property
    def config(self) -> dict:
        with self._lock:
            return dict(self._cfg)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    # -- lifecycle --------------------------------------------------------
    def enable(self, mapping: Optional[dict] = None) -> dict:
        with self._lock:
            if mapping is not None:
                self._cfg = clean_mapping(mapping)
            if self._enabled and self._engine is not None:
                self._engine.set_mapping(self._cfg)
                return {'ok': True, 'message': 'Keyboard and mouse mode is already on.', 'status': self.status()}
            reason = uinput_reason()
            if reason:
                self._message = reason
                return {'ok': False, 'message': reason, 'status': self.status()}
            output = UinputOutput()
            try:
                output.open()
            except MappingUnavailable as exc:
                self._message = str(exc)
                return {'ok': False, 'message': str(exc), 'status': self.status()}
            except Exception as exc:
                self._message = 'Could not create the virtual keyboard or mouse: %s' % exc
                return {'ok': False, 'message': self._message, 'status': self.status()}
            engine = MappingEngine(self._cfg, output.key, output.mouse_button, output.wheel, output.move)
            self._output = output
            self._engine = engine
            self._enabled = True
            self._message = 'Keyboard and mouse mode is on.'
            self._error = ''
            self._started_at = time.time()
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, name='ds4-keymap', daemon=True)
            self._thread.start()
            if self._log:
                self._log.add('system', 'Keyboard/mouse mode enabled (preset: %s).' % self._cfg['preset'])
            return {'ok': True, 'message': 'Keyboard and mouse mode is on.', 'status': self.status()}

    def disable(self) -> dict:
        with self._lock:
            was_enabled = self._enabled
            engine, output, thread = self._engine, self._output, self._thread
            self._enabled = False
            self._engine = None
            self._output = None
            self._thread = None
            self._stop.set()
        if engine is not None:
            try:
                engine.reset()
            except Exception:
                pass
        if output is not None:
            output.close()
        if thread is not None:
            thread.join(timeout=1.0)
        if was_enabled:
            self._message = 'Keyboard and mouse mode is off.'
            if self._log:
                self._log.add('system', 'Keyboard/mouse mode disabled; all virtual keys released.')
        return {'ok': True, 'message': 'Keyboard and mouse mode is off.', 'status': self.status()}

    def shutdown(self):
        self.disable()

    def _run(self):
        last = time.monotonic()
        while not self._stop.wait(0.01):
            now = time.monotonic()
            dt = max(0.002, min(0.05, now - last))
            last = now
            with self._lock:
                engine = self._engine
                if engine is None:
                    continue
                try:
                    engine.tick(dt)
                except Exception as exc:  # a broken virtual device must not kill the thread silently
                    self._error = str(exc)
                    self._message = 'Keyboard/mouse output stopped: %s' % exc
                    if self._log:
                        self._log.add('system', 'Keyboard/mouse output stopped: %s' % exc)
                    self._enabled = False
                    self._engine = None
                    output = self._output
                    self._output = None
                    self._stop.set()
                    if output is not None:
                        try:
                            output.close()
                        except Exception:
                            pass
                    return

    # -- input from the controller monitor --------------------------------
    def feed_button(self, name: str, pressed: bool):
        with self._lock:
            if self._engine is not None:
                try:
                    self._engine.set_button(name, pressed)
                except Exception as exc:
                    self._error = str(exc)

    def feed_axis(self, name: str, value):
        with self._lock:
            if self._engine is not None:
                try:
                    self._engine.set_axis(name, value)
                except Exception as exc:
                    self._error = str(exc)

    def reset(self):
        with self._lock:
            if self._engine is not None:
                self._engine.reset()

    # -- status -----------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            engine = self._engine
            return {
                'enabled': self._enabled,
                'available': uinput_reason() == '',
                'reason': uinput_reason(),
                'state': 'on' if (self._enabled and engine is not None) else ('blocked' if uinput_reason() else 'off'),
                'message': self._message,
                'error': self._error,
                'preset': self._cfg['preset'],
                'held': engine.held() if engine else [],
                'last_output': engine.last_output if engine else '',
                'mouse_moving': engine.mouse_moving if engine else False,
                'config': dict(self._cfg),
                'since': self._started_at,
            }
