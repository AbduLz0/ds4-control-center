/* TEST HARNESS ONLY. Simulates the Python bridge so the real UI can be exercised headlessly.
   The shipped app never loads this file. */
(function () {
  const m = window.__mock = {
    connected: true, seq: 1, down: [], axes: { lx: 0, ly: 0, rx: 0, ry: 0, l2: 0, r2: 0 }, analog: { l2: true, r2: true },
    touch: [{ active: false, x: .5, y: .5 }, { active: false, x: .5, y: .5 }], touch_seen: true,
    motion: { ax: .12, ay: .98, az: -.2, gx: 20, gy: -40, gz: 5 }, counts: {}, events: [], evId: 0, calls: [],
    battery: { percent: 73, status: 'Charging', charging: true, full: false },
    settings: { theme: 'midnight', animations: true, refresh_ms: 50, deadzone: 8, graph_seconds: 20, trail_length: 60, auto_start: false, start_minimized: false, start_page: 'dashboard', auto_reconnect: true, reconnect_attempts: 3, diagnostic_logging: true, notifications: true, low_battery_percent: 20, idle_disconnect_minutes: 0, auto_profile: true, lightbar_color: '', games: [{ appid: '1086940', name: 'Baldur’s Gate 3' }], profiles: { '620': { deadzone: 12, note: '' } }, last_controller: null },
    job: null, steamApp: null, lbState: 'ready', lbColor: '#0a3cff', reports: [],
    history: [90, 88, 86, 85, 83, 80, 78, 75, 73], drain: 4.5,
  };
  const info = () => ({ name: 'Wireless Controller', bus: 'Bluetooth', vendor: '054c', product: '09cc', mac: 'aa:bb:cc:dd:ee:ff', driver: 'hid-playstation', virtual: false, roles: ['gamepad', 'touchpad', 'motion'] });
  m.log = (kind, msg) => { m.events.push({ id: ++m.evId, t: Date.now() / 1000, kind, msg, ts: new Date().toTimeString().slice(0, 8) + '.123' }); m.seq++; };
  const ok = (message, extra) => Object.assign({ ok: true, message: message || 'Done.' }, extra || {});
  const api = {
    get_boot: async () => ({ version: '0.3.0', settings: m.settings, os: 'Zorin OS 17' }),
    get_status: async () => ({ connected: m.connected, info: m.connected ? info() : null, battery: m.connected ? m.battery : null, error: null, evdev: true,
      nodes: [{ role: 'gamepad', readable: true }, { role: 'touchpad', readable: true }, { role: 'motion', readable: true }],
      last_controller: { name: 'Wireless Controller', bus: 'Bluetooth', seen_at: Date.now() / 1000 - 300 }, reconnect: { state: 'idle', attempt: 0, max: 3, enabled: true }, steam_app: m.steamApp, drain_rate: m.drain }),
    get_frame: async (since, evSince) => {
      const evs = m.events.filter((e) => e.id > evSince);
      const base = { rate: m.connected ? 238 : 0, last_input: Date.now() / 1000 - 0.4, events: evs, ev_last: m.evId };
      if (since === m.seq) return Object.assign(base, { same: true, seq: m.seq });
      return Object.assign(base, { seq: m.seq, connected: m.connected, down: m.down, counts: m.counts, axes: m.axes, analog: m.analog, touch: m.touch, touch_seen: m.touch_seen, motion: m.motion, units: { accel: 'g', gyro: 'deg/s' } });
    },
    save_settings: async (p) => { Object.assign(m.settings, p); m.calls.push(['save_settings', p]); return ok('Saved.', { settings: m.settings }); },
    reset_settings: async () => ok('Defaults restored.', { settings: m.settings }),
    get_battery_history: async () => ({ samples: m.history.map((p, i) => ({ t: i * 20, pct: p, charging: false })), drain_rate: m.drain }),
    get_lightbar: async () => ({ state: m.lbState, saved: m.settings.lightbar_color || null, color: m.lbColor, message: m.lbState === 'locked' ? 'The light bar is visible to the system but only root can change it.' : m.lbState === 'unsupported' ? 'The kernel driver does not expose a light bar for this controller.' : '',
      presets: [['Blue', '#0a3cff'], ['Red', '#ff1e1e'], ['Green', '#14e650'], ['Purple', '#a028ff'], ['Orange', '#ff7a00'], ['Pink', '#ff4fa3'], ['White', '#ffffff']] }),
    set_lightbar: async (c) => { m.calls.push(['set_lightbar', c]); m.lbColor = c; m.settings.lightbar_color = c; return ok('Light bar set to ' + c + '.'); },
    save_report: async (text, kind) => { m.reports.push(text); m.calls.push(['save_report', kind]); return ok('Saved to ~/.local/state/ds4-control-center/' + kind + '.md'); },
    reset_diagnostics: async () => { m.counts = {}; m.seq++; return ok(); },
    clear_log: async () => ok(), export_log: async () => ok('Saved to ~/.local/state/ds4-control-center/events.log'),
    rumble: async () => ok('Rumble sent for 500 ms.'),
    reconnect: async () => { m.calls.push(['reconnect']); return ok('Connected.'); },
    disconnect_controller: async () => { m.calls.push(['disconnect']); return ok('Disconnected.'); },
    bt_status: async () => ({ installed: true, available: true, powered: true, name: 'Zorin-Laptop', address: '00:11:22:33:44:55', message: null }),
    bt_devices: async () => [{ mac: 'AA:BB:CC:DD:EE:FF', name: 'Wireless Controller', paired: true, trusted: true, connected: true, controller: true, battery: 73 }, { mac: '11:22:33:44:55:66', name: 'WH-1000XM4', paired: true, trusted: true, connected: false, controller: false, battery: null }],
    bt_set_power: async () => ok(), bt_action: async (a) => { m.calls.push(['bt_action', a]); return ok(); },
    bt_scan: async () => { m.job = { id: 'a', kind: 'scan', state: 'running', step: 'Scanning', progress: .55, message: 'Looking for nearby devices…', devices: [{ mac: 'DE:AD:BE:EF:00:01', name: 'Wireless Controller', controller: true, paired: false }, { mac: 'DE:AD:BE:EF:00:02', name: 'Living room TV', controller: false, paired: false }] }; return ok(); },
    bt_pair: async (mac) => { m.job = { id: 'b', kind: 'pair', mac, state: 'running', step: 'Pairing', progress: .3, message: 'Pairing with ' + mac + '…', devices: [] }; return ok(); },
    bt_job: async () => m.job, bt_cancel: async () => ok(),
    steam_status: async () => ({ installed: true, running: true, kind: 'native', path: '/usr/games/steam' }),
    steam_library: async () => [{ appid: '620', name: 'Portal 2', cover: null }, { appid: '1245620', name: 'ELDEN RING', cover: null }, { appid: '1091500', name: 'Cyberpunk 2077', cover: null }, { appid: '730', name: 'Counter-Strike 2', cover: null }],
    launch_steam: async () => ok(), launch_game: async (id) => { m.calls.push(['launch_game', id]); return ok('Asked Steam to launch app ' + id + '.'); }, open_controller_settings: async () => ok(),
    add_game: async (id, name) => { m.settings.games.push({ appid: id, name: name || id }); return ok('Shortcut added.', { settings: m.settings }); },
    remove_game: async () => ok('', { settings: m.settings }), set_profile: async (id, dz, note) => { m.settings.profiles[id] = { deadzone: dz, note }; return ok('Profile saved.', { settings: m.settings }); }, remove_profile: async () => ok('', { settings: m.settings }),
    system_check: async () => ({ report: 'DS4 Control Center report', checks: [
      { id: 'a', title: 'Input library (python-evdev)', state: 'ok', detail: 'Installed', hint: '' }, { id: 'b', title: 'Game controller', state: 'ok', detail: 'Wireless Controller via Bluetooth', hint: '' },
      { id: 'c', title: 'Permission to read the device', state: 'fail', detail: 'event5 is not readable and writable by your user.', hint: 'Run this app from your normal desktop session (not over SSH, not with sudo).' },
      { id: 'd', title: 'Motion sensors', state: 'info', detail: 'Not exposed by the driver or not readable.', hint: '' }, { id: 'e', title: 'Bluetooth adapter', state: 'warn', detail: 'Powered off', hint: 'Use Enable Bluetooth on the Bluetooth page.' }] }),
  };
  window.pywebview = { api };
  window.addEventListener('DOMContentLoaded', () => setTimeout(() => window.dispatchEvent(new Event('pywebviewready')), 30));
})();
