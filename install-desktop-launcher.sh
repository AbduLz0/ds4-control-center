#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/ds4-control-center.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DS4 Control Center
Comment=DualShock 4 controller dashboard for Linux
Exec=$ROOT/run.sh
Terminal=false
Categories=Utility;Game;
StartupNotify=true
EOF
chmod 644 "$HOME/.local/share/applications/ds4-control-center.desktop"
echo "Desktop launcher installed for current user."
echo "If you move the project directory, rerun this script."
