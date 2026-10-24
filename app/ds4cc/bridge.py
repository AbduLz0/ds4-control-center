"""JavaScript <-> Python bridge exposed through pywebview.

pywebview exposes every public attribute of this object to the page, so all state is
kept in underscore-prefixed attributes and only the intended API methods are public.
"""
from __future__ import annotations

import threading
import time

from . import __version__, lightbar, notify, power
from .bluetooth import MAC_RE, Bluetooth
from .controller import ControllerMonitor
from .diagnostics import STATE_DIR, EventLog
from .games import UniversalGames
from .input_map import (BUTTONS as MAP_BUTTONS, BUTTON_LABELS, STICK_MODE_LABELS, STICK_MODES,
                        InputMapper, clean_mapping, preset_mapping, public_presets, uinput_reason)
from .settings import PROJECT_ROOT, SettingsStore
from .steam import Steam
from .system import os_summary, report_text, run_checks
from .virtual_pad import VirtualPad


def _res(ok: bool, message: str = '', **extra) -> dict:
    return dict(ok=ok, message=message, **extra)


class _Reconnector(threading.Thread):
    """Optionally re-connects a previously used Bluetooth controller (never pairs, never forces)."""

    def __init__(self, settings, monitor, bt, log):
        super().__init__(name='ds4-reconnect', daemon=True)
        self._settings, self._monitor, self._bt, self._log = settings, monitor, bt, log
        self._stop_evt = threading.Event()
        self.state, self.attempt, self.suppressed = 'idle', 0, False
        self._next = 0.0
        self._suppressed_conn = None

    def stop(self):
        self._stop_evt.set()

    def rearm(self):
        self.attempt, self.suppressed, self._next = 0, False, 0.0

    def suppress(self):
        """Stop auto-reconnect until the controller connects again by its own (a new connection)."""
        self._suppressed_conn = self._monitor.connected_since()
        self.suppressed = True

    def snapshot(self, max_attempts: int) -> dict:
        return {'state': self.state, 'attempt': self.attempt, 'max': max_attempts}

    def run(self):
        while not self._stop_evt.wait(3.0):
            cfg = self._settings.get()
            last = cfg.get('last_controller') or {}
            if self._monitor.connected:
                # a disconnect we asked for can take a moment to show up; only a new connection clears the pause
                if not self.suppressed or self._monitor.connected_since() != self._suppressed_conn:
                    self.rearm()
                self.state = 'idle'
                continue
            if not cfg['auto_reconnect'] or last.get('bus') != 'Bluetooth' or not MAC_RE.match(last.get('mac') or ''):
                self.state = 'off'
                continue
            if self.suppressed:
                self.state = 'paused'
                continue
            if self.attempt >= cfg['reconnect_attempts']:
                self.state = 'gave_up'
                continue
            if time.monotonic() < self._next:
                continue
            st = self._bt.status()
            if not st.get('powered'):
                self.state = 'waiting'
                continue
            self.state = 'trying'
            self.attempt += 1
            res = self._bt.action('connect', last['mac'])
            self._log.add('bluetooth', 'Auto-reconnect %d/%d: %s' % (self.attempt, cfg['reconnect_attempts'], res['message']))
            self._next = time.monotonic() + 15


