"""Steam detection, launching, and installed-library discovery.

Nothing here injects input or touches game files. Launching goes through Steam's
documented steam:// URIs, and controller mapping stays with Steam Input.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

FLATPAK_ID = 'com.valvesoftware.Steam'
HOME = Path.home()
STEAM_ROOTS = [HOME / '.local/share/Steam', HOME / '.steam/steam', HOME / '.steam/root',
               HOME / '.var/app' / FLATPAK_ID / '.local/share/Steam', HOME / 'snap/steam/common/.local/share/Steam']
REGISTRY_FILES = [HOME / '.steam/registry.vdf', HOME / '.var/app' / FLATPAK_ID / '.steam/registry.vdf',
                  HOME / 'snap/steam/common/.steam/registry.vdf']
SKIP_NAMES = re.compile(r'^(Proton|Steam Linux Runtime|Steamworks Common|Steam Controller Configs)', re.I)
APPID_RE = re.compile(r'^[0-9]{1,12}$')


def _spawn(args) -> dict:
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {'ok': True, 'message': 'Requested.'}
    except OSError as e:
        return {'ok': False, 'message': str(e)}


class Steam:
    def __init__(self, roots=None):
        self._roots = roots if roots is not None else STEAM_ROOTS
        self._lib_cache = (0.0, [])

    def status(self) -> dict:
        path = shutil.which('steam')
        kind = 'native' if path else None
        if not path:
            for p in ('/usr/games/steam', '/usr/bin/steam'):
                if os.path.exists(p):
                    path, kind = p, 'native'
                    break
        if not path and shutil.which('flatpak'):
            try:
                rc = subprocess.run(['flatpak', 'info', FLATPAK_ID], capture_output=True, timeout=4).returncode
                if rc == 0:
                    path, kind = 'flatpak:' + FLATPAK_ID, 'flatpak'
            except (OSError, subprocess.TimeoutExpired):
                pass
        running = False
        if shutil.which('pgrep'):
            running = subprocess.run(['pgrep', '-x', 'steam'], capture_output=True).returncode == 0
        return {'installed': bool(path), 'running': running, 'path': path, 'kind': kind}

    def _command(self, uri: str = ''):
        st = self.status()
        if not st['installed']:
            return None
        base = ['flatpak', 'run', FLATPAK_ID] if st['kind'] == 'flatpak' else [st['path']]
        return base + ([uri] if uri else [])

    def launch(self) -> dict:
        cmd = self._command()
        if not cmd:
            return {'ok': False, 'message': 'Steam was not detected. Install it from your software center or steampowered.com.'}
        res = _spawn(cmd)
        res['message'] = 'Starting Steam…' if res['ok'] else res['message']
        return res

    def launch_game(self, appid: str) -> dict:
        appid = str(appid or '').strip()
        if not APPID_RE.match(appid):
            return {'ok': False, 'message': 'Enter a numeric Steam App ID.'}
        cmd = self._command('steam://rungameid/' + appid)
        if not cmd:
            return {'ok': False, 'message': 'Steam was not detected.'}
        res = _spawn(cmd)
        res['message'] = 'Asked Steam to launch app %s.' % appid if res['ok'] else res['message']
        return res

    def open_controller_settings(self, appid: str = '') -> dict:
        """steam://controllerconfig/<id> opens Steam Input for a game; steam://open/settings opens Steam settings."""
        appid = str(appid or '').strip()
        if appid and not APPID_RE.match(appid):
            return {'ok': False, 'message': 'Invalid App ID.'}
        cmd = self._command('steam://controllerconfig/' + appid if appid else 'steam://open/settings')
        if not cmd:
            return {'ok': False, 'message': 'Steam was not detected.'}
        res = _spawn(cmd)
        res['message'] = ('Opening Steam Input for this game…' if appid else
                          'Opening Steam settings. Choose Controller in the sidebar.') if res['ok'] else res['message']
        return res

    # -- running game --------------------------------------------------------------
    def running_appid(self, registries=None):
        """App ID of the game Steam says is running, or None. Reads Steam's own registry.vdf (read-only)."""
        for reg in registries if registries is not None else REGISTRY_FILES:
            try:
                text = Path(reg).read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            m = re.search(r'"RunningAppID"\s+"(\d+)"', text)
            if m:
                return m.group(1) if m.group(1) != '0' else None
        return None

    # -- library -----------------------------------------------------------------
    def _steamapps_dirs(self) -> list:
        dirs, seen = [], set()
        for root in self._roots:
            try:
                real = root.resolve()
            except OSError:
                continue
            apps = real / 'steamapps'
            if apps.is_dir() and apps not in seen:
                seen.add(apps)
                dirs.append((real, apps))
            vdf = apps / 'libraryfolders.vdf'
            try:
                for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding='utf-8', errors='replace')):
                    extra = Path(m.group(1)) / 'steamapps'
                    if extra.is_dir() and extra not in seen:
                        seen.add(extra)
                        dirs.append((real, extra))
            except OSError:
                pass
        return dirs

    @staticmethod
    def _cover(root: Path, appid: str):
        cache = root / 'appcache' / 'librarycache'
        for pattern in ('%s_library_600x900.jpg' % appid, '%s/library_600x900.jpg' % appid,
                        '%s/*/library_600x900.jpg' % appid, '%s_header.jpg' % appid, '%s/header.jpg' % appid,
                        '%s/*/header.jpg' % appid):
            try:
                hit = next(cache.glob(pattern), None)
            except OSError:
                hit = None
            if hit:
                return hit.as_uri()
        return None

    def library(self, force: bool = False) -> list:
        ts, cached = self._lib_cache
        if not force and time.time() - ts < 30:
            return cached
        games, seen = [], set()
        for root, apps in self._steamapps_dirs():
            try:
                manifests = sorted(apps.glob('appmanifest_*.acf'))
            except OSError:
                continue
            for mf in manifests:
                try:
                    text = mf.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                aid = re.search(r'"appid"\s+"(\d+)"', text)
                name = re.search(r'"name"\s+"([^"]+)"', text)
                if not aid or not name or aid.group(1) in seen or SKIP_NAMES.match(name.group(1)):
                    continue
                seen.add(aid.group(1))
                games.append({'appid': aid.group(1), 'name': name.group(1), 'cover': self._cover(root, aid.group(1))})
        games.sort(key=lambda g: g['name'].lower())
        self._lib_cache = (time.time(), games)
        return games
