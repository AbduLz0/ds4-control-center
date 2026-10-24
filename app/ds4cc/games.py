"""Universal game discovery, launching and running-game detection.

Steam is supported, but it is not the only way to play. This module also reads
Lutris databases, standard ``.desktop`` entries (which covers Heroic, Bottles,
itch, hand-made launchers and most cracked-game shortcuts) and games the user
adds by hand with a command such as ``wine ~/Games/foo/foo.exe``.

Launching never uses a shell: desktop entries go through ``gio launch`` and
manual commands are split with :mod:`shlex`, so a game name cannot turn into a
shell command. Running-game detection is read-only: it looks at ``/proc`` and
matches executable names, which is enough to switch this app's profiles without
injecting anything into a game.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

HOME = Path.home()
DESKTOP_DIRS = [
    HOME / '.local' / 'share' / 'applications',
    Path('/usr/local/share/applications'),
    Path('/usr/share/applications'),
    Path('/var/lib/flatpak/exports/share/applications'),
    HOME / '.local' / 'share' / 'flatpak' / 'exports' / 'share' / 'applications',
    Path('/var/lib/snapd/desktop/applications'),
]
LUTRIS_DBS = [
    HOME / '.local' / 'share' / 'lutris' / 'pga.db',
    HOME / '.var' / 'app' / 'net.lutris.Lutris' / 'data' / 'lutris' / 'pga.db',
]
COVER_DIRS = [
    HOME / '.local' / 'share' / 'lutris' / 'coverart',
    HOME / '.var' / 'app' / 'net.lutris.Lutris' / 'data' / 'lutris' / 'coverart',
]
PLACEHOLDER_RE = re.compile(r'%[fFuUdDnNickvm]')
ASSIGNMENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
GENERIC_BINARIES = {
    'env', 'sh', 'bash', 'dash', 'zsh', 'python', 'python3', 'python2', 'perl', 'ruby', 'node',
    'flatpak', 'steam', 'wine', 'wine64', 'wine-preloader', 'proton', 'gamescope', 'gamemoderun',
    'mangohud', 'lutris', 'heroic', 'bottles', 'xdg-open', 'gio', 'gtk-launch', 'mono', 'dotnet',
    'sudo', 'pkexec', 'dbus-run-session', 'systemd-run',
}
GENERIC_PROCESS_NAMES = GENERIC_BINARIES | {
    'game.exe', 'start.exe', 'launcher.exe', 'launcher', 'game', 'start', 'run', 'run.sh',
    'steamwebhelper', 'steamwebhelper.sh', 'pressure-vessel', 'pv-bwrap', 'reaper',
}

SOURCE_LABELS = {'steam': 'Steam', 'lutris': 'Lutris', 'desktop': 'Desktop', 'manual': 'Added'}
BROAD_PATHS = {str(HOME), '/home', '/usr', '/usr/bin', '/usr/local', '/opt', '/tmp', '/var', '/mnt', '/media', '/'}
_FLATPAK_CACHE = {}


def _flatpak_installed(app_id: str) -> bool:
    """Small cached check so a missing Flatpak app is reported instead of failing later."""
    if app_id in _FLATPAK_CACHE:
        return _FLATPAK_CACHE[app_id]
    try:
        result = subprocess.run(['flatpak', 'info', app_id], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=4)
        installed = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        installed = False
    _FLATPAK_CACHE[app_id] = installed
    return installed


def normalize_name(name: str) -> str:
    """A forgiving key for de-duplicating the same game from several sources."""
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())


def _clean_name(name: str) -> str:
    name = re.sub(r'\s+', ' ', str(name or '')).strip()
    return name[:120]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def _file_uri(path: Optional[Path]) -> Optional[str]:
    try:
        if path and path.is_file():
            return path.as_uri()
    except (OSError, ValueError):
        pass
    return None


# --------------------------------------------------------------------------
# .desktop entries
# --------------------------------------------------------------------------
def _parse_desktop(path: Path) -> Optional[dict]:
    text = _read(path)
    if not text:
        return None
    fields = {}
    group = ''
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[') and line.endswith(']'):
            group = line[1:-1]
            if group != 'Desktop Entry' and fields:
                break
            continue
        if group != 'Desktop Entry' or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key.endswith(']'):  # localized key such as Name[en_GB]
            continue
        fields[key] = value.strip()
    if fields.get('Type', 'Application') != 'Application':
        return None
    if fields.get('NoDisplay', '').lower() == 'true' or fields.get('Hidden', '').lower() == 'true':
        return None
    name = _clean_name(fields.get('Name', ''))
    if not name:
        return None
    categories = {c.strip().lower() for c in fields.get('Categories', '').split(';') if c.strip()}
    if 'game' not in categories:
        return None
    exec_line = PLACEHOLDER_RE.sub('', fields.get('Exec', '').replace('%%', '\x00')).replace('\x00', '%').strip()
    tokens = desktop_tokens(exec_line)
    binary = exec_binary(tokens)
    path_text = str(path)
    if 'ds4-control-center' in path.name.lower() or 'ds4 control center' in name.lower():
        return None
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', path.stem).strip('-')[:64] or 'game'
    return {
        'id': 'desktop:' + stem,
        'name': name,
        'source': 'desktop',
        'cover': None,
        'exec': exec_line,
        'path': path_text,
        'binary': binary,
        'categories': sorted(categories),
        'comment': _clean_name(fields.get('Comment', '')),
    }


def desktop_tokens(exec_line: str) -> List[str]:
    try:
        tokens = shlex.split(exec_line, posix=True)
    except ValueError:
        return []
    tokens = [token for token in tokens if token and not PLACEHOLDER_RE.fullmatch(token)]
    while tokens and ASSIGNMENT_RE.match(tokens[0]):
        tokens = tokens[1:]
    return tokens


def exec_binary(tokens: List[str]) -> str:
    """The first meaningful executable in an Exec line, for running detection."""
    for token in tokens:
        base = os.path.basename(token).lower()
        if ASSIGNMENT_RE.match(token) or token.startswith('-'):
            continue
        if base in GENERIC_BINARIES or base in ('run', 'launch', 'play'):
            continue
        return token
    return ''


def scan_desktops(dirs: Optional[List[Path]] = None) -> List[dict]:
    entries, seen_ids = [], set()
    for directory in dirs if dirs is not None else DESKTOP_DIRS:
        try:
            paths = sorted(directory.rglob('*.desktop'))
        except OSError:
            continue
        for path in paths[:800]:
            entry = _parse_desktop(path)
            if not entry:
                continue
            base_id = entry['id']
            suffix = 2
            while entry['id'] in seen_ids:
                entry['id'] = '%s-%d' % (base_id, suffix)
                suffix += 1
            seen_ids.add(entry['id'])
            entries.append(entry)
    return entries


# --------------------------------------------------------------------------
# Lutris
# --------------------------------------------------------------------------
def _lutris_cover(game_id, slug: str) -> Optional[str]:
    names = []
    if slug:
        names += ['%s.jpg' % slug, '%s.png' % slug, '%s.webp' % slug]
    names += ['%s.jpg' % game_id, '%s.png' % game_id]
    for directory in COVER_DIRS:
        for name in names:
            uri = _file_uri(directory / name)
            if uri:
                return uri
    return None


def scan_lutris(dbs: Optional[List[Path]] = None) -> List[dict]:
    games, seen = [], set()
    for db in dbs if dbs is not None else LUTRIS_DBS:
        if not db.is_file():
            continue
        try:
            connection = sqlite3.connect('file:%s?mode=ro' % quote(str(db)), uri=True, timeout=2)
            connection.row_factory = sqlite3.Row
            columns = {row[1] for row in connection.execute('PRAGMA table_info(games)')}
            wanted = ['id', 'name', 'slug', 'runner', 'directory', 'configpath']
            if 'installed' in columns:
                wanted.append('installed')
            rows = connection.execute('SELECT %s FROM games' % ', '.join(wanted)).fetchall()
            connection.close()
        except (sqlite3.Error, OSError, ValueError):
            continue
        for row in rows:
            try:
                game_id = int(row['id'])
            except (TypeError, ValueError):
                continue
            if 'installed' in row.keys() and row['installed'] is not None:
                try:
                    if int(row['installed']) == 0:
                        continue
                except (TypeError, ValueError):
                    pass
            name = _clean_name(row['name'] or row['slug'] or '')
            if not name or game_id in seen:
                continue
            seen.add(game_id)
            slug = str(row['slug'] or '')
            games.append({
                'id': 'lutris:%s' % game_id,
                'lutris_id': game_id,
                'name': name,
                'source': 'lutris',
                'cover': _lutris_cover(game_id, slug),
                'slug': slug,
                'runner': str(row['runner'] or ''),
                'directory': str(row['directory'] or ''),
                'configpath': str(row['configpath'] or ''),
            })
    return games


# --------------------------------------------------------------------------
# library and launching
# --------------------------------------------------------------------------
class UniversalGames:
    def __init__(self, steam, log=None):
        self._steam = steam
        self._log = log
        self._lock = threading.RLock()
        self._cache: Optional[tuple] = None
        self._cache_time = 0.0
        self._cache_key = None
        self._procs = ([], 0.0)
        self._lutris_cache = ([], 0.0)

    def invalidate(self):
        with self._lock:
            self._cache = None
            self._cache_time = 0.0

    # -- library ----------------------------------------------------------
    def library(self, steam_games: List[dict], custom_games: List[dict],
                desktop: bool = True, lutris: bool = True,
                force: bool = False) -> dict:
        # The parameter names are deliberately not scan_desktop/scan_lutris:
        # those would shadow the module-level scan functions used below.
        key = (desktop, lutris, tuple((g.get('id'), g.get('command')) for g in custom_games))
        with self._lock:
            age = time.time() - self._cache_time
            if not force and self._cache is not None and self._cache_key == key and age < 30:
                return self._cache

        steam_entries = []
        for game in steam_games or []:
            appid = str(game.get('appid', '')).strip()
            name = _clean_name(game.get('name', ''))
            if not appid or not name:
                continue
            steam_entries.append({
                'id': 'steam:' + appid, 'appid': appid, 'name': name, 'source': 'steam',
                'cover': game.get('cover'),
            })

        lutris_entries = []
        if lutris:
            now = time.time()
            with self._lock:
                cached, at = self._lutris_cache
            if force or not cached or now - at > 60:
                cached = scan_lutris()
                with self._lock:
                    self._lutris_cache = (cached, now)
            lutris_entries = list(cached)

        desktop_entries = scan_desktops() if desktop else []

        manual_entries = []
        for game in custom_games or []:
            game_id = str(game.get('id', ''))
            name = _clean_name(game.get('name', ''))
            command = str(game.get('command', '')).strip()
            if game_id.startswith('manual:') and name and command:
                manual_entries.append({
                    'id': game_id, 'name': name, 'source': 'manual', 'cover': None,
                    'command': command,
                })

        priority = {'manual': 0, 'steam': 1, 'lutris': 2, 'desktop': 3}
        combined = manual_entries + steam_entries + lutris_entries + desktop_entries
        combined.sort(key=lambda g: (priority.get(g['source'], 9), g['name'].lower()))
        games, seen_names = [], set()
        for game in combined:
            key_name = normalize_name(game['name'])
            if not key_name or key_name in seen_names:
                continue
            seen_names.add(key_name)
            games.append(game)
        games.sort(key=lambda g: g['name'].lower())

        counts = {}
        for game in games:
            counts[game['source']] = counts.get(game['source'], 0) + 1
        sources = [{'id': source, 'label': SOURCE_LABELS[source], 'count': counts.get(source, 0)}
                   for source in ('steam', 'lutris', 'desktop', 'manual')]
        result = {
            'games': games,
            'counts': counts,
            'sources': sources,
            'desktop_enabled': bool(desktop),
            'lutris_enabled': bool(lutris),
            'scanned_at': time.time(),
        }
        with self._lock:
            self._cache = result
            self._cache_time = time.time()
            self._cache_key = key
        return result

    # -- launching --------------------------------------------------------
    def launch(self, game: dict) -> dict:
        if not isinstance(game, dict):
            return {'ok': False, 'message': 'Choose a game first.'}
        source = game.get('source')
        name = game.get('name') or 'the game'
        if source == 'steam':
            return self._steam.launch_game(str(game.get('appid', '')))
        if source == 'lutris':
            return self._launch_lutris(game)
        if source == 'desktop':
            return self._launch_desktop(game)
        if source == 'manual':
            return self._launch_command(game)
        return {'ok': False, 'message': 'This game entry has an unknown source.'}

    def _launch_lutris(self, game: dict) -> dict:
        lutris = shutil.which('lutris')
        if lutris:
            command = [lutris, 'lutris:rungameid/%s' % game.get('lutris_id')]
        elif shutil.which('flatpak') and _flatpak_installed('net.lutris.Lutris'):
            command = ['flatpak', 'run', 'net.lutris.Lutris', 'lutris:rungameid/%s' % game.get('lutris_id')]
            if self._log:
                self._log.add('system', 'Launching %s through the Flatpak Lutris build.' % game.get('name'))
        else:
            return {'ok': False, 'message': 'Lutris is listed in its database but the lutris command is not installed.'}
        return self._spawn(command, 'Asked Lutris to launch %s.' % game.get('name'))

    def _launch_desktop(self, game: dict) -> dict:
        path = Path(str(game.get('path', '')))
        if not path.is_file():
            return {'ok': False, 'message': 'That desktop shortcut no longer exists. Rescan the library.'}
        if shutil.which('gio'):
            return self._spawn(['gio', 'launch', str(path)], 'Asked the desktop to launch %s.' % game.get('name'))
        if shutil.which('gtk-launch'):
            return self._spawn(['gtk-launch', path.stem], 'Asked the desktop to launch %s.' % game.get('name'))
        return {'ok': False, 'message': 'Neither gio nor gtk-launch is available, so this desktop shortcut cannot be started.'}

    def _launch_command(self, game: dict) -> dict:
        command = str(game.get('command', '')).strip()
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return {'ok': False, 'message': 'The saved command has unmatched quotes. Edit it and try again.'}
        if not tokens:
            return {'ok': False, 'message': 'The saved command is empty.'}
        if os.path.basename(tokens[0]) in ('sudo', 'pkexec'):
            return {'ok': False, 'message': 'Do not launch games with sudo. This app never needs root.'}
        tokens = [os.path.expanduser(token) if token.startswith('~') else token for token in tokens]
        first = tokens[0]
        if first.endswith(('.exe', '.EXE')):
            return {'ok': False, 'message': 'For a Windows game, put wine or your Proton command before the .exe path.'}
        if os.path.sep in first and not os.path.exists(first):
            return {'ok': False, 'message': 'That program was not found: %s' % first}
        for token in tokens[1:]:
            if token.startswith('/') and token.lower().endswith(('.exe', '.sh', '.appimage', '.x86_64')):
                if not os.path.exists(token):
                    return {'ok': False, 'message': 'That game file was not found: %s' % token}
        return self._spawn(tokens, 'Asked the system to launch %s.' % game.get('name'))

    @staticmethod
    def _spawn(command: List[str], message: str) -> dict:
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return {'ok': True, 'message': message}
        except OSError as exc:
            return {'ok': False, 'message': 'Could not launch it: %s' % exc}

    # -- running game -----------------------------------------------------
    def processes(self, force: bool = False) -> List[List[str]]:
        now = time.time()
        with self._lock:
            cached, at = self._procs
            if not force and cached and now - at < 2.5:
                return cached
        found = []
        own = str(os.getpid())
        try:
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit() or entry.name == own:
                    continue
                try:
                    raw = (entry / 'cmdline').read_bytes()
                except OSError:
                    continue
                if not raw:
                    continue
                args = [part.decode('utf-8', 'replace') for part in raw.split(b'\0') if part]
                if args:
                    found.append(args)
        except OSError:
            pass
        with self._lock:
            self._procs = (found, now)
        return found

    def running(self, steam_appid: Optional[str], library: List[dict],
                processes: Optional[List[List[str]]] = None) -> Optional[dict]:
        steam_appid = str(steam_appid or '').strip()
        if steam_appid:
            for game in library:
                if game.get('source') == 'steam' and game.get('appid') == steam_appid:
                    return {'id': game['id'], 'name': game['name'], 'source': 'steam'}
            return {'id': 'steam:' + steam_appid, 'name': 'Steam app ' + steam_appid, 'source': 'steam'}
        procs = processes if processes is not None else self.processes()
        if not procs:
            return None
        basenames, args_set = set(), set()
        for args in procs:
            for arg in args:
                if not arg:
                    continue
                lower = arg.lower()
                args_set.add(lower)
                base = os.path.basename(lower)
                if base:
                    basenames.add(base)
        for game in sorted(library, key=lambda g: {'manual': 0, 'lutris': 1, 'desktop': 2}.get(g.get('source'), 9)):
            if game.get('source') == 'steam':
                continue
            for hint in self._hints(game):
                lower = hint.lower()
                if len(lower) < 4:
                    continue
                base = os.path.basename(lower)
                path_match = len(lower) >= 6 and lower in args_set
                if not path_match and '/' in lower and len(lower) >= 8 and lower not in BROAD_PATHS:
                    prefix = lower.rstrip('/') + '/'
                    path_match = any(arg.startswith(prefix) for arg in args_set)
                if path_match or (base and len(base) >= 4 and base in basenames
                                  and base not in GENERIC_PROCESS_NAMES):
                    return {'id': game['id'], 'name': game['name'], 'source': game['source']}
        return None

    @staticmethod
    def _hints(game: dict) -> List[str]:
        hints = []
        if game.get('source') == 'manual':
            try:
                tokens = shlex.split(str(game.get('command', '')), posix=True)
            except ValueError:
                tokens = []
            tokens = [os.path.expanduser(token) if token.startswith('~') else token for token in tokens]
            hints += [token for token in tokens if len(token) >= 4]
            if tokens:
                hints.append(os.path.basename(tokens[0]))
        elif game.get('source') == 'lutris':
            for value in (game.get('directory'), game.get('slug'), game.get('configpath')):
                if value:
                    text = str(value)
                    if text not in BROAD_PATHS and len(text) >= 6:
                        hints.append(text)
                    hints.append(os.path.basename(text))
        elif game.get('source') == 'desktop':
            if game.get('binary'):
                hints.append(str(game['binary']))
            hints += [token for token in desktop_tokens(str(game.get('exec', ''))) if len(token) >= 4]
        cleaned = []
        for hint in hints:
            hint = hint.strip().strip('"\'')
            if hint.startswith('-'):
                continue  # command-line flags are not evidence a game is running
            if hint and hint not in cleaned:
                cleaned.append(hint)
        return cleaned


def custom_game_id(name: str, command: str) -> str:
    digest = hashlib.sha1(('%s\0%s' % (name, command)).encode('utf-8', 'replace')).hexdigest()[:10]
    return 'manual:' + digest


def validate_command(command: str) -> str:
    command = str(command or '').strip()
    if not command:
        raise ValueError('Enter the command that starts the game.')
    if len(command) > 500:
        raise ValueError('The command is too long (500 characters maximum).')
    if re.search(r'[\x00-\x1f]', command):
        raise ValueError('The command contains control characters.')
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        raise ValueError('The command has unmatched quotes.')
    if not tokens:
        raise ValueError('Enter the command that starts the game.')
    if os.path.basename(tokens[0]) in ('sudo', 'pkexec'):
        raise ValueError('Do not launch games with sudo or pkexec.')
    return command
