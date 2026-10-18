"""Bluetooth management through BlueZ's `bluetoothctl` (talks to bluetoothd over D-Bus).

No Bluetooth protocol is reimplemented and nothing here needs root. Long operations
(scan, pair) run as one background job with live progress that the UI polls.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Optional

from .diagnostics import EventLog

MAC_RE = re.compile(r'^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|[\x01\x02]')
PROMPT_RE = re.compile(r'\[[^\]\n]*\]#\s?')
CONTROLLER_RE = re.compile(r'wireless controller|dualshock|dualsense|playstation|gamepad|joystick|controller', re.I)
DEVICE_LINE_RE = re.compile(r'Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)')

ERROR_HINTS = (
    ('AuthenticationFailed', 'Authentication failed. Hold Share + PS until the light bar flashes quickly, then try again.'),
    ('AuthenticationRejected', 'The controller rejected pairing. Put it back into pairing mode (Share + PS) and retry.'),
    ('AuthenticationCanceled', 'Pairing was cancelled before it finished.'),
    ('AuthenticationTimeout', 'Pairing timed out. Keep the controller in pairing mode and close to the computer.'),
    ('ConnectionAttemptFailed', 'Could not reach the controller. Make sure it is on and in range.'),
    ('Page Timeout', 'The controller did not answer. Press the PS button to wake it, or re-enter pairing mode.'),
    ('page-timeout', 'The controller did not answer. Press the PS button to wake it, or re-enter pairing mode.'),
    ('Blocked', 'Bluetooth is blocked by rfkill. Use Enable Bluetooth, or unblock it in system settings.'),
    ('NotReady', 'The Bluetooth adapter is not ready. Make sure Bluetooth is turned on.'),
    ('not available', 'The device is not visible to the adapter. Scan again while the controller is in pairing mode.'),
    ('InProgress', 'Another Bluetooth operation is already running. Wait a moment and retry.'),
    ('AlreadyConnected', 'The controller is already connected.'),
    ('profile-unavailable', 'The input (HID) service did not start. Remove the device and pair it again.'),
    ('br-connection', 'The connection failed. Remove the device in Bluetooth settings and pair again.'),
)


def explain(raw: str) -> str:
    for needle, text in ERROR_HINTS:
        if needle.lower() in (raw or '').lower():
            return text
    return (raw or 'Bluetooth command failed.').strip()[:240]


def clean_line(line: str) -> list:
    """Split one raw bluetoothctl output line into clean, prompt-free lines."""
    out = []
    for part in ANSI_RE.sub('', line).replace('\r', '\n').split('\n'):
        part = PROMPT_RE.sub('', part).strip()
        if part:
            out.append(part)
    return out


class _Session:
    """A short-lived interactive bluetoothctl process."""

    def __init__(self):
        env = dict(os.environ, NO_COLOR='1', TERM='dumb')
        self._p = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        self.lines: 'queue.Queue[str]' = queue.Queue()
        self._t = threading.Thread(target=self._pump, daemon=True)
        self._t.start()

    def _pump(self):
        try:
            for raw in self._p.stdout:
                for line in clean_line(raw):
                    self.lines.put(line)
        except (OSError, ValueError):
            pass
        self.lines.put('\x00eof')

    def send(self, cmd: str):
        try:
            self._p.stdin.write(cmd + '\n')
            self._p.stdin.flush()
        except (OSError, ValueError):
            pass

    def read(self, timeout: float) -> Optional[str]:
        try:
            return self.lines.get(timeout=timeout)
        except queue.Empty:
            return None

    def alive(self) -> bool:
        return self._p.poll() is None

    def close(self):
        self.send('quit')
        try:
            self._p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._p.terminate()
            try:
                self._p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._p.kill()
        for stream in (self._p.stdin, self._p.stdout):
            try:
                stream.close()
            except Exception:
                pass


class Bluetooth:
    def __init__(self, log: EventLog):
        self._log = log
        self._job: Optional[dict] = None
        self._job_lock = threading.Lock()
        self._cancel = threading.Event()

    # -- one-shot commands -----------------------------------------------
    @staticmethod
    def installed() -> bool:
        return shutil.which('bluetoothctl') is not None

    @staticmethod
    def _run(args, timeout=6):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False,
                               env=dict(os.environ, NO_COLOR='1'))
            text = ANSI_RE.sub('', ((p.stdout or '') + '\n' + (p.stderr or '')))
            return p.returncode, text.strip()
        except FileNotFoundError:
            return 127, '%s not found' % args[0]
        except subprocess.TimeoutExpired:
            return 124, 'Timed out waiting for %s' % ' '.join(args[:3])

    def status(self) -> dict:
        res = {'installed': self.installed(), 'available': False, 'powered': None, 'discovering': None,
               'name': None, 'address': None, 'blocked': None, 'service': None, 'message': None}
        if not res['installed']:
            res['message'] = 'bluetoothctl is not installed. Install the bluez package.'
            return res
        if shutil.which('systemctl'):
            rc, out = self._run(['systemctl', 'is-active', 'bluetooth'], timeout=3)
            res['service'] = out.splitlines()[-1].strip() if out else None
        if shutil.which('rfkill'):
            rc, out = self._run(['rfkill', 'list', 'bluetooth'], timeout=3)
            if rc == 0 and out:
                res['blocked'] = bool(re.search(r'(Soft|Hard) blocked:\s*yes', out))
        rc, out = self._run(['bluetoothctl', 'show'], timeout=4)
        if rc != 0 or 'No default controller' in out or not out:
            res['message'] = ('No Bluetooth adapter was found.' if 'No default controller' in out
                              else (explain(out) if out else 'The Bluetooth service is not responding.'))
            if res['service'] and res['service'] != 'active':
                res['message'] = 'The Bluetooth service is not running (systemctl status bluetooth).'
            return res
        res['available'] = True
        m = re.search(r'Controller\s+((?:[0-9A-F]{2}:){5}[0-9A-F]{2})', out, re.I)
        res['address'] = m.group(1) if m else None
        for key, field in (('Powered', 'powered'), ('Discovering', 'discovering')):
            m = re.search(r'%s:\s*(yes|no)' % key, out, re.I)
            res[field] = (m.group(1).lower() == 'yes') if m else None
        m = re.search(r'Alias:\s*(.+)', out)
        res['name'] = m.group(1).strip() if m else None
        if res['powered'] is False and res['blocked']:
            res['message'] = 'Bluetooth is blocked by rfkill. Use Enable Bluetooth to unblock it.'
        return res

    def info(self, mac: str) -> Optional[dict]:
        rc, out = self._run(['bluetoothctl', 'info', mac], timeout=4)
        if rc != 0 or 'not available' in out.lower():
            return None

        def field(name):
            m = re.search(r'^\s*%s:\s*(.+)$' % name, out, re.M)
            return m.group(1).strip() if m else None
        name = field('Name') or field('Alias') or mac
        battery = field('Battery Percentage')
        pct = None
        if battery:
            m = re.search(r'\((\d+)\)', battery)
            pct = int(m.group(1)) if m else None
        modalias = field('Modalias') or ''
        return {'mac': mac.upper(), 'name': name, 'paired': field('Paired') == 'yes',
                'trusted': field('Trusted') == 'yes', 'connected': field('Connected') == 'yes',
                'controller': bool(CONTROLLER_RE.search(name) or field('Icon') == 'input-gaming'
                                   or '054c' in modalias.lower()),
                'battery': pct}

    def devices(self, only_paired: bool = True) -> list:
        rc, out = self._run(['bluetoothctl', 'devices'], timeout=4)
        result = []
        for line in out.splitlines():
            m = DEVICE_LINE_RE.search(line)
            if not m or len(result) >= 24:
                continue
            info = self.info(m.group(1))
            if info and (info['paired'] or not only_paired):
                result.append(info)
        result.sort(key=lambda d: (not d['connected'], not d['controller'], d['name'].lower()))
        return result

    def _simple(self, args, ok_text: str, timeout=20) -> dict:
        rc, out = self._run(args, timeout=timeout)
        failed = rc != 0 or bool(re.search(r'Failed|Error', out))
        return {'ok': not failed, 'message': ok_text if not failed else explain(out)}

    def set_power(self, on: bool) -> dict:
        if not self.installed():
            return {'ok': False, 'message': 'bluetoothctl is not installed.'}
        word = 'on' if on else 'off'
        res = self._simple(['bluetoothctl', 'power', word], 'Bluetooth turned %s.' % word)
        if on and not res['ok'] and shutil.which('rfkill'):
            # The user explicitly asked to enable Bluetooth, so lift a soft block.
            self._run(['rfkill', 'unblock', 'bluetooth'], timeout=4)
            time.sleep(0.6)
            res = self._simple(['bluetoothctl', 'power', 'on'], 'Bluetooth turned on.')
        self._log.add('bluetooth', res['message'])
        return res

    def action(self, name: str, mac: str) -> dict:
        if not self.installed():
            return {'ok': False, 'message': 'bluetoothctl is not installed.'}
        if not MAC_RE.match(mac or ''):
            return {'ok': False, 'message': 'Choose a valid device first.'}
        table = {'connect': (['bluetoothctl', 'connect', mac], 'Connected.', 25),
                 'disconnect': (['bluetoothctl', 'disconnect', mac], 'Disconnected.', 10),
                 'trust': (['bluetoothctl', 'trust', mac], 'Device trusted.', 8),
                 'forget': (['bluetoothctl', 'remove', mac], 'Device removed from this computer.', 8)}
        if name not in table:
            return {'ok': False, 'message': 'Unsupported Bluetooth action.'}
        args, ok_text, timeout = table[name]
        res = self._simple(args, ok_text, timeout)
        self._log.add('bluetooth', '%s %s: %s' % (name, mac, res['message']))
        return res

    # -- background jobs -----------------------------------------------------
    def job(self) -> Optional[dict]:
        with self._job_lock:
            if not self._job:
                return None
            j = dict(self._job)
            j['devices'] = list(j['devices'].values()) if isinstance(j['devices'], dict) else j['devices']
            return j

    def cancel(self):
        self._cancel.set()

    def _start(self, kind: str, mac: Optional[str], target, steps: list) -> dict:
        with self._job_lock:
            if self._job and self._job['state'] == 'running':
                return {'ok': False, 'message': 'Another Bluetooth task is still running.'}
            self._cancel.clear()
            self._job = {'id': uuid.uuid4().hex[:8], 'kind': kind, 'mac': mac, 'state': 'running',
                         'step': steps[0], 'steps': steps, 'progress': 0.02, 'message': 'Starting…',
                         'devices': {}, 'started': time.time(), 'ended': None}
        threading.Thread(target=target, name='ds4-bt-' + kind, daemon=True).start()
        return {'ok': True, 'message': 'Started.'}

    def _set(self, **kw):
        with self._job_lock:
            if self._job:
                self._job.update(kw)

    def _note_device(self, mac: str, name: str):
        with self._job_lock:
            if not self._job:
                return
            devs = self._job['devices']
            cur = devs.get(mac.upper(), {'mac': mac.upper(), 'name': '', 'controller': False})
            if name and name.replace('-', ':').upper() != mac.upper():
                cur['name'] = name
            cur['controller'] = bool(CONTROLLER_RE.search(cur['name']))
            devs[mac.upper()] = cur

    def _scan_lines(self, line: str):
        m = re.search(r'\[(NEW|CHG)\]\s+' + DEVICE_LINE_RE.pattern, line)
        if not m:
            return
        kind, mac, rest = m.group(1), m.group(2), m.group(3).strip()
        if kind == 'NEW':
            name = rest
        elif rest.startswith(('Name:', 'Alias:')):
            name = rest.split(':', 1)[1].strip()
        else:
            name = ''  # RSSI, ManufacturerData, ... updates carry no name
        self._note_device(mac, name)

    def _finish(self, ok: bool, message: str):
        self._set(state='done' if ok else 'error', message=message, progress=1.0 if ok else self._job['progress'],
                  ended=time.time())
        self._log.add('bluetooth', message)

    def start_scan(self, seconds: int = 12) -> dict:
        st = self.status()
        if not st['available']:
            return {'ok': False, 'message': st['message'] or 'Bluetooth is unavailable.'}
        if not st['powered']:
            return {'ok': False, 'message': 'Bluetooth is turned off. Enable it first.'}
        return self._start('scan', None, lambda: self._scan(seconds), ['Scanning'])

    def _scan(self, seconds: int):
        s = None
        try:
            s = _Session()
            s.send('scan on')
            end = time.monotonic() + seconds
            while time.monotonic() < end and not self._cancel.is_set() and s.alive():
                self._set(progress=0.05 + 0.9 * (1 - (end - time.monotonic()) / seconds),
                          message='Looking for nearby devices…')
                line = s.read(0.4)
                if line:
                    self._scan_lines(line)
            s.send('scan off')
            time.sleep(0.3)
            found = list(self._job['devices'])
            paired = {d['mac'] for d in self.devices(True)}
            for mac in found:
                self._set_paired(mac, mac in paired)
            n = len(found)
            self._finish(True, 'Scan stopped.' if self._cancel.is_set() else
                         ('Found %d device%s.' % (n, '' if n == 1 else 's') if n else
                          'No devices found. Put the controller in pairing mode and scan again.'))
        except OSError as e:
            self._finish(False, 'Could not start bluetoothctl: %s' % e)
        finally:
            if s:
                s.close()

    def _set_paired(self, mac: str, paired: bool):
        with self._job_lock:
            if self._job and mac in self._job['devices']:
                self._job['devices'][mac]['paired'] = paired

    def start_pair(self, mac: str) -> dict:
        if not MAC_RE.match(mac or ''):
            return {'ok': False, 'message': 'Choose a valid device first.'}
        st = self.status()
        if not st['available'] or not st['powered']:
            return {'ok': False, 'message': 'Bluetooth is turned off or unavailable.'}
        return self._start('pair', mac.upper(), lambda: self._pair(mac.upper()),
                           ['Preparing', 'Pairing', 'Trusting', 'Connecting'])

    def _wait(self, s: _Session, ok_pat: str, fail_pat: str, timeout: float):
        """Return ('ok'|'fail'|'timeout', text)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self._cancel.is_set():
            line = s.read(0.4)
            if line is None:
                if not s.alive():
                    return 'fail', 'bluetoothctl exited unexpectedly'
                continue
            if line == '\x00eof':
                return 'fail', 'bluetoothctl exited unexpectedly'
            self._scan_lines(line)
            if re.search(r'Confirm passkey|Request confirmation|Authorize service', line, re.I):
                s.send('yes')  # answer the agent prompt for the device the user chose to pair
            if re.search(ok_pat, line):
                return 'ok', line
            m = re.search(fail_pat, line)
            if m:
                return 'fail', line
        return ('fail', 'cancelled') if self._cancel.is_set() else ('timeout', 'No response from the controller.')

    def _pair(self, mac: str):
        s = None
        try:
            s = _Session()
            self._set(step='Preparing', progress=0.08, message='Registering a pairing agent…')
            s.send('agent NoInputNoOutput')
            s.send('default-agent')
            s.send('scan on')  # BlueZ must be discovering to pair a device it does not have cached
            time.sleep(1.0)
            self._set(step='Pairing', progress=0.25, message='Pairing with %s…' % mac)
            s.send('pair ' + mac)
            res, text = self._wait(s, r'Pairing successful|AlreadyExists|Already Exists',
                                   r'Failed to pair|not available', 40)
            if res != 'ok':
                s.send('scan off')
                raise RuntimeError(explain(text) if res != 'timeout' else 'Pairing timed out. Keep the controller in pairing mode and retry.')
            self._set(step='Trusting', progress=0.6, message='Trusting the controller so it can reconnect…')
            s.send('trust ' + mac)
            self._wait(s, r'trust succeeded|Trusted: yes', r'Failed to trust', 6)
            self._set(step='Connecting', progress=0.78, message='Connecting…')
            s.send('connect ' + mac)
            res, text = self._wait(s, r'Connection successful|AlreadyConnected', r'Failed to connect', 25)
            s.send('scan off')
            if res != 'ok':
                raise RuntimeError('Paired, but connecting failed: ' + explain(text))
            self._finish(True, 'Paired and connected.')
        except RuntimeError as e:
            self._finish(False, str(e))
        except OSError as e:
            self._finish(False, 'Could not start bluetoothctl: %s' % e)
        finally:
            if s:
                s.close()
