/**
 * LegacyTaskWidget v2.0 — универсальный фронтенд-движок для рендеринга всех задач `astrosim`
 * (как генерируемых, так и архивных ВсОШ) внутри песочницы `<iframe>` платформы `astroprak`.
 *
 * Полностью воспроизводит функциональность `Workbench.tsx`, `Plot.tsx`, `Sheet.tsx`, `Verdict.tsx`,
 * `Content.tsx`, `ArchiveTask.tsx` и `FigurePanel.tsx` старого проекта `astrosite_base` без React-зависимостей.
 */
const LegacyTaskWidget = {
  rootEl: null,
  plot: null,
  taskData: null,
  answers: {},
  marks: [],
  measurements: [],
  isSubmitted: false,
  grading: null,
  sessionCode: '',
  saveTimer: null,
  clockTimer: null,
  startedAtMs: Date.now(),
  pendingInitPayload: null,

  TOOL_LABELS: {
    cursor: 'Курсор',
    loupe: 'Лупа',
    extremum: 'Экстремум',
    segment: 'Отрезок'
  },

  mount(selector = '#widget-root') {
    this.rootEl = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (!this.rootEl) return;

    this.rootEl.innerHTML = `<div class="lw-wrap"><div class="statement-box">Загрузка данных задачи...</div></div>`;

    window.addEventListener('message', (event) => this._onMessage(event));
    
    // Инициализация авторесайза с поддержкой обоих вариантов доступа к Bridge
    const bridge = window.AstrositeBridge || (typeof AstrositeBridge !== 'undefined' ? AstrositeBridge : null);
    if (bridge && typeof bridge.initAutoResize === 'function') {
      bridge.initAutoResize(this.rootEl.id || 'widget-root');
    } else {
      // Резервный наблюдатель на случай отсутствия моста
      const report = () => this._notifyResize();
      window.addEventListener('load', report);
      window.addEventListener('resize', report);
      if (window.ResizeObserver) {
        new ResizeObserver(report).observe(this.rootEl);
      }
      report();
    }

    if (this.pendingInitPayload) {
      const p = this.pendingInitPayload;
      this.pendingInitPayload = null;
      this._initFromPayload(p);
    }
  },

  /** Форматирование чисел в русской традиции (запятая, знак + при sign=true) */
  num(x, decimals = 2, sign = false) {
    if (x === null || x === undefined || Number.isNaN(Number(x))) return '—';
    const val = Number(x);
    const s = val.toFixed(decimals).replace('.', ',').replace('-', '−');
    return sign && val > 0 ? `+${s}` : s;
  },

  /** Форматирование подписей с нижними/верхними индексами и базовым LaTeX ($...$) */
  formatMathAndSubscripts(rawText) {
    if (!rawText) return '';
    let s = String(rawText)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Блочные и строчные формулы $...$
    s = s.replace(/\$\$([^$]+)\$\$/g, (_, tex) => `<div class="lw-math-block">${this._renderSimpleTex(tex)}</div>`);
    s = s.replace(/\$([^$]+)\$/g, (_, tex) => `<span class="lw-math-inline">${this._renderSimpleTex(tex)}</span>`);

    // Индексы вида K_A, M_☉, R_⊕, T_eq, θ_max, v_1, h_1 (вне тегов)
    s = s.replace(/([A-Za-zА-Яа-яθλμσπδvKMRTnhr])_([A-Za-z0-9☉⊕*]+|max|min|eq|t|p|hb|ha)/g, '$1<sub>$2</sub>');
    return s;
  },

  _renderSimpleTex(tex) {
    return String(tex)
      .replace(/\\cdot/g, '·')
      .replace(/\\pm/g, '±')
      .replace(/\\approx/g, '≈')
      .replace(/\\le/g, '≤')
      .replace(/\\ge/g, '≥')
      .replace(/\\neq/g, '≠')
      .replace(/\\times/g, '×')
      .replace(/\\alpha/g, 'α')
      .replace(/\\beta/g, 'β')
      .replace(/\\gamma/g, 'γ')
      .replace(/\\delta/g, 'δ')
      .replace(/\\theta/g, 'θ')
      .replace(/\\lambda/g, 'λ')
      .replace(/\\mu/g, 'μ')
      .replace(/\\pi/g, 'π')
      .replace(/\\sigma/g, 'σ')
      .replace(/\\psi/g, 'ψ')
      .replace(/\\odot/g, '☉')
      .replace(/\\oplus/g, '⊕')
      .replace(/\{,\}/g, ',')
      .replace(/\^\{([^}]+)\}/g, '<sup>$1</sup>')
      .replace(/\^([0-9+-]+)/g, '<sup>$1</sup>')
      .replace(/_\{([^}]+)\}/g, '<sub>$1</sub>')
      .replace(/_([A-Za-z0-9☉⊕*]+)/g, '<sub>$1</sub>');
  },

  _onMessage(event) {
    if (!event.data) return;
    if (event.data.type === 'ASTROSITE_INIT_DATA') {
      if (!this.rootEl) {
        this.pendingInitPayload = event.data;
        return;
      }
      this._initFromPayload(event.data);
    } else if (event.data.type === 'ASTROSITE_SUBMIT_SUCCESS') {
      const grading = event.data.grading || {
        score: event.data.score,
        max_score: event.data.max_score
      };
      this.isSubmitted = true;
      this.grading = grading;
      this._renderSubmittedState();
    }
  },

  _initFromPayload(payload) {
    const { data, draft, session_code, is_submitted, grading } = payload;
    this.taskData = data || {};
    if (session_code) this.sessionCode = session_code;
    this.isSubmitted = !!is_submitted;
    this.grading = grading || null;

    // Восстанавливаем ответы и сохранённые на графике отметки (_marks) из черновика
    this.answers = {};
    if (draft && typeof draft === 'object') {
      for (const [k, v] of Object.entries(draft)) {
        if (k === '_marks' && Array.isArray(v)) {
          this.marks = v;
        } else {
          this.answers[k] = v;
        }
      }
      if (typeof draft.measurements === 'string') {
        try {
          const parsed = JSON.parse(draft.measurements);
          if (Array.isArray(parsed)) this.measurements = parsed;
        } catch (e) {}
      }
    }

    this._renderFullLayout();

    if (this.isSubmitted) {
      this._renderSubmittedState();
    }
  },

  _renderFullLayout() {
    if (!this.rootEl || !this.taskData) return;
    const d = this.taskData;
    const isArchive = d.mode === 'legacy_archive';

    const seedBadge = !isArchive && d.seed !== undefined
      ? `<span class="lw-k">seed</span><code>${d.seed}</code>`
      : '';
    const genBadge = !isArchive && d.generator_version
      ? `<span class="lw-k">генератор</span><code>${d.task_id || ''} ${d.generator_version}</code>`
      : `<span class="lw-k">режим</span><code>архив ВсОШ</code>`;

    let statementHtml = '';
    if (isArchive) {
      statementHtml = this._buildArchiveStatementHtml(d);
    } else {
      const st = d.statement_obj || {};
      const numPrefix = d.seed !== undefined ? `<span class="lw-num">${(Number(d.seed) % 100) + 1}.</span>` : '';
      const asksList = Array.isArray(st.asks) && st.asks.length
        ? `<ol class="lw-asks">${st.asks.map(a => `<li>${this.formatMathAndSubscripts(a)}</li>`).join('')}</ol>`
        : '';
      const noteHtml = st.note
        ? `<div class="lw-note">${this.formatMathAndSubscripts(st.note)}</div>`
        : '';
      statementHtml = `
        <div class="lw-statement">
          <div class="lw-task-title">${numPrefix}${this.formatMathAndSubscripts(st.title || d.family_label || d.task_id)}</div>
          <div class="lw-statement-text">${this.formatMathAndSubscripts(st.text || d.statement || '')}</div>
          ${asksList}
          ${noteHtml}
        </div>
      `;
    }

    const hasPlot = !isArchive && d.axes && (Array.isArray(d.series) || Array.isArray(d.segments));
    const tools = Array.isArray(d.tools) && d.tools.length ? d.tools : ['cursor', 'loupe', 'extremum', 'segment'];
    const plotMeta = d.plot || { caption: '', x: { key: 'x', unit: '', decimals: 2 }, y: { key: 'y', unit: '', decimals: 2 } };

    // Легенда серий, если серий больше одной или есть треки
    let legendHtml = '';
    if (hasPlot) {
      const items = [];
      if (Array.isArray(d.segments)) {
        d.segments.forEach(seg => {
          items.push(`<span class="lw-legend-item"><span class="lw-line-seg"></span>${this.formatMathAndSubscripts(seg.label || seg.id)}</span>`);
        });
      }
      if (Array.isArray(d.series) && (d.series.length > 1 || (d.segments && d.segments.length))) {
        d.series.forEach((s, idx) => {
          const dotCls = s.marker === 'ring' ? 'lw-dot-b' : (s.marker === 'dot' ? 'lw-dot-a' : (idx === 0 ? 'lw-dot-a' : 'lw-dot-b'));
          items.push(`<span class="lw-legend-item"><span class="${dotCls}"></span>${this.formatMathAndSubscripts(s.label || s.id)}</span>`);
        });
      }
      if (items.length) {
        legendHtml = `<div class="lw-legend">${items.join('')}</div>`;
      }
    }

    const leftColHtml = hasPlot ? `
      <div class="lw-left-col">
        <div class="lw-plot-header">
          <div class="lw-plot-caption">${this.formatMathAndSubscripts(plotMeta.caption || '')}</div>
          ${legendHtml}
        </div>
        <div id="lw-plot-mount"></div>
        <div class="toolbar">
          <div class="tools" id="lw-tools-bar">
            ${tools.filter(t => this.TOOL_LABELS[t]).map((t, idx) => `
              <button type="button" id="lw-tool-${t}" data-tool="${t}" class="${idx === 0 ? 'active' : ''}">${this.TOOL_LABELS[t]}</button>
            `).join('')}
          </div>
          <div class="lw-readout-box" id="lw-readout">
            <span class="lw-k">наведите или коснитесь графика</span>
          </div>
        </div>
      </div>
    ` : `<div class="lw-left-col" id="lw-archive-figures-col">${this._buildArchiveFiguresHtml(d)}</div>`;

    const logCardHtml = hasPlot ? `
      <div class="lw-log-card">
        <div class="lw-card-head">
          <h3>Снятые значения</h3>
          <button type="button" class="lw-clear-btn" id="lw-clear-marks" style="display:none;">Очистить все</button>
        </div>
        <div id="lw-marks-body">
          <p class="lw-field-hint">Щелчок или касание сохраняет точку. Используйте инструменты, чтобы измерять значения, экстремумы и отрезки на графике.</p>
        </div>
      </div>
    ` : `
      <div class="lw-log-card" id="lw-archive-measurements-card">
        <div class="lw-card-head">
          <h3>Измерения на рисунках</h3>
        </div>
        <div id="lw-archive-measurements-body"></div>
      </div>
    `;

    const fieldsHtml = this._buildSheetFieldsHtml(d.fields || []);

    this.rootEl.innerHTML = `
      <div class="lw-wrap">
        <div class="lw-topbar">
          <div class="lw-meta-group">
            <span><span class="lw-k">семейство</span><b>${this.formatMathAndSubscripts(d.family_label || d.title || d.task_id)}</b></span>
            ${seedBadge}
            ${genBadge}
          </div>
          <div class="lw-clock" id="lw-clock-display"></div>
        </div>

        <div id="lw-verdict-top-anchor"></div>

        ${statementHtml}

        <div class="lw-grid">
          ${leftColHtml}
          <div class="lw-right-col">
            ${logCardHtml}
            <div class="lw-sheet-card">
              <div class="lw-card-head">
                <h3>Бланк ответа</h3>
                <span class="lw-k">лист 1 из 1</span>
              </div>
              <div class="lw-fields" id="lw-sheet-fields">
                ${fieldsHtml}
              </div>
              <p class="lw-note" style="margin-top: 10px;">Единицы и точность — по условию и подсказкам в полях.</p>
              <div class="lw-submit-row">
                <button type="button" class="lw-submit-btn" id="lw-btn-submit">
                  ${isArchive ? 'Сдать и открыть официальный разбор' : 'Сдать бланк'}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="session-banner" id="lw-session-banner">
          <div style="font-weight: 700; color: #166534; font-size: 14px; margin-bottom: 6px;">
            ✓ Попытка зафиксирована в системе!
          </div>
          <div style="font-size: 13px; color: #14532d; margin-bottom: 8px;">
            Скопируйте 32-значный код сессии для отчёта в электронном журнале:
          </div>
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
            <input type="text" id="lw-session-code-input" readonly
                   style="font-family: monospace; font-size: 13px; padding: 6px 10px; width: 320px; border: 1px solid #86efac; border-radius: 4px; background: #fff;">
            <button type="button" class="lw-fig-btn" id="lw-btn-copy-code">Скопировать код</button>
          </div>
        </div>
      </div>
    `;

    this._bindCommonControls(hasPlot, isArchive, tools);
    if (hasPlot) {
      this._initPlotInstance();
    } else if (isArchive) {
      this._initArchiveFigures();
      this._renderArchiveMeasurements();
    }
    this._startClock();
    this._notifyResize();
  },

  _buildArchiveStatementHtml(d) {
    const arch = d.archive || {};
    const headerMeta = arch.year ? `<div class="lw-k" style="margin-bottom:4px;">ВсОШ ${arch.year} · ${arch.grade} класс · задание ${arch.number}</div>` : '';
    const blocks = (d.statement_blocks || []).filter(b => b.type !== 'figure');
    const blocksHtml = blocks.map(b => {
      if (b.type === 'markdown') return `<div class="lw-statement-text">${this.formatMathAndSubscripts(b.text)}</div>`;
      if (b.type === 'source_excerpt') return `<div class="lw-note">${this.formatMathAndSubscripts(b.note || '')}</div>`;
      return '';
    }).join('');
    const partsHtml = (d.parts || []).map(p =>
      (p.body || []).map(b => b.type === 'markdown' ? `<li>${this.formatMathAndSubscripts(b.text)}</li>` : '').join('')
    ).join('');
    return `
      <div class="lw-statement">
        ${headerMeta}
        <div class="lw-task-title">${this.formatMathAndSubscripts(d.title || d.task_id)}</div>
        ${blocksHtml}
        ${partsHtml ? `<ol class="lw-asks">${partsHtml}</ol>` : ''}
      </div>
    `;
  },

  _buildArchiveFiguresHtml(d) {
    const assetsById = {};
    (d.assets || []).forEach(a => { assetsById[a.id] = a; });
    const figBlocks = (d.statement_blocks || []).filter(b => b.type === 'figure');
    if (!figBlocks.length) {
      return `<div class="lw-note">Иллюстрации условия в внешнем источнике.</div>`;
    }
    return figBlocks.map((b, idx) => {
      const asset = assetsById[b.asset_id];
      if (!asset || !asset.url) return '';
      return `
        <div class="lw-figure" data-asset-id="${asset.id}" data-fig-idx="${idx + 1}">
          <div style="font-size:12.5px; color:#475569; margin-bottom:6px; font-weight:600;">
            Рисунок ${idx + 1}. ${this.formatMathAndSubscripts(b.caption || b.alt || '')}
          </div>
          <div class="lw-fig-controls">
            <button type="button" class="lw-fig-btn" data-action="zoom-out">−</button>
            <span class="lw-zoom-label" style="font-size:12px; font-family:monospace;">100%</span>
            <button type="button" class="lw-fig-btn" data-action="zoom-in">+</button>
            <button type="button" class="lw-fig-btn" data-action="toggle-ruler">Линейка (пикс.)</button>
          </div>
          <div class="lw-fig-scroll">
            <div class="lw-fig-canvas" style="width:100%;">
              <img src="${asset.url}" alt="${b.alt || ''}" draggable="false" />
              <svg class="lw-fig-overlay" viewBox="0 0 1 1"></svg>
            </div>
          </div>
        </div>
      `;
    }).join('');
  },

  _initArchiveFigures() {
    const figs = this.rootEl.querySelectorAll('.lw-figure');
    figs.forEach(figEl => {
      const assetId = figEl.getAttribute('data-asset-id');
      let zoom = 100;
      let ruler = false;
      let pts = [];
      let natSize = { w: 1, h: 1 };

      const canvas = figEl.querySelector('.lw-fig-canvas');
      const img = figEl.querySelector('img');
      const svg = figEl.querySelector('.lw-fig-overlay');
      const zoomLbl = figEl.querySelector('.lw-zoom-label');
      const rulerBtn = figEl.querySelector('[data-action="toggle-ruler"]');

      img.addEventListener('load', () => {
        natSize = { w: img.naturalWidth || 1, h: img.naturalHeight || 1 };
        svg.setAttribute('viewBox', `0 0 ${natSize.w} ${natSize.h}`);
        this._notifyResize();
      });

      figEl.querySelector('[data-action="zoom-out"]').addEventListener('click', () => {
        zoom = Math.max(100, zoom - 50);
        canvas.style.width = `${zoom}%`;
        zoomLbl.textContent = `${zoom}%`;
      });
      figEl.querySelector('[data-action="zoom-in"]').addEventListener('click', () => {
        zoom = Math.min(400, zoom + 50);
        canvas.style.width = `${zoom}%`;
        zoomLbl.textContent = `${zoom}%`;
      });
      rulerBtn.addEventListener('click', () => {
        if (this.isSubmitted) return;
        ruler = !ruler;
        pts = [];
        rulerBtn.classList.toggle('active', ruler);
        img.style.cursor = ruler ? 'crosshair' : 'default';
        svg.innerHTML = '';
      });

      img.addEventListener('click', (e) => {
        if (!ruler || this.isSubmitted) return;
        const rect = img.getBoundingClientRect();
        const p = {
          x: ((e.clientX - rect.left) / rect.width) * natSize.w,
          y: ((e.clientY - rect.top) / rect.height) * natSize.h
        };
        pts = pts.length === 1 ? [pts[0], p] : [p];
        const rCircle = Math.max(3, natSize.w / 180);
        let overlayHtml = '';
        if (pts.length === 2) {
          overlayHtml += `<line x1="${pts[0].x}" y1="${pts[0].y}" x2="${pts[1].x}" y2="${pts[1].y}" />`;
          const len = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);
          this.measurements.push({
            asset_id: assetId,
            x1: Math.round(pts[0].x),
            y1: Math.round(pts[0].y),
            x2: Math.round(pts[1].x),
            y2: Math.round(pts[1].y),
            length: Math.round(len * 10) / 10
          });
          this.answers.measurements = JSON.stringify(this.measurements);
          this._renderArchiveMeasurements();
          this._scheduleSync();
        }
        pts.forEach(pt => {
          overlayHtml += `<circle cx="${pt.x}" cy="${pt.y}" r="${rCircle}" />`;
        });
        svg.innerHTML = overlayHtml;
      });
    });
  },

  _renderArchiveMeasurements() {
    const body = this.rootEl.querySelector('#lw-archive-measurements-body');
    if (!body) return;
    if (!this.measurements.length) {
      body.innerHTML = `<p class="lw-field-hint">Включите «Линейку» над рисунком и отметьте два конца отрезка. Длина записывается в пикселях оригинала.</p>`;
      return;
    }
    body.innerHTML = `
      <table class="lw-log-table">
        <thead><tr><th>№</th><th>Рисунок</th><th>Длина</th><th></th></tr></thead>
        <tbody>
          ${this.measurements.map((m, i) => `
            <tr>
              <td>${i + 1}</td>
              <td>${m.asset_id}</td>
              <td class="lw-col-y">${this.num(m.length, 1)} пикс.</td>
              <td>${!this.isSubmitted ? `<button type="button" class="lw-del-btn" data-del-meas="${i}">×</button>` : ''}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
    body.querySelectorAll('[data-del-meas]').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.getAttribute('data-del-meas'));
        this.measurements.splice(idx, 1);
        this.answers.measurements = JSON.stringify(this.measurements);
        this._renderArchiveMeasurements();
        this._scheduleSync();
      });
    });
  },

  _buildSheetFieldsHtml(fields) {
    const visible = (fields || []).filter(f => f.kind !== 'points');
    if (!visible.length) {
      return `<p class="lw-field-hint">В этой задаче нет числовых полей.</p>`;
    }
    return visible.map(f => {
      const val = this.answers[f.id] !== undefined ? String(this.answers[f.id]) : '';
      const escapedVal = val.replace(/"/g, '&quot;');
      const labelHtml = this.formatMathAndSubscripts(f.label || f.id);
      const unitHtml = this.formatMathAndSubscripts(f.unit || '');
      const hintHtml = f.hint ? `<small class="lw-field-hint">${this.formatMathAndSubscripts(f.hint)}</small>` : '';

      if (f.kind === 'text') {
        return `
          <div class="lw-written" data-field-wrap="${f.id}">
            <label class="lw-field-name" for="lw-ans-${f.id}">${labelHtml}${hintHtml}</label>
            <textarea class="lw-textarea" id="lw-ans-${f.id}" data-field-id="${f.id}" rows="${f.id === 'reasoning' ? 6 : 3}">${val}</textarea>
          </div>
        `;
      }

      if (f.kind === 'choice' && Array.isArray(f.options)) {
        return `
          <div class="lw-written" data-field-wrap="${f.id}">
            <label class="lw-field-name" for="lw-ans-${f.id}">${labelHtml}${hintHtml}</label>
            <select class="lw-select" id="lw-ans-${f.id}" data-field-id="${f.id}">
              <option value="">— Выберите вариант —</option>
              ${f.options.map(opt => `<option value="${opt.replace(/"/g, '&quot;')}" ${val === opt ? 'selected' : ''}>${opt}</option>`).join('')}
            </select>
          </div>
        `;
      }

      if (f.kind === 'yesno') {
        return `
          <div class="lw-field-row" data-field-wrap="${f.id}">
            <div>
              <label class="lw-field-name" for="lw-ans-${f.id}">${labelHtml}</label>
              ${hintHtml}
            </div>
            <div class="lw-input-wrap">
              <div class="lw-yesno-pills">
                <button type="button" class="lw-pill ${val.toLowerCase() === 'да' ? 'active' : ''}" data-yesno-id="${f.id}" data-yesno-val="да">да</button>
                <button type="button" class="lw-pill ${val.toLowerCase() === 'нет' ? 'active' : ''}" data-yesno-id="${f.id}" data-yesno-val="нет">нет</button>
              </div>
              <input type="text" class="lw-input" id="lw-ans-${f.id}" data-field-id="${f.id}" value="${escapedVal}" placeholder="да / нет" />
            </div>
            <span class="lw-unit">${unitHtml}</span>
          </div>
        `;
      }

      const isErr = f.kind === 'number_with_error';
      return `
        <div class="lw-field-row ${isErr ? 'lw-wide' : ''}" data-field-wrap="${f.id}">
          <div>
            <label class="lw-field-name" for="lw-ans-${f.id}">${labelHtml}</label>
            ${hintHtml}
          </div>
          <div class="lw-input-wrap">
            <input type="text" inputmode="decimal" autocomplete="off" spellcheck="false"
                   class="lw-input" id="lw-ans-${f.id}" data-field-id="${f.id}"
                   value="${escapedVal}" placeholder="${isErr ? '0,056 ± 0,002' : ''}" />
            ${isErr ? `<button type="button" class="lw-pm-btn" data-pm-target="lw-ans-${f.id}" title="Вставить ±">±</button>` : ''}
          </div>
          <span class="lw-unit">${unitHtml}</span>
        </div>
      `;
    }).join('');
  },

  _bindCommonControls(hasPlot, isArchive, tools) {
    // Переключение инструментов графика
    if (hasPlot) {
      const toolBtns = this.rootEl.querySelectorAll('#lw-tools-bar button[data-tool]');
      toolBtns.forEach(btn => {
        btn.addEventListener('click', () => {
          if (this.isSubmitted) return;
          const t = btn.getAttribute('data-tool');
          toolBtns.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          if (this.plot) this.plot.setTool(t);
        });
      });

      const clearBtn = this.rootEl.querySelector('#lw-clear-marks');
      if (clearBtn) {
        clearBtn.addEventListener('click', () => {
          if (this.plot && !this.isSubmitted) this.plot.clearMarks();
        });
      }
    }

    // Привязка полей ввода бланка
    const inputs = this.rootEl.querySelectorAll('[data-field-id]');
    inputs.forEach(inp => {
      const fid = inp.getAttribute('data-field-id');
      const handler = () => {
        this.answers[fid] = inp.value;
        // Обновляем подсветку пилюль да/нет, если есть
        this.rootEl.querySelectorAll(`[data-yesno-id="${fid}"]`).forEach(p => {
          p.classList.toggle('active', p.getAttribute('data-yesno-val') === inp.value.trim().toLowerCase());
        });
        this._scheduleSync();
      };
      inp.addEventListener('input', handler);
      inp.addEventListener('change', handler);
    });

    // Кнопки быстрого выбора да/нет
    this.rootEl.querySelectorAll('[data-yesno-id]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (this.isSubmitted) return;
        const fid = btn.getAttribute('data-yesno-id');
        const val = btn.getAttribute('data-yesno-val');
        const inp = this.rootEl.querySelector(`#lw-ans-${fid}`);
        if (inp) {
          inp.value = val;
          this.answers[fid] = val;
          this.rootEl.querySelectorAll(`[data-yesno-id="${fid}"]`).forEach(p => {
            p.classList.toggle('active', p.getAttribute('data-yesno-val') === val);
          });
          this._scheduleSync();
        }
      });
    });

    // Кнопка вставки ± для полей number_with_error
    this.rootEl.querySelectorAll('[data-pm-target]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (this.isSubmitted) return;
        const targetId = btn.getAttribute('data-pm-target');
        const inp = this.rootEl.querySelector(`#${targetId}`);
        if (inp && !inp.value.includes('±')) {
          inp.value = inp.value.trim() + ' ± ';
          inp.focus();
          const fid = inp.getAttribute('data-field-id');
          this.answers[fid] = inp.value;
          this._scheduleSync();
        }
      });
    });

    // Кнопка сдачи
    const submitBtn = this.rootEl.querySelector('#lw-btn-submit');
    if (submitBtn) {
      submitBtn.addEventListener('click', () => {
        if (this.isSubmitted) return;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Проверка и сохранение...';
        if (this.saveTimer) clearTimeout(this.saveTimer);
        if (window.AstrositeBridge) {
          AstrositeBridge.submitAttempt(this._buildFullAnswersPayload());
        }
      });
    }

    // Кнопка копирования кода сессии
    const copyBtn = this.rootEl.querySelector('#lw-btn-copy-code');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        const inp = this.rootEl.querySelector('#lw-session-code-input');
        if (inp) {
          inp.select();
          navigator.clipboard?.writeText(inp.value);
          copyBtn.textContent = 'Скопировано!';
          setTimeout(() => { copyBtn.textContent = 'Скопировать код'; }, 2000);
        }
      });
    }
  },

  _initPlotInstance() {
    const d = this.taskData;
    const px = (d.plot && d.plot.x) || { key: 'x', unit: '', decimals: 2 };
    const py = (d.plot && d.plot.y) || { key: 'y', unit: '', decimals: 2, sign: false };
    const multiSeries = Array.isArray(d.series) && d.series.length > 1;
    const tools = Array.isArray(d.tools) && d.tools.length ? d.tools : ['cursor', 'loupe', 'extremum', 'segment'];

    this.plot = new AstroPlot({
      container: '#lw-plot-mount',
      data: d,
      initialTool: tools[0] || 'cursor',
      disabled: this.isSubmitted,
      onReading: ({ reading, pending, extremum }) => {
        const box = this.rootEl.querySelector('#lw-readout');
        if (!box) return;
        if (!reading) {
          box.innerHTML = `<span class="lw-k">${this.isSubmitted ? 'бланк сдан' : 'наведите или коснитесь графика'}</span>`;
          return;
        }
        if (extremum) {
          box.innerHTML = `
            <span class="lw-k">${extremum.kind}</span>
            <span class="lw-k">${px.key}</span><span class="lw-readout-val">${this.num(extremum.x, px.decimals)}</span>
            <span class="lw-k">${py.key}</span><span class="lw-readout-val">${this.num(extremum.y, py.decimals, py.sign)}</span>
            <span class="lw-k">${py.unit || ''}${extremum.series && multiSeries ? ` · ${extremum.series}` : ''}</span>
          `;
        } else if (pending) {
          const dx = reading.x - pending.x;
          const dy = reading.y - pending.y;
          const segLen = this.plot ? this.plot.segmentLength(pending.x, pending.y, reading.x, reading.y) : Math.abs(dx);
          const extra = d.spherical
            ? `ℓ = ${this.num(segLen, py.decimals)} ${py.unit || '°'}`
            : `Δ${px.key} = ${this.num(Math.abs(dx), px.decimals)} ${px.unit || ''}, Δ${py.key} = ${this.num(dy, py.decimals, true)} ${py.unit || ''}`;
          box.innerHTML = `<span class="lw-readout-val">${extra}</span>`;
        } else {
          box.innerHTML = `
            <span class="lw-k">${px.key}</span><span class="lw-readout-val">${this.num(reading.x, px.decimals)}</span>
            <span class="lw-k">${py.key}</span><span class="lw-readout-val">${this.num(reading.y, py.decimals, py.sign)}</span>
            <span class="lw-k">${py.unit || ''}${reading.series && multiSeries ? ` · ${reading.series}` : ''}</span>
          `;
        }
      },
      onMarksChange: (marks) => {
        this.marks = marks.slice();
        this._renderMarksTable();
        this._scheduleSync();
        this._notifyResize();
      }
    });

    if (this.marks && this.marks.length) {
      this.plot.setMarks(this.marks);
    }
  },

  _renderMarksTable() {
    const body = this.rootEl.querySelector('#lw-marks-body');
    const clearBtn = this.rootEl.querySelector('#lw-clear-marks');
    if (!body) return;

    const d = this.taskData || {};
    const px = (d.plot && d.plot.x) || { key: 'x', unit: '', decimals: 2 };
    const py = (d.plot && d.plot.y) || { key: 'y', unit: '', decimals: 2, sign: false };
    const multiSeries = Array.isArray(d.series) && d.series.length > 1;

    if (!this.marks || this.marks.length === 0) {
      if (clearBtn) clearBtn.style.display = 'none';
      body.innerHTML = `<p class="lw-field-hint">Щелчок или касание сохраняет точку. Используйте инструменты, чтобы измерять значения, экстремумы и отрезки на графике.</p>`;
      return;
    }

    if (clearBtn) clearBtn.style.display = this.isSubmitted ? 'none' : 'inline-block';

    const rowsHtml = this.marks.map((m, idx) => {
      const isSeg = m.kind === 'отрезок';
      const colX = isSeg
        ? `${this.num(m.x, px.decimals)} → ${this.num(m.x2, px.decimals)}`
        : this.num(m.x, px.decimals);

      let colY = '';
      let colWhat = '';
      if (isSeg) {
        const sLen = m.sphericalLen !== undefined ? m.sphericalLen : m.len;
        const dy = (m.y2 ?? 0) - m.y;
        const dx = (m.x2 ?? 0) - m.x;
        if (d.spherical || (d.segments && d.segments.length)) {
          colY = `ℓ = ${this.num(sLen, py.decimals)}`;
          colWhat = `отрезок, Δ${px.key} = ${this.num(dx, px.decimals)}, Δ${py.key} = ${this.num(dy, py.decimals, true)}`;
        } else {
          colY = `Δ${py.key} = ${this.num(dy, py.decimals, true)}`;
          colWhat = `отрезок, Δ${px.key} = ${this.num(Math.abs(dx), px.decimals)} ${px.unit || ''}`;
        }
      } else {
        colY = this.num(m.y, py.decimals, py.sign);
        colWhat = multiSeries && m.series && m.series !== '—' ? `${m.series}, ${m.kind}` : m.kind;
      }

      return `
        <tr>
          <td>${m.id || idx + 1}</td>
          <td>${colX}</td>
          <td class="lw-col-y">${colY}</td>
          <td class="lw-col-kind">${colWhat}</td>
          <td>${!this.isSubmitted ? `<button type="button" class="lw-del-btn" data-del-mark="${idx}" title="Удалить">×</button>` : ''}</td>
        </tr>
      `;
    }).join('');

    body.innerHTML = `
      <table class="lw-log-table">
        <thead>
          <tr>
            <th>№</th>
            <th>${this.formatMathAndSubscripts(px.key)}${px.unit ? `, ${this.formatMathAndSubscripts(px.unit)}` : ''}</th>
            <th>${this.formatMathAndSubscripts(py.key)}${py.unit ? `, ${this.formatMathAndSubscripts(py.unit)}` : ''}</th>
            <th>что</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    `;

    body.querySelectorAll('[data-del-mark]').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.getAttribute('data-del-mark'));
        if (this.plot && !this.isSubmitted) this.plot.removeMark(idx);
      });
    });
  },

  _buildFullAnswersPayload() {
    const out = { ...this.answers };
    if (this.marks && this.marks.length) {
      out._marks = this.marks;
    }
    return out;
  },

  _scheduleSync() {
    if (this.isSubmitted) return;
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => {
      if (window.AstrositeBridge) {
        AstrositeBridge.sendAnswerChange(this._buildFullAnswersPayload());
      }
    }, 300);
  },

  _renderSubmittedState() {
    if (!this.rootEl) return;

    // 1. Блокируем все поля ввода и кнопки инструментов
    this.rootEl.querySelectorAll('[data-field-id], [data-yesno-id], [data-pm-target], #lw-tools-bar button').forEach(el => {
      el.disabled = true;
    });
    if (this.plot) {
      this.plot.setDisabled(true);
    }
    this._renderMarksTable();

    const submitBtn = this.rootEl.querySelector('#lw-btn-submit');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Работа сдана';
    }

    // 2. Показываем баннер с кодом сессии для электронного дневника
    const banner = this.rootEl.querySelector('#lw-session-banner');
    if (banner) {
      const codeInput = this.rootEl.querySelector('#lw-session-code-input');
      if (codeInput) codeInput.value = this.sessionCode || 'сессия активна';
      banner.style.display = 'block';
    }

    // 3. Строим карточку Вердикта и Пошагового Разбора (Solution)
    const g = this.grading || {};
    const anchor = this.rootEl.querySelector('#lw-verdict-top-anchor');
    if (!anchor) return;

    const isManual = g.mode === 'manual' || (this.taskData && this.taskData.mode === 'legacy_archive');
    const details = g.details || {};
    const fields = (this.taskData && this.taskData.fields) || [];

    // Подсветка инпутов на бланке
    for (const [fid, res] of Object.entries(details)) {
      const inp = this.rootEl.querySelector(`#lw-ans-${fid}`);
      if (!inp) continue;
      if (res.status === 'ok' || res.ok) {
        inp.style.borderColor = '#16a34a';
        inp.style.backgroundColor = '#f0fdf4';
      } else if (res.status === 'near') {
        inp.style.borderColor = '#d97706';
        inp.style.backgroundColor = '#fffbeb';
      } else {
        inp.style.borderColor = '#dc2626';
        inp.style.backgroundColor = '#fef2f2';
      }
    }

    let verdictRowsHtml = '';
    fields.filter(f => f.kind !== 'points').forEach(f => {
      const r = details[f.id];
      if (!r) return;
      const statusCls = r.status === 'ok' ? 'lw-ok' : (r.status === 'near' ? 'lw-near' : 'lw-bad');
      const userAns = (this.answers[f.id] !== undefined && String(this.answers[f.id]).trim() !== '')
        ? String(this.answers[f.id])
        : (r.user !== null && r.user !== undefined ? String(r.user) : '—');
      const penaltiesHtml = Array.isArray(r.penalties) && r.penalties.length
        ? r.penalties.map(p => `<div class="lw-penalty">${this.formatMathAndSubscripts(p)}</div>`).join('')
        : '';

      verdictRowsHtml += `
        <tr class="${statusCls}">
          <td class="lw-v-name">${this.formatMathAndSubscripts(f.label || f.id)}</td>
          <td class="lw-v-ans">${this.formatMathAndSubscripts(userAns)} ${f.unit ? `<span class="lw-k">${this.formatMathAndSubscripts(f.unit)}</span>` : ''}</td>
          ${!isManual ? `<td class="lw-v-pts">${r.score} / ${r.max}</td>` : ''}
          <td class="lw-v-comment">
            ${this.formatMathAndSubscripts(r.comment || (r.ok ? `Верно (эталон: ${r.truth})` : `Эталон: ${r.truth} ± ${r.tol}`))}
            ${penaltiesHtml}
          </td>
        </tr>
      `;
    });

    // Пошаговый разбор
    const solSteps = g.solution_steps || [];
    const solAssetsById = {};
    (g.solution_assets || []).forEach(a => { solAssetsById[a.id] = a; });

    let solHtml = '';
    if (solSteps.length) {
      const stepsItems = solSteps.map(st => {
        let bodyHtml = '';
        if (st.text) {
          bodyHtml += `<span>${this.formatMathAndSubscripts(st.text)}</span>`;
        }
        if (Array.isArray(st.blocks)) {
          bodyHtml += st.blocks.map(b => {
            if (b.type === 'markdown') return `<div>${this.formatMathAndSubscripts(b.text)}</div>`;
            if (b.type === 'figure') {
              const asset = solAssetsById[b.asset_id];
              return asset && asset.url
                ? `<div class="lw-figure"><div style="font-size:12px; color:#475569; margin-bottom:4px;">${this.formatMathAndSubscripts(b.caption || b.alt || '')}</div><img src="${asset.url}" alt="${b.alt || ''}" style="max-width:100%; height:auto;" /></div>`
                : '';
            }
            if (b.type === 'source_excerpt') {
              return `<div class="lw-note">${this.formatMathAndSubscripts(b.note || '')}</div>`;
            }
            return '';
          }).join('');
        }
        return `<li><span class="lw-sol-step-title">${this.formatMathAndSubscripts(st.title)}:</span> ${bodyHtml}</li>`;
      }).join('');

      const resultsChips = Array.isArray(g.solution_results) && g.solution_results.length
        ? `<div class="lw-sol-results">${g.solution_results.map(res => `<span class="lw-sol-res-chip">${this.formatMathAndSubscripts(res.text)}</span>`).join('')}</div>`
        : '';

      solHtml = `
        <div class="lw-solution-box">
          <h4>${this.formatMathAndSubscripts(g.solution_title || 'Разбор задачи')}</h4>
          <ol class="lw-sol-steps">${stepsItems}</ol>
          ${resultsChips}
        </div>
      `;
    }

    const scoreTitle = isManual
      ? `<div class="lw-score-badge">Разбор открыт</div>`
      : `<div class="lw-score-badge"><b>${g.score !== undefined ? g.score : '—'}</b> из ${g.max_score || 25} баллов</div>`;

    anchor.innerHTML = `
      <div class="lw-verdict-box" style="margin-bottom: 18px;">
        <div class="lw-verdict-head">
          <h3>Вердикт</h3>
          ${scoreTitle}
          ${g.grader_version ? `<span class="lw-k" style="margin-left:auto;">проверка ${g.grader_version}</span>` : ''}
        </div>
        <table class="lw-verdict-table">
          <tbody>${verdictRowsHtml}</tbody>
        </table>
        ${solHtml}
      </div>
    `;

    this._notifyResize();
  },

  _startClock() {
    if (this.clockTimer) clearInterval(this.clockTimer);
    const updateClock = () => {
      const el = this.rootEl && this.rootEl.querySelector('#lw-clock-display');
      if (!el) return;
      if (this.isSubmitted) {
        el.innerHTML = `<span class="lw-k">статус</span><span style="color:#16a34a;">✓ сдано</span>`;
        return;
      }
      const elapsedMin = (Date.now() - this.startedAtMs) / 60000;
      const leftMin = Math.max(0, 100 - elapsedMin);
      const hh = Math.floor(leftMin / 60);
      const mm = String(Math.floor(leftMin % 60)).padStart(2, '0');
      el.innerHTML = `<span class="lw-k">осталось</span><b>${hh}:${mm}</b>`;
    };
    updateClock();
    this.clockTimer = setInterval(updateClock, 5000);
  },

  _notifyResize() {
    setTimeout(() => {
      const bridge = window.AstrositeBridge || (typeof AstrositeBridge !== 'undefined' ? AstrositeBridge : null);
      if (bridge && typeof bridge.forceResize === 'function') {
        bridge.forceResize(this.rootEl ? (this.rootEl.id || 'widget-root') : 'widget-root');
      } else {
        const root = this.rootEl || document.getElementById('widget-root');
        const contentH = root ? Math.ceil(root.getBoundingClientRect().height) : document.body.offsetHeight;
        window.parent.postMessage({
          type: 'ASTROSITE_FRAME_RESIZE',
          height: contentH + 32
        }, '*');
      }
    }, 60);
  }
};
