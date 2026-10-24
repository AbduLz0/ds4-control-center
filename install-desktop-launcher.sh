#!/usr/bin/env bash
# Adds an application-menu entry for the current user only.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DIR"
cat > "$DIR/ds4-control-center.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=DS4 Control Center
Comment=DualShock 4 dashboard: live tester, Bluetooth, any-game support, key mapping
Exec="$ROOT/run.sh"
Icon=$ROOT/assets/icon.svg
Terminal=false
Categories=Utility;Game;
Keywords=controller;gamepad;dualshock;ps4;bluetooth;
StartupNotify=true
DESK
chmod 644 "$DIR/ds4-control-center.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$DIR" 2>/dev/null || true
echo "Launcher installed for your user. If you move this folder, run this script again."
