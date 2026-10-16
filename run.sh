#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"; else PY="${PYTHON:-python3}"; fi
if ! "$PY" -c 'import webview, evdev' >/dev/null 2>&1; then
  echo "Dependencies are missing. Run ./install.sh first." >&2
  exit 1
fi
exec "$PY" "$ROOT/app/main.py" "$@"
