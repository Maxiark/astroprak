import { useLayoutEffect, type RefObject } from 'react';

// Same-origin teaching documents contain CSS, SVG and nested srcdoc lessons.
// Adapt their color declarations, never their pixels, geometry or application state.
// Original values remain as fallbacks, so light mode is exactly reversible.
const colorLiteral = /#[\da-f]{3,8}\b|rgba?\([^)]*\)|\b(?:white|black|gray|grey|red|blue|green|orange|purple|navy)\b/gi;
const named: Record<string, string> = {
  white: '#ffffff', black: '#000000', gray: '#808080', grey: '#808080',
  red: '#ff0000', blue: '#0000ff', green: '#008000', orange: '#ffa500',
  purple: '#800080', navy: '#000080',
};

function rgb(value: string): number[] | null {
  value = named[value.toLowerCase()] || value;
  if (value.startsWith('#')) {
    let hex = value.slice(1);
    if (hex.length === 3 || hex.length === 4) hex = [...hex].map(c => c + c).join('');
    if (hex.length !== 6 && hex.length !== 8) return null;
    return [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16)).concat(hex.length === 8 ? parseInt(hex.slice(6), 16) / 255 : 1);
  }
  if (value.includes('%')) return null;
  const values = value.match(/[\d.]+/g)?.map(Number);
  return values && values.length >= 3 ? [...values.slice(0, 3), values[3] ?? 1] : null;
}

function darkColor(value: string, role: 'background' | 'border' | 'foreground'): string | null {
  const channels = rgb(value);
  if (!channels) return null;
  const [r, g, b, alpha] = channels;
  if (alpha === 0) return null;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const lightness = (max + min) / 510;
  const neutral = max - min < 45;
  let result: number[];
  if (neutral) {
    // Authored slate surfaces and readable foregrounds, not RGB inversion.
    result = role === 'border' ? [84, 102, 126] : role === 'background'
      ? (lightness > 0.99 ? [24, 34, 49] : lightness > 0.8 ? [32, 46, 64] : [42, 59, 80])
      : (lightness > 0.8 || lightness < 0.25 ? [230, 237, 246] : [172, 187, 206]);
  } else {
    // Keep the hue of each scientific series and status; adjust only its lightness.
    const delta = (max - min) / 255;
    const saturation = delta / (1 - Math.abs(2 * lightness - 1));
    let hue = max === r ? ((g - b) / (max - min)) % 6 : max === g ? (b - r) / (max - min) + 2 : (r - g) / (max - min) + 4;
    hue = (hue * 60 + 360) % 360;
    const target = role === 'background' ? 0.22 : 0.76;
    return `hsl(${hue.toFixed(1)} ${Math.min(saturation * 100, 80).toFixed(1)}% ${target * 100}% / ${alpha})`;
  }
  return `rgba(${result.join(', ')}, ${alpha})`;
}

const documents = new WeakMap<Document, {
  style: HTMLStyleElement;
  colors: Map<string, string>;
  palette: Map<string, string>;
}>();

