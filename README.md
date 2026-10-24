# DS4 Control Center

A desktop dashboard for the Sony DualShock 4 on Linux (built for Zorin OS and other Ubuntu-based distributions). It has a live controller tester, stick and trigger diagnostics, Bluetooth pairing, a game library that is **not limited to Steam**, and two ways to make the controller work with games that do not support it directly:

- **Any-game compatibility:** a virtual **Microsoft X-Box 360 pad** for games that only look for Xbox-style controllers.
- **Keyboard & mouse mode:** turn every controller button into a keyboard key or mouse button, with ready-made presets such as WASD movement and mouse-look on the right stick.

Everything on screen comes from the Linux kernel or from files the app reads. When something is not available (battery, touchpad, motion, uinput permission, trigger pressure) the app says **unavailable**; it never shows a made-up number or a fake connection.

## Screenshots

Version **1.4.0** follows the existing GitHub tag **v1.3.0** and aligns the in-app version with release tags.

These screenshots use the real frontend with the test bridge. Controller readings and game entries are simulated examples, not hardware verification.

![DS4 Control Center overview](docs/overview-v1.4.png)

| Universal game library | Keyboard and mouse mapping |
|---|---|
| ![Steam, Lutris, desktop and manual games](docs/gaming-v1.4.png) | ![Mapping presets, stick options and button bindings](docs/mapping-v1.4.png) |

See the [screenshot gallery](docs/README.md) and [release notes](docs/releases/v1.4.0.md).

## New in version 1.4.0

- **Any game, not just Steam.** The Gaming page now combines:
  - your Steam library (native or Flatpak),
  - installed **Lutris** games from its own database,
  - **desktop shortcuts** with `Categories=Game;` (this covers many Heroic, Bottles, itch, Wine and hand-made launchers, including cracked-game shortcuts),
  - and games you add yourself with a command such as `wine ~/Games/foo/foo.exe`.

  Each game has a source badge, launches from the same page, and can have its own dead-zone profile. Running-game detection is read-only and matches processes from all of these sources, so automatic profiles work for games started anywhere.
- **Virtual Xbox 360 pad.** For games that only see XInput-style controllers, the app creates a standard `Microsoft X-Box 360 pad` through uinput and mirrors every button, stick, trigger and D-pad direction into it. While it is on, the physical DualShock is reserved by the app so a game does not receive the same press twice. This is the compatibility path for older, Wine/Proton and non-Steam games that ignore the DualShock.
- **Keyboard & mouse mode.** Map all 18 DualShock inputs to Linux key codes, mouse buttons, the mouse wheel or WASD/arrow movement. Ready presets:
  - **Shooter (WASD + mouse):** left stick WASD, right stick mouse look, R2 fire, L2 aim, R reload, Space jump, Ctrl crouch, E interact, Tab scoreboard, and more.
  - **Action / platformer:** left stick WASD, right stick and D-pad arrows.
  - **Classic / menus:** arrows and mouse, Enter/Escape face buttons, L1/R1 wheel scrolling.
  - **Racing:** left stick steers A/D, R2 = W, L2 = S, Space handbrake.

  Rebind any button by clicking **Rebind** and pressing a key or mouse button. Dead zone, mouse sensitivity, vertical inversion, trigger threshold and “reserve the controller” are adjustable, and the page shows the virtual keys currently held.
- **Honest permission handling for virtual input.** Uinput is normally root-only. The app reports the exact problem and never changes permissions itself. `./scripts/enable-uinput.sh` is an optional, explicit helper that adds one udev rule and a modules-load entry after asking for confirmation. Without it, the rest of the app keeps working.
- **Troubleshooting** now checks uinput access, keyboard-mode state, the virtual pad, and game sources.
- **Fixes and quality:** settings writers keep mapping data intact, profile IDs accept every game source, malformed custom games are dropped without preventing startup, and the UI test covers the new pages.

## What was in version 0.3

- Light bar colour presets and custom picker, remembered per controller; battery history and low-battery alert; idle disconnect; desktop notifications; automatic game profiles; Markdown test report; keyboard shortcuts.
- Live controller illustration, touchpad and motion display, diagnostics (drift, circularity, button tester, trigger graph, rumble, event log), Bluetooth pairing, four themes, saved settings, responsive layout.

## Install

```bash
./install.sh            # asks before running apt; installs GTK/WebKit, python3-evdev, bluez, libnotify-bin
./run.sh                # start the app
./install-desktop-launcher.sh   # optional: add to the application menu

# optional, only for keyboard/mouse mode and the virtual Xbox pad:
./scripts/enable-uinput.sh
```

`install.sh` uses `sudo` only for `apt`, tells you which packages and why, and does nothing until you confirm. Use `--no-apt` to install the packages yourself:
`python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 (or -4.0) python3-evdev bluez libnotify-bin`.

Requirements: Zorin OS 17/18 or another Ubuntu/Debian desktop, Python 3.8+, a graphical session. The app refuses to run as root.

