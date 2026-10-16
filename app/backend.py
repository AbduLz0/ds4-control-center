"""Linux integration bridge for DS4 Control Center. Never requires root."""
from __future__ import annotations
import json, os, shutil, subprocess, threading, time, glob, re
from pathlib import Path
from collections import deque

APP_DIR = Path.home() / '.config' / 'ds4-control-center'
SETTINGS_FILE = APP_DIR / 'settings.json'
DEFAULTS = {
    'theme': 'midnight', 'animations': True, 'refresh_ms': 50,
    'deadzone': 8, 'auto_start': False, 'diagnostic_logging': True, 'games': []
}

BTN_MAP = {
    'BTN_SOUTH':'cross', 'BTN_EAST':'circle', 'BTN_WEST':'square', 'BTN_NORTH':'triangle',
    'BTN_TL':'l1', 'BTN_TR':'r1', 'BTN_TL2':'l2', 'BTN_TR2':'r2',
    'BTN_THUMBL':'l3', 'BTN_THUMBR':'r3', 'BTN_START':'options', 'BTN_SELECT':'share',
    'BTN_MODE':'ps', 'BTN_TOUCH':'touchpad', 'BTN_DPAD_UP':'dpad-up', 'BTN_DPAD_DOWN':'dpad-down',
    'BTN_DPAD_LEFT':'dpad-left', 'BTN_DPAD_RIGHT':'dpad-right'
}
ABS_MAP = {'ABS_X':'lx','ABS_Y':'ly','ABS_RX':'rx','ABS_RY':'ry','ABS_Z':'l2_axis','ABS_RZ':'r2_axis',
           'ABS_BRAKE':'l2_axis','ABS_GAS':'r2_axis','ABS_HAT0X':'hatx','ABS_HAT0Y':'haty'}

