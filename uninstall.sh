#!/usr/bin/env bash
# Removes everything this app created for your user. System packages are left alone.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
echo "This will remove:"
echo "  - the menu launcher and the autostart entry (if present)"
echo "  - the project virtual environment: $ROOT/.venv"
read -r -p "Also delete saved settings and logs (~/.config/ds4-control-center, ~/.local/state/ds4-control-center)? [y/N] " wipe
read -r -p "Continue? [y/N] " ok; [[ "$ok" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 1; }
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/ds4-control-center.desktop" "$CFG/autostart/ds4-control-center.desktop"
rm -rf "$ROOT/.venv"
[[ "$wipe" =~ ^[Yy]$ ]] && rm -rf "$CFG/ds4-control-center" "$HOME/.local/state/ds4-control-center"
echo "Done. You can now delete this folder. Shared system packages (GTK, bluez, python3-evdev) were not removed."
