/* Builds the DualShock 4 SVG and updates it from live frames. Geometry: viewBox 900x540. */
(function () {
  'use strict';
  const DS4 = window.DS4;
  const MIRROR = 'matrix(-1 0 0 1 900 0)';
  const FACE = { triangle: '#44d9b4', circle: '#ff6b81', cross: '#5aa8ff', square: '#e48bff' };

  function build(prefix, opts) {
    const p = prefix + '-';
    const mini = !!(opts && opts.mini);
    const sym = {
      triangle: (x, y) => '<path class="sym" d="M' + x + ' ' + (y - 8) + 'l8 14h-16z"/>',
      circle: (x, y) => '<circle class="sym" cx="' + x + '" cy="' + y + '" r="7" style="fill:none"/>',
      cross: (x, y) => '<path class="sym" d="M' + (x - 7) + ' ' + (y - 7) + 'l14 14M' + (x + 7) + ' ' + (y - 7) + 'l-14 14"/>',
      square: (x, y) => '<rect class="sym" x="' + (x - 7) + '" y="' + (y - 7) + '" width="14" height="14" rx="1.5" style="fill:none"/>',
    };
    const face = (name, x, y) => '<g class="key face" data-btn="' + name + '" style="--c:' + FACE[name] + '"><circle cx="' + x + '" cy="' + y + '" r="18.5"/>' + sym[name](x, y) + '</g>';
    const dp = (name, d, chev) => '<g class="key dp" data-btn="' + name + '"><path class="k" d="' + d + '"/><path class="chev" d="' + chev + '"/></g>';
    const stick = (btn, cx, cy) => '<g class="key stick" data-btn="' + btn + '" data-cx="' + cx + '" data-cy="' + cy + '">' +
      '<circle class="well" cx="' + cx + '" cy="' + cy + '" r="45"/>' +
      '<g class="cap" transform="translate(0 0)"><circle class="capface" cx="' + cx + '" cy="' + cy + '" r="31"/><circle class="caprim" cx="' + cx + '" cy="' + cy + '" r="21"/>' +
      '<circle class="caprim" cx="' + cx + '" cy="' + cy + '" r="9"/></g></g>';
    const shoulder = (btn, mirror) => '<g class="key" data-btn="' + btn + '"' + (mirror ? ' transform="' + MIRROR + '"' : '') + '><path class="sh" d="M214 128C212 102 228 86 252 84L322 93C335 95 340 104 337 114L331 127Z"/></g>';
    const trigger = (btn, mirror) => '<g class="key" data-btn="' + btn + '"' + (mirror ? ' transform="' + MIRROR + '"' : '') + '>' +
      '<path class="tbase" d="M236 88C236 62 246 44 266 42L318 50C330 52 334 60 332 72L330 90Z"/>' +
      '<rect class="tfill" data-fill="' + btn + '" x="230" y="90" width="110" height="0" clip-path="url(#' + p + 'clip)"/></g>';
    const tlab = (btn, x) => '<text class="tlabel" data-tl="' + btn + '" x="' + x + '" y="28">' + btn.toUpperCase() + '</text>';
    const bodyPath = 'M450 118C405 118 360 112 316 108C270 104 236 112 214 138C188 168 160 250 138 352C124 418 126 470 166 486C204 500 238 478 262 432C282 394 312 382 352 380C392 378 420 380 450 380';

    return '<svg class="pad' + (mini ? ' mini' : '') + '" viewBox="0 0 900 540" role="img" aria-label="DualShock 4 controller">' +
      '<defs><linearGradient id="' + p + 'body" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--pad-top)"/><stop offset="1" stop-color="var(--pad-bot)"/></linearGradient>' +
      '<clipPath id="' + p + 'clip"><path d="M236 88C236 62 246 44 266 42L318 50C330 52 334 60 332 72L330 90Z"/></clipPath></defs>' +
      /* ground shadow */
      '<ellipse cx="450" cy="508" rx="290" ry="18" fill="#000" opacity=".35"/>' +
      /* triggers + shoulders sit behind the body */
      trigger('l2', false) + trigger('r2', true) + shoulder('l1', false) + shoulder('r1', true) +
      /* body: left half path mirrored to make the right half */
      '<path class="body" fill="url(#' + p + 'body)" d="' + bodyPath + 'L450 380" />' +
      '<path class="body" fill="url(#' + p + 'body)" transform="' + MIRROR + '" d="' + bodyPath + 'L450 380" />' +
      '<path class="sheen" d="M232 140C206 172 178 252 158 346" /><path class="sheen" transform="' + MIRROR + '" d="M232 140C206 172 178 252 158 346"/>' +
      /* light bar */
      '<path class="lightbar" d="M366 127Q450 134 534 127"/>' +
      /* touchpad */
      '<g class="key touchpad" data-btn="touchpad"><rect class="tp" x="352" y="142" width="196" height="100" rx="16"/>' +
      '<path class="tpgrid" d="M352 192h196M450 142v100" opacity=".7"/>' +
      '<circle class="finger" data-finger="0" r="11" cx="450" cy="192"/><circle class="finger" data-finger="1" r="11" cx="450" cy="192"/></g>' +
      /* share / options */
      '<g class="key small" data-btn="share"><rect x="311" y="150" width="15" height="38" rx="7.5"/></g>' +
      '<g class="key small" data-btn="options"><rect x="574" y="150" width="15" height="38" rx="7.5"/></g>' +
      /* d-pad */
      '<circle class="recess" cx="262" cy="218" r="58"/>' +
      dp('dpad-up', 'M248 174h28v36l-14 9-14-9z', 'M255 196l7-7 7 7') +
      dp('dpad-down', 'M248 262h28v-36l-14-9-14 9z', 'M255 240l7 7 7-7') +
      dp('dpad-left', 'M218 204v28h36l9-14-9-14z', 'M240 211l-7 7 7 7') +
      dp('dpad-right', 'M306 204v28h-36l-9-14 9-14z', 'M284 211l7 7-7 7') +
      /* face buttons */
      '<circle class="recess" cx="638" cy="218" r="62"/>' +
      face('triangle', 638, 178) + face('circle', 678, 218) + face('cross', 638, 258) + face('square', 598, 218) +
      /* sticks, PS button, speaker */
      stick('l3', 357, 332) + stick('r3', 543, 332) +
      '<g class="key ps" data-btn="ps"><circle cx="450" cy="284" r="16"/><path d="M445 277v15l11-7.5z"/></g>' +
      '<g class="speaker">' + [0, 1, 2].map((r) => [0, 1, 2, 3, 4].map((c) => '<circle cx="' + (430 + c * 10) + '" cy="' + (330 + r * 9) + '" r="2"/>').join('')).join('') + '</g>' +
      (mini ? '' : tlab('l2', 283) + tlab('r2', 617)) +
      '</svg>';
  }

  /* Live view bound to a built SVG. */
  function View(host, prefix) {
    host.innerHTML = build(prefix || 'live');
    this.svg = host.querySelector('svg');
    this.keys = {};
    DS4.$$('[data-btn]', this.svg).forEach((el) => { this.keys[el.dataset.btn] = el; });
    this.fills = {};
    DS4.$$('[data-fill]', this.svg).forEach((el) => { this.fills[el.dataset.fill] = el; });
    this.labels = {};
    DS4.$$('[data-tl]', this.svg).forEach((el) => { this.labels[el.dataset.tl] = el; });
    this.caps = {
      l: this.keys.l3.querySelector('.cap'), r: this.keys.r3.querySelector('.cap'),
    };
    this.fingers = DS4.$$('[data-finger]', this.svg);
    this.on = {};
  }
  const TRAVEL = 17;
  const FILL_Y0 = 90, FILL_H = 52;   /* trigger fill grows upward from the base */
  View.prototype.setLive = function (live) { this.svg.classList.toggle('live', !!live); };
  View.prototype.update = function (f) {
    const down = new Set(f.down || []);
    const axes = f.axes || {};
    for (const name of Object.keys(this.keys)) {
      let pressed = down.has(name);
      if (name === 'l2' || name === 'r2') pressed = pressed || (axes[name] || 0) > 0.04;
      if (this.on[name] !== pressed) {
        this.on[name] = pressed;
        this.keys[name].classList.toggle('on', pressed);
      }
    }
    for (const t of ['l2', 'r2']) {
      const v = DS4.clamp(axes[t] || 0, 0, 1);
      const analog = f.analog && f.analog[t];
      const digital = down.has(t);
      const level = analog ? v : (digital ? 1 : 0);
      this.fills[t].setAttribute('y', String(FILL_Y0 - FILL_FH(level)));
      this.fills[t].setAttribute('height', String(FILL_FH(level)));
      const lab = this.labels[t];
      if (lab) {
        lab.textContent = t.toUpperCase() + ' ' + (analog ? Math.round(v * 100) + '%' : (digital ? 'on' : '—'));
        lab.classList.toggle('hot', level > 0.04);
      }
    }
    this.caps.l.setAttribute('transform', 'translate(' + (DS4.clamp(axes.lx || 0, -1, 1) * TRAVEL).toFixed(1) + ' ' + (DS4.clamp(axes.ly || 0, -1, 1) * TRAVEL).toFixed(1) + ')');
    this.caps.r.setAttribute('transform', 'translate(' + (DS4.clamp(axes.rx || 0, -1, 1) * TRAVEL).toFixed(1) + ' ' + (DS4.clamp(axes.ry || 0, -1, 1) * TRAVEL).toFixed(1) + ')');
    const touch = f.touch || [];
    this.fingers.forEach((el, i) => {
      const t = touch[i];
      const act = !!(t && t.active);
      el.classList.toggle('act', act);
      if (act) {
        el.setAttribute('cx', (352 + 11 + t.x * (196 - 22)).toFixed(1));
        el.setAttribute('cy', (142 + 11 + t.y * (100 - 22)).toFixed(1));
      }
    });
  };
  function FILL_FH(level) { return Math.round(FILL_H * level); }

  DS4.ControllerView = View;
  DS4.buildController = build;
})();
