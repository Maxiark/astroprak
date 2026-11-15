/**
 * AstroPlot v2.0 — единая библиотека интерактивных астрономических графиков и снимков.
 * Полностью обратно совместима с виджетами astroprak v1.0.2 и включает все возможности
 * оригинального компонента Plot.tsx из astrosite_base:
 * - серии точек 'dot' (.pt.a), полые кольца 'ring' (.pt.b) и спектральные линии 'line' (.series-line);
 * - отрезки треков звёзд `segments` (с прилипанием визира к обоим концам следа);
 * - сферическую метрику `spherical: true` (угловая длина отрезка с поправкой на cos δ);
 * - поиск локального экстремума по ближайшей серии (nearestSeries) с окном ±3W и медианой;
 * - метаданные форматирования осей `plot` (key, unit, decimals, sign);
 * - сохранение и восстановление пользовательских измерений (setMarks / getMarks).
 */
class AstroPlot {
  constructor(options) {
    this.container = typeof options.container === 'string'
      ? document.querySelector(options.container)
      : options.container;

    this.W = options.width || 640;
    this.H = options.height || 360;
    this.PL = options.paddingLeft || 56;
    this.PR = options.paddingRight || 14;
    this.PT = options.paddingTop || 14;
    this.PB = options.paddingBottom || 40;

    this.SNAP = options.snapRadius || 12;
    this.EXTREMUM_WINDOW = options.extremumWindow || 0.08;

    this.data = options.data || null;
    this.currentTool = options.initialTool || 'cursor';
    this.disabled = !!options.disabled;

    this.reading = null;
    this.pending = null;
    this.marks = [];
    this.nextMarkId = 1;
    this.touching = false;

    this.onReading = options.onReading || null;
    this.onMarksChange = options.onMarksChange || null;
    this.onMove = options.onMove || null;

    this._initDOM();
    this._bindEvents();
    if (this.data && this.data.axes) {
      this.render();
    }
  }

  setData(data) {
    this.data = data;
    this.render();
  }

  setDisabled(disabled) {
    this.disabled = !!disabled;
    if (this.disabled) {
      this.reading = null;
      this.pending = null;
    }
    if (this.svg) {
      this.svg.setAttribute('class', `rv tool-${this.currentTool}${this.disabled ? ' is-disabled' : ''}`);
    }
    this.render();
  }

  setTool(tool) {
    this.currentTool = tool;
    this.pending = null;
    if (this.svg) {
      this.svg.setAttribute('class', `rv tool-${tool}${this.disabled ? ' is-disabled' : ''}`);
    }
    this.render();
  }

  setMarks(marks) {
    if (!Array.isArray(marks)) return;
    this.marks = marks.map((m, idx) => ({ ...m, id: m.id || idx + 1 }));
    this.nextMarkId = this.marks.reduce((acc, m) => Math.max(acc, m.id || 0), 0) + 1;
    if (this.onMarksChange) this.onMarksChange(this.marks);
    this.render();
  }

  getMarks() {
    return this.marks.slice();
  }

  clearMarks() {
    this.marks = [];
    this.pending = null;
    this.nextMarkId = 1;
    if (this.onMarksChange) this.onMarksChange(this.marks);
    this.render();
  }

  removeMark(idxOrId, byId = false) {
    if (byId) {
      this.marks = this.marks.filter(m => m.id !== idxOrId);
    } else {
      this.marks.splice(idxOrId, 1);
    }
    if (this.onMarksChange) this.onMarksChange(this.marks);
    this.render();
  }

