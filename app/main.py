"""DS4 Control Center desktop entry point (PyWebView + GTK/WebKit)."""
from __future__ import annotations

import argparse
import fcntl
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))


def acquire_single_instance():
    """Hold an advisory lock for the lifetime of the process so a second copy exits cleanly."""
    base = os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir()
    fh = open(os.path.join(base, 'ds4-control-center.lock'), 'a+')
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def main() -> int:
    parser = argparse.ArgumentParser(description='DS4 Control Center')
    parser.add_argument('--minimized', action='store_true', help='start minimized')
    parser.add_argument('--debug', action='store_true', help='enable the WebKit inspector')
    args = parser.parse_args()

    if os.geteuid() == 0:
        print('Please do not run DS4 Control Center as root. It does not need it.', file=sys.stderr)
        return 1
    lock = acquire_single_instance()
    if lock is None:
        print('DS4 Control Center is already running.', file=sys.stderr)
        return 0

    import webview
    from ds4cc.bridge import Api

    api = Api()
    minimized = args.minimized or api.get_settings().get('start_minimized', False)
    webview.create_window('DS4 Control Center', str(ROOT / 'index.html'), js_api=api,
                          width=1360, height=900, min_size=(900, 640), background_color='#0b0e13',
                          minimized=bool(minimized))
    try:
        webview.start(debug=args.debug)
    finally:
        api._shutdown()
        lock.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
