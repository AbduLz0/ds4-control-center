#!/usr/bin/env bash
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export QTWEBENGINE_DISABLE_SANDBOX=1
export PYWEBVIEW_GUI=qt
export QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --no-sandbox"
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"; else PY="${PYTHON:-python3}"; fi
if ! "$PY" -c 'import webview, evdev' >/dev/null 2>&1; then
  echo "Dependencies are missing. Run ./install.sh first." >&2
  command -v notify-send >/dev/null && notify-send "DS4 Control Center" "Dependencies are missing. Run ./install.sh" || true
  exit 1
fi
exec "$PY" "$ROOT/app/main.py" "$@"
