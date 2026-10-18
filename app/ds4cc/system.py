"""Read-only environment checks that power the Troubleshooting page."""
from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Optional


def _check(cid: str, title: str, state: str, detail: str, hint: str = '') -> dict:
    return {'id': cid, 'title': title, 'state': state, 'detail': detail, 'hint': hint}


def os_summary() -> str:
    try:
        with open('/etc/os-release', encoding='utf-8') as fh:
            for line in fh:
                if line.startswith('PRETTY_NAME='):
                    return line.split('=', 1)[1].strip().strip('"') + ' / kernel ' + platform.release()
    except OSError:
        pass
    return platform.platform()


def run_checks(monitor_status: dict, bt_status: dict, steam_status: dict) -> list:
    checks = []
    checks.append(_check('python', 'Python runtime', 'ok', 'Python ' + platform.python_version()))
    if monitor_status.get('evdev', True):
        checks.append(_check('evdev', 'Input library (python-evdev)', 'ok', 'Installed'))
    else:
        checks.append(_check('evdev', 'Input library (python-evdev)', 'fail', 'Not installed',
                             'Run ./install.sh to install it.'))
    nodes = monitor_status.get('nodes', [])
    pads = [n for n in nodes if n['role'] == 'gamepad']
    real = [n for n in pads if not n.get('virtual')]
    info = monitor_status.get('info')
    if not pads:
        checks.append(_check('device', 'Game controller', 'warn', 'No gamepad input device is visible to the system.',
                             'Plug in the USB cable or pair over Bluetooth, then press the PS button.'))
    elif info:
        checks.append(_check('device', 'Game controller', 'ok', '%s via %s' % (info['name'], info['bus'])))
    else:
        checks.append(_check('device', 'Game controller', 'warn', pads[0]['name'] + ' was found but is not being read.'))
    denied = [n for n in pads if not n['readable']]
    if denied:
        checks.append(_check('access', 'Permission to read the device', 'fail',
                             '%s cannot be read by your user.' % denied[0]['event'],
                             'Run this app from your normal desktop session (not over SSH, not with sudo). '
                             'Check access with: ls -l /dev/input/' + denied[0]['event']))
    elif pads:
        checks.append(_check('access', 'Permission to read the device', 'ok', 'Your user can read this device.'))
        if not pads[0].get('writable', True):
            checks.append(_check('rumble', 'Rumble (write access)', 'info', 'The device is read-only for your user, so the rumble test is unavailable.',
                                 'Input still works. Rumble needs the same session-based access that games use.'))
    if info:
        drv = info.get('driver')
        if drv in ('hid-playstation', 'hid-sony'):
            checks.append(_check('driver', 'Kernel driver', 'ok', drv))
        else:
            checks.append(_check('driver', 'Kernel driver', 'warn', drv or 'Unknown',
                                 'Button names may differ. Kernel 5.12+ includes hid-playstation, which this app targets.'))
        roles = set(info.get('roles', []))
        checks.append(_check('touchpad', 'Touchpad input', 'ok' if 'touchpad' in roles else 'info',
                             'Available' if 'touchpad' in roles else 'Not exposed by the driver or not readable.'))
        checks.append(_check('motion', 'Motion sensors', 'ok' if 'motion' in roles else 'info',
                             'Available' if 'motion' in roles else 'Not exposed by the driver or not readable.'))
    virtual = [n for n in nodes if n.get('virtual') and n['role'] == 'gamepad']
    if virtual:
        checks.append(_check('steaminput', 'Virtual gamepads', 'info',
                             '%d virtual pad%s present (for example from Steam Input).' % (len(virtual), '' if len(virtual) == 1 else 's'),
                             'This app reads the physical controller and ignores virtual pads when a real one exists.'
                             if real else 'Only a virtual pad is visible. Close Steam or disable Steam Input for this controller to test the physical device.'))
    if not bt_status.get('installed'):
        checks.append(_check('bluez', 'Bluetooth tools (bluetoothctl)', 'fail', 'Not installed', 'Install with: sudo apt install bluez'))
    else:
        svc = bt_status.get('service')
        checks.append(_check('btservice', 'Bluetooth service', 'ok' if svc == 'active' else 'fail',
                             svc or 'Unknown', '' if svc == 'active' else 'Start it with: sudo systemctl enable --now bluetooth'))
        if bt_status.get('available'):
            on = bt_status.get('powered')
            checks.append(_check('btadapter', 'Bluetooth adapter', 'ok' if on else 'warn',
                                 'Powered on' if on else 'Powered off', '' if on else 'Use Enable Bluetooth on the Bluetooth page.'))
        else:
            checks.append(_check('btadapter', 'Bluetooth adapter', 'fail', bt_status.get('message') or 'Unavailable',
                                 'Check that your adapter is recognised: bluetoothctl list'))
    if steam_status.get('installed'):
        checks.append(_check('steam', 'Steam', 'ok', 'Installed (%s)' % steam_status.get('kind')))
    else:
        checks.append(_check('steam', 'Steam', 'info', 'Not detected', 'Optional. Needed only for the Gaming page.'))
    return checks


def report_text(checks: list, os_line: Optional[str] = None) -> str:
    icons = {'ok': '[ok]  ', 'warn': '[warn]', 'fail': '[FAIL]', 'info': '[info]'}
    lines = ['DS4 Control Center report', os_line or os_summary(), '']
    for c in checks:
        lines.append('%s %s: %s' % (icons.get(c['state'], '[?]   '), c['title'], c['detail']))
        if c['hint'] and c['state'] != 'ok':
            lines.append('        -> ' + c['hint'])
    return '\n'.join(lines)
