#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then echo 'python3 is required.' >&2; exit 1; fi
if ! command -v apt-get >/dev/null 2>&1; then echo 'This installer currently targets Ubuntu/Zorin/Debian-based systems.' >&2; exit 1; fi
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev build-essential pkg-config libgtk-3-dev libwebkit2gtk-4.1-dev libayatana-appindicator3-dev gir1.2-gtk-3.0 gir1.2-webkit2-4.1 bluez
python3 -m venv --system-site-packages "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install --upgrade pip wheel
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
chmod +x "$ROOT/run.sh" "$ROOT/scripts/diagnose.sh"
echo
echo 'Install complete. Start with: ./run.sh'
echo 'If controller access is denied, run: ./scripts/diagnose.sh'