function attachTheme(frame: HTMLIFrameElement): () => void {
  let doc: Document | null;
  try { doc = frame.contentDocument; } catch { return () => {}; }
  if (!doc?.head || !doc.body) return () => {};
  const document = doc;
  let state = documents.get(document);
  if (!state) {
    const style = document.createElement('style');
    style.dataset.astroFrameTheme = 'true';
    document.head.append(style);
    state = { style, colors: new Map(), palette: new Map() };
    documents.set(document, state);
  }
  const { style, colors, palette } = state;
  const sheets = new WeakSet<CSSStyleSheet>();
  const children = new Map<HTMLIFrameElement, () => void>();
  let applying = false;

  function convert(value: string, property: string): string {
    if (value.includes('var(') || value.includes('url(')) return value;
    const background = /background|^--.*(?:bg|background|surface|card|layout-color)/.test(property);
    return value.replace(colorLiteral, original => {
      const channels = rgb(original);
      const paleFill = property === 'fill' && channels && Math.min(...channels.slice(0, 3)) > 220;
      const role = background || paleFill ? 'background' : /border|outline|^--(?:line|grid)$/.test(property) ? 'border' : 'foreground';
      const mapped = darkColor(original, role);
      if (!mapped) return original;
      const key = `${role}-${original.toLowerCase()}`;
      let variable = colors.get(key);
      if (!variable) {
        variable = `--astro-frame-${colors.size}`;
        colors.set(key, variable);
        palette.set(variable, mapped);
      }
      return `var(${variable}, ${original})`;
    });
  }

  function declarations(declaration: CSSStyleDeclaration) {
    for (const property of [...declaration]) {
      if (!/color|background|border|outline|shadow|^fill$|^stroke$|^--/.test(property)) continue;
      const value = declaration.getPropertyValue(property);
      const next = convert(value, property);
      if (next !== value) declaration.setProperty(property, next, declaration.getPropertyPriority(property));
    }
  }

  function rules(list: CSSRuleList) {
    for (const rule of [...list]) {
      if ('style' in rule) declarations((rule as CSSStyleRule).style);
      if ('cssRules' in rule) rules((rule as CSSGroupingRule).cssRules);
    }
  }

  function scan(root: Element) {
    for (const element of [root, ...root.querySelectorAll('[style], [fill], [stroke], iframe')]) {
      if (element instanceof document.defaultView!.HTMLElement || element instanceof document.defaultView!.SVGElement) {
        declarations((element as HTMLElement).style);
      }
      for (const attribute of ['fill', 'stroke']) {
        const value = element.getAttribute(attribute);
        if (value) {
          const next = convert(value, attribute);
          if (next !== value) element.setAttribute(attribute, next);
        }
      }
      if (element.tagName === 'IFRAME' && !children.has(element as HTMLIFrameElement)) {
        children.set(element as HTMLIFrameElement, watchFrame(element as HTMLIFrameElement));
      }
    }
  }

  function refresh() {
    if (applying) return;
    applying = true;
    for (const sheet of [...document.styleSheets]) {
      if (sheet === style.sheet || sheets.has(sheet)) continue;
      try { rules(sheet.cssRules); sheets.add(sheet); } catch { /* Cross-origin CSS is left untouched. */ }
    }
    scan(document.documentElement);
    const css = `:root[data-theme="dark"] { color-scheme: dark; ${[...palette].map(([k, v]) => `${k}: ${v};`).join('')} }
      :root[data-theme="dark"] body { background-color: #182231; color: #e6edf6; }
      :root[data-theme="dark"] :is(input, textarea, select) { color: #e6edf6; background-color: #131d2b; }
      :root[data-theme="dark"] :is(button, input, textarea, select, summary, a):focus-visible { outline: 3px solid #b5d8ff; outline-offset: 2px; }
      :root[data-theme="dark"] a { color: #8fc5ff; }
      :root[data-theme="dark"] svg text:not([fill]):not([style]) { fill: #acbbce; }
      :root[data-theme="dark"] iframe { color-scheme: dark; background: #182231; }
      :root[data-theme="dark"] :is(.tools button.active, .lw-pill.active, .lw-fig-btn.active) { background: #244a73; color: #e6edf6; }
      :root[data-theme="dark"] :is(.lw-submit-btn, .btn, button.primary, button.selected) { color: #e6edf6; }
      :root[data-theme="dark"] :is(.lw-submit-btn) { background-color: #71302f; }
      :root[data-theme="dark"] :is(.btn-secondary, .lw-fig-btn, .lw-pill) { background-color: #202e40; color: #e6edf6; }
      :root[data-theme="dark"] :is(button.primary, button.selected, .step, .btn) { background-color: #244a73; color: #e6edf6; }
      :root[data-theme="dark"] :is(.btn-green, .btn-success) { background-color: #1c5b42; }
      :root[data-theme="dark"] .lw-dot-b { background: #182231; }
      :root[data-theme="dark"] .lw-dot-a { background: var(--primary); }
      :root[data-theme="dark"] .lw-line-seg { background: #e6edf6; }
      :root[data-theme="dark"] line.grid { stroke: #35465c; }
      :root[data-theme="dark"] circle.pt.b { fill: #182231; stroke: #e6edf6; }
      :root[data-theme="dark"] g.loupe circle.loupe-bg { fill: #182231; }
      :root[data-theme="dark"] g.loupe circle.loupe-ring { stroke: #acbbce; }`;
    if (style.textContent !== css) style.textContent = css;
    observer.takeRecords();
    applying = false;
  }
  const observer = new MutationObserver(refresh);
  refresh();
  observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['style', 'fill', 'stroke'] });
  const sync = () => {
    document.documentElement.dataset.theme = frame.ownerDocument.documentElement.dataset.theme || 'light';
    frame.style.colorScheme = document.documentElement.dataset.theme;
  };
  const parentObserver = new MutationObserver(sync);
  parentObserver.observe(frame.ownerDocument.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  // Covers stylesheets or nested lesson documents finishing after the first scan.
  document.addEventListener('load', refresh, true);
  sync();
  return () => {
    observer.disconnect(); parentObserver.disconnect();
    document.removeEventListener('load', refresh, true);
    children.forEach(cleanup => cleanup());
  };
}

function watchFrame(frame: HTMLIFrameElement): () => void {
  const visibility = frame.style.visibility;
  frame.style.visibility = 'hidden';
  let cleanup = () => {};
  const loaded = () => {
    cleanup();
    cleanup = attachTheme(frame);
    frame.style.visibility = visibility;
  };
  try {
    if (frame.contentDocument?.readyState === 'complete' && frame.contentDocument.URL !== 'about:blank') loaded();
  } catch { frame.style.visibility = visibility; }
  frame.addEventListener('load', loaded);
  return () => { frame.removeEventListener('load', loaded); cleanup(); frame.style.visibility = visibility; };
}

export function useFrameTheme(ref: RefObject<HTMLIFrameElement>, source: string | null) {
  useLayoutEffect(() => {
    if (ref.current) return watchFrame(ref.current);
  }, [ref, source]);
}