GTK is the default renderer. If you have separately installed Qt dependencies, select it with `PYWEBVIEW_GUI=qt ./run.sh`. The WebKit graphics workarounds remain enabled by default; set `WEBKIT_DISABLE_COMPOSITING_MODE=0` and/or `WEBKIT_DISABLE_DMABUF_RENDERER=0` to override them when troubleshooting.

## Using it

| Page | What it does |
|---|---|
| Overview | Live controller, connection, battery, sticks, touchpad, motion, recent input. Reconnect and Disconnect live here. |
| Diagnostics | Sticks, Buttons & triggers, and Event log tabs. “Reset measurements” clears drift, circularity and graphs. |
| Bluetooth | Hold **Share + PS** until the light bar double-flashes, press **Scan for devices**, then **Pair**. |
| Gaming | Steam, Lutris, desktop and hand-added games; virtual Xbox pad; launch, add, remove, per-game profiles. |
| Key mapping | Keyboard/mouse mode, presets, per-button rebinding, mouse look options, live output. |
| Settings | Saved automatically. Every setting has a real effect. |
| Troubleshooting | Read-only system check, including uinput and game sources. |

**Keyboard shortcuts:** `1`–`7` switch pages; on Diagnostics `S` saves a report, `D` starts the drift test, `R` resets measurements; `?` shows the shortcut list. Shortcuts are ignored while you type in a field.

### Any-game compatibility (virtual Xbox pad)

Open **Gaming** and switch on **Any-game compatibility**. The app creates a virtual Xbox 360 controller and mirrors the physical DualShock into it:

- Cross → A, Circle → B, Square → X, Triangle → Y
- L1/R1 → bumpers, L2/R2 → analog triggers, L3/R3 → stick clicks
- Share → Select, Options → Start, PS and touchpad click → Guide
- D-pad → hat, both sticks scaled with a dead zone

The physical controller is reserved for this app while the virtual pad is on, so a game does not see two controllers. Turn it off to let Steam or the game see the physical DualShock again. The virtual pad does not forward force feedback, so rumble from a game reaches the controller only through the normal physical-pad path.

### Keyboard & mouse mode

1. Install the optional uinput access once (`./scripts/enable-uinput.sh`), then log out and back in. Troubleshooting tells you when this is missing.
2. Open **Key mapping** and switch the mode on. A virtual keyboard and mouse are created; keys go to whichever window has focus.
3. Pick a preset or click **Rebind** on a button and press a key or mouse button. **Escape** cancels a rebind.
4. If a game still reacts to the physical controller too, turn on **Reserve the controller**. This grabs the physical pad while the mode is on. The app still reads it for diagnostics.

Mouse look uses a radial dead zone and a curve; sensitivity, dead zone and vertical inversion are on the same page. Keys are sent as standard Linux key codes. A game that applies your keyboard layout may label them differently, and games with anti-cheat software may ignore or block synthetic input. This app does not try to bypass anti-cheat.

## Permissions

The app runs as your normal user and never edits udev rules, groups, or system settings by itself.

- **Reading input** needs read access to `/dev/input/eventN`. If it is denied, the Overview and Troubleshooting pages say so.
- **Rumble** needs write access too. Without it, input still works and the rumble test explains why it is unavailable.
- **Virtual keyboard/mouse and virtual Xbox pad** need write access to `/dev/uinput`. That is root-only by default on many distributions. The optional `./scripts/enable-uinput.sh` adds this rule after asking you:

  ```
  KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", TAG+="uaccess"
  ```

  It also writes `/etc/modules-load.d/ds4-control-center-uinput.conf` containing `uinput`. Both files are printed before they are written. `./scripts/enable-uinput.sh --remove` deletes them again. This is the only optional system change the project offers beyond installing packages, and it is never run automatically.
- **Enable Bluetooth** may run `rfkill unblock bluetooth` for you if the adapter is soft-blocked, because you asked it to turn Bluetooth on.
- **Light bar** colour needs write access to the controller's files under `/sys/class/leds/`. On most systems only root has it, so the card shows “Read-only”. The app will not change permissions for you. If you want colour control, add your own udev rule that makes `brightness` and `multi_intensity` writable for your user; that is a system change you make yourself and is untested here.
- **Idle disconnect** uses the same Bluetooth disconnect as the Disconnect button and pauses auto-reconnect until the controller wakes up on its own.
- **Pairing** uses BlueZ's normal agent and answers its prompt only for the device you chose.

## Troubleshooting

Open the **Troubleshooting** page first, or run `./scripts/diagnose.sh` (read-only).

- **No controller found:** plug in USB or pair over Bluetooth, then press the PS button. Check that the kernel driver loaded (`hid-playstation` on kernel 5.12+).
- **Found but cannot read it:** start the app from your desktop session, not over SSH and not with `sudo`. Check `ls -l /dev/input/event*`.
- **Only a virtual pad is visible:** Steam Input may be presenting its own pad. Close Steam or disable Steam Input for this controller to test the physical device.
- **Keyboard mode says it needs permission:** run `./scripts/enable-uinput.sh`, then log out and back in. Check `ls -l /dev/uinput`; it should be writable by your user or the `input` group.
- **Game does not see the controller even with the virtual pad:** make sure the virtual pad is on before launching the game, close Steam Input for that title, and check that the game accepts controllers without anti-cheat blocking virtual devices.
- **Keyboard mode types into the wrong window:** keys follow focus. Click the game window. If the game also receives the physical pad, enable **Reserve the controller**.
- **Bluetooth unavailable:** `systemctl status bluetooth`, `rfkill list`, `bluetoothctl show`.
- **Pairing fails:** use **Forget** on any old entry, re-enter pairing mode, and scan again.
- **Battery shows N/A:** the kernel did not report one. This is not 0%.
- **Blank window:** install the GTK/WebKit packages and run `./run.sh` from a terminal to read the error.

