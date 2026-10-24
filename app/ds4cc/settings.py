"""Persistent settings, per-game profiles and user-level autostart."""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from pathlib import Path

from .games import custom_game_id, validate_command
from .input_map import clean_mapping, default_mapping

CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'ds4-control-center'
SETTINGS_FILE = CONFIG_DIR / 'settings.json'
AUTOSTART_FILE = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'autostart' / 'ds4-control-center.desktop'
PROJECT_ROOT = Path(__file__).resolve().parents[2]

THEMES = ('midnight', 'graphite', 'aurora', 'plasma')
PAGES = ('dashboard', 'diagnostics', 'bluetooth', 'gaming', 'mapping', 'settings', 'help')

DEFAULTS = {
    'theme': 'midnight',
    'animations': True,
    'refresh_ms': 50,
    'deadzone': 8,
    'graph_seconds': 20,
    'trail_length': 60,
    'auto_start': False,
    'start_minimized': False,
    'start_page': 'dashboard',
    'auto_reconnect': True,
    'reconnect_attempts': 3,
    'diagnostic_logging': True,
    'notifications': True,
    'low_battery_percent': 20,
    'idle_disconnect_minutes': 0,
    'auto_profile': True,
    'lightbar_color': '',
    'games': [],
    'profiles': {},
    'last_controller': None,
    'custom_games': [],
    'mapping': default_mapping(),
    'virtual_pad_enabled': False,
    'scan_desktop_games': True,
    'scan_lutris_games': True,
}


def _int(lo, hi):
    return lambda v: max(lo, min(hi, int(v)))


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError('expected true or false')
    return v


def _choice(*options):
    def check(v):
        if v not in options:
            raise ValueError('invalid choice')
        return v
    return check


def _hexcolor(v):
    if v == '' or v is None:
        return ''
    if not isinstance(v, str) or not re.match(r'^#[0-9a-fA-F]{6}$', v):
        raise ValueError('invalid colour')
    return v.lower()


def _mapping(v):
    if not isinstance(v, dict):
        raise ValueError('mapping must be an object')
    return clean_mapping(v)


SCHEMA = {
    'theme': _choice(*THEMES),
    'animations': _bool,
    'refresh_ms': _int(30, 500),
    'deadzone': _int(0, 40),
    'graph_seconds': _int(5, 120),
    'trail_length': _int(0, 200),
    'auto_start': _bool,
    'start_minimized': _bool,
    'start_page': _choice(*PAGES),
    'auto_reconnect': _bool,
    'reconnect_attempts': _int(1, 10),
    'diagnostic_logging': _bool,
    'notifications': _bool,
    'low_battery_percent': _choice(0, 10, 15, 20, 30),
    'idle_disconnect_minutes': _choice(0, 5, 10, 15, 30, 60),
    'auto_profile': _bool,
    'lightbar_color': _hexcolor,
    'mapping': _mapping,
    'virtual_pad_enabled': _bool,
    'scan_desktop_games': _bool,
    'scan_lutris_games': _bool,
}

