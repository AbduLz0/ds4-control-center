"""Light bar colour through the kernel LED class (sysfs). No root, no hidraw, no udev changes.

hid-playstation exposes a multicolour LED (`inputN:rgb:indicator`); hid-sony exposes separate
`:red`, `:green` and `:blue` LEDs. Most systems make these files writable by root only, in which
case this module reports the situation instead of pretending it worked.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
PRESETS = [('Blue', '#0a3cff'), ('Red', '#ff1e1e'), ('Green', '#14e650'), ('Purple', '#a028ff'),
           ('Orange', '#ff7a00'), ('Pink', '#ff4fa3'), ('White', '#ffffff')]


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return ''


def _leds_dir(devdir: str) -> Optional[Path]:
    """The LED class devices sit under the HID device, a few levels above the input node."""
    try:
        p = Path(devdir).resolve()
    except OSError:
        return None
    for _ in range(5):
        p = p.parent
        if (p / 'leds').is_dir():
            return p / 'leds'
    return None


def find(devdir: str) -> Optional[dict]:
    leds = _leds_dir(devdir)
    if not leds:
        return None
    try:
        children = sorted(c for c in leds.iterdir() if c.is_dir() or c.is_symlink())
    except OSError:
        return None
    for c in children:
        if c.name.endswith(':rgb:indicator') and (c / 'multi_intensity').exists():
            order = _read(c / 'multi_index').split() or ['red', 'green', 'blue']
            max_b = int(_read(c / 'max_brightness') or 255) if _read(c / 'max_brightness').isdigit() else 255
            return {'kind': 'multicolor', 'path': c, 'order': order, 'max': max(1, max_b),
                    'writable': os.access(c / 'multi_intensity', os.W_OK) and os.access(c / 'brightness', os.W_OK)}
    split = {}
    for c in children:
        for color in ('red', 'green', 'blue'):
            if c.name.endswith(':' + color) and (c / 'brightness').exists():
                split[color] = c
    if len(split) == 3:
        max_b = [int(_read(p / 'max_brightness')) if _read(p / 'max_brightness').isdigit() else 255 for p in split.values()]
        return {'kind': 'split', 'paths': split, 'max': max(1, min(max_b)),
                'writable': all(os.access(p / 'brightness', os.W_OK) for p in split.values())}
    return None


def hex_to_rgb(value: str) -> tuple:
    if not isinstance(value, str) or not HEX_RE.match(value):
        raise ValueError('Colour must look like #rrggbb.')
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return '#%02x%02x%02x' % (r, g, b)


def current(led: dict) -> Optional[str]:
    """Best-effort read of the current colour; None when it cannot be known."""
    try:
        if led['kind'] == 'multicolor':
            vals = [int(x) for x in _read(led['path'] / 'multi_intensity').split()]
            bright = int(_read(led['path'] / 'brightness') or led['max'])
            if len(vals) != 3:
                return None
            by = dict(zip(led['order'], vals))
            scale = 255.0 / led['max']
            return rgb_to_hex(*[min(255, int(by.get(c, 0) * scale * bright / led['max'])) for c in ('red', 'green', 'blue')])
        vals = [int(_read(led['paths'][c] / 'brightness')) for c in ('red', 'green', 'blue')]
        scale = 255.0 / led['max']
        return rgb_to_hex(*[min(255, int(v * scale)) for v in vals])
    except (ValueError, KeyError):
        return None


def apply(led: dict, color: str) -> dict:
    """Write the colour. Returns {'ok', 'message'}; permission and I/O errors are explained."""
    try:
        r, g, b = hex_to_rgb(color)
    except ValueError as e:
        return {'ok': False, 'message': str(e)}
    if not led.get('writable'):
        return {'ok': False, 'message': 'Your user cannot change the light bar. The kernel exposes it, but only root may write to it.'}
    m = led['max']
    scaled = {'red': round(r * m / 255), 'green': round(g * m / 255), 'blue': round(b * m / 255)}
    try:
        if led['kind'] == 'multicolor':
            (led['path'] / 'multi_intensity').write_text(' '.join(str(scaled.get(c, 0)) for c in led['order']))
            (led['path'] / 'brightness').write_text(str(m))
        else:
            for c, p in led['paths'].items():
                (p / 'brightness').write_text(str(scaled[c]))
    except OSError as e:
        return {'ok': False, 'message': 'Could not write the light bar (%s).' % (e.strerror or e)}
    return {'ok': True, 'message': 'Light bar set to %s.' % color}
