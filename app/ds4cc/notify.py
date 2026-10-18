"""Desktop notifications through notify-send (no extra Python dependency)."""
from __future__ import annotations

import shutil
import subprocess


def available() -> bool:
    return shutil.which('notify-send') is not None


def send(title: str, body: str = '', urgency: str = 'normal', icon: str = 'input-gaming') -> bool:
    """Fire-and-forget. Returns False when notify-send is missing or cannot start.
    Arguments are passed as a list, never through a shell."""
    exe = shutil.which('notify-send')
    if not exe:
        return False
    if urgency not in ('low', 'normal', 'critical'):
        urgency = 'normal'
    try:
        subprocess.Popen([exe, '--app-name=DS4 Control Center', '--urgency=' + urgency, '--icon=' + icon,
                          '--', str(title)[:80], str(body)[:200]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False