class ControlCenter:
    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.settings = self._load_settings()
        self.state = {'connected':False,'name':None,'path':None,'connection':'Unknown','vendor':None,'product':None,
                      'battery':None,'charging':None,'buttons':{},'axes':{'lx':0,'ly':0,'rx':0,'ry':0,'l2_axis':0,'r2_axis':0},
                      'last_input':None,'last_event':None,'events':[],'drift':{'left':0,'right':0},'bluetooth':{'available':False,'powered':None,'devices':[]},'steam':{'installed':False,'running':False,'path':None},'error':None}
        self.stop_event = threading.Event()
        self.monitor_thread = threading.Thread(target=self._monitor, daemon=True, name='ds4-input-monitor')
        self.monitor_thread.start()

    def _load_settings(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            return {**DEFAULTS, **data}
        except (OSError, ValueError, TypeError): return dict(DEFAULTS)

    def _save_settings(self):
        tmp = SETTINGS_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.settings, indent=2))
        os.chmod(tmp, 0o600); tmp.replace(SETTINGS_FILE)

    def get_state(self):
        with self.lock:
            state = json.loads(json.dumps(self.state))
        state['settings'] = dict(self.settings)
        return state

    def get_settings(self): return dict(self.settings)

    def save_settings(self, settings):
        allowed = set(DEFAULTS)
        with self.lock:
            for key, val in (settings or {}).items():
                if key in allowed and key != 'games': self.settings[key] = val
            self._set_autostart(bool(self.settings.get('auto_start', False)))
            self.settings['refresh_ms'] = max(30, min(250, int(self.settings.get('refresh_ms', 50))))
            self.settings['deadzone'] = max(0, min(30, int(self.settings.get('deadzone', 8))))
            self._save_settings()
        return {'ok':True, 'settings':self.settings}

    def reset_settings(self):
        with self.lock:
            self.settings = dict(DEFAULTS); self._set_autostart(False); self._save_settings()
        return {'ok':True, 'settings':self.settings}

    def _set_autostart(self, enabled):
        # User-level autostart only; no root or system-wide changes.
        target = Path.home() / '.config' / 'autostart' / 'ds4-control-center.desktop'
        if enabled:
            target.parent.mkdir(parents=True, exist_ok=True)
            project_root = Path(__file__).resolve().parent.parent
            content = ('[Desktop Entry]\nType=Application\nName=DS4 Control Center\n'
                       'Comment=DualShock 4 controller dashboard\n'
                       f'Exec=\"{project_root / "run.sh"}\"\nTerminal=false\nX-GNOME-Autostart-enabled=true\n')
            tmp = target.with_suffix('.tmp')
            tmp.write_text(content); os.chmod(tmp, 0o600); tmp.replace(target)
        else:
            try: target.unlink()
            except FileNotFoundError: pass

    def _run(self, args, timeout=5):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
            return p.returncode, (p.stdout or '').strip(), (p.stderr or '').strip()
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return 127, '', str(e)

    def _evdev(self):
        try:
            import evdev
            return evdev
        except ImportError: return None

    def _find_controller(self):
        evdev = self._evdev()
        if not evdev: return None
        paths = sorted(set(glob.glob('/dev/input/event*')))
        for path in paths:
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities(verbose=True)
                keys = caps.get(evdev.ecodes.EV_KEY, [])
                keynames = {str(x[0][1]) if isinstance(x, tuple) else evdev.ecodes.KEY.get(x, str(x)) for x in keys}
                name = (dev.name or '').lower()
                looks_like_pad = any(k in str(keys) for k in ('BTN_GAMEPAD','BTN_SOUTH','BTN_A')) or any(x in name for x in ('wireless controller','dualshock','playstation','sony interactive'))
                if looks_like_pad and (evdev.ecodes.EV_ABS in caps or evdev.ecodes.EV_KEY in caps):
                    return dev
                dev.close()
            except (OSError, PermissionError): continue
        return None

    def _connection_type(self, event_path):
        try:
            p = os.path.realpath('/sys/class/input/' + os.path.basename(event_path) + '/device').lower()
            if '/bluetooth/' in p or 'bluetooth' in p: return 'Bluetooth'
            if '/usb' in p or 'usb' in p: return 'USB / wired'
        except OSError: pass
        return 'Unknown'

    def _read_battery(self, event_path):
        # Linux HID drivers may expose a power_supply entry for a wireless controller.
        try:
            event = os.path.basename(event_path)
            device_root = Path('/sys/class/input') / event / 'device'
            candidates = list(device_root.glob('**/power_supply/*'))
            candidates += [p for p in Path('/sys/class/power_supply').glob('*') if any(k in p.name.lower() for k in ('sony','ds4','dualshock','controller','wireless_controller'))]
            for p in candidates:
                try:
                    typ = (p / 'type').read_text().strip().lower() if (p / 'type').exists() else ''
                    name = p.name.lower()
                    nested_for_device = str(p).startswith(str(device_root))
                    controller_named = any(k in name for k in ('sony','ds4','dualshock','controller','wireless_controller'))
                    if (typ == 'battery' and (nested_for_device or controller_named)) or controller_named:
                        cap = p / 'capacity'; status = p / 'status'
                        if cap.exists():
                            value = max(0, min(100, int(cap.read_text().strip())))
                            charging = status.read_text().strip().lower() in ('charging', 'full') if status.exists() else None
                            with self.lock: self.state['battery'] = value; self.state['charging'] = charging
                            return
                except (OSError, ValueError): continue
        except OSError: pass

    def _monitor(self):
        evdev = self._evdev()
        if not evdev:
            with self.lock: self.state['error'] = 'python-evdev is not installed. Run ./install.sh to install the controller input dependency.'
            while not self.stop_event.wait(2): pass
            return
        while not self.stop_event.is_set():
            dev = self._find_controller()
            if dev is None:
                with self.lock:
                    if self.state['connected']:
                        self.state.update(connected=False, name=None, path=None, buttons={}, battery=None, charging=None, error=None, axes={'lx':0,'ly':0,'rx':0,'ry':0,'l2_axis':0,'r2_axis':0})
                    else: self.state['connected'] = False
                self.stop_event.wait(1.2); continue
            try:
                info = {'connected':True, 'name':dev.name or 'Game controller', 'path':dev.path,
                        'connection':self._connection_type(dev.path),
                        'vendor':f'{dev.info.vendor:04x}', 'product':f'{dev.info.product:04x}', 'error':None}
                with self.lock:
                    self.state.update(info)
                    self.state['battery'] = None
                    self.state['charging'] = None
                self._read_battery(dev.path)
                # Read blocking events; disconnects and permission failures are handled below.
                for event in dev.read_loop():
                    if self.stop_event.is_set(): break
                    did_input = False
                    if event.type == evdev.ecodes.EV_KEY:
                        aliases = evdev.ecodes.bytype.get(evdev.ecodes.EV_KEY, {}).get(event.code, [])
                        if isinstance(aliases, str): aliases = [aliases]
                        code = next((name for name in aliases if name in BTN_MAP), evdev.ecodes.KEY.get(event.code, str(event.code)))
                        button = BTN_MAP.get(code)
                        if button:
                            with self.lock:
                                self.state['buttons'][button] = bool(event.value)
                                did_input = True
                                self._event(f'{button.upper()} {'pressed' if event.value else 'released'}')
                    elif event.type == evdev.ecodes.EV_ABS:
                        aliases = evdev.ecodes.bytype.get(evdev.ecodes.EV_ABS, {}).get(event.code, [])
                        if isinstance(aliases, str): aliases = [aliases]
                        code = next((name for name in aliases if name in ABS_MAP), evdev.ecodes.ABS.get(event.code, str(event.code))); axis = ABS_MAP.get(code)
                        if axis:
                            try:
                                info_abs = dev.absinfo(event.code); val = event.value
                                if axis in ('lx','ly','rx','ry'):
                                    center = (info_abs.min + info_abs.max) / 2
                                    half = max(1, (info_abs.max - info_abs.min) / 2)
                                    val = max(-1.0, min(1.0, (val-center)/half))
                                elif axis.endswith('_axis'):
                                    span = max(1, info_abs.max - info_abs.min); val = max(0.0,min(1.0,(val-info_abs.min)/span))
                                with self.lock:
                                    self.state['axes'][axis] = round(float(val), 3)
                                    did_input = True
                                    if axis in ('hatx','haty'):
                                        direction = {'hatx':('dpad-left','dpad-right'),'haty':('dpad-up','dpad-down')}[axis]
                                        self.state['buttons'][direction[0]] = val < 0
                                        self.state['buttons'][direction[1]] = val > 0
                            except (OSError, ValueError): pass
                    if did_input:
                        with self.lock:
                            self.state['last_input'] = time.time(); self.state['last_event'] = time.time()
                dev.close()
            except (OSError, PermissionError) as e:
                with self.lock: self.state.update(connected=False, name=None, path=None, buttons={}, battery=None, charging=None, axes={'lx':0,'ly':0,'rx':0,'ry':0,'l2_axis':0,'r2_axis':0}, error=f'Controller input ended: {e}')
                try: dev.close()
                except Exception: pass
                self.stop_event.wait(.5)

    def _event(self, message):
        if not self.settings.get('diagnostic_logging', True): return
        self.state['events'].insert(0, {'time':time.strftime('%H:%M:%S'), 'message':message})
        del self.state['events'][80:]

    def reset_diagnostics(self):
        with self.lock:
            self.state['events'] = []
            self.state['drift'] = {'left':0,'right':0}
        return {'ok':True}

    def bluetooth_status(self):
        if not shutil.which('bluetoothctl'): return {'available':False,'powered':None,'devices':[],'message':'bluetoothctl not installed'}
        rc, out, err = self._run(['bluetoothctl','show'], timeout=3)
        if rc != 0: return {'available':False,'powered':None,'devices':[],'message':err or out or 'BlueZ is unavailable'}
        powered = None
        m = re.search(r'Powered:\s*(yes|no)', out, re.I)
        if m: powered = m.group(1).lower() == 'yes'
        _, devout, _ = self._run(['bluetoothctl','devices','Paired'], timeout=3)
        devices = []
        for line in devout.splitlines():
            m = re.match(r'Device\s+([0-9A-Fa-f:]{17})\s+(.+)', line)
            if m: devices.append({'mac':m.group(1),'name':m.group(2)})
        return {'available':True,'powered':powered,'devices':devices,'message':None}

    def bluetooth_scan(self):
        if not shutil.which('bluetoothctl'): return {'ok':False,'message':'Install bluez first.'}
        # Starts a bounded discovery session; does not change system settings.
        rc, out, err = self._run(['bluetoothctl','--timeout','8','scan','on'], timeout=11)
        _, devices, _ = self._run(['bluetoothctl','devices'], timeout=3)
        found=[]
        for line in devices.splitlines():
            m=re.match(r'Device\s+([0-9A-Fa-f:]{17})\s+(.+)',line)
            if m: found.append({'mac':m.group(1),'name':m.group(2)})
        return {'ok':rc==0 or bool(found),'devices':found,'message':err or None}

    def bluetooth_action(self, action, mac=''):
        if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', mac or '') and action in ('pair','connect','disconnect','trust'):
            return {'ok':False,'message':'Choose a valid device address first.'}
        commands={'power-on':['bluetoothctl','power','on'],'power-off':['bluetoothctl','power','off'],
                  'pair':['bluetoothctl','pair',mac],'connect':['bluetoothctl','connect',mac],
                  'disconnect':['bluetoothctl','disconnect',mac],'trust':['bluetoothctl','trust',mac]}
        if action not in commands: return {'ok':False,'message':'Unsupported Bluetooth action.'}
        rc,out,err=self._run(commands[action],timeout=20)
        return {'ok':rc==0,'message':out or err or ('Command completed.' if rc==0 else 'Bluetooth command failed.'),'status':self.bluetooth_status()}

    def steam_status(self):
        path = shutil.which('steam')
        if not path:
            for p in ('/usr/bin/steam','/usr/games/steam'):
                if os.path.exists(p): path=p; break
        flatpak = shutil.which('flatpak')
        if not path and flatpak:
            rc,out,_=self._run(['flatpak','info','com.valvesoftware.Steam'],timeout=3)
            if rc==0: path='flatpak:com.valvesoftware.Steam'
        running = False
        if shutil.which('pgrep'): running = self._run(['pgrep','-x','steam'],timeout=2)[0] == 0
        return {'installed':bool(path),'running':running,'path':path}

    def launch_steam(self):
        status=self.steam_status()
        if not status['installed']: return {'ok':False,'message':'Steam was not detected. Install it using your preferred package manager.'}
        try:
            args=['flatpak','run','com.valvesoftware.Steam'] if str(status['path']).startswith('flatpak:') else [status['path']]
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return {'ok':True,'message':'Steam launch requested.'}
        except OSError as e: return {'ok':False,'message':str(e)}

    def launch_game(self, target):
        target=str(target or '').strip()
        if not target: return {'ok':False,'message':'Enter a Steam app ID or launch URI.'}
        if not re.fullmatch(r'(?:[0-9]{1,12}|steam://rungameid/[0-9]{1,12})',target):
            return {'ok':False,'message':'For safety, enter a numeric Steam app ID or steam://rungameid/APPID URI.'}
        uri=target if target.startswith('steam://') else f'steam://rungameid/{target}'
        if shutil.which('xdg-open'):
            try: subprocess.Popen(['xdg-open',uri],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); return {'ok':True,'message':'Steam game launch requested.'}
            except OSError as e: return {'ok':False,'message':str(e)}
        return {'ok':False,'message':'xdg-open is unavailable.'}

    def open_controller_settings(self):
        candidates=[['steam','steam://open/settings/controller'],['xdg-open','steam://open/settings/controller']]
        for args in candidates:
            if shutil.which(args[0]):
                try: subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); return {'ok':True,'message':'Controller settings opened.'}
                except OSError: pass
        return {'ok':False,'message':'Could not open Steam controller settings. Open Steam → Settings → Controller.'}

    def shutdown(self): self.stop_event.set()
