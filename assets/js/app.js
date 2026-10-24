/* DS4 Control Center - application logic. Depends on util.js, controller-view.js, charts.js. */
(function () {
  'use strict';
  const D = window.DS4, $ = D.$, esc = D.esc, icon = D.icon;
  const BUTTONS = ['cross', 'circle', 'square', 'triangle', 'dpad-up', 'dpad-down', 'dpad-left', 'dpad-right', 'l1', 'r1', 'l2', 'r2', 'l3', 'r3', 'share', 'options', 'ps', 'touchpad'];
  const NAMES = { cross: 'Cross', circle: 'Circle', square: 'Square', triangle: 'Triangle', 'dpad-up': 'D-pad up', 'dpad-down': 'D-pad down', 'dpad-left': 'D-pad left', 'dpad-right': 'D-pad right', l1: 'L1', r1: 'R1', l2: 'L2', r2: 'R2', l3: 'L3', r3: 'R3', share: 'Share', options: 'Options', ps: 'PS button', touchpad: 'Touchpad' };
  const TITLES = {
    dashboard: ['Overview', 'Live view of your controller'], diagnostics: ['Diagnostics', 'Measure sticks, triggers and buttons'],
    bluetooth: ['Bluetooth', 'Pair, reconnect and disconnect'], gaming: ['Gaming', 'Steam, Lutris, desktop and any game'],
    mapping: ['Key mapping', 'Turn the controller into a keyboard and mouse'],
    settings: ['Settings', 'Saved automatically'], help: ['Troubleshooting', 'Check what this app depends on'],
  };

  const S = {
    settings: { theme: 'midnight', animations: true, refresh_ms: 50, deadzone: 8, graph_seconds: 20, trail_length: 60, games: [], profiles: {}, last_controller: null, custom_games: [], mapping: null, virtual_pad_enabled: false, scan_desktop_games: true, scan_lutris_games: true },
    page: 'dashboard', dtab: 'sticks', frame: null, status: null, seq: 0, evSeq: 0, events: [], logFilter: 'all',
    dirty: true, bridge: false, profile: null, bt: { status: null, paired: [], nearby: [], job: null, busy: null, jobTimer: null, scanned: false },
    drift: { state: 'idle', t0: 0, sum: [0, 0], max: [0, 0], n: 0 }, circ: { on: false }, lib: [], rateTick: 0,
    driftResult: null, dismissedApp: null, lb: null, batSig: '', wasLive: null,
    allGames: [], gameSources: [], gameRunning: null, steamStatus: null, vpad: null,
    mapInfo: null, mapping: null, capture: null, swallowClick: false, mapSaveTimer: null,
  };
  const cache = {};
  const setText = (id, v) => { if (cache[id] !== v) { cache[id] = v; $(id).textContent = v; } };
  const setHtml = (id, v) => { if (cache['h' + id] !== v) { cache['h' + id] = v; $(id).innerHTML = v; } };
  const effectiveDz = () => (S.profile && S.profile.dz != null ? S.profile.dz : S.settings.deadzone);

  /* ---------- views ---------- */
  const view = new D.ControllerView($('ctl-host'), 'live');
  const pads = { ol: new D.StickPad($('ov-left')), or: new D.StickPad($('ov-right')), dl: new D.StickPad($('dg-left')), dr: new D.StickPad($('dg-right')) };
  const tline = new D.Timeline($('tl-canvas'), [
    { color: () => D.colors.accent }, { color: () => D.colors.ok }, { color: () => D.colors.warn }, { color: () => '#c58bff' }]);
  const circ = { l: new D.Polar($('circ-left')), r: new D.Polar($('circ-right')) };
  const rateSpark = new D.Spark($('rate-spark'), 40), trigSpark = new D.Spark($('tg-canvas'), 120), batSpark = new D.Spark($('bat-spark'), 2);
  const touch = new D.TouchView($('touch-canvas')), motion = new D.MotionView($('motion-canvas'));
  $('tl-legend').innerHTML = [['Left X', 'var(--accent)'], ['Left Y', 'var(--ok)'], ['Right X', 'var(--warn)'], ['Right Y', '#c58bff']]
    .map((s) => '<span class="chip"><i class="dot" style="background:' + s[1] + '"></i>' + s[0] + '</span>').join('');
  $('guide-host').innerHTML = D.buildController('guide', { mini: true });
  D.$$('#guide-host [data-btn=share], #guide-host [data-btn=ps]').forEach((e) => e.classList.add('lit'));
  $('tester').innerHTML = BUTTONS.map((b) => '<div class="tbtn" data-t="' + b + '"><span>' + NAMES[b] + '</span><span class="n">0</span></div>').join('');
  const testerEls = {}; D.$$('#tester .tbtn').forEach((e) => { testerEls[e.dataset.t] = e; });

  /* ---------- settings ---------- */
  function applySettings(s) {
    Object.assign(S.settings, s);
    if (s && s.mapping) S.mapping = s.mapping;
    document.body.dataset.theme = S.settings.theme;
    document.body.classList.toggle('no-anim', !S.settings.animations);
    D.readColors();
    for (const p of Object.values(pads)) p.setTrail(S.settings.trail_length);
    tline.win = S.settings.graph_seconds;
    refreshDz(); S.dirty = true;
  }
  function refreshDz() { for (const p of Object.values(pads)) p.dz = effectiveDz(); S.dirty = true; renderProfileChip(); }
  function loadSettingsUI() {
    const s = S.settings;
    D.$$('#s-theme .sw').forEach((b) => b.classList.toggle('on', b.dataset.t === s.theme));
    $('s-anim').checked = !!s.animations; $('s-refresh').value = String(s.refresh_ms);
    $('s-dz').value = s.deadzone; $('s-dz-v').textContent = s.deadzone + '%'; $('s-graph').value = String(s.graph_seconds);
    $('s-trail').value = s.trail_length; $('s-trail-v').textContent = s.trail_length;
    $('s-reconnect').checked = !!s.auto_reconnect; $('s-attempts').value = String(s.reconnect_attempts || 3);
    $('s-autostart').checked = !!s.auto_start; $('s-min').checked = !!s.start_minimized; $('s-page').value = s.start_page || 'dashboard';
    $('s-log').checked = s.diagnostic_logging !== false;
    $('s-notify').checked = s.notifications !== false; $('s-lowbat').value = String(s.low_battery_percent != null ? s.low_battery_percent : 20);
    $('s-idle').value = String(s.idle_disconnect_minutes || 0); $('s-autoprofile').checked = s.auto_profile !== false;
    $('s-scan-desktop').checked = s.scan_desktop_games !== false; $('s-scan-lutris').checked = s.scan_lutris_games !== false;
  }
  let saveTimer = null, savedTimer = null, pending = {};
  function saveSoon(partial) {
    applySettings(partial);  /* apply instantly, persist shortly after */
    Object.assign(pending, partial);  /* merge, so quick successive changes are all saved */
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const batch = pending; pending = {};
      if (!S.bridge) return;
      try {
        const r = await D.call('save_settings', batch);
        if (r.ok) { $('saved').classList.add('show'); clearTimeout(savedTimer); savedTimer = setTimeout(() => $('saved').classList.remove('show'), 1400); }
        else D.report(r);
      } catch (e) { D.toast('Could not save settings.', 'bad'); }
    }, 250);
  }
  D.$$('#s-theme .sw').forEach((b) => b.addEventListener('click', () => { saveSoon({ theme: b.dataset.t }); loadSettingsUI(); }));
  const bindSel = (id, key, num) => $(id).addEventListener('change', (e) => saveSoon({ [key]: num ? Number(e.target.value) : e.target.value }));
  const bindChk = (id, key) => $(id).addEventListener('change', (e) => saveSoon({ [key]: e.target.checked }));
  bindSel('s-refresh', 'refresh_ms', 1); bindSel('s-graph', 'graph_seconds', 1); bindSel('s-attempts', 'reconnect_attempts', 1); bindSel('s-page', 'start_page');
  bindSel('s-lowbat', 'low_battery_percent', 1); bindSel('s-idle', 'idle_disconnect_minutes', 1);
  bindChk('s-notify', 'notifications'); bindChk('s-autoprofile', 'auto_profile');
  bindChk('s-anim', 'animations'); bindChk('s-reconnect', 'auto_reconnect'); bindChk('s-autostart', 'auto_start'); bindChk('s-min', 'start_minimized'); bindChk('s-log', 'diagnostic_logging');
  bindChk('s-scan-desktop', 'scan_desktop_games'); bindChk('s-scan-lutris', 'scan_lutris_games');
  $('s-dz').addEventListener('input', (e) => { $('s-dz-v').textContent = e.target.value + '%'; saveSoon({ deadzone: Number(e.target.value) }); });
  $('s-trail').addEventListener('input', (e) => { $('s-trail-v').textContent = e.target.value; saveSoon({ trail_length: Number(e.target.value) }); });
  $('s-reset').addEventListener('click', async () => {
    if (!S.bridge) return D.toast('Open the desktop app to change settings.', 'bad');
    const r = await D.call('reset_settings'); if (r.ok) { applySettings(r.settings); loadSettingsUI(); } D.report(r);
  });

  /* ---------- navigation ---------- */
  function showPage(p) {
    if (p !== 'mapping' && S.capture) { S.capture = null; S.swallowClick = false; }
    S.page = p;
    D.$$('.page').forEach((e) => e.classList.toggle('on', e.id === 'page-' + p));
    D.$$('#nav button').forEach((b) => b.classList.toggle('on', b.dataset.page === p));
    $('page-title').textContent = TITLES[p][0]; $('page-sub').textContent = TITLES[p][1];
    if (p === 'dashboard') refreshLightbar(); if (p === 'bluetooth') refreshBluetooth(); if (p === 'gaming') refreshGaming(); if (p === 'mapping') refreshMapping(); if (p === 'settings') loadSettingsUI(); if (p === 'help') runChecks();
    S.dirty = true; renderLog();
  }
  D.$$('[data-page]').forEach((b) => b.addEventListener('click', () => showPage(b.dataset.page)));
  document.addEventListener('click', (e) => { const g = e.target.closest('[data-goto]'); if (g) showPage(g.dataset.goto); });
  D.$$('#dseg button').forEach((b) => b.addEventListener('click', () => {
    S.dtab = b.dataset.dtab; D.$$('#dseg button').forEach((x) => x.classList.toggle('on', x === b));
    D.$$('.dtab').forEach((t) => t.classList.toggle('on', t.id === 'dtab-' + S.dtab)); S.dirty = true; renderLog();
  }));

  /* ---------- live frames ---------- */
  function ingest(f) {
    if (f.events && f.events.length) {
      for (const e of f.events) S.events.unshift(e);
      S.events.length = Math.min(S.events.length, 300); S.evSeq = f.events[f.events.length - 1].id;
      renderEvents();
    } else if (f.ev_last != null && f.ev_last < S.evSeq) { S.evSeq = 0; S.events = []; renderEvents(); }
    if (!f.same) { S.frame = f; S.seq = f.seq; }
    const fr = S.frame; if (!fr) return;
    S.rate = f.rate || 0; S.lastInput = f.last_input;
    const now = performance.now();
    if (now - S.rateTick > 1000) { S.rateTick = now; rateSpark.push(S.rate); setText('rate-val', String(S.rate)); }
    const live = !!fr.connected, a = fr.axes || {}, down = new Set(fr.down || []);
    $('stage').classList.toggle('idle', !live);
    view.setLive(live); view.update(fr);
    pads.ol.push(a.lx, a.ly, live, down.has('l3')); pads.or.push(a.rx, a.ry, live, down.has('r3'));
    pads.dl.push(a.lx, a.ly, live, down.has('l3')); pads.dr.push(a.rx, a.ry, live, down.has('r3'));
    if (live) tline.push(now / 1000, [a.lx, a.ly, a.rx, a.ry]);
    if (live) trigSpark.push(Math.max(a.l2 || 0, a.r2 || 0));
    touch.push(live ? (fr.touch || [{}, {}]) : [{}, {}], live && down.has('touchpad'), fr.touch_seen); touch.ok = live;
    motion.push(live ? fr.motion : null, fr.units);
    for (const k of ['l', 'r']) if (circ.on && live) circ[k].push(a[k + 'x'], a[k + 'y']);
    stepDrift(a, live);
    S.dirty = true;
    renderValues(fr, a, down, live);
  }

  function renderValues(fr, a, down, live) {
    const v = D.fmt;
    for (const k of ['lx', 'ly', 'rx', 'ry']) setText('ov-' + k, v(a[k]));
    if (S.page === 'diagnostics' && S.dtab === 'sticks') {
      for (const [p, x, y] of [['dl', a.lx, a.ly], ['dr', a.rx, a.ry]]) {
        const r = Math.hypot(x || 0, y || 0), ang = r > 0.05 ? ((Math.atan2(-(y || 0), x || 0) * 180 / Math.PI + 360) % 360) : null;
        setText(p + '-x', v(x)); setText(p + '-y', v(y)); setText(p + '-r', Math.round(Math.min(r, 1) * 100) + '%'); setText(p + '-a', ang == null ? '—' : Math.round(ang) + '°');
      }
      const dz = effectiveDz();
      for (const [id, x, y] of [['dg-lchip', a.lx, a.ly], ['dg-rchip', a.rx, a.ry]]) {
        const out = Math.hypot(x || 0, y || 0) * 100 > dz; const el = $(id);
        el.textContent = !live ? 'No data' : out ? 'Outside dead zone' : 'Inside dead zone'; el.className = 'chip ' + (live && out ? 'accent' : '');
      }
      for (const k of ['l', 'r']) { const s = circ[k].stats(); setText('c' + k + '-cov', Math.round(s.coverage * 100) + '%'); setText('c' + k + '-round', s.round == null ? '—' : Math.round(s.round * 100) + '%'); }
    }
    if (S.page === 'diagnostics' && S.dtab === 'buttons') {
      let seen = 0;
      for (const b of BUTTONS) {
        const n = (fr.counts && fr.counts[b]) || 0, el = testerEls[b]; if (n > 0) seen++;
        el.classList.toggle('seen', n > 0); el.classList.toggle('now', down.has(b));
        const t = String(n); if (el.lastChild.textContent !== t) el.lastChild.textContent = t;
      }
      setText('tester-count', seen + ' / ' + BUTTONS.length + ' tested');
      for (const t of ['l2', 'r2']) {
        const an = fr.analog && fr.analog[t], val = a[t] || 0;
        $('tg-' + t).style.width = (an ? val * 100 : down.has(t) ? 100 : 0) + '%';
        setText('tg-' + t + 'v', an ? Math.round(val * 100) + '%' : (live ? (down.has(t) ? 'on' : 'off') : '—'));
      }
      setText('trig-note', !live ? 'Connect a controller to read triggers' : (fr.analog.l2 || fr.analog.r2) ? 'Analog pressure reported by the driver' : 'Trigger pressure not reported yet. Pull a trigger; digital-only drivers show on/off.');
    }
    if (S.page === 'dashboard') {
      const tc = $('touch-chip'); const ts = fr.touch_seen;
      setText('touch-chip', !live ? '—' : ts ? (fr.touch.filter((t) => t.active).length + ' finger' + (fr.touch.filter((t) => t.active).length === 1 ? '' : 's')) : 'No data'); tc.className = 'chip' + (ts && live ? ' accent' : '');
      const m = live ? fr.motion : null; setText('motion-chip', !live ? '—' : m ? 'Streaming' : 'Unavailable');
      setHtml('motion-read', m ? '<span>Accel <b>' + [m.ax, m.ay, m.az].map((x) => x.toFixed(2)).join(' · ') + '</b> ' + (fr.units.accel === 'g' ? 'g' : '') + '</span><span>Gyro <b>' + [m.gx, m.gy, m.gz].map((x) => Math.round(x)).join(' · ') + '</b> ' + (fr.units.gyro === 'deg/s' ? '°/s' : '') + '</span>'
        : '<span>' + (live ? 'This driver does not expose motion sensors.' : 'Waiting for a controller') + '</span>');
      setText('c-input', !live ? '—' : S.lastInput ? D.ago(S.lastInput) : 'no input yet');
    }
  }

  /* ---------- drift test ---------- */
  function stepDrift(a, live) {
    const d = S.drift; if (d.state !== 'run') return;
    const el = (performance.now() - d.t0) / 1000;
    if (!live) return abortDrift('The controller disconnected.');
    const r = [Math.hypot(a.lx || 0, a.ly || 0), Math.hypot(a.rx || 0, a.ry || 0)];
    if (r[0] > 0.6 || r[1] > 0.6) return abortDrift('A stick was moved. Keep both sticks untouched and start again.');
    d.n++; for (let i = 0; i < 2; i++) { d.sum[i] += r[i]; d.max[i] = Math.max(d.max[i], r[i]); }
    $('drift-prog').style.width = Math.min(100, el / 5 * 100) + '%';
    if (el >= 5) {
      d.state = 'done'; $('drift-start').textContent = 'Run again'; $('drift-start').disabled = false;
      const dz = effectiveDz() / 100; S.driftResult = { dz: dz * 100, at: Date.now() };
      [['l', 0], ['r', 1]].forEach(([k, i]) => {
        const mean = d.sum[i] / d.n; setText('drift-' + k, (mean * 100).toFixed(1) + '%');
        const vd = $('drift-' + k + 'v'), mx = d.max[i];
        const [cls, txt] = mx <= dz ? ['ok', 'Within dead zone (peak ' + (mx * 100).toFixed(1) + '%)'] : mean > dz ? ['bad', 'Exceeds dead zone (peak ' + (mx * 100).toFixed(1) + '%)'] : ['warn', 'Peaks above dead zone (' + (mx * 100).toFixed(1) + '%)'];
        vd.className = 'verdict ' + cls; vd.textContent = txt; S.driftResult[k] = { mean: mean * 100, peak: mx * 100, verdict: txt };
      });
    }
  }
  function abortDrift(msg) { S.drift.state = 'idle'; $('drift-start').textContent = 'Start drift test'; $('drift-start').disabled = false; $('drift-prog').style.width = '0'; D.toast(msg, 'bad'); }
  $('drift-start').addEventListener('click', () => {
    if (!S.frame || !S.frame.connected) return D.toast('Connect a controller first.', 'bad');
    S.drift = { state: 'run', t0: performance.now(), sum: [0, 0], max: [0, 0], n: 0 };
    for (const k of ['l', 'r']) { setText('drift-' + k, '…'); $('drift-' + k + 'v').textContent = ''; }
    $('drift-start').textContent = 'Measuring…'; $('drift-start').disabled = true;
  });
  $('circ-toggle').addEventListener('click', () => { circ.on = !circ.on; $('circ-toggle').textContent = circ.on ? 'Stop' : 'Start'; $('circ-toggle').classList.toggle('primary', circ.on); });
  $('circ-reset').addEventListener('click', () => { circ.l.reset(); circ.r.reset(); S.dirty = true; });
  $('btn-reset-diag').addEventListener('click', async () => {
    S.drift = { state: 'idle', t0: 0, sum: [0, 0], max: [0, 0], n: 0 }; S.driftResult = null; $('drift-prog').style.width = '0'; $('drift-start').textContent = 'Start drift test'; $('drift-start').disabled = false;
    for (const k of ['l', 'r']) { setText('drift-' + k, '—'); $('drift-' + k + 'v').textContent = ''; }
    circ.l.reset(); circ.r.reset(); tline.reset(); Object.values(pads).forEach((p) => p.reset()); S.dirty = true;
    if (S.bridge) { try { await D.call('reset_diagnostics'); S.seq = 0; } catch (e) { /* ignore */ } }
    D.toast('Measurements reset.', 'ok');
  });
  const bindRange = (id, out) => $(id).addEventListener('input', (e) => { $(out).textContent = e.target.value + '%'; });
  bindRange('rum-strong', 'rum-strong-v'); bindRange('rum-weak', 'rum-weak-v');
  $('rum-go').addEventListener('click', async () => {
    try { D.report(await D.call('rumble', $('rum-strong').value / 100, $('rum-weak').value / 100, 500)); } catch (e) { D.toast('Open the desktop app to use rumble.', 'bad'); }
  });

  /* ---------- event log ---------- */
  const evRow = (e) => '<div class="ev ' + esc(e.kind) + '"><time class="mono">' + esc(e.ts) + '</time><i></i><span>' + esc(e.msg) + '</span></div>';
  function renderEvents() {
    setHtml('ov-events', S.events.slice(0, 7).map(evRow).join('') || '<div class="empty">No input yet. Press a button on the controller.</div>');
    renderLog();
  }
  function renderLog() {
    if (S.page !== 'diagnostics' || S.dtab !== 'log') return;
    const rows = S.events.filter((e) => S.logFilter === 'all' || e.kind === S.logFilter);
    setHtml('log-list', rows.slice(0, 200).map(evRow).join('') || '<div class="empty">Nothing logged yet.</div>');
    setText('log-count', rows.length + ' event' + (rows.length === 1 ? '' : 's'));
  }
  D.$$('#log-filter button').forEach((b) => b.addEventListener('click', () => { S.logFilter = b.dataset.f; D.$$('#log-filter button').forEach((x) => x.classList.toggle('on', x === b)); renderLog(); }));
  $('log-clear').addEventListener('click', async () => { S.events = []; if (S.bridge) await D.call('clear_log'); renderEvents(); });
  $('log-export').addEventListener('click', async () => { try { D.report(await D.call('export_log')); } catch (e) { D.toast('Open the desktop app to export.', 'bad'); } });

  /* ---------- status (1 Hz) ---------- */
  function renderStatus(st) {
    S.status = st; const info = st.info, live = !!info, last = st.last_controller;
    setText('conn-text', live ? 'Connected' : 'No controller'); $('conn-dot').className = 'dot' + (live ? ' on' : '');
    $('nav-live').classList.toggle('hidden', !live);
    setText('ctl-name', live ? info.name : 'No controller');
    setHtml('ctl-chips', live ? '<span class="chip ok">' + icon(info.bus === 'USB' ? 'usb' : 'wifi', 'sm') + info.bus + '</span>' +
      (info.driver ? '<span class="chip">' + esc(info.driver) + '</span>' : '') + '<span class="chip mono">' + esc(info.vendor) + ':' + esc(info.product) + '</span>' +
      (info.virtual ? '<span class="chip warn">Virtual pad</span>' : '') : '<span class="chip">Not connected</span>');
    $('btn-reconnect').disabled = live; $('btn-disconnect').disabled = !live;
    setText('c-chip', live ? 'Connected' : 'Disconnected'); $('c-chip').className = 'chip ' + (live ? 'ok' : '');
    setText('c-link', live ? info.bus : '—'); setText('c-driver', live && info.driver ? info.driver : '—');
    setText('c-id', live ? info.vendor + ':' + info.product : '—');
    setText('c-last', live ? 'now' : last && last.seen_at ? D.ago(last.seen_at) + ' · ' + last.bus : 'never');
    const rc = st.reconnect || {};
    setText('c-reconnect', live ? '' : !rc.enabled ? 'Auto-reconnect is off.' : rc.state === 'trying' ? 'Trying to reconnect (attempt ' + rc.attempt + ' of ' + rc.max + ')…' : rc.state === 'gave_up' ? 'Stopped after ' + rc.max + ' attempts. Wake the controller and press Reconnect.' : rc.state === 'waiting' ? 'Waiting for Bluetooth to be turned on.' : rc.state === 'paused' ? 'Auto-reconnect paused because you disconnected the controller.' : '');
    renderBattery(st.battery, live, st.drain_rate);
    autoProfile(st.running_game, st.steam_app);
    if (st.virtual_pad) { S.vpad = st.virtual_pad; renderVpad(); }
    if (S.page === 'mapping' && st.mapping && S.mapInfo) updateMappingChip(st.mapping);
    if (S.wasLive !== live) { S.wasLive = live; refreshLightbar(); refreshBatteryHistory(); }
    setText('banner-title', !S.bridge ? 'Desktop app required' : st.error ? 'Controller found, cannot read it' : 'No controller detected');
    setText('banner-text', !S.bridge ? 'Start this project with ./run.sh. A plain browser has no access to controllers.' : st.error ? st.error : 'Plug in the USB cable, or hold Share + PS until the light bar flashes and pair it on the Bluetooth page.');
    const have = (r) => (st.nodes || []).some((n) => n.role === r && n.readable);
    const nrow = (r, ic, title, sub) => '<div class="node ' + (have(r) && live ? 'ok' : '') + '">' + icon(ic) + '<div><b>' + title + '</b><small>' + sub + '</small></div><span class="chip st ' + (have(r) && live ? 'ok' : '') + '">' + (have(r) && live ? 'Reading' : live ? 'Not exposed' : '—') + '</span></div>';
    setHtml('ov-nodes', nrow('gamepad', 'pad', 'Buttons, sticks, triggers', 'Main gamepad input') + nrow('touchpad', 'touch', 'Touchpad', 'Finger position and click') + nrow('motion', 'rotate', 'Motion sensors', 'Accelerometer and gyro'));
    setText('rd-dev-t', live ? 'Controller connected' : 'No controller'); setText('rd-dev-s', live ? info.name + ' · ' + info.bus : 'Connect one to begin.'); $('rd-dev').className = 'dot' + (live ? ' on' : '');
    const act = live && S.lastInput && Date.now() / 1000 - S.lastInput < 2; setText('rd-in-t', act ? 'Receiving input' : 'No recent input'); $('rd-in').className = 'dot' + (act ? ' on' : '');
    setText('rail-title', S.bridge ? 'System bridge' : 'Browser preview'); setText('rail-sub', S.bridge ? (st.evdev ? 'Reading Linux input' : 'evdev missing') : 'No hardware access'); $('rail-dot').className = 'dot' + (S.bridge && st.evdev ? ' on' : S.bridge ? ' bad' : ' warn');
  }
  function renderBattery(b, live, drain) {
    const arc = $('bat-arc'), C = 264;
    if (!live || !b) {
      arc.setAttribute('class', 'arc na'); setText('bat-pct', 'N/A'); setText('bat-sub', 'unavailable'); setText('bat-chip', live ? 'Not reported' : '—'); $('bat-chip').className = 'chip';
      setText('bat-note', live ? 'The kernel did not report a battery for this controller. This is not the same as 0%.' : 'Connect a controller to read its battery.'); return;
    }
    arc.setAttribute('class', 'arc' + (b.percent <= 15 ? ' low' : b.percent <= 35 ? ' mid' : ''));
    arc.style.strokeDashoffset = String(C * (1 - b.percent / 100)); arc.style.strokeDasharray = String(C);
    setText('bat-pct', b.percent + '%'); setText('bat-sub', b.charging ? 'charging' : b.full ? 'full' : b.charging === false ? 'on battery' : 'status unknown');
    setText('bat-chip', b.charging ? 'Charging' : b.full ? 'Full' : b.status); $('bat-chip').className = 'chip ' + (b.charging || b.full ? 'ok' : b.percent <= 15 ? 'bad' : '');
    setText('bat-note', 'Reported by the Linux power-supply interface, refreshed every 20 seconds.');
    setText('bat-rate', drain != null && b.charging === false ? 'using about ' + drain + '% per hour' : '');
  }
  async function act(fn, after) {
    try { const r = await D.call(fn); D.report(r); if (after !== false) { setTimeout(pollStatus, 1500); setTimeout(pollStatus, 4500); } return r; }
    catch (e) { D.toast('Open the desktop app to do this.', 'bad'); }
  }
  $('btn-reconnect').addEventListener('click', () => { $('btn-reconnect').disabled = true; act('reconnect'); });
  $('btn-disconnect').addEventListener('click', () => { $('btn-disconnect').disabled = true; act('disconnect_controller'); });
  $('btn-refresh').addEventListener('click', () => { pollStatus(); if (S.page === 'dashboard') { refreshLightbar(); refreshBatteryHistory(); } if (S.page === 'bluetooth') refreshBluetooth(); if (S.page === 'gaming') refreshGaming(true); if (S.page === 'help') runChecks(); D.toast('Refreshed.'); });


  /* ---------- battery history (session) ---------- */
  async function refreshBatteryHistory() {
    try {
      const h = await D.call('get_battery_history'), v = (h.samples || []).map((x) => x.pct), sig = v.join(',');
      if (sig === S.batSig) return; S.batSig = sig;
      batSpark.v = v; batSpark.n = Math.max(2, v.length); S.dirty = true;
    } catch (e) { /* no bridge */ }
  }

  /* ---------- light bar ---------- */
  const LB_STATES = { ready: ['Available', 'ok'], locked: ['Read-only', 'warn'], unsupported: ['Not exposed', ''], disconnected: ['—', ''] };
  const same = (a, b) => !!a && !!b && a.toLowerCase() === b.toLowerCase();
  function renderLightbar(r) {
    S.lb = r; const st = LB_STATES[r.state] || ['—', ''], p = $('lb-panel');
    p.classList.toggle('locked', r.state === 'locked'); p.classList.toggle('nolb', r.state !== 'ready' && r.state !== 'locked');
    setText('lb-chip', st[0]); $('lb-chip').className = 'chip ' + st[1];
    setHtml('lb-swatches', (r.presets || []).map((c) => '<button class="lb-sw' + (same(c[1], r.saved || r.color) ? ' on' : '') + '" style="--c:' + esc(c[1]) + '" data-lb="' + esc(c[1]) + '" title="' + esc(c[0]) + '" aria-label="' + esc(c[0]) + '"></button>').join(''));
    setText('lb-note', r.message || (r.saved ? 'Restored automatically each time the controller connects.' : 'Pick a colour. It is remembered and re-applied on connect.'));
    $('lb-clear').disabled = !r.saved;
  }
  async function refreshLightbar() {
    try { renderLightbar(await D.call('get_lightbar')); } catch (e) { setText('lb-chip', '—'); $('lb-panel').classList.add('nolb'); setText('lb-note', 'Needs the desktop app (./run.sh).'); }
  }
  async function setLight(color) {
    try { const r = await D.call('set_lightbar', color); D.report(r); refreshLightbar(); } catch (e) { D.toast('Open the desktop app to do this.', 'bad'); }
  }
  $('lb-swatches').addEventListener('click', (e) => { const b = e.target.closest('[data-lb]'); if (b) { $('lb-color').value = b.dataset.lb; setLight(b.dataset.lb); } });
  $('lb-apply').addEventListener('click', () => setLight($('lb-color').value));
  $('lb-clear').addEventListener('click', async () => {
    try { const r = await D.call('save_settings', { lightbar_color: '' }); if (r.ok) { applySettings(r.settings); D.toast('The light bar colour will no longer be restored.', 'ok'); refreshLightbar(); } } catch (e) { D.toast('Open the desktop app to do this.', 'bad'); }
  });

  /* ---------- automatic game profiles ---------- */
  function profileFor(id) {
    const profiles = S.settings.profiles || {};
    if (!id) return null;
    if (profiles[id]) return profiles[id];
    if (id.indexOf('steam:') === 0 && profiles[id.slice(6)]) return profiles[id.slice(6)];
    return null;
  }
  function gameName(id) {
    if (!id) return 'this game';
    const all = S.allGames && S.allGames.length ? S.allGames : (S.lib || []);
    const want = String(id).replace(/^steam:/, '');
    const g = all.find((x) => x.id === id || String(x.appid) === want || x.id === 'steam:' + want) ||
      (S.settings.games || []).find((x) => String(x.appid) === want);
    return g ? g.name : id;
  }
  function autoProfile(running, steamApp) {
    if (S.settings.auto_profile === false) { if (S.profile && S.profile.auto) { S.profile = null; refreshDz(); } return; }
    const id = running && running.id ? running.id : (steamApp ? 'steam:' + steamApp : null);
    if (id !== S.dismissedApp) S.dismissedApp = null;
    const pf = profileFor(id), dz = pf && pf.deadzone != null ? pf.deadzone : null;
    if (S.profile && !S.profile.auto) return;                 /* a profile from a manual launch wins */
    if (id && dz != null && id !== S.dismissedApp) {
      const name = running && running.name ? running.name : gameName(id);
      if (!S.profile || S.profile.appid !== id || S.profile.dz !== dz) { S.profile = { name, dz, auto: true, appid: id }; refreshDz(); }
    } else if (S.profile && S.profile.auto) { S.profile = null; refreshDz(); }
  }

  /* ---------- test report ---------- */
  function buildReport() {
    const st = S.status || {}, info = st.info, fr = S.frame || {}, b = st.battery, dz = effectiveDz(), lines = [];
    const pct = (v) => (Number.isFinite(v) ? v.toFixed(1) + '%' : 'not measured');
    lines.push('# DS4 controller test report', '', 'Created: ' + new Date().toLocaleString(), '');
    lines.push('## Controller', '', info ? '- Name: ' + info.name + '\n- Link: ' + info.bus + (info.driver ? '\n- Driver: ' + info.driver : '') + '\n- Device ID: ' + info.vendor + ':' + info.product : '- No controller connected when this report was made.', '');
    lines.push('## Battery', '', b ? '- ' + b.percent + '% (' + b.status + ')' + (st.drain_rate != null && b.charging === false ? '\n- Using about ' + st.drain_rate + '% per hour this session' : '') : '- Not reported by the kernel.', '');
    lines.push('## Sticks', '', '- Dead-zone guide: ' + dz + '%');
    const dr = S.driftResult;
    if (dr) lines.push('- Drift test (5 s, hands off): left ' + pct(dr.l.mean) + ' avg / ' + pct(dr.l.peak) + ' peak (' + dr.l.verdict + '); right ' + pct(dr.r.mean) + ' avg / ' + pct(dr.r.peak) + ' peak (' + dr.r.verdict + ')');
    else lines.push('- Drift test: not run');
    for (const [k, n] of [['l', 'Left'], ['r', 'Right']]) { const c = circ[k].stats(); lines.push('- ' + n + ' circularity: coverage ' + Math.round(c.coverage * 100) + '%, roundness ' + (c.round == null ? 'not measured' : Math.round(c.round * 100) + '%')); }
    const counts = fr.counts || {}, seen = BUTTONS.filter((x) => (counts[x] || 0) > 0), missing = BUTTONS.filter((x) => !(counts[x] > 0));
    lines.push('', '## Buttons', '', '- Tested: ' + seen.length + ' of ' + BUTTONS.length, '- Not pressed yet: ' + (missing.map((x) => NAMES[x]).join(', ') || 'none'));
    lines.push('', '## Triggers', '', '- ' + ((fr.analog && (fr.analog.l2 || fr.analog.r2)) ? 'Analog pressure is reported by the driver.' : 'No analog trigger data seen (digital-only, or no trigger pulled yet).'));
    lines.push('', '## Input', '', '- Events per second at the time of the report: ' + (S.rate || 0), '', '_Drift and circularity figures are hints, not a calibration._');
    return lines.join('\n');
  }
  async function saveReport() {
    if (!S.status || !S.status.info) return D.toast('Connect a controller first.', 'bad');
    try { D.report(await D.call('save_report', buildReport(), 'test-report')); } catch (e) { D.toast('Open the desktop app to save reports.', 'bad'); }
  }
  $('btn-save-report').addEventListener('click', saveReport);

  /* ---------- keyboard shortcuts ---------- */
  const PAGE_KEYS = ['dashboard', 'diagnostics', 'bluetooth', 'gaming', 'mapping', 'settings', 'help'];
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
    const t = e.target, tag = t && t.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable) || document.querySelector('dialog[open]')) return;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (k >= '1' && k <= '7') { showPage(PAGE_KEYS[Number(k) - 1]); return; }
    if (k === "?") { showPage("settings"); const kb = document.querySelector('.keys'); if (kb) kb.scrollIntoView({ block: 'center' }); return; }
    if (S.page !== 'diagnostics') return;
    if (k === 's') saveReport();
    else if (k === 'r') $('btn-reset-diag').click();
    else if (k === 'd' && !$('drift-start').disabled) { if (S.dtab !== 'sticks') D.$$('#dseg [data-dtab=sticks]')[0].click(); $('drift-start').click(); }
  });

  /* ---------- Bluetooth ---------- */
  const devRow = (d, paired) => {
    const busy = S.bt.busy === d.mac;
    const acts = paired
      ? '<button class="btn sm" data-bt="' + (d.connected ? 'disconnect' : 'connect') + '" data-mac="' + d.mac + '"' + (busy ? ' disabled' : '') + '>' + (busy ? 'Working…' : d.connected ? 'Disconnect' : 'Connect') + '</button><button class="btn sm ghost danger" data-bt="forget" data-mac="' + d.mac + '"' + (busy ? ' disabled' : '') + '>Forget</button>'
      : (d.paired ? '<span class="chip ok">Paired</span>' : '<button class="btn sm primary" data-bt="pair" data-mac="' + d.mac + '"' + (S.bt.job && S.bt.job.state === 'running' ? ' disabled' : '') + '>Pair</button>');
    return '<div class="dev ' + (d.controller ? 'ctl' : '') + '"><div class="di">' + icon(d.controller ? 'pad' : 'bt') + '</div><div class="meta"><b>' + esc(d.name || d.mac) + '</b><small class="mono">' + (paired && d.connected ? '<span class="okc">Connected</span> · ' : '') + esc(d.mac) + (d.battery != null ? ' · ' + d.battery + '%' : '') + '</small></div><div class="acts">' + acts + '</div></div>';
  };
  function renderBt() {
    const st = S.bt.status; if (!st) return;
    const on = st.available && st.powered;
    setText('bt-chip', !st.available ? 'Unavailable' : on ? 'On' : 'Off'); $('bt-chip').className = 'chip ' + (on ? 'ok' : st.available ? 'warn' : 'bad');
    $('bt-orb').className = 'bt-orb' + (on ? '' : ' off');
    setText('bt-title', !st.available ? 'Bluetooth unavailable' : on ? 'Bluetooth is on' : 'Bluetooth is off');
    setText('bt-sub', st.message || (st.available ? (st.name || 'Adapter') + (st.address ? ' · ' + st.address : '') : ''));
    const running = S.bt.job && S.bt.job.state === 'running';
    $('bt-on').disabled = !st.installed || on; $('bt-off').disabled = !on; $('bt-scan').disabled = !on || running;
    setHtml('bt-paired', S.bt.paired.length ? S.bt.paired.map((d) => devRow(d, true)).join('') : '<div class="empty">' + (st.available ? 'No paired devices yet.' : 'Bluetooth is not available.') + '</div>');
    const near = S.bt.nearby.slice().sort((a, b) => (b.controller - a.controller) || (a.name || '').localeCompare(b.name || ''));
    setHtml('bt-near', near.length ? near.map((d) => devRow(d, false)).join('') : '<div class="empty">' + (S.bt.scanned ? 'No devices found. Put the controller in pairing mode and scan again.' : 'Scan to discover devices.') + '</div>');
  }
  function renderJob(j) {
    const steps = j && j.kind === 'pair' ? ['Prepare', 'Pair', 'Trust', 'Connect'] : ['Scan'];
    const names = j && j.kind === 'pair' ? ['Preparing', 'Pairing', 'Trusting', 'Connecting'] : ['Scanning'];
    const cur = j ? Math.max(0, names.indexOf(j.step)) : -1;
    setHtml('job-steps', (j ? steps : ['Scan', 'Pair', 'Trust', 'Connect']).map((s, i) => '<li class="' + (j ? (j.state === 'done' || i < cur ? 'done' : i === cur ? (j.state === 'error' ? 'err' : 'cur') : '') : '') + '">' + s + '</li>').join(''));
    $('job-fill').style.width = (j ? Math.round(j.progress * 100) : 0) + '%'; $('job-bar').className = 'bar' + (j && j.state === 'running' ? ' run' : '');
    const m = $('job-msg'); m.textContent = j ? j.message : 'Start a scan to find your controller.'; m.className = 'jobmsg' + (j && j.state === 'error' ? ' bad' : j && j.state === 'done' ? ' ok' : '');
    setText('job-sub', !j ? 'No task running' : j.kind === 'scan' ? 'Scanning for devices' : 'Pairing ' + (j.mac || ''));
    $('job-cancel').classList.toggle('hidden', !(j && j.state === 'running'));
  }
  async function pollJob() {
    clearTimeout(S.bt.jobTimer);
    try {
      const j = await D.call('bt_job'); S.bt.job = j; renderJob(j);
      if (j && j.kind === 'scan') { S.bt.nearby = j.devices || []; S.bt.scanned = true; }
      renderBt();
      if (j && j.state === 'running') S.bt.jobTimer = setTimeout(pollJob, 600);
      else if (j && S.bt.lastDone !== j.id) { S.bt.lastDone = j.id; refreshBluetooth(); setTimeout(pollStatus, 1500); }
    } catch (e) { /* bridge missing */ }
  }
  async function refreshBluetooth() {
    try {
      S.bt.status = await D.call('bt_status'); S.bt.paired = S.bt.status.available ? await D.call('bt_devices') : [];
      renderBt();
    } catch (e) { setText('bt-title', 'Desktop app required'); setText('bt-sub', 'Bluetooth is only available when started with ./run.sh'); setText('bt-chip', 'Preview'); }
  }
  $('bt-on').addEventListener('click', async () => { D.report(await D.call('bt_set_power', true)); refreshBluetooth(); });
  $('bt-off').addEventListener('click', async () => { D.report(await D.call('bt_set_power', false)); refreshBluetooth(); });
  $('bt-scan').addEventListener('click', async () => { S.bt.nearby = []; const r = await D.call('bt_scan'); if (!r.ok) return D.report(r); pollJob(); });
  $('job-cancel').addEventListener('click', () => D.call('bt_cancel'));
  $('bt-refresh').addEventListener('click', refreshBluetooth);
  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-bt]'); if (!b) return;
    const mac = b.dataset.mac, a = b.dataset.bt;
    if (a === 'pair') { const r = await D.call('bt_pair', mac); if (!r.ok) D.report(r); else pollJob(); return; }
    if (a === 'forget' && !confirm('Remove this device from the computer? You will need to pair it again.')) return;
    S.bt.busy = mac; renderBt();
    try { D.report(await D.call('bt_action', a, mac)); } finally { S.bt.busy = null; await refreshBluetooth(); setTimeout(pollStatus, 1500); }
  });

  /* ---------- Gaming: Steam plus any other game ---------- */
  const hue = (s) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
  const SOURCE_LABELS = { steam: 'Steam', lutris: 'Lutris', desktop: 'Desktop', manual: 'Added by me' };
  const gameProfileKey = (g) => (g.source === 'steam' && g.appid ? String(g.appid) : g.id);
  function allLibrary() {
    const list = (S.allGames || []).slice();
    const have = new Set(list.map((g) => String(g.appid || '')));
    for (const g of S.settings.games || []) {
      if (g.appid && !have.has(String(g.appid))) {
        list.push({ id: 'steam:' + g.appid, appid: String(g.appid), name: g.name, source: 'steam', cover: null, added: true });
      }
    }
    return list;
  }
  async function refreshGaming(force) {
    try {
      const st = await D.call('steam_status');
      S.steamStatus = st;
      setText('st-title', st.installed ? 'Steam is installed' : 'Steam not detected');
      setText('st-sub', st.installed ? (st.kind === 'flatpak' ? 'Flatpak install' : 'Native install') + (st.running ? ' · running now' : ' · not running') : 'Steam is optional. Games can be added below without it.');
      $('st-launch').disabled = !st.installed; $('st-settings').disabled = !st.installed;
      $('rd-steam').className = 'dot' + (st.running ? ' on' : ''); setText('rd-steam-t', st.running ? 'Steam is running' : 'Steam not running');
    } catch (e) {
      setText('st-title', 'Desktop app required'); setText('st-sub', 'Game detection needs the desktop app (./run.sh).');
    }
    let loaded = false;
    try {
      const r = await D.call('get_games', !!force);
      if (r && Array.isArray(r.games)) {
        S.allGames = r.games; S.gameSources = r.sources || []; S.gameRunning = r.running || null;
        S.lib = r.games.filter((g) => g.source === 'steam');
        loaded = true;
        if (r.error) D.toast(r.error, 'bad');
      }
    } catch (e) { /* older bridge: use the Steam-only API below */ }
    if (!loaded) {
      try {
        const lib = await D.call('steam_library', !!force);
        S.allGames = (lib || []).map((g) => ({ id: 'steam:' + g.appid, appid: String(g.appid), name: g.name, source: 'steam', cover: g.cover }));
        S.lib = S.allGames.slice();
        S.gameSources = [{ id: 'steam', label: 'Steam', count: S.allGames.length }];
      } catch (e) { S.allGames = []; S.lib = []; S.gameSources = []; }
    }
    renderGames();
    try {
      const vp = await D.call('get_virtual_pad');
      if (vp && vp.status) { S.vpad = vp.status; renderVpad(); }
    } catch (e) { /* older bridge */ }
  }
  function renderGames() {
    const q = $('lib-search').value.trim().toLowerCase();
    const src = $('lib-source') ? $('lib-source').value : 'all';
    const all = allLibrary();
    const filtered = all.filter((g) => (src === 'all' || g.source === src) && (!q || g.name.toLowerCase().includes(q)));
    setHtml('games', filtered.map((g) => {
      const key = gameProfileKey(g), pf = profileFor(key), h = hue(g.name);
      const art = g.cover ? 'background-image:url(&quot;' + esc(g.cover) + '&quot;)' : 'background-image:linear-gradient(145deg,hsl(' + h + ' 45% 26%),hsl(' + ((h + 50) % 360) + ' 40% 12%))';
      const launch = '<button class="btn sm primary" data-game="launch" data-id="' + esc(g.id) + '" data-appid="' + esc(g.appid || '') + '" data-source="' + esc(g.source) + '" data-name="' + esc(g.name) + '">Launch</button>';
      const steamInput = g.source === 'steam' && g.appid ? '<button class="btn sm icon" title="Open Steam Input for this game" aria-label="Steam Input" data-game="input" data-id="' + esc(g.appid) + '">' + icon('pad', 'sm') + '</button>' : '';
      const remove = (g.source === 'manual' || g.added) ? '<button class="btn sm icon ghost" title="Remove from this list" aria-label="Remove" data-game="remove" data-id="' + esc(g.id) + '" data-appid="' + esc(g.appid || '') + '" data-source="' + esc(g.source) + '">' + icon('trash', 'sm') + '</button>' : '';
      return '<div class="game' + (pf ? ' has-profile' : '') + '"><div class="art" style="' + art + '">' + (g.cover ? '' : '<span class="ini">' + esc(g.name.trim().slice(0, 2).toUpperCase()) + '</span>') +
        '<span class="src-badge">' + esc(SOURCE_LABELS[g.source] || g.source) + '</span>' +
        '<div class="tag chips">' + (pf ? '<span class="chip accent">Profile</span>' : '') + '</div></div>' +
        '<div class="info"><b title="' + esc(g.command || g.name) + '">' + esc(g.name) + '</b><div>' + launch + steamInput +
        '<button class="btn sm icon" title="App profile" aria-label="Profile" data-game="profile" data-id="' + esc(g.id) + '" data-key="' + esc(key) + '" data-name="' + esc(g.name) + '">' + icon('sliders', 'sm') + '</button>' + remove + '</div></div></div>';
    }).join('') || '<div class="empty" style="grid-column:1/-1">' + (all.length ? 'No games match this search or source.' : 'No games found yet. Add a Steam App ID, or use Add any game for a Lutris, desktop or hand-made launcher.') + '</div>');
    const counts = S.gameSources && S.gameSources.length ? S.gameSources.filter((x) => x.count).map((x) => x.count + ' ' + x.label).join(' · ') : '';
    setText('lib-note', all.length ? all.length + ' game' + (all.length === 1 ? '' : 's') + ' available' + (counts ? ' · ' + counts : '') + '. Each tile shows its source; this app does not change the game’s controls.' : '');
  }
  function renderSources() { if (S.gameSources) renderGames(); }
  $('lib-search').addEventListener('input', renderGames);
  if ($('lib-source')) $('lib-source').addEventListener('change', renderGames);
  $('lib-refresh').addEventListener('click', () => refreshGaming(true));
  $('st-launch').addEventListener('click', () => act('launch_steam', false)); $('st-settings').addEventListener('click', () => act('open_controller_settings', false));
  $('vpad-enable').addEventListener('change', async (e) => {
    const want = e.target.checked;
    try {
      const r = await D.call('set_virtual_pad', want);
      if (r.settings) applySettings(r.settings);
      S.vpad = r.virtual_pad || S.vpad;
      if (!r.ok) {
        e.target.checked = !want; D.report(r);
        if (want) openUinputHelp();
      } else D.toast(want ? 'Virtual Xbox pad is on.' : 'Virtual Xbox pad is off.', 'ok');
      renderVpad();
    } catch (err) { e.target.checked = !want; D.toast('Open the desktop app to do this.', 'bad'); }
  });
  function renderVpad() {
    if (!$('vpad-enable')) return;
    const st = S.vpad || {};
    const on = !!st.enabled;
    const wanted = st.desired !== undefined ? !!st.desired : !!S.settings.virtual_pad_enabled;
    const chip = $('vpad-chip');
    if (chip) {
      setText('vpad-chip', on ? 'On' : wanted && st.available === false ? 'Needs permission' : wanted ? 'Starting…' : 'Off');
      chip.className = 'chip ' + (on ? 'ok' : wanted && st.available === false ? 'warn' : wanted ? 'warn' : '');
    }
    if ($('vpad-enable').checked !== (on || wanted)) $('vpad-enable').checked = on || wanted;
    let note = st.error || st.reason || st.message || (on ? 'Games now see a standard Xbox 360 pad.' : 'Turn it on for games that do not see the DualShock 4.');
    const grab = st.grab || {};
    if (on && grab.wanted && !grab.active) note = 'The controller could not be reserved exclusively' + (grab.error ? ': ' + grab.error : '.') + ' A game may see both pads.';
    setText('vpad-note', note);
  }
  let profileApp = null, profileName = '';
  document.addEventListener('click', async (e) => {
    if (S.swallowClick) return;
    const b = e.target.closest('[data-game]'); if (!b) return;
    const id = b.dataset.id, a = b.dataset.game;
    const g = allLibrary().find((x) => x.id === id) || { id, appid: b.dataset.appid, source: b.dataset.source, name: b.dataset.name };
    try {
      if (a === 'launch') {
        const r = g.source === 'steam' && g.appid ? await D.call('launch_game', g.appid) : await D.call('launch_any_game', id);
        D.report(r);
        const pf = profileFor(gameProfileKey(g));
        if (r.ok && pf && pf.deadzone != null) { S.profile = { name: g.name, dz: pf.deadzone, appid: gameProfileKey(g) }; refreshDz(); }
        else if (r.ok && S.profile && !S.profile.auto) { S.profile = null; refreshDz(); }
      } else if (a === 'input') D.report(await D.call('open_controller_settings', g.appid || id));
      else if (a === 'remove') {
        const r = g.source === 'steam' ? await D.call('remove_game', g.appid || id) : await D.call('remove_custom_game', id);
        if (r.ok) { applySettings(r.settings); refreshGaming(true); }
        else D.report(r);
      } else if (a === 'profile') {
        profileApp = b.dataset.key || gameProfileKey(g); profileName = b.dataset.name || g.name;
        const pf = profileFor(profileApp) || { deadzone: null, note: '' };
        $('pf-title').textContent = profileName; $('pf-on').checked = pf.deadzone != null; $('pf-dz').value = pf.deadzone != null ? pf.deadzone : S.settings.deadzone;
        $('pf-dz-v').textContent = $('pf-dz').value + '%'; $('pf-dz').disabled = pf.deadzone == null; $('pf-note').value = pf.note || ''; $('dlg-profile').showModal();
      }
    } catch (err) { D.toast('Open the desktop app to do this.', 'bad'); }
  });
  $('pf-on').addEventListener('change', () => { $('pf-dz').disabled = !$('pf-on').checked; });
  $('pf-dz').addEventListener('input', (e) => { $('pf-dz-v').textContent = e.target.value + '%'; });
  $('pf-cancel').addEventListener('click', () => $('dlg-profile').close());
  $('pf-save').addEventListener('click', async () => {
    const r = await D.call('set_profile', profileApp, $('pf-on').checked ? Number($('pf-dz').value) : null, $('pf-note').value);
    if (r.ok) { applySettings(r.settings); renderGames(); $('dlg-profile').close(); } D.report(r, 'Profile saved. It is used when this game runs or when you launch it here.');
  });
  $('pf-remove').addEventListener('click', async () => { const r = await D.call('remove_profile', profileApp); if (r.ok) { applySettings(r.settings); renderGames(); $('dlg-profile').close(); } });
  $('lib-add').addEventListener('click', () => { $('add-id').value = ''; $('add-name').value = ''; $('dlg-add').showModal(); $('add-id').focus(); });
  $('add-cancel').addEventListener('click', () => $('dlg-add').close());
  $('add-save').addEventListener('click', async () => {
    try { const r = await D.call('add_game', $('add-id').value, $('add-name').value); if (r.ok) { applySettings(r.settings); refreshGaming(true); $('dlg-add').close(); } D.report(r); } catch (e) { D.toast('Open the desktop app to do this.', 'bad'); }
  });
  $('lib-add-any').addEventListener('click', () => { $('any-name').value = ''; $('any-command').value = ''; $('dlg-add-any').showModal(); $('any-name').focus(); });
  $('any-cancel').addEventListener('click', () => $('dlg-add-any').close());
  $('any-save').addEventListener('click', async () => {
    try {
      const r = await D.call('add_custom_game', $('any-name').value, $('any-command').value);
      if (r.ok) { applySettings(r.settings); $('dlg-add-any').close(); refreshGaming(true); }
      D.report(r);
    } catch (e) { D.toast('Open the desktop app to add a game.', 'bad'); }
  });
  function renderProfileChip() {
    const c = $('profile-chip'); c.classList.toggle('hidden', !S.profile);
    if (S.profile) { c.textContent = (S.profile.auto ? 'Auto profile: ' : 'Profile: ') + S.profile.name + ' · dead zone ' + S.profile.dz + '% (click to clear)'; }
  }
  $('profile-chip').addEventListener('click', () => { if (S.profile && S.profile.auto) S.dismissedApp = S.profile.appid; S.profile = null; refreshDz(); });

  /* ---------- Key mapping ---------- */
  const KEY_NAMES = {
    KEY_SPACE: 'Space', KEY_ENTER: 'Enter', KEY_ESC: 'Escape', KEY_TAB: 'Tab', KEY_BACKSPACE: 'Backspace',
    KEY_LEFTCTRL: 'Left Ctrl', KEY_RIGHTCTRL: 'Right Ctrl', KEY_LEFTSHIFT: 'Left Shift', KEY_RIGHTSHIFT: 'Right Shift',
    KEY_LEFTALT: 'Left Alt', KEY_RIGHTALT: 'Right Alt', KEY_LEFTMETA: 'Left Super', KEY_RIGHTMETA: 'Right Super',
    KEY_UP: '↑ Up', KEY_DOWN: '↓ Down', KEY_LEFT: '← Left', KEY_RIGHT: '→ Right', KEY_INSERT: 'Insert', KEY_DELETE: 'Delete',
    KEY_HOME: 'Home', KEY_END: 'End', KEY_PAGEUP: 'Page Up', KEY_PAGEDOWN: 'Page Down', KEY_CAPSLOCK: 'Caps Lock',
    KEY_MINUS: '-', KEY_EQUAL: '=', KEY_LEFTBRACE: '[', KEY_RIGHTBRACE: ']', KEY_BACKSLASH: '\\', KEY_SEMICOLON: ';',
    KEY_APOSTROPHE: "'", KEY_GRAVE: '`', KEY_COMMA: ',', KEY_DOT: '.', KEY_SLASH: '/',
    BTN_LEFT: 'Left mouse', BTN_RIGHT: 'Right mouse', BTN_MIDDLE: 'Middle mouse',
    WHEEL_UP: 'Wheel up', WHEEL_DOWN: 'Wheel down',
  };
  const CODE_TO_KEY = {};
  'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').forEach((c) => { CODE_TO_KEY['Key' + c] = 'KEY_' + c; });
  for (let i = 0; i <= 9; i++) { CODE_TO_KEY['Digit' + i] = 'KEY_' + i; CODE_TO_KEY['Numpad' + i] = 'KEY_KP' + i; }
  for (let i = 1; i <= 12; i++) CODE_TO_KEY['F' + i] = 'KEY_F' + i;
  Object.assign(CODE_TO_KEY, {
    ArrowUp: 'KEY_UP', ArrowDown: 'KEY_DOWN', ArrowLeft: 'KEY_LEFT', ArrowRight: 'KEY_RIGHT',
    Space: 'KEY_SPACE', Enter: 'KEY_ENTER', Tab: 'KEY_TAB', Backspace: 'KEY_BACKSPACE', Insert: 'KEY_INSERT', Delete: 'KEY_DELETE',
    Home: 'KEY_HOME', End: 'KEY_END', PageUp: 'KEY_PAGEUP', PageDown: 'KEY_PAGEDOWN', CapsLock: 'KEY_CAPSLOCK',
    Minus: 'KEY_MINUS', Equal: 'KEY_EQUAL', BracketLeft: 'KEY_LEFTBRACE', BracketRight: 'KEY_RIGHTBRACE',
    Backslash: 'KEY_BACKSLASH', Semicolon: 'KEY_SEMICOLON', Quote: 'KEY_APOSTROPHE', Backquote: 'KEY_GRAVE',
    Comma: 'KEY_COMMA', Period: 'KEY_DOT', Slash: 'KEY_SLASH',
    ShiftLeft: 'KEY_LEFTSHIFT', ShiftRight: 'KEY_RIGHTSHIFT', ControlLeft: 'KEY_LEFTCTRL', ControlRight: 'KEY_RIGHTCTRL',
    AltLeft: 'KEY_LEFTALT', AltRight: 'KEY_RIGHTALT', MetaLeft: 'KEY_LEFTMETA', MetaRight: 'KEY_RIGHTMETA',
    NumpadAdd: 'KEY_KPPLUS', NumpadSubtract: 'KEY_KPMINUS', NumpadMultiply: 'KEY_KPASTERISK',
    NumpadDivide: 'KEY_KPSLASH', NumpadEnter: 'KEY_KPENTER', NumpadDecimal: 'KEY_KPDOT', NumLock: 'KEY_NUMLOCK',
    PrintScreen: 'KEY_SYSRQ', ScrollLock: 'KEY_SCROLLLOCK', Pause: 'KEY_PAUSE',
  });
  const prettyKey = (name) => name ? (KEY_NAMES[name] || name.replace(/^KEY_/, '').replace(/_/g, ' ').toLowerCase().replace(/(^|\s)\w/g, (m) => m.toUpperCase())) : 'Unmapped';
  function openUinputHelp() {
    const path = (S.mapInfo && S.mapInfo.script) || './scripts/enable-uinput.sh';
    const cmd = 'sudo "' + path + '"';
    $('uinput-command').textContent = cmd;
    $('dlg-uinput').showModal();
  }
  async function refreshMapping() {
    try {
      const info = await D.call('get_mapping');
      S.mapInfo = info; S.mapping = info.mapping || {};
      renderMapping();
    } catch (e) {
      S.mapInfo = null; renderMappingUnavailable();
    }
  }
  function renderMappingUnavailable() {
    setText('map-chip', 'Desktop app required'); $('map-chip').className = 'chip warn';
    setText('map-state-title', 'Desktop app required');
    setText('map-state-sub', 'Key mapping only works inside the app. Start it with ./run.sh.');
    setText('map-note', 'The page is visible here so you can see what the feature does; it cannot create virtual devices in a plain browser.');
    $('map-enable').checked = false; $('map-enable').disabled = true;
    setHtml('map-presets', '<div class="empty">Presets are available in the desktop app.</div>');
    setHtml('map-rows', '<div class="empty">Button bindings are available in the desktop app.</div>');
    $('map-live').textContent = 'Nothing pressed.';
  }
  function renderMappingStatus(st) {
    const m = S.mapping || {}, on = !!m.enabled, available = !S.mapInfo || S.mapInfo.available !== false;
    let chipText = 'Off', cls = '', title = 'Off', sub = 'Turn it on to send keys to the focused window.';
    if (!S.bridge) { chipText = 'Preview'; cls = 'warn'; title = 'Desktop app required'; sub = 'Start the app with ./run.sh.'; }
    else if (st && st.state === 'on') {
      chipText = 'On'; cls = 'ok';
      const presetLabel = S.mapInfo && (S.mapInfo.presets || []).find((p) => p.id === st.preset);
      const presetText = st.preset === 'custom' ? 'Custom' : (presetLabel ? presetLabel.label : (st.preset || 'Custom'));
      if (st.controller === false) {
        title = 'On — waiting for a controller'; sub = 'Preset: ' + presetText + '. Connect a controller; virtual keys are released while none is present.';
      } else {
        title = 'On — sending keyboard and mouse input';
        sub = 'Preset: ' + presetText + ' · ' + ((st.held || []).length) + ' virtual output' + ((st.held || []).length === 1 ? '' : 's') + ' held.';
      }
    }
    else if (!available) { chipText = 'Needs permission'; cls = 'warn'; title = 'Virtual input is not available yet'; sub = (st && st.reason) || (S.mapInfo && S.mapInfo.reason) || 'Your user cannot write to /dev/uinput.'; }
    else if (on && st && st.state === 'blocked') { chipText = 'Needs permission'; cls = 'warn'; title = 'Needs permission'; sub = (st && st.reason) || (S.mapInfo && S.mapInfo.reason) || 'Your user cannot write to /dev/uinput.'; }
    else if (on) { chipText = 'Starting…'; cls = 'warn'; title = 'Starting…'; sub = (st && st.message) || 'Creating the virtual keyboard and mouse.'; }
    setText('map-chip', chipText); $('map-chip').className = 'chip ' + cls;
    setText('map-state-title', title); setText('map-state-sub', sub);
    setText('map-note', (st && (st.error || st.reason)) || (S.mapInfo && S.mapInfo.reason) || 'Keys go to the focused window. Use the button map below to change any binding.');
    $('map-dot').className = 'dot' + (st && st.state === 'on' ? ' on' : on ? ' bad' : available ? '' : ' warn');
  }
  function renderMappingLive() {
    const st = (S.mapInfo && S.mapInfo.status) || {};
    const held = st.held || [];
    const parts = held.map((h) => '<span class="keychip">' + esc(prettyKey(h)) + '</span>');
    if (st.mouse_moving) parts.push('<span class="moving">Mouse moving</span>');
    $('map-live').innerHTML = parts.length ? parts.join('') : '<span>Nothing pressed.</span>';
    setText('map-live-chip', held.length || st.mouse_moving ? 'Active' : 'Idle');
    $('map-live-chip').className = 'chip ' + (held.length || st.mouse_moving ? 'ok' : '');
    renderMappingStatus(st);
  }
  function renderMapping() {
    const info = S.mapInfo, m = S.mapping || (info && info.mapping) || {};
    if (!info || !info.mapping) return renderMappingUnavailable();
    $('map-enable').disabled = !S.bridge;
    if ($('map-enable').checked !== !!m.enabled) $('map-enable').checked = !!m.enabled;
    renderMappingStatus(info.status || {});
    const preset = (info.presets || []).find((p) => p.id === m.preset);
    setText('map-preset-chip', preset ? preset.label : 'Custom');
    setHtml('map-presets', (info.presets || []).map((p) => '<button class="preset' + (m.preset === p.id ? ' on' : '') + '" data-preset="' + esc(p.id) + '"><b>' + esc(p.label) + (m.preset === p.id ? '<span class="chip accent">Active</span>' : '') + '</b><small>' + esc(p.description) + '</small></button>').join(''));
    const modes = info.stick_modes || [];
    const options = (list) => list.map((x) => '<option value="' + esc(x.id) + '">' + esc(x.label) + '</option>').join('');
    $('map-left').innerHTML = options(modes.filter((x) => x.id !== 'mouse'));
    $('map-right').innerHTML = options(modes);
    $('map-left').value = m.left_stick || 'wasd'; $('map-right').value = m.right_stick || 'mouse';
    $('map-dz').value = Math.round((m.deadzone != null ? m.deadzone : 0.18) * 100); $('map-dz-v').textContent = $('map-dz').value + '%';
    $('map-sens').value = Math.round((m.sensitivity != null ? m.sensitivity : 1) * 100); $('map-sens-v').textContent = (Number($('map-sens').value) / 100).toFixed(1) + '×';
    $('map-trig').value = Math.round((m.trigger_threshold != null ? m.trigger_threshold : 0.35) * 100); $('map-trig-v').textContent = $('map-trig').value + '%';
    $('map-invert').checked = !!m.invert_y; $('map-grab').checked = !!m.grab;
    renderMapRows();
    renderMappingLive();
  }
  function renderMapRows() {
    const info = S.mapInfo || {}, m = S.mapping || {};
    const buttons = info.buttons || [];
    if (!buttons.length) { setHtml('map-rows', '<div class="empty">No bindings available.</div>'); return; }
    const bindings = m.bindings || {};
    let mapped = 0;
    setHtml('map-rows', buttons.map((b) => {
      const key = bindings[b.id] || ''; if (key) mapped++;
      const capturing = S.capture === b.id;
      return '<div class="map-row' + (capturing ? ' capturing' : '') + '" data-btn="' + esc(b.id) + '">' +
        '<div class="map-name"><b>' + esc(b.label) + '</b><small>' + esc(b.id) + '</small></div>' +
        '<button class="bind' + (key ? '' : ' empty') + '" data-rebind="' + esc(b.id) + '" title="Click, then press a key or mouse button">' + esc(prettyKey(key)) + '</button>' +
        '<button class="btn sm' + (capturing ? ' primary' : '') + '" data-rebind="' + esc(b.id) + '">' + (capturing ? 'Press…' : 'Rebind') + '</button>' +
        '<button class="btn sm icon ghost" title="Clear this binding" aria-label="Clear" data-clear="' + esc(b.id) + '">' + icon('x', 'sm') + '</button></div>';
    }).join(''));
    setText('map-count', mapped + ' / ' + buttons.length + ' mapped');
  }
  function saveMappingSoon() {
    if (!S.mapping) return;
    clearTimeout(S.mapSaveTimer);
    const snapshot = JSON.parse(JSON.stringify(S.mapping || {}));
    S.mapSaveTimer = setTimeout(async () => {
      try {
        const r = await D.call('save_mapping', snapshot);
        if (r.ok) {
          S.mapInfo = r.mapping; S.mapping = (r.mapping && r.mapping.mapping) || snapshot;
          if (r.settings) applySettings(r.settings);
          renderMapping();
        } else { D.report(r); refreshMapping(); }
      } catch (e) { D.toast('Open the desktop app to save the mapping.', 'bad'); }
    }, 200);
  }
  function bindButton(button, key) {
    if (!S.mapping) return;
    S.mapping = Object.assign({}, S.mapping, { preset: 'custom', bindings: Object.assign({}, S.mapping.bindings || {}, { [button]: key }) });
    S.capture = null; S.mapInfo.mapping = S.mapping;
    renderMapRows(); saveMappingSoon();
  }
  document.addEventListener('keydown', (e) => {
    if (!S.capture) return;
    e.preventDefault(); e.stopPropagation();
    if (e.key === 'Escape') { S.capture = null; renderMapRows(); return; }
    const key = CODE_TO_KEY[e.code];
    if (!key) { D.toast('That key is not supported yet. Try another one.'); return; }
    bindButton(S.capture, key);
  }, true);
  document.addEventListener('mousedown', (e) => {
    if (!S.capture) return;
    e.preventDefault(); e.stopPropagation();
    const map = { 0: 'BTN_LEFT', 1: 'BTN_MIDDLE', 2: 'BTN_RIGHT' };
    if (map[e.button]) {
      S.swallowClick = true;
      setTimeout(() => { S.swallowClick = false; }, 500);
      bindButton(S.capture, map[e.button]);
    }
  }, true);
  document.addEventListener('wheel', (e) => {
    if (!S.capture) return;
    e.preventDefault(); e.stopPropagation();
    bindButton(S.capture, e.deltaY < 0 ? 'WHEEL_UP' : 'WHEEL_DOWN');
  }, { capture: true, passive: false });
  document.addEventListener('click', (e) => {
    if (!S.swallowClick) return;
    S.swallowClick = false; e.preventDefault(); e.stopPropagation();
  }, true);
  $('map-rows').addEventListener('click', (e) => {
    const rb = e.target.closest('[data-rebind]');
    if (rb) { S.capture = rb.dataset.rebind; renderMapRows(); D.toast('Press a key or mouse button. Escape cancels.'); return; }
    const cl = e.target.closest('[data-clear]');
    if (cl) { bindButton(cl.dataset.clear, ''); }
  });
  $('map-presets').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-preset]'); if (!b) return;
    try {
      const r = await D.call('apply_mapping_preset', b.dataset.preset);
      if (r.ok) { S.mapInfo = r.mapping; S.mapping = r.mapping.mapping; if (r.settings) applySettings(r.settings); renderMapping(); D.toast('Preset applied.', 'ok'); }
      else D.report(r);
    } catch (err) { D.toast('Open the desktop app to change presets.', 'bad'); }
  });
  $('map-enable').addEventListener('change', async (e) => {
    const want = e.target.checked;
    try {
      const r = await D.call('set_mapping_enabled', want);
      if (r.settings) applySettings(r.settings);
      S.mapInfo = r.mapping || S.mapInfo; S.mapping = (r.mapping && r.mapping.mapping) || S.mapping;
      if (!r.ok) { e.target.checked = !want; D.report(r); if (want) openUinputHelp(); }
      else D.toast(want ? 'Keyboard and mouse mode is on.' : 'Keyboard and mouse mode is off.', 'ok');
      renderMapping();
    } catch (err) { e.target.checked = !want; D.toast('Open the desktop app to change this setting.', 'bad'); }
  });
  $('map-refresh').addEventListener('click', refreshMapping);
  $('map-help').addEventListener('click', openUinputHelp);
  $('uinput-close').addEventListener('click', () => $('dlg-uinput').close());
  $('uinput-copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('uinput-command').textContent); D.toast('Command copied.', 'ok'); }
    catch (e) { D.toast('Copy is blocked here; select the command above.'); }
  });
  $('map-reset-bindings').addEventListener('click', async () => {
    const preset = (S.mapping && S.mapping.preset && S.mapping.preset !== 'custom') ? S.mapping.preset : 'shooter';
    try {
      const r = await D.call('apply_mapping_preset', preset);
      if (r.ok) { S.mapInfo = r.mapping; S.mapping = r.mapping.mapping; if (r.settings) applySettings(r.settings); renderMapping(); D.toast('Bindings reset.', 'ok'); }
      else D.report(r);
    } catch (e) { D.toast('Open the desktop app to change bindings.', 'bad'); }
  });
  const mapSelect = (id, key, transform, marksCustom) => $(id).addEventListener('change', (e) => {
    if (!S.mapping) return;
    S.mapping[key] = transform ? transform(e.target.value) : e.target.value;
    if (marksCustom) S.mapping.preset = 'custom';
    saveMappingSoon(); renderMapping();
  });
  const mapCheck = (id, key) => $(id).addEventListener('change', (e) => {
    if (!S.mapping) return;
    S.mapping[key] = e.target.checked; saveMappingSoon();
  });
  mapSelect('map-left', 'left_stick', null, true); mapSelect('map-right', 'right_stick', null, true);
  mapSelect('map-dz', 'deadzone', (v) => Number(v) / 100);
  mapSelect('map-sens', 'sensitivity', (v) => Number(v) / 100);
  mapSelect('map-trig', 'trigger_threshold', (v) => Number(v) / 100);
  mapCheck('map-invert', 'invert_y'); mapCheck('map-grab', 'grab');
  $('map-dz').addEventListener('input', (e) => { $('map-dz-v').textContent = e.target.value + '%'; });
  $('map-sens').addEventListener('input', (e) => { $('map-sens-v').textContent = (Number(e.target.value) / 100).toFixed(1) + '×'; });
  $('map-trig').addEventListener('input', (e) => { $('map-trig-v').textContent = e.target.value + '%'; });
  function updateMappingChip(summary) {
    if (!S.mapInfo || !summary) return;
    const st = S.mapInfo.status || {};
    if (summary.enabled !== !!st.enabled) {
      st.enabled = summary.enabled;
      if (!summary.enabled) st.state = 'off';
      else if (st.state === 'off') st.state = 'on';
      renderMappingStatus(st);
    }
  }

  /* ---------- troubleshooting ---------- */
  let report = '';
  async function runChecks() {
    try {
      const r = await D.call('system_check'); report = r.report;
      const ic = { ok: 'check', warn: 'alert', fail: 'x', info: 'info' };
      setHtml('checks', r.checks.map((c) => '<div class="check ' + c.state + '"><div class="ci">' + icon(ic[c.state] || 'info', 'sm') + '</div><div><b>' + esc(c.title) + '</b><div class="d">' + esc(c.detail) + '</div>' + (c.hint && c.state !== 'ok' ? '<div class="h">' + esc(c.hint) + '</div>' : '') + '</div></div>').join(''));
      $('report').textContent = report;
    } catch (e) { setHtml('checks', '<div class="empty">Troubleshooting needs the desktop app. Start it with ./run.sh.</div>'); }
  }
  $('help-run').addEventListener('click', runChecks);
  $('help-copy').addEventListener('click', async () => {
    if (!report) return D.toast('Run the checks first.', 'bad');
    try { await navigator.clipboard.writeText(report); D.toast('Report copied.', 'ok'); } catch (e) { $('report').classList.remove('hidden'); D.toast('Copy is blocked here. The report is shown below to select.'); }
  });

  /* ---------- loops ---------- */
  async function pollFrame() {
    try { ingest(await D.call('get_frame', S.seq, S.evSeq)); } catch (e) { /* no bridge or transient */ }
    setTimeout(pollFrame, document.hidden ? 500 : Math.max(20, S.settings.refresh_ms || 50));
  }
  async function pollStatus() { try { renderStatus(await D.call('get_status')); } catch (e) { /* ignore */ } }
  function draw() {
    if (S.dirty && !document.hidden) {
      S.dirty = false;
      if (S.page === 'dashboard') { pads.ol.draw(); pads.or.draw(); touch.draw(); motion.draw(); rateSpark.draw(20); batSpark.draw(100); }
      if (S.page === 'diagnostics') {
        if (S.dtab === 'sticks') { pads.dl.draw(); pads.dr.draw(); tline.draw(); circ.l.draw(); circ.r.draw(); }
        if (S.dtab === 'buttons') trigSpark.draw(1);
      }
    }
    requestAnimationFrame(draw);
  }
  window.addEventListener('resize', () => { S.dirty = true; });

  async function init() {
    D.readColors();
    S.bridge = D.hasBridge();
    if (S.bridge) {
      try { const b = await D.call('get_boot'); applySettings(b.settings); $('ver').textContent = 'v' + b.version; showPage(b.settings.start_page || 'dashboard'); } catch (e) { /* defaults */ }
      pollStatus(); setInterval(pollStatus, 1000); pollFrame(); setInterval(refreshBatteryHistory, 20000); setInterval(() => { if (S.page === 'dashboard') refreshLightbar(); }, 10000);
      setInterval(() => { if (S.page === 'bluetooth' && !(S.bt.job && S.bt.job.state === 'running')) refreshBluetooth(); if (S.page === 'gaming') refreshGaming(); }, 6000);
      setInterval(async () => {
        if (S.page !== 'mapping' || !S.bridge || !S.mapInfo) return;
        try { const info = await D.call('get_mapping'); S.mapInfo = info; if (!S.capture) S.mapping = info.mapping; renderMappingLive(); } catch (e) { /* transient */ }
      }, 2500);
    } else {
      renderStatus({ info: null, nodes: [], battery: null, evdev: true });
      setText('conn-text', 'Preview only'); setText('ctl-name', 'Browser preview');
      D.toast('Browser preview: start the app with ./run.sh for hardware access.');
    }
    renderEvents(); renderJob(null); draw();
  }
  let started = false;
  const go = () => { if (!started) { started = true; init(); } };
  window.addEventListener('pywebviewready', go);
  window.addEventListener('DOMContentLoaded', () => setTimeout(() => { if (D.hasBridge()) go(); }, 50));
  setTimeout(go, 800);
  D.state = S;
})();
