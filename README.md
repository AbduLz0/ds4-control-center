# DS4 Control Center

A desktop dashboard for the Sony DualShock 4 on Linux (built for Zorin OS and other Ubuntu-based distributions): a live controller tester, stick and trigger diagnostics, Bluetooth pairing, and a small Steam launcher in one app.

Everything on screen comes from the Linux kernel. When something is not available (battery, touchpad, motion, trigger pressure) the app says **unavailable**; it never shows a made-up number or a fake connection.

## Maintenance fixes

- The launcher now defaults to GTK/WebKit, matching the installer. An explicit `PYWEBVIEW_GUI` override is respected, and the launcher no longer disables the Qt browser sandbox.
- Malformed game profiles and nonfinite numeric settings no longer prevent startup. Boolean preferences require actual `true` or `false` values, and duplicate saved game IDs are normalized.
- Backend tests isolate autostart changes from your desktop settings and cover startup options and settings recovery.
- Keep `evdev` on its compatible 1.x series; version 2 requires Python 3.11+, while this app supports Python 3.8+.

## New in version 0.3

- **Light bar colour.** Colour presets plus a custom picker on the Overview page, remembered and re-applied every time the controller connects. It uses the kernel's LED interface, which most systems make root-only. When your user cannot write to it, the card says so and stays disabled instead of pretending (see Permissions).
- **Battery history and low-battery alert.** A session graph under the battery ring, an estimated drain rate (shown only once there is enough data to be honest), and one alert per discharge at 10, 15, 20 or 30 percent.
- **Turn off when idle.** Optionally disconnects a Bluetooth controller after 5 to 60 minutes with no real input (a held button, trigger or stick counts as input; resting stick noise does not). Off by default. Wired controllers are never touched.
- **Desktop notifications.** Connected, disconnected and low battery, through `notify-send`. Starting the app while the controller is already connected stays quiet.
- **Automatic game profiles.** The dead-zone profile for a game now applies whenever Steam reports that game running, even if you started it outside this app. Click the profile chip to dismiss it for that run.
- **Save test report.** One click writes drift, circularity, button coverage, trigger and battery results to a Markdown file in `~/.local/state/ds4-control-center/`. Anything not measured is labelled "not run" or "not measured". Useful when buying or selling a used controller.
- **Keyboard shortcuts.** `1` to `6` switch pages; on Diagnostics `S` saves a report, `D` starts the drift test, `R` resets measurements; `?` shows the list. Shortcuts are ignored while you type in a field.
- **Fixes:** several settings changed within a quarter of a second are now all saved (only the last used to be); a disconnect you ask for can no longer be undone by auto-reconnect racing it; the battery lookup now also checks the HID device's own power-supply folder.

## What's in version 0.2

- **Live controller illustration.** Every button lights on press. Sticks move on the body. L2/R2 fill with real analog pressure. The touchpad shows up to two fingers and its click. Light bar reflects link state.
- **Touchpad and motion.** Finger tracking on the Overview page. Accelerometer bubble and gyro bars from the motion sensors.
- **Diagnostics.** Stick pads with dead-zone ring and trails, a scrolling X/Y graph, a timed 5-second drift test, a circularity test, a 18-button tester with press counts, trigger graph, rumble test, and a filterable, exportable event log.
- **Bluetooth.** Adapter on/off, scan, pair (with progress steps and plain-language errors), connect, disconnect, forget, optional auto-reconnect.
- **Gaming.** Steam detection (native or Flatpak), your installed games with cover art, add games by App ID, per-game profiles, Steam Input shortcuts.
- **Troubleshooting page.** A live system check with fix hints and a copyable report.
- **Four themes**, saved settings, and a responsive layout down to narrow windows.

### Fixed from the previous version

- It required Python 3.12 (a nested f-string) and would not start on Zorin OS 17 (Python 3.10). It now runs on Python 3.8+.
- Device detection could attach to the touchpad or motion-sensor node instead of the gamepad, and permission errors were hidden. It now classifies the three DS4 nodes, prefers the physical pad over Steam's virtual ones, and reports permission problems.
- Sticks on the controller graphic never moved, battery was read only once, and the drift figure was measured while you were using the sticks.
- The Steam settings link used an undocumented URI. It now uses `steam://open/settings` and per-game `steam://controllerconfig/<appid>`, both documented by Valve.

## Install

```bash
./install.sh            # asks before running apt; installs GTK/WebKit, python3-evdev, bluez, libnotify-bin
./run.sh                # start the app
./install-desktop-launcher.sh   # optional: add to the application menu
```

`install.sh` uses `sudo` only for `apt`, tells you which packages and why, and does nothing until you confirm. Use `--no-apt` to install the packages yourself:
`python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 (or -4.0) python3-evdev bluez libnotify-bin`.

Requirements: Zorin OS 17/18 or another Ubuntu/Debian desktop, Python 3.8+, a graphical session. The app refuses to run as root.

GTK is the default renderer. If you have separately installed Qt dependencies, you can select it with `PYWEBVIEW_GUI=qt ./run.sh`. The WebKit graphics workarounds remain enabled by default; set `WEBKIT_DISABLE_COMPOSITING_MODE=0` and/or `WEBKIT_DISABLE_DMABUF_RENDERER=0` to override them when troubleshooting.

## Using it