class _Watcher(threading.Thread):
    """Background housekeeping: alerts, idle disconnect, running-game detection, light bar restore.
    Each job is gated by its own setting, and every action is written to the event log."""

    def __init__(self, api):
        super().__init__(name='ds4-watcher', daemon=True)
        self._api = api
        self._stop_evt = threading.Event()
        self._alert = power.LowBatteryAlert()
        self._lb_for = None          # connection timestamp the light bar was last restored for
        self._idle_fired_for = None  # connection timestamp an idle disconnect was already sent for
        self._was_connected = None
        self.running_app = None
        self.running_game = None

    def stop(self):
        self._stop_evt.set()

    def run(self):
        while not self._stop_evt.wait(3.0):
            try:
                self.tick()
            except Exception as e:  # housekeeping must never take the app down
                self._api._log.add('system', 'Background task error: %s' % e)

    def tick(self, now=None):
        api = self._api
        now = time.time() if now is None else now
        cfg = api._settings.get()
        mon = api._monitor
        info = mon.status()['info']
        live = info is not None
        since = mon.connected_since()

        # connect / disconnect notifications (not on the very first look, so starting the app is quiet)
        if self._was_connected is not None and live != self._was_connected and cfg['notifications']:
            if live:
                notify.send('Controller connected', '%s via %s' % (info['name'], info['bus']))
            else:
                notify.send('Controller disconnected', 'The controller is no longer available.', 'low')
        self._was_connected = live

        # running game (read-only) for automatic profiles, from Steam plus desktop/Lutris/manual entries
        self.running_app = api._steam.running_appid() if cfg['auto_profile'] else None
        self.running_game = None
        if cfg['auto_profile']:
            try:
                library = api._library()['games']
                self.running_game = api._games.running(self.running_app, library)
            except Exception as e:
                api._log.add('system', 'Could not check the running game: %s' % e)

        if not live:
            self._alert.armed = True
            return

        # low battery
        if cfg['notifications'] or cfg['low_battery_percent']:
            msg = self._alert.check(mon.status()['battery'], cfg['low_battery_percent'])
            if msg:
                api._log.add('system', msg)
                if cfg['notifications']:
                    notify.send('Controller battery low', msg, 'critical')

        # restore the saved light bar colour once per connection
        if cfg['lightbar_color'] and self._lb_for != since:
            self._lb_for = since
            res = api._apply_lightbar(cfg['lightbar_color'])
            if res['ok']:
                api._log.add('system', 'Light bar restored to %s.' % cfg['lightbar_color'])

        # idle disconnect (Bluetooth only, off by default)
        idle = power.idle_seconds(mon.last_active(), since, now)
        if (self._idle_fired_for != since and
                power.should_idle_disconnect(idle, cfg['idle_disconnect_minutes'], info['bus'], info.get('mac'))):
            self._idle_fired_for = since
            api._reconnector.suppress()
            res = api._bt.action('disconnect', info['mac'].upper())
            api._log.add('bluetooth', 'Idle for %d min: %s' % (cfg['idle_disconnect_minutes'], res['message']))
            if cfg['notifications'] and res['ok']:
                notify.send('Controller turned off', 'Disconnected after %d minutes without input.' % cfg['idle_disconnect_minutes'], 'low')


