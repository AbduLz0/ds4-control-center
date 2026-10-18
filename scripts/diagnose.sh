#!/usr/bin/env bash
# Read-only environment report. Changes nothing.
set +e
h() { printf '\n--- %s ---\n' "$1"; }
echo "=== DS4 Control Center diagnostics ==="
h "OS and kernel"; grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release; uname -r
h "Session"; echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unknown}  XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-unknown}  user=$(id -un)"
h "Tools"; for x in python3 bluetoothctl rfkill steam flatpak; do printf '%-14s' "$x"; command -v "$x" || echo "not found"; done
h "Python modules"; python3 - <<'PY'
import importlib.util
for m in ("evdev", "webview", "gi"):
    print("%-8s %s" % (m, "installed" if importlib.util.find_spec(m) else "MISSING"))
PY
h "Controller input nodes (name / bus / readable)"
for d in /sys/class/input/event*; do
  n=$(cat "$d/device/name" 2>/dev/null); case "$n" in *ontroller*|*ualShock*|*ualSense*|*amepad*|*pad*|*Joystick*)
    b=$(cat "$d/device/id/bustype" 2>/dev/null); e=/dev/input/$(basename "$d")
    printf '%-9s %-40s bus=%s  read=%s write=%s\n' "$(basename "$d")" "$n" "$b" "$([ -r "$e" ] && echo yes || echo NO)" "$([ -w "$e" ] && echo yes || echo no)";; esac
done
echo "(bus 0003 = USB, 0005 = Bluetooth)"
h "Kernel drivers"; lsmod 2>/dev/null | grep -E 'hid_playstation|hid_sony|uinput' || echo "none of hid_playstation / hid_sony loaded as modules (may be built in)"
h "Bluetooth"; systemctl is-active bluetooth 2>/dev/null; rfkill list bluetooth 2>/dev/null; bluetoothctl show 2>&1 | head -12
h "Steam"; command -v steam || flatpak info com.valvesoftware.Steam 2>/dev/null | head -3 || echo "not installed"
printf '\nDone. This script only reads system state.\n'
