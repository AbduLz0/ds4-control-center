#!/usr/bin/env bash
# Optional, explicit system change that lets your normal user create virtual
# keyboards, mice and gamepads for DS4 Control Center's keyboard mode and the
# virtual Xbox pad. The app itself never runs this and never edits system files.
#
#   ./scripts/enable-uinput.sh            # add the rule (asks for confirmation)
#   ./scripts/enable-uinput.sh --remove   # remove it again
set -euo pipefail

RULE=/etc/udev/rules.d/70-ds4-control-center-uinput.rules
MODULE=/etc/modules-load.d/ds4-control-center-uinput.conf
MODE=add
ASSUME_YES=0

for arg in "$@"; do
  case "$arg" in
    --remove) MODE=remove ;;
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help)
      echo "Usage: ./scripts/enable-uinput.sh [--remove] [--yes]"
      echo "  Adds one udev rule and a modules-load entry for /dev/uinput."
      echo "  --remove  remove those two files again"
      echo "  --yes     do not ask before using sudo"
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this as your normal user, not root. It uses sudo only for the two files below." >&2
  exit 1
fi
command -v sudo >/dev/null || { echo "sudo is required for this optional step." >&2; exit 1; }

if [[ "$MODE" == remove ]]; then
  echo "This will remove:"
  echo "  $RULE"
  echo "  $MODULE"
  if [[ $ASSUME_YES -eq 0 ]]; then
    read -r -p "Continue? [y/N] " ans || true
    [[ "${ans:-}" =~ ^[Yy]$ ]] || { echo "Cancelled. Nothing was changed."; exit 1; }
  fi
  sudo rm -f "$RULE" "$MODULE"
  sudo udevadm control --reload-rules 2>/dev/null || true
  sudo udevadm trigger --name-match=uinput 2>/dev/null || true
  echo "Removed. Log out and back in (or reboot) for the old permissions to return."
  exit 0
fi

cat <<'EOF'
DS4 Control Center can create a virtual keyboard, mouse and Xbox pad through
the kernel's uinput interface. On most Linux systems only root may write to
/dev/uinput, so this optional step adds:

  1. /etc/udev/rules.d/70-ds4-control-center-uinput.rules
     Makes /dev/uinput writable by the input group and by the user who is
     logged in at the computer (the standard "uaccess" tag).

  2. /etc/modules-load.d/ds4-control-center-uinput.conf
     Loads the uinput module at boot.

Nothing else on the system is changed. Without this, the rest of the app
still works; only keyboard/mouse mode and the virtual Xbox pad are disabled.
EOF
echo
echo "The udev rule that will be written:"
echo 'KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", TAG+="uaccess"'
echo
if [[ $ASSUME_YES -eq 0 ]]; then
  read -r -p "Continue? [y/N] " ans || true
  [[ "${ans:-}" =~ ^[Yy]$ ]] || { echo "Cancelled. Nothing was changed."; exit 1; }
fi

printf '%s\n' \
  '# DS4 Control Center: allow the active desktop user to create virtual input devices.' \
  'KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", TAG+="uaccess"' \
  | sudo tee "$RULE" >/dev/null

printf '%s\n' '# DS4 Control Center: ensure uinput exists at boot.' 'uinput' \
  | sudo tee "$MODULE" >/dev/null

sudo modprobe uinput 2>/dev/null || echo "Note: the uinput module could not be loaded now; it will be tried at boot."
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput 2>/dev/null || true

echo
if [[ -w /dev/uinput ]]; then
  echo "Done. /dev/uinput is now writable by your user. You can switch the feature on now."
else
  echo "Rule installed. Log out and back in (or reboot), then try again."
  echo "If it still is not writable, check that your user is in the input group:"
  echo "  sudo usermod -aG input \"$USER\"   # then log out and back in"
fi
echo
echo "To undo this later: ./scripts/enable-uinput.sh --remove"