class Api:
    def __init__(self):
        self._settings = SettingsStore()
        self._log = EventLog()
        self._log.enabled = self._settings.get()['diagnostic_logging']
        self._bt = Bluetooth(self._log)
        self._steam = Steam()
        self._games = UniversalGames(self._steam, self._log)
        self._mapper = InputMapper(self._log)
        self._vpad = VirtualPad(self._log)
        self._monitor = ControllerMonitor(self._log, on_event=self._on_controller)
        self._monitor.add_output(self._mapper)
        self._monitor.add_output(self._vpad)
        self._reconnector = _Reconnector(self._settings, self._monitor, self._bt, self._log)
        self._watcher = _Watcher(self)
        self._monitor.start()
        self._apply_input_settings(self._settings.get())
        self._reconnector.start()
        self._watcher.start()

    # -- internal ---------------------------------------------------------------
    def _on_controller(self, kind: str, info: dict):
        prev = self._settings.get().get('last_controller') or {}
        self._settings.remember_controller({
            'name': info['name'], 'bus': info['bus'], 'mac': info.get('mac') or prev.get('mac'),
            'vendor': info['vendor'], 'product': info['product'],
            'seen_at': time.time(), 'connected': kind == 'connected'})

    def _apply_lightbar(self, color):
        node = self._monitor.primary_node()
        led = lightbar.find(node.devdir) if node else None
        if not led:
            return _res(False, 'The kernel does not expose a light bar for this controller.')
        return lightbar.apply(led, color)

    def _sync_grab(self):
        """Reserve the physical pad when the app is presenting a virtual one or a keyboard mapper grabs it."""
        cfg = self._settings.get()
        mapping = cfg.get('mapping') if isinstance(cfg, dict) else None
        mapping = mapping if isinstance(mapping, dict) else {}
        want = bool(self._vpad.enabled) or (self._mapper.enabled and mapping.get('grab') is True)
        self._monitor.set_grab(want)

    def _apply_input_settings(self, data: dict):
        mapping = data.get('mapping') if isinstance(data, dict) else None
        mapping = mapping if isinstance(mapping, dict) else None
        if mapping is not None:
            self._mapper.configure(mapping)
            if mapping.get('enabled') is True:
                res = self._mapper.enable(mapping)
                if not res['ok']:
                    self._log.add('system', res['message'])
            else:
                self._mapper.disable()
        if data.get('virtual_pad_enabled') is True:
            res = self._vpad.enable()
            if not res['ok']:
                self._log.add('system', res['message'])
        else:
            self._vpad.disable()
        self._sync_grab()

    def _library(self, force: bool = False) -> dict:
        cfg = self._settings.get()
        steam_games = self._steam.library(force)
        return self._games.library(steam_games, cfg['custom_games'],
                                   cfg['scan_desktop_games'], cfg['scan_lutris_games'], force)

    def _shutdown(self):
        self._watcher.stop()
        self._reconnector.stop()
        self._bt.cancel()
        self._monitor.stop()
        self._mapper.shutdown()
        self._vpad.shutdown()

    # -- app --------------------------------------------------------------------
    def get_boot(self):
        return {'version': __version__, 'settings': self._settings.get(), 'os': os_summary()}

    # -- live data --------------------------------------------------------------
    def get_frame(self, since=0, ev_since=0):
        f = self._monitor.frame(int(since or 0))
        f['events'] = self._log.since(int(ev_since or 0))
        f['ev_last'] = self._log.last_id
        return f

    def get_status(self):
        cfg = self._settings.get()
        st = self._monitor.status()
        st['last_controller'] = cfg.get('last_controller')
        st['reconnect'] = self._reconnector.snapshot(cfg['reconnect_attempts'])
        st['reconnect']['enabled'] = cfg['auto_reconnect']
        st['steam_app'] = self._watcher.running_app
        st['running_game'] = self._watcher.running_game
        st['virtual_pad'] = self._vpad.status()
        st['virtual_pad']['grab'] = st.get('grab')
        st['virtual_pad']['desired'] = cfg.get('virtual_pad_enabled', False)
        st['mapping'] = {'enabled': self._mapper.enabled, 'available': not uinput_reason()}
        st['drain_rate'] = self._monitor.battery_history.drain_rate()
        return st

    # -- settings ---------------------------------------------------------------
    def get_settings(self):
        return self._settings.get()

    def save_settings(self, partial):
        try:
            data, changed = self._settings.update(partial or {})
            self._log.enabled = data['diagnostic_logging']
            if changed & {'mapping', 'virtual_pad_enabled'}:
                self._apply_input_settings(data)
            if changed & {'scan_desktop_games', 'scan_lutris_games'}:
                self._games.invalidate()
            return _res(True, 'Saved.', settings=data, changed=sorted(changed),
                        virtual_pad=self._vpad.status())
        except OSError as e:
            return _res(False, 'Could not write settings: %s' % e)

    def reset_settings(self):
        try:
            data = self._settings.reset()
            self._log.enabled = data['diagnostic_logging']
            self._apply_input_settings(data)
            self._games.invalidate()
            return _res(True, 'Defaults restored.', settings=data)
        except OSError as e:
            return _res(False, str(e))

    # -- diagnostics ----------------------------------------------------------------
    def reset_diagnostics(self):
        self._monitor.reset_measurements()
        return _res(True, 'Measurements reset.')

    def clear_log(self):
        self._log.clear()
        return _res(True, 'Log cleared.')

    def export_log(self):
        try:
            path = self._log.export()
            return _res(True, 'Saved to %s' % path, path=str(path))
        except OSError as e:
            return _res(False, 'Could not save the log: %s' % e)

    def rumble(self, strong=0.6, weak=0.6, ms=500):
        try:
            return self._monitor.rumble(float(strong), float(weak), int(ms))
        except (TypeError, ValueError):
            return _res(False, 'Invalid rumble values.')

    def save_report(self, text, kind='report'):
        """Write a text report (built by the page from real measurements) to the state folder."""
        if not isinstance(text, str) or not text.strip():
            return _res(False, 'There is nothing to save yet.')
        try:
            directory = STATE_DIR
            directory.mkdir(parents=True, exist_ok=True)
            safe = ''.join(ch for ch in str(kind) if ch.isalnum() or ch in '-_')[:24] or 'report'
            path = directory / time.strftime('%s-%%Y%%m%%d-%%H%%M%%S.md' % safe)
            path.write_text(text[:200000], encoding='utf-8')
            return _res(True, 'Saved to %s' % path, path=str(path))
        except OSError as e:
            return _res(False, 'Could not save the report: %s' % e)

    # -- battery / light bar ---------------------------------------------------------
    def get_battery_history(self):
        return {'samples': self._monitor.battery_history.samples(),
                'drain_rate': self._monitor.battery_history.drain_rate()}

    def get_lightbar(self):
        node = self._monitor.primary_node()
        led = lightbar.find(node.devdir) if node else None
        saved = self._settings.get()['lightbar_color'] or None
        if node is None:
            return {'state': 'disconnected', 'message': 'Connect a controller to change its light bar.', 'saved': saved,
                    'presets': lightbar.PRESETS}
        if not led:
            return {'state': 'unsupported', 'saved': saved, 'presets': lightbar.PRESETS,
                    'message': 'The kernel driver does not expose a light bar for this controller.'}
        if not led['writable']:
            return {'state': 'locked', 'saved': saved, 'presets': lightbar.PRESETS, 'color': lightbar.current(led),
                    'message': 'The light bar is visible to the system but only root can change it. '
                               'This app never changes system permissions. See the README for an optional rule you can add yourself.'}
        return {'state': 'ready', 'saved': saved, 'presets': lightbar.PRESETS, 'color': lightbar.current(led), 'message': ''}

    def set_lightbar(self, color):
        res = self._apply_lightbar(str(color or ''))
        if res['ok']:
            try:
                self._settings.update({'lightbar_color': str(color).lower()})
            except OSError as e:
                res['message'] += ' (Could not remember it: %s)' % e
        return res

    # -- controller link ----------------------------------------------------------------
    def reconnect(self):
        """Re-connect the last known Bluetooth controller; wired controllers cannot be reconnected by software."""
        last = self._settings.get().get('last_controller') or {}
        self._reconnector.rearm()
        if self._monitor.connected:
            return _res(True, 'The controller is already connected.')
        mac = last.get('mac')
        if last.get('bus') != 'Bluetooth' or not MAC_RE.match(mac or ''):
            devs = [d for d in self._bt.devices(True) if d['controller']] if self._bt.installed() else []
            if not devs:
                return _res(False, 'No previously paired Bluetooth controller was found. Pair one on the Bluetooth page, or plug in the USB cable.')
            mac = devs[0]['mac']
        res = self._bt.action('connect', mac)
        if not res['ok']:
            res['message'] += ' Press the PS button on the controller so it is awake, then try again.'
        return res

    def disconnect_controller(self):
        info = self._monitor.status().get('info')
        if not info:
            return _res(False, 'No controller is connected.')
        if info['bus'] != 'Bluetooth' or not info.get('mac'):
            return _res(False, 'This controller is wired. Unplug the USB cable to disconnect it.')
        self._reconnector.suppress()
        return self._bt.action('disconnect', info['mac'].upper())

    # -- bluetooth ----------------------------------------------------------------------
    def bt_status(self):
        return self._bt.status()

    def bt_devices(self):
        return self._bt.devices(True) if self._bt.installed() else []

    def bt_set_power(self, on):
        return self._bt.set_power(bool(on))

    def bt_action(self, action, mac):
        return self._bt.action(str(action), str(mac))

    def bt_scan(self):
        return self._bt.start_scan()

    def bt_pair(self, mac):
        return self._bt.start_pair(str(mac))

    def bt_job(self):
        return self._bt.job()

    def bt_cancel(self):
        self._bt.cancel()
        return _res(True, 'Cancelling…')

    # -- steam / games -------------------------------------------------------------------
    def steam_status(self):
        return self._steam.status()

    def steam_library(self, force=False):
        return self._steam.library(bool(force))

    def launch_steam(self):
        return self._steam.launch()

    def launch_game(self, appid):
        return self._steam.launch_game(appid)

    def open_controller_settings(self, appid=''):
        return self._steam.open_controller_settings(appid)

    def add_game(self, appid, name=''):
        try:
            self._settings.add_game(appid, name)
            return _res(True, 'Shortcut added.', settings=self._settings.get())
        except ValueError as e:
            return _res(False, str(e))

    def remove_game(self, appid):
        self._settings.remove_game(appid)
        return _res(True, 'Shortcut removed.', settings=self._settings.get())

    def set_profile(self, appid, deadzone, note=''):
        try:
            self._settings.set_profile(appid, deadzone, note)
            return _res(True, 'Profile saved.', settings=self._settings.get())
        except (ValueError, TypeError) as e:
            return _res(False, str(e))

    def remove_profile(self, appid):
        self._settings.remove_profile(appid)
        return _res(True, 'Profile removed.', settings=self._settings.get())

    # -- universal games ------------------------------------------------------------------
    def get_games(self, force=False):
        try:
            result = dict(self._library(bool(force)))
            result['running'] = self._watcher.running_game
            result['steam'] = self._steam.status()
            return result
        except OSError as e:
            return {'games': [], 'counts': {}, 'sources': [], 'running': None,
                    'error': 'Could not read the game libraries: %s' % e}

    def launch_any_game(self, game_id):
        game_id = str(game_id or '').strip()
        if game_id.startswith('steam:'):
            return self._steam.launch_game(game_id[6:])
        if game_id.isdigit():
            return self._steam.launch_game(game_id)
        library = self._library()['games']
        game = next((g for g in library if g['id'] == game_id), None)
        if game is None:
            return _res(False, 'That game is no longer in the library. Rescan and try again.')
        return self._games.launch(game)

    def add_custom_game(self, name, command):
        try:
            entry = self._settings.add_custom_game(name, command)
        except ValueError as e:
            return _res(False, str(e))
        except OSError as e:
            return _res(False, 'Could not save the game: %s' % e)
        self._games.invalidate()
        return _res(True, 'Added %s.' % entry['name'], settings=self._settings.get(), game=entry)

    def remove_custom_game(self, game_id):
        try:
            removed = self._settings.remove_custom_game(game_id)
        except ValueError as e:
            return _res(False, str(e))
        except OSError as e:
            return _res(False, 'Could not save the change: %s' % e)
        self._games.invalidate()
        return _res(True, 'Removed.' if removed else 'That game was not in the list.',
                    settings=self._settings.get())

    # -- keyboard / mouse mapping --------------------------------------------------------
    def get_mapping(self):
        cfg = self._settings.get()
        status = self._mapper.status()
        status['controller'] = self._monitor.connected
        return {
            'mapping': cfg['mapping'],
            'status': status,
            'presets': public_presets(),
            'available': not uinput_reason(),
            'reason': uinput_reason(),
            'buttons': [{'id': button, 'label': BUTTON_LABELS[button]} for button in MAP_BUTTONS],
            'stick_modes': [{'id': mode, 'label': STICK_MODE_LABELS[mode]} for mode in STICK_MODES],
            'script': str(PROJECT_ROOT / 'scripts' / 'enable-uinput.sh'),
        }

    def _mapping_response(self, message: str, ok: bool = True) -> dict:
        return _res(ok, message, settings=self._settings.get(), mapping=self.get_mapping())

    def save_mapping(self, partial):
        if not isinstance(partial, dict):
            return _res(False, 'Invalid mapping.')
        cfg = self._settings.get()['mapping']
        merged = dict(cfg)
        for key, value in partial.items():
            if key == 'bindings' and isinstance(value, dict):
                merged['bindings'] = dict(cfg['bindings'])
                merged['bindings'].update(value)
            elif key in cfg:
                merged[key] = value
        cleaned = clean_mapping(merged)
        try:
            self._settings.update({'mapping': cleaned})
        except OSError as e:
            return _res(False, 'Could not save the mapping: %s' % e)
        self._mapper.configure(cleaned)
        if cleaned['enabled']:
            res = self._mapper.enable(cleaned)
            if not res['ok']:
                return self._mapping_response(res['message'], ok=False)
        else:
            self._mapper.disable()
        self._sync_grab()
        return self._mapping_response('Mapping saved.')

    def apply_mapping_preset(self, preset):
        if preset not in [p['id'] for p in public_presets()]:
            return _res(False, 'Unknown preset.')
        cfg = self._settings.get()['mapping']
        base = preset_mapping(preset)
        merged = dict(cfg)
        merged.update({'preset': preset, 'bindings': base['bindings'],
                       'left_stick': base['left_stick'], 'right_stick': base['right_stick']})
        cleaned = clean_mapping(merged)
        try:
            self._settings.update({'mapping': cleaned})
        except OSError as e:
            return _res(False, 'Could not save the preset: %s' % e)
        self._mapper.configure(cleaned)
        if cleaned['enabled']:
            res = self._mapper.enable(cleaned)
            if not res['ok']:
                return self._mapping_response(res['message'], ok=False)
        self._sync_grab()
        return self._mapping_response('Applied the %s preset.' % preset)

    def set_mapping_enabled(self, on):
        cfg = self._settings.get()['mapping']
        if on:
            updated = dict(cfg)
            updated['enabled'] = True
            res = self._mapper.enable(updated)
            if not res['ok']:
                disabled = dict(updated)
                disabled['enabled'] = False
                try:
                    self._settings.update({'mapping': disabled})
                except OSError:
                    pass
                return self._mapping_response(res['message'], ok=False)
        else:
            updated = dict(cfg)
            updated['enabled'] = False
            self._mapper.disable()
        try:
            self._settings.update({'mapping': clean_mapping(updated)})
        except OSError as e:
            return _res(False, 'Could not save the mapping: %s' % e)
        self._sync_grab()
        return self._mapping_response('Keyboard and mouse mode is on.' if on
                                      else 'Keyboard and mouse mode is off.')

    def get_virtual_pad(self):
        status = self._vpad.status()
        status['grab'] = self._monitor.status().get('grab', {})
        status['desired'] = self._settings.get().get('virtual_pad_enabled', False)
        return {'status': status, 'enabled': self._vpad.enabled, 'available': status['available']}

    def set_virtual_pad(self, on):
        if on:
            res = self._vpad.enable()
            if not res['ok']:
                return _res(False, res['message'], virtual_pad=self._vpad.status())
        else:
            self._vpad.disable()
        try:
            self._settings.update({'virtual_pad_enabled': bool(on)})
        except OSError as e:
            return _res(False, 'Could not save the setting: %s' % e)
        self._sync_grab()
        return _res(True, 'The virtual Xbox pad is on.' if on else 'The virtual Xbox pad is off.',
                    virtual_pad=self._vpad.status(), settings=self._settings.get())

    # -- troubleshooting -------------------------------------------------------------------
    def system_check(self):
        cfg = self._settings.get()
        mapping = self._mapper.status()
        mapping['desired'] = cfg['mapping']['enabled']
        vpad = self._vpad.status()
        vpad['desired'] = cfg['virtual_pad_enabled']
        checks = run_checks(self._monitor.status(), self._bt.status(), self._steam.status(),
                            uinput={'available': not uinput_reason(), 'reason': uinput_reason()},
                            mapping=mapping, vpad=vpad)
        return {'checks': checks, 'report': report_text(checks)}