## Project layout

```
docs/index.html               Product landing page and screenshot gallery
docs/style.css                Landing-page design system and animations
docs/script.js                Lightbox, reveals, copy buttons and navigation
docs/screenshots/             Captures used by the landing page
index.html                    Pages, dialogs and layout
assets/css/                   theme.css (tokens, 4 themes), app.css
assets/js/                    util.js, controller-view.js (SVG), charts.js, app.js
app/main.py                   Window, single-instance lock
app/ds4cc/controller.py       sysfs discovery, evdev input, rumble, grab
app/ds4cc/input_map.py        Pure mapping engine, presets, virtual keyboard/mouse
app/ds4cc/virtual_pad.py      Pure Xbox state machine and the virtual Xbox 360 pad
app/ds4cc/games.py            Steam/Lutris/desktop/manual library, launch, running detection
app/ds4cc/settings.py         Settings, profiles, custom games, autostart
app/ds4cc/bridge.py           The API exposed to the page
app/ds4cc/bluetooth.py        bluetoothctl pairing jobs
app/ds4cc/steam.py            Steam detection, launching, library
app/ds4cc/system.py           Troubleshooting checks
app/ds4cc/power.py            Battery history, low-battery and idle logic (pure, tested)
app/ds4cc/lightbar.py         Light bar through sysfs LEDs
app/ds4cc/notify.py           Desktop notifications
scripts/diagnose.sh           Read-only report
scripts/enable-uinput.sh      Optional udev rule for virtual input (asks first)
tests/                        Backend tests and headless UI test
```

## Tests

```bash
python3 -m unittest discover -s tests -v     # backend + feature tests, no hardware needed

# Optional UI test. Install Playwright once in the project venv, then:
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/ui_smoke.py /tmp/shots
```

The tests fake sysfs, game libraries, uinput devices and the JavaScript bridge. Nothing is sent to a real game. The UI test drives the real frontend with a simulated bridge (`tests/ui_mock.js`, test-only, never loaded by the app).

## Known limitations

- **Not yet verified on a physical DualShock 4.** Button mapping, touchpad, and motion follow the kernel's documented `hid-playstation` behavior and are covered by tests using simulated events and a fake sysfs tree, but real-hardware behavior may differ, especially motion-axis orientation and `hid-sony` on older kernels. The virtual Xbox pad and keyboard mapper were exercised against simulated uinput devices and the headless UI harness; real uinput creation could not be tested in the development environment because `/dev/uinput` is root-only until the optional rule is installed.
- **Virtual pad fidelity.** It presents a standard Xbox 360 pad and mirrors buttons, sticks, triggers and the D-pad. Touchpad gestures, motion and force feedback are not exposed through it. While it is on, the physical pad is reserved for this app.
- **Keyboard mapping is global.** It sends keys to the focused window; it does not switch layouts per game. Per-game profiles currently change only this app's dead-zone guide, not the button map. Do not run Steam Input remapping and this mapper for the same game at the same time.
- **Virtual pad and Steam Input can collide** if both try to own the controller. Turn off Steam Input for that title when using the virtual Xbox pad.
- **Anti-cheat and focus.** Synthetic keyboard/mouse input can be ignored or blocked by anti-cheat software, and keys go to whichever window has focus. The app does not attempt to bypass either.
- Trigger pressure appears only if the driver reports analog axes; otherwise triggers show on/off.
- The drift and circularity figures are diagnostic hints, not a calibration.
- Bluetooth pairing depends on your BlueZ version's `bluetoothctl` output. Errors are shown as reported.
- Auto-reconnect only reconnects a previously used Bluetooth controller that is awake. It never pairs.
- The light bar on the illustration is only a link indicator. Real colour changes need the kernel LED files to be writable (see Permissions). Not verified on a physical controller.
- Automatic game detection reads Steam's `registry.vdf`, Lutris's `pga.db`, desktop entries and `/proc` (read-only). Unusual installs may need **Add any game** instead.
- Desktop detection requires `Categories=Game;`. Games whose shortcut lacks that category can be added manually.
- Notifications need `notify-send` (package `libnotify-bin`).
- Wayland and X11 are both expected to work through GTK; the app logic and headless UI were tested here.

## Uninstall

```bash
./uninstall.sh    # removes launcher, autostart, .venv; optionally saved settings and logs
```

If you ran the optional uinput helper, remove its two files with:

```bash
./scripts/enable-uinput.sh --remove
```

Then delete the project folder. Shared system packages are left installed.
