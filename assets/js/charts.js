/* Lightweight canvas charts. Each one draws only when visible and when asked to. */
(function () {
  'use strict';
  const DS4 = window.DS4;

  function fit(canvas) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (!w || !h) return null;
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w: canvas.clientWidth, h: canvas.clientHeight };
  }
  DS4.fitCanvas = fit;

  /* ---- stick position pad with dead-zone ring and motion trail ---- */
  class StickPad {
    constructor(canvas, trailLen) {
      this.c = canvas; this.trail = []; this.max = trailLen == null ? 60 : trailLen;
      this.x = 0; this.y = 0; this.dz = 8; this.live = false; this.pressed = false;
    }
    setTrail(n) { this.max = n; while (this.trail.length > n) this.trail.shift(); }
    push(x, y, live, pressed) {
      this.x = x; this.y = y; this.live = live; this.pressed = !!pressed;
      if (this.max > 0) { this.trail.push([x, y]); if (this.trail.length > this.max) this.trail.shift(); }
    }
    reset() { this.trail = []; }
    draw() {
      const f = fit(this.c); if (!f) return;
      const { ctx, w, h } = f, col = DS4.colors;
      const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 3;
      ctx.clearRect(0, 0, w, h);
      const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
      bg.addColorStop(0, col.bg); bg.addColorStop(1, col.panel);
      ctx.fillStyle = bg; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.fill();
      ctx.strokeStyle = col.line2; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.strokeStyle = col.line; ctx.lineWidth = 1;
      for (const k of [0.33, 0.66]) { ctx.beginPath(); ctx.arc(cx, cy, R * k, 0, 7); ctx.stroke(); }
      ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();
      const dzR = R * this.dz / 100;
      if (dzR > 1) {
        ctx.fillStyle = col.soft; ctx.beginPath(); ctx.arc(cx, cy, dzR, 0, 7); ctx.fill();
        ctx.setLineDash([4, 4]); ctx.strokeStyle = col.accent; ctx.globalAlpha = .7; ctx.beginPath(); ctx.arc(cx, cy, dzR, 0, 7); ctx.stroke();
        ctx.setLineDash([]); ctx.globalAlpha = 1;
      }
      if (!this.live) return;
      const t = this.trail;
      for (let i = 1; i < t.length; i++) {
        ctx.strokeStyle = col.accent; ctx.globalAlpha = (i / t.length) * .55; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(cx + t[i - 1][0] * R, cy + t[i - 1][1] * R); ctx.lineTo(cx + t[i][0] * R, cy + t[i][1] * R); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      const px = cx + DS4.clamp(this.x, -1, 1) * R, py = cy + DS4.clamp(this.y, -1, 1) * R;
      ctx.shadowColor = col.glow; ctx.shadowBlur = 14; ctx.fillStyle = col.accent;
      ctx.beginPath(); ctx.arc(px, py, this.pressed ? 8 : 6, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
      if (this.pressed) { ctx.strokeStyle = col.text; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(px, py, 11, 0, 7); ctx.stroke(); }
    }
  }

  /* ---- scrolling multi-series time graph ---- */
  class Timeline {
    constructor(canvas, series) { this.c = canvas; this.series = series; this.data = []; this.win = 20; }
    push(t, values) {
      this.data.push([t, values]);
      const cutoff = t - 125;
      while (this.data.length && this.data[0][0] < cutoff) this.data.shift();
    }
    reset() { this.data = []; }
    draw() {
      const f = fit(this.c); if (!f) return;
      const { ctx, w, h } = f, col = DS4.colors;
      ctx.clearRect(0, 0, w, h);
      const L = 34, T = 8, B = 20, W = w - L - 8, H = h - T - B;
      ctx.font = '11px system-ui,sans-serif'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      for (const v of [1, .5, 0, -.5, -1]) {
        const y = T + (1 - (v + 1) / 2) * H;
        ctx.strokeStyle = v === 0 ? col.line2 : col.line; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(L + W, y); ctx.stroke();
        ctx.fillStyle = col.dim; ctx.fillText(v.toFixed(1), L - 6, y);
      }
      ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
      const now = performance.now() / 1000;
      for (let s = 0; s <= this.win; s += this.win <= 20 ? 5 : 10) {
        const x = L + W - (s / this.win) * W;
        ctx.fillStyle = col.dim; ctx.textAlign = s === 0 ? 'right' : 'center'; ctx.fillText(s === 0 ? 'now' : '-' + s + 's', x, h - 5);
      }
      this.series.forEach((s, si) => {
        ctx.strokeStyle = s.color(); ctx.lineWidth = 1.6; ctx.beginPath();
        let started = false;
        for (const [t, vals] of this.data) {
          const age = now - t; if (age > this.win) continue;
          const x = L + W - (age / this.win) * W, y = T + (1 - (DS4.clamp(vals[si], -1, 1) + 1) / 2) * H;
          if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      });
    }
  }

  /* ---- circularity test: furthest radius reached at each angle ---- */
  class Polar {
    constructor(canvas) { this.c = canvas; this.N = 72; this.reset(); this.active = false; }
    reset() { this.r = new Array(this.N).fill(0); }
    push(x, y) {
      const rad = Math.hypot(x, y); if (rad < 0.25) return;
      const a = (Math.atan2(y, x) + Math.PI) / (2 * Math.PI);
      const i = Math.min(this.N - 1, Math.floor(a * this.N));
      if (rad > this.r[i]) this.r[i] = Math.min(1.05, rad);
    }
    stats() {
      const hit = this.r.filter((v) => v > 0);
      const cov = hit.length / this.N;
      if (hit.length < 8) return { coverage: cov, round: null, max: hit.length ? Math.max(...hit) : null };
      return { coverage: cov, round: Math.min(...hit) / Math.max(...hit), max: Math.max(...hit) };
    }
    draw() {
      const f = fit(this.c); if (!f) return;
      const { ctx, w, h } = f, col = DS4.colors;
      const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 8;
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = col.line; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();
      ctx.setLineDash([5, 5]); ctx.strokeStyle = col.line2; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.stroke(); ctx.setLineDash([]);
      const step = 2 * Math.PI / this.N;
      ctx.fillStyle = col.soft; ctx.strokeStyle = col.accent; ctx.lineWidth = 1.8; ctx.lineJoin = 'round';
      for (let i = 0; i < this.N; i++) {
        if (!(this.r[i] > 0)) continue;
        const a0 = i * step - Math.PI, rr = this.r[i] * R;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, rr, a0, a0 + step); ctx.closePath(); ctx.fill();
        ctx.beginPath(); ctx.arc(cx, cy, rr, a0, a0 + step); ctx.stroke();
      }
    }
  }

  /* ---- sparkline ---- */
  class Spark {
    constructor(canvas, n) { this.c = canvas; this.n = n || 60; this.v = []; }
    push(v) { this.v.push(v); if (this.v.length > this.n) this.v.shift(); }
    draw(maxHint) {
      const f = fit(this.c); if (!f) return;
      const { ctx, w, h } = f, col = DS4.colors;
      ctx.clearRect(0, 0, w, h);
      const max = Math.max(maxHint || 10, ...this.v);
      ctx.strokeStyle = col.line; ctx.beginPath(); ctx.moveTo(0, h - .5); ctx.lineTo(w, h - .5); ctx.stroke();
      if (this.v.length < 2) return;
      ctx.beginPath();
      this.v.forEach((v, i) => { const x = (i / (this.n - 1)) * w, y = h - 2 - (v / max) * (h - 4); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.strokeStyle = col.accent; ctx.lineWidth = 1.6; ctx.stroke();
      ctx.lineTo((this.v.length - 1) / (this.n - 1) * w, h); ctx.lineTo(0, h); ctx.closePath(); ctx.fillStyle = col.soft; ctx.fill();
    }
  }

  /* ---- touchpad view (1920x942 aspect) ---- */
  class TouchView {
    constructor(canvas) { this.c = canvas; this.f = [null, null]; this.trails = [[], []]; this.click = false; this.seen = false; this.ok = false; }
    push(touch, click, seen) {
      this.click = !!click; this.seen = seen;
      touch.forEach((t, i) => {
        this.f[i] = t.active ? t : null;
        if (t.active) { this.trails[i].push([t.x, t.y]); if (this.trails[i].length > 40) this.trails[i].shift(); } else this.trails[i] = [];
      });
    }
    draw() {
      const f = fit(this.c); if (!f) return;
      const { ctx, w, h } = f, col = DS4.colors, r = 14;
      ctx.clearRect(0, 0, w, h);
      ctx.beginPath(); ctx.roundRect ? ctx.roundRect(1, 1, w - 2, h - 2, r) : ctx.rect(1, 1, w - 2, h - 2);
      ctx.fillStyle = this.click ? col.soft : col.bg; ctx.fill();
      ctx.strokeStyle = this.click ? col.accent : col.line2; ctx.lineWidth = this.click ? 2 : 1.4; ctx.stroke();
      ctx.strokeStyle = col.line; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(w / 2, 6); ctx.lineTo(w / 2, h - 6); ctx.moveTo(6, h / 2); ctx.lineTo(w - 6, h / 2); ctx.stroke();
      this.trails.forEach((tr, i) => {
        for (let k = 1; k < tr.length; k++) {
          ctx.globalAlpha = k / tr.length * .5; ctx.strokeStyle = col.accent; ctx.lineWidth = 3;
          ctx.beginPath(); ctx.moveTo(tr[k - 1][0] * w, tr[k - 1][1] * h); ctx.lineTo(tr[k][0] * w, tr[k][1] * h); ctx.stroke();
        }
      });
      ctx.globalAlpha = 1;
      this.f.forEach((t, i) => {
        if (!t) return;
        ctx.shadowColor = col.glow; ctx.shadowBlur = 16; ctx.fillStyle = col.accent;
        ctx.beginPath(); ctx.arc(t.x * w, t.y * h, 11, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
        ctx.fillStyle = '#04121f'; ctx.font = '600 11px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(String(i + 1), t.x * w, t.y * h + .5);
      });
    }
  }

  /* ---- motion: level bubble (accelerometer X/Z) + gyro bars ---- */
  class MotionView {
    constructor(canvas) { this.c = canvas; this.m = null; this.units = {}; }
    push(m, units) { this.m = m; this.units = units || {}; }
    draw() {
      const f = fit(this.c); if (!f) return;
      const { ctx, w, h } = f, col = DS4.colors;
      ctx.clearRect(0, 0, w, h);
      const R = Math.min(h / 2 - 6, w * .3), cx = R + 8, cy = h / 2;
      ctx.strokeStyle = col.line2; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.stroke();
      ctx.strokeStyle = col.line; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(cx, cy, R / 2, 0, 7); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();
      const gx0 = cx + R + 28, gw = w - gx0 - 8;
      ctx.font = '11.5px system-ui'; ctx.textBaseline = 'middle';
      ['gx', 'gy', 'gz'].forEach((k, i) => {
        const y = h / 2 + (i - 1) * 30;
        ctx.fillStyle = col.muted; ctx.textAlign = 'left'; ctx.fillText(k.toUpperCase(), gx0, y - 11);
        ctx.fillStyle = col.line; ctx.fillRect(gx0, y - 3, gw, 6);
        ctx.fillStyle = col.dim; ctx.fillRect(gx0 + gw / 2 - .5, y - 6, 1, 12);
        if (this.m) {
          const scale = this.units.gyro === 'deg/s' ? 360 : 1;
          const v = DS4.clamp(this.m[k] / scale, -1, 1);
          ctx.fillStyle = col.accent;
          if (v >= 0) ctx.fillRect(gx0 + gw / 2, y - 3, v * gw / 2, 6); else ctx.fillRect(gx0 + gw / 2 + v * gw / 2, y - 3, -v * gw / 2, 6);
        }
      });
      if (this.m) {
        const scale = this.units.accel === 'g' ? 1.2 : 1;
        const bx = cx + DS4.clamp(this.m.ax / scale, -1, 1) * R * .85, by = cy + DS4.clamp(this.m.az / scale, -1, 1) * R * .85;
        ctx.shadowColor = col.glow; ctx.shadowBlur = 12; ctx.fillStyle = col.accent;
        ctx.beginPath(); ctx.arc(bx, by, 7, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
      }
    }
  }

  Object.assign(DS4, { StickPad, Timeline, Polar, Spark, TouchView, MotionView });
})();
