#!/usr/bin/env bash
# Installs DS4 Control Center dependencies. Uses sudo only for APT, and only after you confirm.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ASSUME_YES=0; SKIP_APT=0
for a in "$@"; do case "$a" in -y|--yes) ASSUME_YES=1;; --no-apt) SKIP_APT=1;; -h|--help)
  echo "Usage: ./install.sh [--yes] [--no-apt]"; echo "  --yes     do not ask before running apt"; echo "  --no-apt  skip system packages (you must install them yourself)"; exit 0;; esac; done

[[ $EUID -eq 0 ]] && { echo "Run this as your normal user, not root. It asks for sudo only when needed." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || { echo "Python 3.8 or newer is required." >&2; exit 1; }

if [[ $SKIP_APT -eq 0 ]]; then
  command -v apt-get >/dev/null || { echo "This installer targets Zorin/Ubuntu/Debian. Re-run with --no-apt after installing the packages listed in README.md." >&2; exit 1; }
  # Zorin OS 17 (Ubuntu 22.04) and 18 (Ubuntu 24.04) both ship WebKitGTK 4.1; fall back to 4.0 for older bases.
  if apt-cache show gir1.2-webkit2-4.1 >/dev/null 2>&1; then WEBKIT=gir1.2-webkit2-4.1; else WEBKIT=gir1.2-webkit2-4.0; fi
  PKGS=(python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 "$WEBKIT" python3-evdev bluez libnotify-bin)
  echo "This will install these system packages with apt: ${PKGS[*]}"
  echo "Why: GTK + WebKit draw the window, python3-evdev reads the controller, bluez provides bluetoothctl, libnotify-bin lets the app show desktop notifications."
  if [[ $ASSUME_YES -eq 0 ]]; then read -r -p "Continue? [y/N] " ans; [[ "$ans" =~ ^[Yy]$ ]] || { echo "Cancelled. Nothing was changed."; exit 1; }; fi
  sudo apt-get update
  sudo apt-get install -y "${PKGS[@]}"
fi

# --system-site-packages lets the venv see the apt-installed GTK bindings and evdev.
python3 -m venv --system-site-packages "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install --quiet --upgrade pip
"$ROOT/.venv/bin/pip" install --quiet -r "$ROOT/requirements.txt"
chmod +x "$ROOT/run.sh" "$ROOT/uninstall.sh" "$ROOT/install-desktop-launcher.sh" "$ROOT/scripts/diagnose.sh" "$ROOT/scripts/enable-uinput.sh"
"$ROOT/.venv/bin/python" -c 'import webview, evdev, gi; print("Dependencies OK")' || { echo "A dependency failed to import. Run ./scripts/diagnose.sh" >&2; exit 1; }
echo; echo "Install complete."; echo "  Start:           ./run.sh"; echo "  Add to menu:     ./install-desktop-launcher.sh"; echo "  Check system:    ./scripts/diagnose.sh"
if [[ ! -w /dev/uinput ]]; then
  echo; echo "Optional: keyboard/mouse mode and the virtual Xbox pad need write access to /dev/uinput."
  echo "  Run once:        ./scripts/enable-uinput.sh    (adds one udev rule; asks with sudo)"
fi
