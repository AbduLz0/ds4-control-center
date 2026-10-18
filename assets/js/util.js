/* Shared helpers and the Python bridge wrapper. Exposes window.DS4. */
(function () {
  'use strict';
  const DS4 = window.DS4 = {};
  DS4.$ = (id) => document.getElementById(id);
  DS4.$$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  DS4.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  DS4.clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  DS4.icon = (name, cls) => '<svg class="ico ' + (cls || '') + '" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  DS4.fmt = (v, d) => (Number.isFinite(v) ? v.toFixed(d == null ? 3 : d) : '—');

  DS4.ago = (epoch) => {
    if (!epoch) return 'never';
    const s = Math.max(0, Date.now() / 1000 - epoch);
    if (s < 5) return 'just now';
    if (s < 60) return Math.round(s) + ' s ago';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  };

  /* The page runs inside pywebview. Opened in a plain browser there is no bridge,
     and the UI says so instead of inventing data. */
  DS4.hasBridge = () => !!(window.pywebview && window.pywebview.api);
  DS4.call = (name, ...args) => {
    if (!DS4.hasBridge() || typeof window.pywebview.api[name] !== 'function') {
      return Promise.reject(new Error('no-bridge'));
    }
    return window.pywebview.api[name](...args);
  };

  let toastTimer = null;
  DS4.toast = (msg, kind) => {
    const el = DS4.$('toast');
    el.textContent = msg;
    el.className = 'toast show' + (kind ? ' ' + kind : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = 'toast' + (kind ? ' ' + kind : ''); }, 3600);
  };
  /* Convert a bridge result into a toast. */
  DS4.report = (res, okText) => {
    if (!res) return;
    DS4.toast(res.ok ? (okText || res.message || 'Done.') : (res.message || 'That did not work.'), res.ok ? 'ok' : 'bad');
  };

  /* Cached theme colours for canvas drawing. */
  DS4.colors = {};
  DS4.readColors = () => {
    const cs = getComputedStyle(document.body);
    const g = (n) => cs.getPropertyValue(n).trim();
    Object.assign(DS4.colors, {
      accent: g('--accent'), glow: g('--accent-glow'), soft: g('--accent-soft'), line: g('--line'), line2: g('--line-2'),
      dim: g('--dim'), muted: g('--muted'), text: g('--text'), ok: g('--ok'), warn: g('--warn'), bad: g('--bad'), panel: g('--panel'),
      bg: g('--bg-raise'),
    });
  };
})();