  _initDOM() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="plot-container">
        <svg class="rv tool-${this.currentTool}${this.disabled ? ' is-disabled' : ''}" viewBox="0 0 ${this.W} ${this.H}" style="touch-action: none;"></svg>
      </div>
    `;
    this.svg = this.container.querySelector('svg');
  }

  _getBounds() {
    if (!this.data || !this.data.axes) {
      return { xlo: 0, xhi: 1, xinv: false, ylo: 0, yhi: 1, yinv: false };
    }
    const ax = this.data.axes;
    return {
      xlo: Math.min(ax.x.min, ax.x.max),
      xhi: Math.max(ax.x.min, ax.x.max),
      xinv: !!ax.x.inverted,
      ylo: Math.min(ax.y.min, ax.y.max),
      yhi: Math.max(ax.y.min, ax.y.max),
      yinv: !!ax.y.inverted
    };
  }

  _getMeta() {
    const plotMeta = (this.data && this.data.plot) || {};
    const ax = (this.data && this.data.axes) || { x: { tick: 1 }, y: { tick: 1 } };
    const xdecDefault = this._tickDecimals(ax.x ? ax.x.tick : 1);
    const ydecDefault = this._tickDecimals(ax.y ? ax.y.tick : 1);
    return {
      caption: plotMeta.caption || '',
      x: {
        key: (plotMeta.x && plotMeta.x.key) || 'x',
        unit: (plotMeta.x && plotMeta.x.unit) || '',
        decimals: (plotMeta.x && typeof plotMeta.x.decimals === 'number') ? plotMeta.x.decimals : Math.max(2, xdecDefault)
      },
      y: {
        key: (plotMeta.y && plotMeta.y.key) || 'y',
        unit: (plotMeta.y && plotMeta.y.unit) || '',
        decimals: (plotMeta.y && typeof plotMeta.y.decimals === 'number') ? plotMeta.y.decimals : Math.max(2, ydecDefault),
        sign: !!(plotMeta.y && plotMeta.y.sign)
      }
    };
  }

  _tickDecimals(tick) {
    if (!tick || tick <= 0) return 2;
    return Math.max(0, -Math.floor(Math.log10(tick) + 1e-9));
  }

  _fmtTick(val, decimals, sign = false) {
    const s = Number(val).toFixed(decimals).replace(/\.0+$/, '').replace(/(\.\d*?[1-9])0+$/, '$1');
    const clean = decimals === 0 ? Number(val).toFixed(0) : Number(val).toFixed(decimals);
    const out = clean.replace('-', '−');
    return sign && val > 0 ? `+${out}` : out;
  }

  sx(x) {
    const b = this._getBounds();
    return this.PL + (b.xinv ? (b.xhi - x) : (x - b.xlo)) / (b.xhi - b.xlo || 1) * (this.W - this.PL - this.PR);
  }

  sy(y) {
    const b = this._getBounds();
    return this.PT + (b.yinv ? (y - b.ylo) : (b.yhi - y)) / (b.yhi - b.ylo || 1) * (this.H - this.PT - this.PB);
  }

  invX(px) {
    const b = this._getBounds();
    const f = (px - this.PL) / (this.W - this.PL - this.PR);
    return b.xinv ? b.xhi - f * (b.xhi - b.xlo) : b.xlo + f * (b.xhi - b.xlo);
  }

  invY(py) {
    const b = this._getBounds();
    const f = (py - this.PT) / (this.H - this.PT - this.PB);
    return b.yinv ? b.ylo + f * (b.yhi - b.ylo) : b.yhi - f * (b.yhi - b.ylo);
  }

  _clamp(val, min, max) {
    return Math.min(max, Math.max(min, val));
  }

  _range(min, max, step) {
    if (!step || step <= 0) return [min, max];
    const out = [];
    const n = Math.round((max - min) / step);
    for (let i = 0; i <= n; i++) out.push(Math.round((min + i * step) * 1e9) / 1e9);
    return out;
  }

  _toSvg(e) {
    if (!this.svg) return null;
    const pt = this.svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = this.svg.getScreenCTM();
    if (!ctm) return null;
    return pt.matrixTransform(ctm.inverse());
  }

  /** Угловая или евклидова длина отрезка: на сферическом поле Δα берётся с cos δ. */
  segmentLength(x1, y1, x2, y2) {
    const isSpherical = !!(this.data && this.data.spherical);
    const k = isSpherical ? Math.cos(((y1 + y2) / 2) * Math.PI / 180) : 1;
    return Math.hypot((x2 - x1) * k, y2 - y1);
  }

  _readingAt(px, py) {
    if (!this.data) return null;
    const b = this._getBounds();
    const meta = this._getMeta();
    const xround = Math.pow(10, meta.x.decimals + 1);
    const yround = Math.pow(10, meta.y.decimals);

    let best = null;

    // 1. Прилипание к концам следов (segments, например в comet-trails)
    const segments = this.data.segments || [];
    for (const set of segments) {
      if (!Array.isArray(set.items)) continue;
      set.items.forEach(([x1, y1, x2, y2], idx) => {
        for (const [x, y] of [[x1, y1], [x2, y2]]) {
          const d = Math.hypot(this.sx(x) - px, this.sy(y) - py);
          if (d <= this.SNAP && (!best || d < best.d)) {
            best = { d, s: set.id, i: idx, x, y, isSegmentEnd: true };
          }
        }
      });
    }

    // 2. Прилипание к точкам серий (series)
    const series = this.data.series || [];
    for (const s of series) {
      if (!Array.isArray(s.points)) continue;
      s.points.forEach(([x, y], i) => {
        const d = Math.hypot(this.sx(x) - px, this.sy(y) - py);
        if (d <= this.SNAP && (!best || d < best.d)) {
          best = { d, s: s.id, i, x, y, isSegmentEnd: false };
        }
      });
    }

    if (best) {
      return { x: best.x, y: best.y, series: best.s, index: best.i };
    }

    const x = this._clamp(this.invX(px), b.xlo, b.xhi);
    const y = this._clamp(this.invY(py), b.ylo, b.yhi);
    return {
      x: Math.round(x * xround) / xround,
      y: Math.round(y * yround) / yround,
      series: null,
      index: null
    };
  }

  _nearestSeries(x, y) {
    const series = (this.data && this.data.series) || [];
    if (!series.length) return null;
    let best = series[0];
    let bd = Infinity;
    for (const s of series) {
      if (!Array.isArray(s.points)) continue;
      for (const [p, q] of s.points) {
        const d = Math.hypot(this.sx(p) - this.sx(x), this.sy(q) - this.sy(y));
        if (d < bd) {
          bd = d;
          best = s;
        }
      }
    }
    return best;
  }

  _extremumNear(r) {
    if (!r || !this.data || !this.data.series || !this.data.series.length) return null;
    const b = this._getBounds();
    const s = (r.series && this.data.series.find(z => z.id === r.series)) || this._nearestSeries(r.x, r.y);
    if (!s || !Array.isArray(s.points) || !s.points.length) return null;

    const win = this.EXTREMUM_WINDOW * (b.xhi - b.xlo);
    const windowPts = s.points.filter(([p]) => Math.abs(p - r.x) < win);
    if (!windowPts.length) return null;

    const wide = s.points.filter(([p]) => Math.abs(p - r.x) < 3 * win);
    const mean = windowPts.reduce((acc, [, y]) => acc + y, 0) / windowPts.length;
    let baseline = wide.length ? wide.reduce((acc, [, y]) => acc + y, 0) / wide.length : mean;
    if (wide.length === windowPts.length) {
      const allY = s.points.map(([, y]) => y).sort((a, c) => a - c);
      baseline = allY[Math.floor(allY.length / 2)];
    }

    const larger = mean > baseline;
    const [x, y] = windowPts.reduce((acc, p) => (larger ? p[1] > acc[1] : p[1] < acc[1]) ? p : acc);
    const kind = larger !== b.yinv ? 'максимум' : 'минимум';
    return { kind, series: s.id, x, y };
  }

  _commitMark(r) {
    if (!r || this.disabled) return;

    if (this.currentTool === 'extremum') {
      const ext = this._extremumNear(r);
      if (ext) {
        this.marks.push({
          id: this.nextMarkId++,
          kind: ext.kind,
          series: ext.series || '—',
          x: ext.x,
          y: ext.y
        });
      }
    } else if (this.currentTool === 'segment') {
      if (!this.pending) {
        this.pending = r;
      } else {
        const dx = r.x - this.pending.x;
        const dy = r.y - this.pending.y;
        const dt = Math.abs(dx);
        const segLen = this.segmentLength(this.pending.x, this.pending.y, r.x, r.y);
        const isSphericalOr2D = !!(this.data && (this.data.spherical || (this.data.segments && this.data.segments.length)));
        this.marks.push({
          id: this.nextMarkId++,
          kind: 'отрезок',
          series: '—',
          x: this.pending.x,
          y: this.pending.y,
          x2: r.x,
          y2: r.y,
          dx: dx,
          dy: dy,
          dt: dt,
          sphericalLen: segLen,
          // Для обратной совместимости с cepheid-pl (где m.len = Δt) и сферическими полями (где m.len = угловая длина):
          len: isSphericalOr2D ? segLen : dt
        });
        this.pending = null;
      }
    } else {
      this.marks.push({
        id: this.nextMarkId++,
        kind: 'точка',
        series: r.series || '—',
        x: r.x,
        y: r.y
      });
    }

    if (this.onMarksChange) this.onMarksChange(this.marks);
    this.render();
  }

  _bindEvents() {
    if (!this.svg) return;
    const onMove = (e) => {
      if (this.disabled) return;
      const p = this._toSvg(e);
      if (!p) return;
      const inside = p.x >= this.PL && p.x <= this.W - this.PR && p.y >= this.PT && p.y <= this.H - this.PB;
      this.reading = inside ? this._readingAt(p.x, p.y) : null;

      if (this.onReading) {
        const ext = (this.reading && this.currentTool === 'extremum') ? this._extremumNear(this.reading) : null;
        this.onReading({ reading: this.reading, pending: this.pending, extremum: ext });
      }
      if (this.reading && this.onMove) {
        this.onMove(this.reading);
      }
      this.render();
    };

    this.svg.addEventListener('pointerdown', (e) => {
      if (this.disabled) return;
      if (e.pointerType === 'touch') {
        this.touching = true;
        this.svg.setPointerCapture?.(e.pointerId);
      }
      onMove(e);
    });

    this.svg.addEventListener('pointermove', onMove);

    this.svg.addEventListener('pointerup', (e) => {
      if (this.disabled) return;
      const p = this._toSvg(e);
      const inside = p && p.x >= this.PL && p.x <= this.W - this.PR && p.y >= this.PT && p.y <= this.H - this.PB;
      if (e.pointerType === 'touch') {
        this.touching = false;
        if (inside) this._commitMark(this._readingAt(p.x, p.y));
        this.reading = null;
        if (this.onReading) this.onReading({ reading: null, pending: this.pending, extremum: null });
        this.render();
        return;
      }
      if (inside) this._commitMark(this._readingAt(p.x, p.y));
    });

    this.svg.addEventListener('pointerleave', () => {
      if (!this.touching) {
        this.reading = null;
        if (this.onReading) this.onReading({ reading: null, pending: this.pending, extremum: null });
        this.render();
      }
    });
  }

  _renderSeriesAndMarks() {
    let html = '';

    // 1. Следы звёзд (segments)
    if (this.data && Array.isArray(this.data.segments)) {
      this.data.segments.forEach(set => {
        if (!Array.isArray(set.items)) return;
        set.items.forEach(([x1, y1, x2, y2]) => {
          html += `<line class="trail" x1="${this.sx(x1).toFixed(2)}" y1="${this.sy(y1).toFixed(2)}" x2="${this.sx(x2).toFixed(2)}" y2="${this.sy(y2).toFixed(2)}" />`;
        });
      });
    }

    // 2. Точки и линии серий (series)
    if (this.data && Array.isArray(this.data.series)) {
      this.data.series.forEach((s, sIdx) => {
        if (!Array.isArray(s.points)) return;
        if (s.marker === 'line') {
          const pts = s.points.map(([x, y]) => `${this.sx(x).toFixed(1)},${this.sy(y).toFixed(1)}`).join(' ');
          html += `<polyline class="series-line" points="${pts}"/>`;
        } else {
          const cls = s.marker === 'ring' ? 'pt b' : (s.marker === 'dot' ? 'pt a' : (sIdx === 0 ? 'pt a' : 'pt b'));
          const r = s.marker === 'ring' ? '3.4' : '3.2';
          s.points.forEach(([x, y]) => {
            html += `<circle class="${cls}" cx="${this.sx(x).toFixed(1)}" cy="${this.sy(y).toFixed(1)}" r="${r}"/>`;
          });
        }
      });
    }

    // 3. Зафиксированные отметки и отрезки (marks)
    const isSpherical = !!(this.data && this.data.spherical);
    this.marks.forEach(m => {
      if (m.kind === 'отрезок') {
        const x1 = this.sx(m.x), y1 = this.sy(m.y);
        const x2 = this.sx(m.x2), y2 = this.sy(m.y2);
        html += `<g class="mark-seg">
          <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" />
          <circle cx="${x1}" cy="${y1}" r="4" />
          <circle cx="${x2}" cy="${y2}" r="4" />
          ${!isSpherical ? `
            <line x1="${x1}" y1="${this.H - this.PB}" x2="${x2}" y2="${this.H - this.PB}" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" />
            <line x1="${x1}" y1="${y1}" x2="${x1}" y2="${this.H - this.PB}" stroke="var(--accent)" stroke-width="1" stroke-dasharray="2,2" />
            <line x1="${x2}" y1="${y2}" x2="${x2}" y2="${this.H - this.PB}" stroke="var(--accent)" stroke-width="1" stroke-dasharray="2,2" />
          ` : ''}
          <text x="${(x1 + x2) / 2}" y="${Math.min(y1, y2) - 8}" font-size="11" font-weight="bold" fill="var(--accent)" text-anchor="middle">#${m.id}</text>
        </g>`;
      } else {
        const tag = m.kind === 'максимум' ? ' max' : m.kind === 'минимум' ? ' min' : '';
        html += `<g class="mark">
          <circle cx="${this.sx(m.x)}" cy="${this.sy(m.y)}" r="7" />
          <text x="${this.sx(m.x) + 9}" y="${this.sy(m.y) - 8}">${m.id}${tag}</text>
        </g>`;
      }
    });

    if (this.pending) {
      html += `<circle class="pending" cx="${this.sx(this.pending.x)}" cy="${this.sy(this.pending.y)}" r="5"/>`;
      if (this.reading) {
        html += `<line x1="${this.sx(this.pending.x)}" y1="${this.sy(this.pending.y)}" x2="${this.sx(this.reading.x)}" y2="${this.sy(this.reading.y)}" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="4,3" />`;
      }
    }

    if (this.reading) {
      const lx = this.sx(this.reading.x);
      const ly = this.sy(this.reading.y);
      html += `<g class="cursor">
        <line x1="${lx}" y1="${this.PT}" x2="${lx}" y2="${this.H - this.PB}" />
        <line x1="${this.PL}" y1="${ly}" x2="${this.W - this.PR}" y2="${ly}" />
        ${this.reading.series ? `<circle cx="${lx}" cy="${ly}" r="6" />` : ''}
      </g>`;
    }

    return html;
  }

  render() {
    if (!this.svg) return;
    if (!this.data || !this.data.axes) return;

    const ax = this.data.axes;
    const b = this._getBounds();
    const meta = this._getMeta();

    const ticksX = this._range(b.xlo, b.xhi, ax.x.tick || 1);
    const ticksY = this._range(b.ylo, b.yhi, ax.y.tick || 1);
    const xdec = this._tickDecimals(ax.x.tick || 1);
    const ydec = this._tickDecimals(ax.y.tick || 1);

    let html = '';

    ticksY.forEach(y => {
      html += `<line class="grid" x1="${this.PL}" y1="${this.sy(y)}" x2="${this.W - this.PR}" y2="${this.sy(y)}" />`;
      html += `<text class="tick" x="${this.PL - 6}" y="${this.sy(y) + 4}" text-anchor="end">${this._fmtTick(y, ydec, meta.y.sign)}</text>`;
    });

    ticksX.forEach(x => {
      html += `<line class="grid" x1="${this.sx(x)}" y1="${this.PT}" x2="${this.sx(x)}" y2="${this.H - this.PB}" />`;
      html += `<text class="tick" x="${this.sx(x)}" y="${this.H - this.PB + 16}" text-anchor="middle">${this._fmtTick(x, xdec, false)}</text>`;
    });

    html += `<rect class="axes" x="${this.PL}" y="${this.PT}" width="${this.W - this.PL - this.PR}" height="${this.H - this.PT - this.PB}" />`;
    html += `<text class="label" x="${(this.PL + this.W - this.PR) / 2}" y="${this.H - 6}" text-anchor="middle">${ax.x.label || ''}</text>`;
    html += `<text class="label" transform="translate(14 ${(this.PT + this.H - this.PB) / 2}) rotate(-90)" text-anchor="middle">${ax.y.label || ''}</text>`;

    const seriesContent = this._renderSeriesAndMarks();
    html += seriesContent;

    const showLoupe = this.reading && (this.currentTool === 'loupe' || this.touching);
    if (showLoupe) {
      const lx = this.sx(this.reading.x);
      const ly = this.sy(this.reading.y);
      const loupeR = 46, loupeK = 2.5;
      const loupeDy = this.touching ? -78 : -64;
      const loupeCx = this._clamp(lx, this.PL + loupeR, this.W - this.PR - loupeR);
      const loupeCy = Math.max(this.PT + loupeR, ly + loupeDy);

      html += `<defs>
        <clipPath id="loupe-clip">
          <circle cx="${loupeCx}" cy="${loupeCy}" r="${loupeR}" />
        </clipPath>
      </defs>`;

      html += `<g class="loupe">
        <circle class="loupe-bg" cx="${loupeCx}" cy="${loupeCy}" r="${loupeR}" />
        <g clip-path="url(#loupe-clip)">
          <g transform="translate(${loupeCx} ${loupeCy}) scale(${loupeK}) translate(${-lx} ${-ly})">
            ${ticksY.map(y => `<line class="grid" x1="${this.PL}" y1="${this.sy(y)}" x2="${this.W - this.PR}" y2="${this.sy(y)}" />`).join('')}
            ${ticksX.map(x => `<line class="grid" x1="${this.sx(x)}" y1="${this.PT}" x2="${this.sx(x)}" y2="${this.H - this.PB}" />`).join('')}
            ${seriesContent}
          </g>
        </g>
        <circle class="loupe-ring" cx="${loupeCx}" cy="${loupeCy}" r="${loupeR}" />
        <line class="crosshair" x1="${loupeCx - 10}" y1="${loupeCy}" x2="${loupeCx + 10}" y2="${loupeCy}" />
        <line class="crosshair" x1="${loupeCx}" y1="${loupeCy - 10}" x2="${loupeCx}" y2="${loupeCy + 10}" />
      </g>`;
    }

    this.svg.innerHTML = html;
  }
}

const AstrositeBridge = {
  lastSentHeight: 0,
  resizeTimer: null,

  initAutoResize(targetId = 'widget-root') {
    const report = () => {
      if (this.resizeTimer) clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(() => {
        const root = document.getElementById(targetId);
        const contentH = root ? Math.ceil(root.getBoundingClientRect().height) : document.body.offsetHeight;
        if (Math.abs(contentH - this.lastSentHeight) > 6) {
          this.lastSentHeight = contentH;
          window.parent.postMessage({
            type: 'ASTROSITE_FRAME_RESIZE',
            height: contentH + 24
          }, '*');
        }
      }, 50);
    };

    window.addEventListener('load', report);
    window.addEventListener('resize', report);
    if (window.ResizeObserver) {
      const target = document.getElementById(targetId) || document.body;
      new ResizeObserver(() => report()).observe(target);
    }
    report();
  },

  forceResize(targetId = 'widget-root') {
    const root = document.getElementById(targetId);
    const contentH = root ? Math.ceil(root.getBoundingClientRect().height) : document.body.offsetHeight;
    this.lastSentHeight = contentH;
    window.parent.postMessage({
      type: 'ASTROSITE_FRAME_RESIZE',
      height: contentH + 28
    }, '*');
  },

  sendAnswerChange(answers) {
    window.parent.postMessage({
      type: 'ASTROSITE_ANSWER_CHANGE',
      answers: answers
    }, '*');
  },

  submitAttempt(answers) {
    window.parent.postMessage({
      type: 'ASTROSITE_SUBMIT_ATTEMPT',
      answers: answers
    }, '*');
  }
};
// Явный экспорт в глобальный объект для виджетов в iframe
if (typeof window !== 'undefined') {
  window.AstroPlot = AstroPlot;
  window.AstrositeBridge = AstrositeBridge;
}
if (typeof globalThis !== 'undefined') {
  globalThis.AstroPlot = AstroPlot;
  globalThis.AstrositeBridge = AstrositeBridge;
}
