#!/usr/bin/env bash
set +e
printf '%s\n' '=== DS4 CONTROL CENTER DIAGNOSTICS ==='
printf '\n%s\n' '--- OS ---'; cat /etc/os-release | grep -E '^(PRETTY_NAME|VERSION_ID)='
printf '\n%s\n' '--- Desktop session ---'; printf 'XDG_SESSION_TYPE=%s\n' "${XDG_SESSION_TYPE:-unknown}"; printf 'XDG_CURRENT_DESKTOP=%s\n' "${XDG_CURRENT_DESKTOP:-unknown}"
printf '\n%s\n' '--- Dependencies ---'; for x in python3 bluetoothctl busctl steam flatpak; do printf '%-14s' "$x"; command -v "$x" || echo 'not found'; done
printf '\n%s\n' '--- Input devices ---'; ls -l /dev/input/event* /dev/input/by-id/* 2>/dev/null || echo 'No readable event nodes or by-id links found.'
printf '\n%s\n' '--- Input group membership ---'; id; getent group input || true
printf '\n%s\n' '--- BlueZ service ---'; systemctl is-active bluetooth 2>/dev/null || true; bluetoothctl show 2>&1 | head -25
printf '\n%s\n' '--- Python modules ---'; python3 - <<'PY'
import importlib.util
for m in ('evdev','webview'):
 print(f'{m}: {"installed" if importlib.util.find_spec(m) else "missing"}')
PY
printf '\n%s\n' '--- Steam ---'; command -v steam || flatpak info com.valvesoftware.Steam 2>/dev/null | head -5 || true
printf '\n%s\n' 'Diagnosis complete. This script only reads system state; it does not modify permissions or configuration.'
