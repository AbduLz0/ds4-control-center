#!/usr/bin/env bash
set -euo pipefail
# Match the GTK/WebKit dependencies installed by install.sh. Allow an explicit
# renderer override for users who have installed an alternative backend.
export PYWEBVIEW_GUI="${PYWEBVIEW_GUI:-gtk}"
# Keep the existing WebKit graphics workarounds, while honoring user overrides.
export WEBKIT_DISABLE_COMPOSITING_MODE="${WEBKIT_DISABLE_COMPOSITING_MODE:-1}"
export WEBKIT_DISABLE_DMABUF_RENDERER="${WEBKIT_DISABLE_DMABUF_RENDERER:-1}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"; else PY="${PYTHON:-python3}"; fi
if ! "$PY" -c 'import webview, evdev' >/dev/null 2>&1; then
  echo "Dependencies are missing. Run ./install.sh first." >&2
  command -v notify-send >/dev/null && notify-send "DS4 Control Center" "Dependencies are missing. Run ./install.sh" || true
  exit 1
fi
exec "$PY" "$ROOT/app/main.py" "$@"
