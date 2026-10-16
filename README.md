# DS4 Control Center

A lightweight Linux desktop dashboard for the Sony DualShock 4. It combines live Linux input events, a controller visualization, diagnostics, BlueZ controls, Steam shortcuts, and locally saved settings.

> **Status:** Stage 1 implementation. Real `evdev` input and basic `bluetoothctl` / Steam actions are implemented. Hardware validation has not yet been performed on a physical Zorin OS machine. Battery reporting is best-effort via Linux `power_supply` sysfs and may be unavailable for some controller/driver combinations. Input mapping can vary with kernel driver and device mode.

## Features

- Real controller detection through Linux `evdev`; USB and Bluetooth devices where exposed by the kernel.
- Live button illumination and stick/trigger values based on kernel-reported events. No fake input data is generated.
- Input event log, axis telemetry, dead-zone guide circles, and a simple resting-offset measurement.
- BlueZ status, timed device scan, pairing, trust, connect/disconnect and power controls through `bluetoothctl`.
- Steam detection and launch, Steam controller settings shortcut, and game launch by Steam App ID.
- Local settings in `~/.config/ds4-control-center/settings.json`.
- Read-only diagnostic script and a convenient launcher.

## Project layout

```text
ds4-control-center/
├── index.html              # Dashboard views and controller SVG
├── assets/
│   ├── app.js              # UI rendering and bridge calls
│   └── style.css           # Responsive dark UI
├── app/
│   ├── main.py             # PyWebView desktop entry point
│   └── backend.py          # evdev, BlueZ, Steam, settings bridge
├── scripts/diagnose.sh     # Read-only environment diagnostic
├── tests/test_backend.py   # Basic backend and input mapping tests
├── requirements.txt
├── install.sh
├── install-desktop-launcher.sh
└── run.sh
```

## Requirements

- Zorin OS or a compatible Ubuntu/Debian-based Linux desktop.
- Python 3.10+.
- GTK 3 and WebKitGTK 4.1 libraries for PyWebView's GTK backend.
- `python-evdev`, BlueZ (`bluetoothctl`) for Bluetooth management, and optional Steam.
- A graphical desktop session. The app is not designed to run as root.

## Install

From the extracted project directory:

```bash
./install.sh
```

The installer uses `sudo` only to install operating-system packages through APT, then creates a project-local Python virtual environment. Review `install.sh` before running it if you prefer to install dependencies manually.

Launch the application:

```bash
./run.sh
```

Optional: install a launcher in your current user account’s application menu:

```bash
./install-desktop-launcher.sh
```

To inspect the machine without changing its configuration:

```bash
./scripts/diagnose.sh
```

The dashboard can also be opened directly in a browser for layout review, but browser mode does **not** have controller, Bluetooth, or Steam access. It intentionally shows the desktop-app requirement rather than simulating a connected controller.

## Permissions

Do not run the application with `sudo`. Access to `/dev/input/event*` depends on your distribution's session and device permissions. If controller access is denied:

1. Connect the controller and run `./scripts/diagnose.sh`.
2. Check that your user can read the relevant `/dev/input/event*` device.
3. Follow Zorin/Ubuntu's documented input-device permissions guidance for your release and desktop session.
4. Log out and back in after any administrator-approved group or udev policy change.

The project does not automatically edit udev rules, groups, Bluetooth policy, or other system configuration.

## Usage

- **Overview:** connection state, custom controller SVG, button/axis values, recent events.
- **Input diagnostics:** stick coordinates, trigger values when analog axes are available, and a basic resting-offset sample.
- **Bluetooth:** power state, scan, pair, connect, disconnect, trust. Put the DS4 in pairing mode (hold **Share + PS** until its light flashes), then scan and select the device. The operating system may request confirmation.
- **Gaming hub:** launch Steam, open Steam controller settings where supported, or enter a numeric Steam App ID to launch through Steam's URI handler.
- **Settings:** theme, UI refresh interval, dead-zone guide size, animation toggle, per-user launch-at-login, and event logging.

## Important limitations

- The kernel may expose different button/axis names depending on USB/Bluetooth mode, driver, or SDL mapping. The initial map follows common Linux gamepad codes; it does not remap controls at the kernel level.
- Trigger axes are only displayed as analog values if the driver exposes them. Digital trigger buttons are still highlighted, but pressure cannot be inferred.
- Battery and charging status are shown only if the kernel exposes a suitable power-supply entry.
- “Event interval” in this first version is a rough interval between observed input-event timestamps, **not** a measured end-to-end controller latency benchmark.
- The stick drift display is a simple maximum radial offset over recent samples. It is a diagnostic hint, not a certified calibration test.
- Automatic background reconnect is not implemented in this version. The “Launch at login” setting creates or removes a per-user desktop autostart file only after you save settings.
- Game shortcuts launch Steam-supported URIs; they do not change game controls. Use Steam Input or native game support for actual mapping.
- Bluetooth discovery/pairing relies on `bluetoothctl` behavior available on the installed BlueZ version. Error output is surfaced when commands fail.

## Troubleshooting

- **No controller found:** check `ls -l /dev/input/event*`, run the diagnostic script, and verify `python-evdev` is installed in `.venv`.
- **Permission denied:** do not use `sudo ./run.sh`; inspect the device ownership/group and apply only distribution-supported permission changes.
- **Bluetooth unavailable:** check `systemctl status bluetooth` and `bluetoothctl show`. Ensure the adapter is not blocked and the controller is in pairing mode.
- **Pairing fails:** remove stale pairings in the OS Bluetooth settings, retry discovery, and accept any system authentication prompt.
- **Steam not detected:** install Steam or confirm that its package/Flatpak is visible to the current user.
- **Blank desktop window:** verify GTK 3 and WebKitGTK 4.1 packages, then run `./run.sh` from a terminal to read errors.

## Uninstall

1. Close the application.
2. Remove the project directory.
3. Optionally remove the local settings directory:

   ```bash
   rm -r ~/.config/ds4-control-center
   ```

4. If you want to remove only the project virtual environment, delete `.venv/`. The installer-installed OS packages are shared system dependencies and are intentionally not removed automatically.

## Development and tests

Run the basic tests using the project environment:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The current test suite covers mapping/configuration logic and does not substitute for testing with a physical DualShock 4 on Zorin OS.