| Page | What it does |
|---|---|
| Overview | Live controller, connection, battery, sticks, touchpad, motion, recent input. Reconnect and Disconnect live here. |
| Diagnostics | Sticks, Buttons & triggers, and Event log tabs. "Reset measurements" clears drift, circularity and graphs. |
| Bluetooth | Hold **Share + PS** until the light bar double-flashes, press **Scan for devices**, then **Pair**. |
| Gaming | Launch Steam or a game, open Steam Input for a game, add shortcuts, set per-game profiles. |
| Settings | Saved automatically. Every setting has a real effect (see below). Includes alerts, idle disconnect and the shortcut list. |
| Troubleshooting | Read-only system check. |

**Settings:** notifications; low-battery level; idle disconnect; automatic game profiles; theme; animations; refresh rate; dead-zone guide (also the drift pass mark); graph window; trail length; auto-reconnect and attempt limit; launch at login; start minimized; opening page; log button events. Reset keeps your game shortcuts.

**Game profiles** change only this app's dead-zone guide while you play. They apply when you launch from here or, with automatic profiles on, whenever Steam reports the game as running. They do not change any game's controls. Use Steam Input for remapping.

## Permissions

The app runs as your normal user and never edits udev rules, groups, or system settings. Logged-in desktop sessions normally have access to game controllers automatically.

- **Reading input** needs read access to `/dev/input/eventN`. If it is denied, the Overview and Troubleshooting pages say so.
- **Rumble** needs write access too. Without it, input still works and the rumble test explains why it is unavailable.
- **Enable Bluetooth** may run `rfkill unblock bluetooth` for you if the adapter is soft-blocked, because you asked it to turn Bluetooth on.
- **Light bar** colour needs write access to the controller's files under `/sys/class/leds/`. On most systems only root has it, so the card shows "Read-only". The app will not change permissions for you. If you want colour control, you can add your own udev rule that makes those two files (`brightness` and `multi_intensity`) writable for your user; that rule is a system change you make yourself, and it is **untested here**.
- **Idle disconnect** uses the same Bluetooth disconnect as the Disconnect button and pauses auto-reconnect until the controller wakes up on its own.
- **Pairing** uses BlueZ's normal agent and answers its prompt only for the device you chose.

## Troubleshooting

Open the **Troubleshooting** page first, or run `./scripts/diagnose.sh` (read-only).

- **No controller found:** plug in USB or pair over Bluetooth, then press the PS button. Check that the kernel driver loaded (`hid-playstation` on kernel 5.12+).
- **Found but cannot read it:** start the app from your desktop session, not over SSH and not with `sudo`. Check `ls -l /dev/input/event*`.
- **Only a virtual pad is visible:** Steam Input may be presenting its own pad. Close Steam to test the physical controller.
- **Bluetooth unavailable:** `systemctl status bluetooth`, `rfkill list`, `bluetoothctl show`.
- **Pairing fails:** use **Forget** on any old entry, re-enter pairing mode, and scan again.
- **Battery shows N/A:** the kernel did not report one. This is not 0%.
- **Blank window:** install the GTK/WebKit packages and run `./run.sh` from a terminal to read the error.

## Project layout

```
index.html                 Pages and layout
assets/css/                theme.css (tokens, 4 themes), app.css
assets/js/                 util.js, controller-view.js (SVG), charts.js, app.js
app/main.py                Window, single-instance lock
app/ds4cc/controller.py    sysfs discovery, evdev input, rumble
app/ds4cc/bluetooth.py     bluetoothctl pairing jobs
app/ds4cc/steam.py         Steam detection, launching, library
app/ds4cc/settings.py      Settings, profiles, autostart
app/ds4cc/diagnostics.py   Event log, rate meter
app/ds4cc/system.py        Troubleshooting checks
app/ds4cc/power.py         Battery history, low-battery and idle logic (pure, tested)
app/ds4cc/lightbar.py      Light bar through sysfs LEDs
app/ds4cc/notify.py        Desktop notifications
app/ds4cc/bridge.py        The API exposed to the page
scripts/diagnose.sh        Read-only report
tests/                     Backend tests and headless UI test
```

## Tests

```bash
python3 -m unittest discover -s tests -v     # backend + launcher tests, no hardware needed
python3 tests/ui_smoke.py /tmp/shots         # 64 UI checks + screenshots (needs playwright)
```

The UI test drives the real frontend with a simulated bridge (`tests/ui_mock.js`, test-only, never loaded by the app).

## Known limitations

- **Not yet verified on a physical DualShock 4.** Button mapping, touchpad, and motion follow the kernel's documented `hid-playstation` behavior and are covered by tests using simulated events and a fake sysfs tree, but real-hardware behavior may differ, especially motion-axis orientation and `hid-sony` on older kernels.
- Trigger pressure appears only if the driver reports analog axes; otherwise triggers show on/off.
- The drift and circularity figures are diagnostic hints, not a calibration.
- Bluetooth pairing depends on your BlueZ version's `bluetoothctl` output. Errors are shown as reported.
- Auto-reconnect only reconnects a previously used Bluetooth controller that is awake. It never pairs.
- The light bar on the illustration is only a link indicator. Real colour changes need the kernel LED files to be writable (see Permissions). Not verified on a physical controller.
- Automatic game profiles read Steam's own `registry.vdf` for the running App ID. That file's layout can differ between Steam versions or installs; if it is not found the feature simply does nothing.
- Idle detection only sees buttons, triggers, touchpad and sticks. Gyro-only or rumble-only use looks idle, so leave the idle setting off if you play that way.
- Notifications need `notify-send` (package `libnotify-bin`).
- Wayland and X11 are both expected to work through GTK; only the app logic was tested here.

## Uninstall

```bash
./uninstall.sh    # removes launcher, autostart, .venv; optionally saved settings and logs
```
Then delete the project folder. Shared system packages are left installed.