APPID_RE = re.compile(r'^[0-9]{1,12}$')
# Steam profiles keep their plain App ID. Other sources use their library ID.
GAME_ID_RE = re.compile(r'^(?:[0-9]{1,12}|steam:[0-9]{1,12}|'
                        r'(?:lutris|desktop|manual):[A-Za-z0-9._-]{1,120})$')


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_FILE):
        self._path = path
        self._lock = threading.RLock()
        self._data = self._load()

    # -- persistence -----------------------------------------------------
    def _load(self) -> dict:
        data = copy.deepcopy(DEFAULTS)
        try:
            raw = json.loads(self._path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise ValueError('settings root must be an object')
        except FileNotFoundError:
            return data
        except (OSError, ValueError):
            try:  # keep the unreadable file for inspection instead of destroying it
                self._path.replace(self._path.with_suffix('.corrupt'))
            except OSError:
                pass
            return data
        for key, check in SCHEMA.items():
            if key in raw:
                try:
                    data[key] = check(raw[key])
                except (ValueError, TypeError, OverflowError):
                    pass
        data['games'] = self._clean_games(raw.get('games'))
        data['profiles'] = self._clean_profiles(raw.get('profiles'))
        data['custom_games'] = self._clean_custom_games(raw.get('custom_games'))
        data['mapping'] = clean_mapping(raw.get('mapping')) if isinstance(raw.get('mapping'), dict) else default_mapping()
        lc = raw.get('last_controller')
        data['last_controller'] = lc if isinstance(lc, dict) else None
        return data

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self._data, indent=2), encoding='utf-8')
        os.chmod(tmp, 0o600)
        tmp.replace(self._path)

    # -- cleaning helpers --------------------------------------------------
    @staticmethod
    def _clean_games(raw) -> list:
        out, seen = [], set()
        for g in raw if isinstance(raw, list) else []:
            if not isinstance(g, dict):
                continue
            appid = str(g.get('appid', ''))
            if APPID_RE.fullmatch(appid) and appid not in seen:
                seen.add(appid)
                out.append({'appid': appid, 'name': str(g.get('name') or 'Steam game')[:80]})
        return out

    @staticmethod
    def _clean_profiles(raw) -> dict:
        out = {}
        for game_id, p in (raw or {}).items() if isinstance(raw, dict) else []:
            key = str(game_id).strip()
            if key.startswith('steam:'):
                key = key[6:]
            if GAME_ID_RE.fullmatch(key) and isinstance(p, dict):
                dz = p.get('deadzone')
                try:
                    dz = None if dz is None else _int(0, 40)(dz)
                except (ValueError, TypeError, OverflowError):
                    continue  # one malformed profile must not prevent startup
                out[key] = {'deadzone': dz, 'note': str(p.get('note') or '')[:200]}
        return out

    @staticmethod
    def _clean_custom_games(raw) -> list:
        out, seen = [], set()
        for game in raw if isinstance(raw, list) else []:
            if not isinstance(game, dict):
                continue
            name = str(game.get('name') or '').strip()[:80]
            try:
                command = validate_command(game.get('command'))
            except ValueError:
                continue
            if not name:
                continue
            game_id = str(game.get('id') or '')
            if not re.fullmatch(r'manual:[A-Za-z0-9._-]{1,120}', game_id):
                game_id = custom_game_id(name, command)
            if game_id in seen:
                continue
            seen.add(game_id)
            out.append({'id': game_id, 'name': name, 'command': command})
        return out

    # -- public API ------------------------------------------------------------
    def get(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def update(self, partial: dict):
        """Apply validated changes. Returns (settings, set_of_changed_keys)."""
        changed = set()
        with self._lock:
            for key, val in (partial or {}).items():
                check = SCHEMA.get(key)
                if not check:
                    continue
                try:
                    clean = check(val)
                except (ValueError, TypeError, OverflowError):
                    continue
                if self._data.get(key) != clean:
                    self._data[key] = clean
                    changed.add(key)
            if changed:
                self._save()
        if 'auto_start' in changed:
            set_autostart(self._data['auto_start'])
        return self.get(), changed

    def reset(self) -> dict:
        with self._lock:
            keep = copy.deepcopy({k: self._data[k] for k in ('games', 'profiles', 'custom_games', 'last_controller')})
            self._data = copy.deepcopy(DEFAULTS)
            self._data.update(keep)  # resetting preferences must not delete the user's shortcuts
            self._save()
        set_autostart(False)
        return self.get()

    def add_game(self, appid: str, name: str):
        appid = str(appid or '').strip()
        if not APPID_RE.match(appid):
            raise ValueError('Enter a numeric Steam App ID.')
        with self._lock:
            games = [g for g in self._data['games'] if g['appid'] != appid]
            games.append({'appid': appid, 'name': (name or '').strip()[:80] or 'Steam game ' + appid})
            self._data['games'] = games
            self._save()

    def remove_game(self, appid: str):
        with self._lock:
            self._data['games'] = [g for g in self._data['games'] if g['appid'] != str(appid)]
            self._data['profiles'].pop(str(appid), None)
            self._save()

    @staticmethod
    def _profile_key(game_id) -> str:
        key = str(game_id or '').strip()
        if key.startswith('steam:'):
            key = key[6:]
        if not GAME_ID_RE.fullmatch(key):
            raise ValueError('Invalid game ID.')
        return key

    def set_profile(self, appid: str, deadzone, note: str):
        key = self._profile_key(appid)
        try:
            dz = None if deadzone is None else max(0, min(40, int(deadzone)))
        except (TypeError, ValueError, OverflowError):
            raise ValueError('Invalid dead zone.')
        with self._lock:
            self._data['profiles'][key] = {'deadzone': dz, 'note': str(note or '')[:200]}
            self._save()

    def remove_profile(self, appid: str):
        key = self._profile_key(appid)
        with self._lock:
            self._data['profiles'].pop(key, None)
            self._save()

    # -- games the user adds by hand -------------------------------------
    def add_custom_game(self, name: str, command: str) -> dict:
        name = str(name or '').strip()[:80]
        if not name:
            raise ValueError('Give the game a name.')
        command = validate_command(command)
        game_id = custom_game_id(name, command)
        entry = {'id': game_id, 'name': name, 'command': command}
        with self._lock:
            self._data['custom_games'] = [g for g in self._data['custom_games'] if g['id'] != game_id]
            self._data['custom_games'].append(entry)
            self._save()
        return entry

    def remove_custom_game(self, game_id: str) -> bool:
        game_id = str(game_id or '')
        if not re.fullmatch(r'manual:[A-Za-z0-9._-]{1,120}', game_id):
            raise ValueError('Invalid game ID.')
        with self._lock:
            before = len(self._data['custom_games'])
            self._data['custom_games'] = [g for g in self._data['custom_games'] if g['id'] != game_id]
            removed = len(self._data['custom_games']) != before
            profile_was_there = self._data['profiles'].pop(game_id, None) is not None
            if removed or profile_was_there:
                self._save()
        return removed

    def remember_controller(self, info: dict):
        with self._lock:
            self._data['last_controller'] = info
            self._save()


def set_autostart(enabled: bool, target: Path = AUTOSTART_FILE):
    """User-level autostart only (no root, no system-wide change)."""
    if enabled:
        target.parent.mkdir(parents=True, exist_ok=True)
        run = PROJECT_ROOT / 'run.sh'
        content = ('[Desktop Entry]\nType=Application\nName=DS4 Control Center\n'
                   'Comment=DualShock 4 controller dashboard\n'
                   'Exec="%s"\nTerminal=false\nX-GNOME-Autostart-enabled=true\n' % run)
        tmp = target.with_suffix('.tmp')
        tmp.write_text(content, encoding='utf-8')
        os.chmod(tmp, 0o644)
        tmp.replace(target)
    else:
        try:
            target.unlink()
        except FileNotFoundError:
            pass


def now() -> float:
    return time.time()
