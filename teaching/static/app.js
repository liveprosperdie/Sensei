/* Akira Study Room — front end.
   Security notes: all model/user text is inserted with textContent / createTextNode
   (never innerHTML), the Markdown renderer builds DOM nodes directly and only allows
   https links, diagrams are parsed as XML and imported node-by-node, and every
   request carries a per-launch token that lives only in this tab. */
(() => {
'use strict';

const root = document.getElementById('app');

/* ── token & prefs ───────────────────────────────────────── */
let TOKEN = sessionStorage.getItem('akira_t') || '';
const tm = location.hash.match(/t=([\w-]+)/);
if (tm) { TOKEN = tm[1]; sessionStorage.setItem('akira_t', TOKEN); history.replaceState(null, '', location.pathname + '#/'); }
const prefs = {
  get(k, d) { try { const v = localStorage.getItem('akira_' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('akira_' + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
document.documentElement.dataset.theme = prefs.get('theme', 'paper');
document.documentElement.style.setProperty('--read', prefs.get('read', 19) + 'px');

/* ── tiny DOM helpers ────────────────────────────────────── */
const SVGNS = 'http://www.w3.org/2000/svg';
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const ICONS = {
  book: ['M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z', 'M19 19v2H6'],
  plus: ['M12 5v14M5 12h14'],
  play: ['M7 4l13 8-13 8z'], pause: ['M8 5v14M16 5v14'],
  split: ['M3 4h18v16H3z', 'M13 4v16'],
  sun: ['M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4', 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z'],
  moon: ['M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z'],
  check: ['M5 12.5l4.5 4.5L19 7'], lock: ['M6 11h12v9H6z', 'M8.5 11V8a3.5 3.5 0 0 1 7 0v3'],
  arrow: ['M5 12h14M13 6l6 6-6 6'], back: ['M19 12H5M11 6l-6 6 6 6'],
  file: ['M6 3h8l4 4v14H6z', 'M14 3v4h4'], shield: ['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z', 'M9 12l2 2 4-4'],
  feather: ['M20 4c-6 0-12 4-12 11l-3 5', 'M8 15h7c3 0 5-4 5-11'],
  smile: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M8.5 14.5c1 1.4 2.2 2 3.5 2s2.5-.6 3.5-2M9 9.5h.01M15 9.5h.01'],
  down: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M8 15.5h8M9 9.5h.01M15 9.5h.01'],
  up: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M8 12h8M12 8v8'],
  trash: ['M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13'], list: ['M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01'],
  spark: ['M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z'], type: ['M5 19l6-15 6 15M7.5 13h7'],
  speaker: ['M4 9h4l5-4v14l-5-4H4z', 'M16.5 8.5a5 5 0 0 1 0 7'],
  mic: ['M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z', 'M19 10v2a7 7 0 0 1-14 0v-2', 'M12 19v4', 'M8 23h8'],
  timer: ['M12 2v2', 'M12 6a8 8 0 1 0 8 8 8 8 0 0 0-8-8z', 'M12 10v4l2 2'],
  focus: ['M3 7V3h4', 'M17 3h4v4', 'M21 17v4h-4', 'M7 21H3v-4'],
  brain: ['M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.04z', 'M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.04z'],
};
function icon(name) {
  const s = document.createElementNS(SVGNS, 'svg');
  s.setAttribute('class', 'i'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
  for (const d of ICONS[name] || []) { const p = document.createElementNS(SVGNS, 'path'); p.setAttribute('d', d); s.append(p); }
  return s;
}
const ago = (iso) => { try { return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); } catch { return ''; } };
const pct = (x) => Math.round((x || 0) * 100);
const hue = (slug) => { let n = 0; for (const c of slug) n = (n * 31 + c.charCodeAt(0)) % 360; return `hsl(${n} 38% 42%)`; };

/* ── API ─────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const headers = { 'X-Akira-Token': TOKEN, ...(opts.headers || {}) };
  let body = opts.raw;
  if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body); }
  const res = await fetch('/api' + path, { method: opts.method || 'GET', headers, body });
  let data = null;
  try { data = await res.json(); } catch { /* no body */ }
  if (res.status === 401) { gate(); throw new Error('Session expired'); }
  if (!res.ok) throw new Error((data && data.detail) || `Request failed (${res.status})`);
  return data;
}
function toast(msg, bad = false) {
  const t = h('div', { class: 'toast' + (bad ? ' bad' : ''), role: 'status', text: msg });
  document.body.append(t); setTimeout(() => t.remove(), 4200);
}
function gate() {
  root.replaceChildren(h('div', { class: 'gate' },
    h('div', { class: 'seal', style: 'margin:0 auto 18px;width:52px;height:52px;font-size:30px', text: 'A' }),
    h('h1', { class: 'h-display', text: 'Session ended' }),
    h('p', { class: 'lede', text: 'For your privacy the Study Room only opens from Akira. Say “Akira, open the study room”, or run python -m teaching, to start a fresh session.' })));
}

/* ── busy overlay + job polling ──────────────────────────── */
function busy(title, sub) {
  const stage = h('p', { text: sub || 'One moment' });
  const ov = h('div', { class: 'busy', role: 'alert' }, h('div', { class: 'busy-in' },
    (() => { const s = document.createElementNS(SVGNS, 'svg'); s.setAttribute('class', 'pen'); s.setAttribute('viewBox', '0 0 220 90');
      const p = document.createElementNS(SVGNS, 'path'); p.setAttribute('d', 'M8 62c18-34 34-34 46-10s26 22 40-4 28-30 44-6 28 18 44-8 22-12 30-6'); s.append(p); return s; })(),
    h('h3', { text: title }), stage));
  document.body.append(ov);
  return { set: (t) => { stage.textContent = t; }, close: () => ov.remove() };
}
async function runJob(jobId, title) {
  const b = busy(title);
  try {
    for (;;) {
      await new Promise((r) => setTimeout(r, 650));
      const j = await api('/jobs/' + jobId);
      b.set(j.stage);
      if (j.status === 'done') return;
      if (j.status === 'error') throw new Error(j.error || 'Generation failed');
    }
  } finally { b.close(); }
}

/* ── chrome & concentration timer ────────────────────────── */
let focusSeconds = 25 * 60;
let focusRunning = false;
let focusInterval = null;
function formatFocusTime(sec) {
  const m = Math.floor(sec / 60); const s = sec % 60;
  return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
}

function topbar(crumb) {
  const curTheme = document.documentElement.dataset.theme || 'paper';
  const themeNext = curTheme === 'paper' ? 'night' : curTheme === 'night' ? 'cyber' : 'paper';
  const themeNames = { paper: 'Paper', night: 'Night', cyber: 'Zen Focus' };
  const themeIcons = { paper: 'sun', night: 'moon', cyber: 'spark' };

  const timerEl = h('div', { class: 'focus-pill' + (focusRunning ? ' active' : ''), title: 'Pomodoro Concentration Sprint' },
    icon('timer'),
    h('span', { id: 'focus-clock', text: formatFocusTime(focusSeconds) }),
    h('button', {
      'aria-label': focusRunning ? 'Pause focus timer' : 'Start focus timer',
      onclick: (e) => {
        e.stopPropagation();
        focusRunning = !focusRunning;
        if (focusRunning) {
          if (!focusInterval) {
            focusInterval = setInterval(() => {
              if (focusSeconds > 0) {
                focusSeconds--;
                const c = document.getElementById('focus-clock');
                if (c) c.textContent = formatFocusTime(focusSeconds);
              } else {
                clearInterval(focusInterval); focusInterval = null; focusRunning = false;
                toast('Focus sprint complete! Great concentration session.');
                if (S.voice) speakText('Focus sprint complete. Take a short pause.');
                const p = document.querySelector('.focus-pill');
                if (p) p.classList.remove('active');
              }
            }, 1000);
          }
        } else {
          clearInterval(focusInterval); focusInterval = null;
        }
        const p = document.querySelector('.focus-pill');
        if (p) p.classList.toggle('active', focusRunning);
        const btn = p && p.querySelector('button');
        if (btn) btn.replaceChildren(icon(focusRunning ? 'pause' : 'play'));
      }
    }, icon(focusRunning ? 'pause' : 'play')));

  return h('header', { class: 'bar' },
    h('button', { class: 'brand', 'aria-label': 'Back to your shelf', onclick: () => nav('#/') },
      h('span', { class: 'seal', text: 'A' }), h('span', { class: 'brand-name' }, 'Akira ', h('em', { text: 'study room' }))),
    crumb ? h('div', { class: 'crumb' }, icon('arrow'), h('b', { text: crumb })) : null,
    h('div', { class: 'grow' }),
    timerEl,
    h('span', { class: 'privacy-pill', title: 'Courses, files and results are saved only in a private folder on this PC.' }, icon('shield'), 'Private on PC'),
    h('button', { class: 'chip-btn', 'aria-label': 'Cycle theme', onclick: () => {
      document.documentElement.dataset.theme = themeNext;
      prefs.set('theme', themeNext);
      route();
    } }, icon(themeIcons[curTheme] || 'moon'), themeNames[curTheme] || 'Theme'));
}
function page(crumb, body, extraClass = '') {
  root.replaceChildren(topbar(crumb), h('main', { class: 'scroll ' + extraClass }, body));
}
const nav = (hash) => { if (location.hash === hash) route(); else location.hash = hash; };

/* ── safe Markdown renderer ──────────────────────────────── */
function inline(text) {
  const out = []; let last = 0, m;
  const re = /(\*\*([^*]+)\*\*|`([^`]+)`|\*([^*\s][^*]*)\*|\[([^\]]+)\]\((https:\/\/[^)\s]+)\))/g;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(document.createTextNode(text.slice(last, m.index)));
    if (m[2] !== undefined) out.push(h('strong', {}, ...inline(m[2])));
    else if (m[3] !== undefined) out.push(h('code', { text: m[3] }));
    else if (m[4] !== undefined) out.push(h('em', {}, ...inline(m[4])));
    else out.push(h('a', { href: m[6], target: '_blank', rel: 'noopener noreferrer', text: m[5] }));
    last = re.lastIndex;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}
function renderMarkdown(md, ctx) {
  const frag = document.createDocumentFragment();
  const lines = md.replace(/\r/g, '').split('\n');
  let i = 0, sec = 0, firstPara = true;
  const isBlockStart = (l) => /^(#{1,3}\s|>|\s*[-*]\s|\s*\d+\.\s|```|\||---+\s*$|<!--|\{\{)/.test(l);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if ((m = line.match(/^<!--\s*source-ref:\s*(\{.*\})\s*-->\s*$/))) {
      try { const ref = JSON.parse(m[1]); frag.append(stamp(ref, ctx)); } catch { /* ignore */ }
      i++; continue;
    }
    if ((m = line.match(/^\{\{\s*diagram:\s*([^}\s]+)\s*\}\}\s*$/))) {
      const fig = h('figure', { class: 'fig' }, h('div', { class: 'diagram', 'aria-label': 'Diagram' }), h('figcaption', { text: 'Figure' }));
      frag.append(fig);
      const code = ctx.diagrams && ctx.diagrams[m[1]];
      if (code) drawDiagram(fig.querySelector('.diagram'), code); else fig.remove();
      i++; continue;
    }
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
      const lvl = m[1].length;
      if (lvl === 1) frag.append(h('h1', {}, ...inline(m[2])));
      else if (lvl === 2) { sec++; frag.append(h('h2', {}, h('span', { class: 'n', text: String(sec).padStart(2, '0') }), h('span', {}, ...inline(m[2])))); }
      else frag.append(h('h3', {}, ...inline(m[2])));
      i++; continue;
    }
    if (/^```/.test(line)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; frag.append(h('pre', {}, h('code', { text: buf.join('\n') }))); continue;
    }
    if (/^---+\s*$/.test(line)) { frag.append(h('hr')); i++; continue; }
    if (/^\|/.test(line) && i + 1 < lines.length && /^\|[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const cells = (l) => l.replace(/^\||\|\s*$/g, '').split('|').map((c) => c.trim());
      const head = cells(line); i += 2; const rows = [];
      while (i < lines.length && /^\|/.test(lines[i])) rows.push(cells(lines[i++]));
      frag.append(h('table', {}, h('thead', {}, h('tr', {}, head.map((c) => h('th', {}, ...inline(c))))),
        h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => h('td', {}, ...inline(c))))))));
      continue;
    }
    if (/^>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ''));
      frag.append(h('blockquote', {}, h('p', {}, ...inline(buf.join(' '))))); continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line); const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''));
      frag.append(h(ordered ? 'ol' : 'ul', {}, items.map((t) => h('li', {}, ...inline(t))))); continue;
    }
    const buf = [line]; i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) buf.push(lines[i++]);
    frag.append(h('p', { class: firstPara ? 'first' : '' }, ...inline(buf.join(' '))));
    firstPara = false;
  }
  return frag;
}

/* ── diagrams ────────────────────────────────────────────── */
let mmCounter = 0;
function initMermaid() {
  if (!window.mermaid) return;
  const night = document.documentElement.dataset.theme === 'night';
  window.mermaid.initialize({
    startOnLoad: false, securityLevel: 'strict', theme: 'base', flowchart: { htmlLabels: false, curve: 'basis' },
    themeVariables: night
      ? { background: '#231f18', primaryColor: '#2f3a38', primaryBorderColor: '#7fbab3', primaryTextColor: '#efe6d4', lineColor: '#b3a78f', secondaryColor: '#3a2f27', tertiaryColor: '#231f18', fontFamily: 'Georgia, serif' }
      : { background: '#fbf7ee', primaryColor: '#efe3c8', primaryBorderColor: '#2f5d62', primaryTextColor: '#1f1b16', lineColor: '#5f5648', secondaryColor: '#e6d3c9', tertiaryColor: '#fbf7ee', fontFamily: 'Georgia, serif' },
  });
}
async function drawDiagram(host, code) {
  try {
    const { svg } = await window.mermaid.render('mm' + (++mmCounter), code);
    const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
    if (doc.querySelector('parsererror')) throw new Error('bad svg');
    host.replaceChildren(document.importNode(doc.documentElement, true));
  } catch {
    host.replaceChildren(h('pre', {}, h('code', { text: code })));
  }
}

/* ── state ───────────────────────────────────────────────── */
const S = { meta: null, srcCache: {}, srcActive: null, follow: prefs.get('follow', true), srcOpen: prefs.get('srcOpen', true), srcWidth: prefs.get('srcWidth', 40), voice: prefs.get('voice', false) };
let observer = null;

/* ── source pane ─────────────────────────────────────────── */
async function loadSource(slug, id) {
  if (!S.srcCache[id]) S.srcCache[id] = await api(`/topics/${slug}/sources/${id}`);
  return S.srcCache[id];
}
function srcEntries(meta) { return [...meta.sources.local_files, ...meta.sources.web_sources]; }
function stamp(ref, ctx) {
  const entry = ctx.entries && ctx.entries.find((e) => e.id === ref.file);
  const label = h('span', { text: `p. ${ref.page} · ${entry ? entry.name : ref.file}` });
  const b = h('button', { class: 'stamp', 'data-src': ref.file, 'data-page': ref.page, 'data-quote': ref.quote || '', title: 'Show this passage in your source', onclick: () => focusSource(ref.file, ref.page, ref.quote, true) }, icon('file'), label);
  return h('div', { class: 'srcref' }, b);
}
function normalize(s) { return s.toLowerCase().replace(/\s+/g, ' '); }
function paintPage(pageEl, text, quote) {
  const body = pageEl.querySelector('.body');
  body.replaceChildren();
  let idx = -1, len = 0;
  if (quote) {
    const hay = text.toLowerCase();
    const q = quote.toLowerCase().replace(/\s+/g, ' ').trim();
    idx = hay.indexOf(q); len = q.length;
    if (idx < 0) { // whitespace-tolerant search
      const rx = new RegExp(q.split(' ').filter(Boolean).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+'), 'i');
      const mm = rx.exec(text); if (mm) { idx = mm.index; len = mm[0].length; }
    }
    if (idx < 0) { const first = q.split(' ').slice(0, 4).join(' '); idx = hay.indexOf(first); len = first.length; }
  }
  if (idx >= 0) body.append(document.createTextNode(text.slice(0, idx)), h('mark', { text: text.slice(idx, idx + len) }), document.createTextNode(text.slice(idx + len)));
  else body.append(document.createTextNode(text));
}
async function focusSource(id, pageNo, quote, forceOpen) {
  const slug = S.meta.topic_slug;
  if (forceOpen && !S.srcOpen) { S.srcOpen = true; prefs.set('srcOpen', true); const col = document.querySelector('.src-col'); if (col) col.hidden = false; }
  const pane = document.querySelector('.src-scroll');
  if (!pane) return;
  try {
    if (S.srcActive !== id) { S.srcActive = id; await renderSourcePane(); }
    const src = await loadSource(slug, id);
    const pg = src.pages.find((p) => p.page === Number(pageNo));
    const el = document.querySelector(`.page[data-page="${Number(pageNo)}"]`);
    if (!pg || !el) return;
    document.querySelectorAll('.page.focus').forEach((p) => { p.classList.remove('focus'); const q = S.srcCache[id].pages.find((x) => x.page === Number(p.dataset.page)); if (q) paintPage(p, q.text, ''); });
    paintPage(el, pg.text, quote); el.classList.add('focus');
    const scroller = document.querySelector('.src-scroll');
    scroller.scrollTo({ top: Math.max(0, el.offsetTop - 28), behavior: 'smooth' });
    document.querySelectorAll('.stamp').forEach((s) => s.classList.toggle('active', s.dataset.src === id && s.dataset.page === String(pageNo) && s.dataset.quote === (quote || '')));
  } catch (e) { toast(e.message, true); }
}
async function renderSourcePane() {
  const col = document.querySelector('.src-col');
  if (!col) return;
  const entries = srcEntries(S.meta);
  const tabs = col.querySelector('.tabs'); const scroll = col.querySelector('.src-scroll');
  tabs.replaceChildren(); scroll.replaceChildren();
  if (!entries.length) {
    scroll.append(h('div', { class: 'empty-src' }, h('div', {}, h('p', { text: 'No source documents on this course.' }), h('p', { class: 'hint', text: 'Start a new course and bring your own notes or slides. The matching passage will open here as you read.' }))));
    return;
  }
  if (!S.srcActive || !entries.some((e) => e.id === S.srcActive)) S.srcActive = entries[0].id;
  for (const e of entries) tabs.append(h('button', { role: 'tab', 'aria-selected': String(e.id === S.srcActive), onclick: () => { S.srcActive = e.id; renderSourcePane(); } }, icon('file'), e.name));
  try {
    const src = await loadSource(S.meta.topic_slug, S.srcActive);
    for (const p of src.pages) {
      const el = h('article', { class: 'page', 'data-page': p.page }, h('span', { class: 'pn', text: `page ${p.page}` }), h('div', { class: 'body' }));
      paintPage(el, p.text, ''); scroll.append(el);
    }
  } catch (err) { scroll.append(h('div', { class: 'empty-src', text: err.message })); }
}
function observeStamps(scroller) {
  if (observer) observer.disconnect();
  const marks = scroller.querySelectorAll('.srcref .stamp');
  if (!marks.length) return;
  observer = new IntersectionObserver((entries) => {
    if (!S.follow || !S.srcOpen) return;
    const hit = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (hit) { const d = hit.target.dataset; focusSource(d.src, d.page, d.quote, false); }
  }, { root: scroller, rootMargin: '-8% 0px -62% 0px', threshold: 0 });
  marks.forEach((m) => observer.observe(m));
}

/* ── read aloud (on-device speech synthesis; nothing is uploaded) ── */
let speaking = false;
function stopSpeech() { speaking = false; if (window.speechSynthesis) speechSynthesis.cancel(); document.querySelectorAll('.reading').forEach((e) => e.classList.remove('reading')); const b = document.getElementById('read-btn'); if (b) { b.setAttribute('aria-pressed', 'false'); b.replaceChildren(icon('play'), 'Read aloud'); } }
function speakText(text, onend) {
  if (!window.speechSynthesis) return false;
  const u = new SpeechSynthesisUtterance(text); u.rate = 1.0; u.onend = onend || null; u.onerror = onend || null; speechSynthesis.speak(u); return true;
}
function readAloud() {
  if (speaking) { stopSpeech(); return; }
  const nodes = [...document.querySelectorAll('.lesson > h1, .lesson > h2, .lesson > p, .lesson > ul > li, .lesson > ol > li, .lesson > blockquote')];
  if (!nodes.length || !window.speechSynthesis) { toast('Speech is not available in this browser.', true); return; }
  speaking = true;
  const b = document.getElementById('read-btn'); b.setAttribute('aria-pressed', 'true'); b.replaceChildren(icon('pause'), 'Stop reading');
  let k = 0;
  const next = () => {
    if (!speaking || k >= nodes.length) { stopSpeech(); return; }
    const n = nodes[k++]; document.querySelectorAll('.reading').forEach((e) => e.classList.remove('reading'));
    n.classList.add('reading'); n.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const ref = n.previousElementSibling && n.previousElementSibling.querySelector && n.previousElementSibling.querySelector('.stamp');
    if (ref) focusSource(ref.dataset.src, ref.dataset.page, ref.dataset.quote, false);
    speakText(n.textContent.replace(/^\d+\s*/, ''), next);
  };
  next();
}

/* ═══ VIEWS ═══════════════════════════════════════════════ */

async function viewShelf() {
  stopSpeech();
  let topics = [];
  try { topics = (await api('/topics')).topics; } catch (e) { if (e.message === 'Session expired') return; toast(e.message, true); }
  const books = topics.map((t) => {
    const frac = t.lesson_count ? t.completed / t.lesson_count : 0;
    const b = h('button', { class: 'book', 'aria-label': 'Open ' + t.topic, onclick: () => nav('#/t/' + t.topic_slug) },
      h('div', { class: 'book-in' }, h('span', { class: 'spine', style: `--hue:${hue(t.topic_slug)}` }),
        t.status === 'completed' ? null : h('span', { class: 'ribbon' }),
        h('div', { class: 'kicker', text: t.status === 'draft' ? 'Not started' : t.status === 'completed' ? 'Completed' : 'In progress' }),
        h('h3', { text: t.topic }),
        h('div', { class: 'progress', 'aria-label': 'progress' }, h('i', { style: `width:${pct(frac)}%` })),
        h('div', { class: 'meta' }, h('span', { class: 'tag', text: `${t.completed}/${t.lesson_count || '–'} lessons` }),
          t.level ? h('span', { class: 'tag', text: t.level }) : null,
          t.avg_score !== null && t.avg_score !== undefined ? h('span', { class: 'tag', text: `avg ${pct(t.avg_score)}%` }) : null)));
    const wrap = h('div', { style: 'position:relative' }, b,
      h('button', { class: 'del', title: 'Delete this course', 'aria-label': 'Delete ' + t.topic, onclick: async (ev) => {
        ev.stopPropagation();
        if (!confirm(`Delete “${t.topic}” and everything saved for it?`)) return;
        try { await api('/topics/' + t.topic_slug, { method: 'DELETE' }); route(); } catch (e) { toast(e.message, true); }
      } }, icon('trash')));
    return wrap;
  });
  const fresh = h('button', { class: 'book new', onclick: () => nav('#/new') }, h('div', { class: 'book-in' }, h('div', { class: 'plus', text: '+' }), h('b', { style: 'font-family:var(--serif);font-size:19px', text: 'Begin a new subject' }), h('span', { text: 'Name a topic. Optionally bring your own notes.' })));
  page(null, h('div', { class: 'shelf-wrap' },
    h('div', { class: 'kicker', text: 'Your private tutor' }),
    h('h1', { class: 'h-display' }, 'What shall we ', h('em', { text: 'learn' }), ' today?'),
    h('p', { class: 'lede', text: topics.length ? 'Pick up where you left off, or open a fresh notebook. Each course adapts to how you actually do.' : 'Your tutor builds a roadmap, teaches one lesson at a time, and reshapes the course around your quiz results.' }),
    h('div', { class: 'books' }, books, fresh)));
}

function viewNew(existingSlug) {
  stopSpeech();
  const state = { files: [], level: 'beginner' };
  const err = h('div', { class: 'err', role: 'alert' });
  const topic = h('input', { class: 'big-input', id: 'topic-input', placeholder: 'e.g. How Kubernetes networking works', maxlength: '100', 'aria-label': 'Topic' });
  const fileList = h('ul', { class: 'files' });
  const picker = h('input', { type: 'file', class: 'sr', multiple: true, accept: '.pdf,.docx,.txt,.md', id: 'picker' });
  const levels = ['beginner', 'intermediate', 'advanced'];
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Your level' }, levels.map((l) => h('button', { 'aria-pressed': String(l === state.level), onclick: (e) => { state.level = l; [...seg.children].forEach((c) => c.setAttribute('aria-pressed', String(c === e.currentTarget))); } }, l[0].toUpperCase() + l.slice(1))));
  function addFiles(list) {
    for (const f of list) {
      if (!/\.(pdf|docx|txt|md)$/i.test(f.name)) { err.textContent = `“${f.name}” isn’t a supported type (PDF, DOCX, TXT, MD).`; continue; }
      if (f.size > 15 * 1024 * 1024) { err.textContent = `“${f.name}” is over 15 MB.`; continue; }
      if (state.files.length >= 8) { err.textContent = 'Up to 8 files per course.'; break; }
      const entry = { file: f, cloud: false }; state.files.push(entry);
      const cb = h('input', { type: 'checkbox', 'aria-label': 'Allow cloud model to read excerpts of ' + f.name, onchange: () => { entry.cloud = cb.checked; } });
      const li = h('li', {}, icon('file'), h('span', { class: 'name', text: f.name }),
        h('label', { class: 'hint', style: 'display:flex;gap:6px;align-items:center', title: 'Unticked: only a model running on this PC may read this file.' }, cb, 'cloud AI may read excerpts'),
        h('button', { class: 'chip-btn', 'aria-label': 'Remove ' + f.name, onclick: () => { state.files.splice(state.files.indexOf(entry), 1); li.remove(); } }, icon('trash')));
      fileList.append(li);
    }
  }
  picker.addEventListener('change', () => { addFiles(picker.files); picker.value = ''; });
  const drop = h('label', { class: 'drop', for: 'picker' }, icon('feather'), h('div', { text: 'Drop notes, slides or a paper here, or click to choose' }), h('small', { text: 'PDF · DOCX · TXT · MD — read on this PC; the original file is never stored.' }));
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => addFiles(e.dataTransfer.files));
  const go = h('button', { class: 'btn accent', id: 'draft-btn', onclick: async () => {
    err.textContent = '';
    if (topic.value.trim().length < 2) { err.textContent = 'Give your subject a name first.'; topic.focus(); return; }
    go.disabled = true;
    try {
      const topic_slug = existingSlug || (await api('/topics', { method: 'POST', body: { topic: topic.value.trim(), level: state.level } })).topic_slug;
      for (const f of state.files) {
        await api(`/topics/${topic_slug}/sources/upload?name=${encodeURIComponent(f.file.name)}&cloud=${f.cloud ? 1 : 0}`, { method: 'POST', raw: await f.file.arrayBuffer(), headers: { 'Content-Type': 'application/octet-stream' } });
      }
      const { job_id } = await api(`/topics/${topic_slug}/plan`, { method: 'POST', body: {} });
      await runJob(job_id, 'Drafting your roadmap');
      nav('#/t/' + topic_slug);
    } catch (e) { err.textContent = e.message; go.disabled = false; }
  } }, icon('spark'), 'Draft my roadmap');
  topic.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
  page('New subject', h('div', { class: 'sheet-wrap' }, h('div', { class: 'sheet' },
    h('div', { class: 'kicker', text: 'A fresh notebook' }), h('h1', { class: 'h-display', style: 'font-size:38px;margin-bottom:26px' }, 'What do you want to ', h('em', { text: 'understand' }), '?'),
    h('div', { class: 'field' }, h('label', { for: 'topic-input', text: 'Subject' }), topic),
    h('div', { class: 'field' }, h('span', { class: 'label', text: 'Where are you starting from?' }), seg),
    h('div', { class: 'field' }, h('span', { class: 'label', text: 'Bring your own material (optional)' }), drop, picker, fileList,
      h('div', { class: 'consent' }, icon('shield'), h('div', { text: 'Files stay on this PC. Teaching excerpts are only sent to a cloud AI if you tick the box beside that file; otherwise only a model running locally can read it, and obvious secrets such as keys or passwords are always blanked out first.' }))),
    err, h('div', { style: 'display:flex;gap:12px;align-items:center;margin-top:8px' }, go, h('button', { class: 'btn ghost', onclick: () => nav('#/'), text: 'Cancel' })))));
  setTimeout(() => topic.focus(), 50);
}

function viewRoadmap(meta) {
  stopSpeech();
  const arch = meta.curriculum_architecture;
  const approved = new Set(arch.reliable_sources.map((s, i) => (s.approved ? i : -1)).filter((i) => i >= 0));
  const srcCards = arch.reliable_sources.map((s, i) => {
    const can = s.status === 'ok';
    const label = can ? ['ok', 'Trusted site'] : s.status === 'citation_only' ? ['off', 'Reference only'] : s.status === 'not_allowlisted' ? ['warn', 'Not on trusted list'] : ['off', 'Unusable link'];
    const cb = h('input', { type: 'checkbox', disabled: !can, checked: approved.has(i), 'aria-label': 'Let the tutor read ' + s.name, onchange: () => { cb.checked ? approved.add(i) : approved.delete(i); card.dataset.off = cb.checked ? '0' : '1'; } });
    const card = h('div', { class: 'src-card', 'data-off': can && approved.has(i) ? '0' : '1' }, cb,
      h('div', {}, h('h5', {}, s.name, h('span', { class: 'status ' + label[0], text: label[1] })), h('p', { text: s.why || s.type }), s.url_or_ref ? h('p', { style: 'word-break:break-all;margin-top:4px;color:var(--ink-faint)', text: s.url_or_ref }) : null));
    return card;
  });
  const own = srcEntries(meta).filter((e) => e.kind !== 'web' && !e.url);
  const begin = h('button', { class: 'btn accent', id: 'begin-btn', onclick: async () => {
    begin.disabled = true;
    try {
      await api(`/topics/${meta.topic_slug}/approve-sources`, { method: 'POST', body: { approved: [...approved] } });
      const { job_id } = await api(`/topics/${meta.topic_slug}/begin`, { method: 'POST', body: {} });
      await runJob(job_id, 'Writing lesson one');
      nav('#/t/' + meta.topic_slug);
    } catch (e) { toast(e.message, true); begin.disabled = false; }
  } }, 'Begin lesson 1', icon('arrow'));
  page(meta.topic, h('div', { class: 'road' },
    h('section', {}, h('div', { class: 'kicker', text: `Roadmap · designed for a ${arch.assumed_level} learner` }),
      h('h1', { class: 'h-display', style: 'font-size:40px' }, meta.topic),
      arch.audience_note ? h('p', { class: 'lede', style: 'margin-bottom:26px', text: arch.audience_note }) : null,
      h('ol', { class: 'chapters' }, meta.lessons.map((l, i) => h('li', { style: `animation-delay:${i * 70}ms` }, h('h4', { text: l.title }), h('p', { text: l.summary }), h('div', { class: 'concepts' }, l.key_concepts.map((c) => h('span', { class: 'tag', text: c.replace(/-/g, ' ') }))))))),
    h('aside', {}, h('div', { class: 'kicker', style: 'margin-bottom:10px', text: 'Sources the tutor will trust' }),
      own.length ? h('div', { class: 'src-card', style: 'grid-template-columns:auto 1fr' }, icon('file'), h('div', {}, h('h5', { text: 'Your material' }), h('p', { text: own.map((e) => e.name + (e.allow_cloud ? '' : ' (local model only)')).join(' · ') }))) : null,
      srcCards.length ? srcCards : h('p', { class: 'hint', text: 'The tutor will teach from general knowledge.' }),
      h('div', { class: 'notice', style: 'margin:14px 0 4px' }, icon('shield'), h('span', { text: 'Only sites on the trusted list can be read, and only the ones you tick. Nothing else is fetched.' })),
      h('div', { class: 'sticky' }, begin, h('button', { class: 'btn ghost', onclick: () => nav('#/'), text: 'Not now' })))));
}

/* — study — */
async function viewStudy(meta, lid, mode) {
  stopSpeech();
  S.meta = meta;
  const lesson = meta.lessons.find((l) => l.id === lid);
  if (!lesson || lesson.state === 'locked') { nav('#/t/' + meta.topic_slug); return; }
  if (!lesson.generated) {
    try { const { job_id } = await api(`/topics/${meta.topic_slug}/lessons/${lid}/generate`, { method: 'POST', body: {} }); await runJob(job_id, 'Writing your next lesson'); }
    catch (e) { toast(e.message, true); nav('#/'); return; }
    return route();
  }
  let data;
  try { data = await api(`/topics/${meta.topic_slug}/lessons/${lid}`); } catch (e) { toast(e.message, true); nav('#/'); return; }
  initMermaid();

  const toc = h('ol', { class: 'toc' }, meta.lessons.map((l, i) => {
    const locked = l.state === 'locked';
    const cls = [l.state === 'completed' ? 'done' : '', l.state === 'current' ? 'cur' : '', l.id === lid && mode !== 'journal' ? 'sel' : '', l.type === 'remedial' || l.type === 'prerequisite' ? 'rem' : ''].join(' ');
    return h('li', {}, h('button', { class: cls, disabled: locked, onclick: () => nav(`#/t/${meta.topic_slug}/${l.id}`), 'aria-current': l.id === lid ? 'step' : null },
      h('span', { class: 'dot' }, l.state === 'completed' ? icon('check') : locked ? icon('lock') : String(i + 1)),
      h('span', {}, h('div', { class: 't', text: l.title }), h('div', { class: 'k', text: l.quiz_score !== null && l.quiz_score !== undefined ? `quiz ${pct(l.quiz_score)}%` : locked ? 'locked' : 'ready' }))));
  }));
  const spine = h('nav', { class: 'spine-nav', 'aria-label': 'Course roadmap' },
    h('div', { class: 'kicker', text: 'Roadmap' }), h('h2', { text: meta.topic }), h('div', { class: 'sub', text: `${meta.calibration.calibrated_depth} depth` }), toc,
    h('button', { class: 'btn ghost journal-link', onclick: () => nav(`#/t/${meta.topic_slug}/journal`) }, icon('list'), 'Course journal'));

  const lessonCol = h('section', { class: 'lesson-col' });
  const entries = srcEntries(meta);
  const srcCol = h('aside', { class: 'src-col', style: `flex-basis:${S.srcWidth}%`, hidden: !S.srcOpen, 'aria-label': 'Source document' }, h('div', { class: 'tabs', role: 'tablist' }), h('div', { class: 'src-scroll' }));
  const split = h('div', { class: 'split', role: 'separator', 'aria-orientation': 'vertical', 'aria-label': 'Resize source pane' });
  split.addEventListener('pointerdown', (e) => {
    split.setPointerCapture(e.pointerId); split.classList.add('drag');
    const total = document.querySelector('.study').getBoundingClientRect(); 
    const move = (ev) => { const w = Math.min(62, Math.max(22, ((total.right - ev.clientX) / total.width) * 100)); srcCol.style.flexBasis = w + '%'; S.srcWidth = w; };
    const up = () => { split.classList.remove('drag'); prefs.set('srcWidth', S.srcWidth); split.removeEventListener('pointermove', move); split.removeEventListener('pointerup', up); };
    split.addEventListener('pointermove', move); split.addEventListener('pointerup', up);
  });
  split.hidden = !S.srcOpen;

  const study = h('div', { class: 'study' }, spine, lessonCol, split, srcCol);
  root.replaceChildren(topbar(meta.topic), study);

  if (mode === 'quiz') renderQuiz(lessonCol, meta, lesson, data);
  else if (mode === 'result') renderResult(lessonCol, meta, lesson, data, null);
  else if (mode === 'feynman') renderFeynman(lessonCol, meta, lesson, data);
  else renderLesson(lessonCol, meta, lesson, data, entries, split, srcCol);
  if (mode === 'lesson') await renderSourcePane();
  else srcCol.hidden = true, split.hidden = true;
}

function renderLesson(col, meta, lesson, data, entries, split, srcCol) {
  const toolbar = h('div', { class: 'toolbar' },
    h('button', { class: 'chip-btn', id: 'read-btn', 'aria-pressed': 'false', onclick: readAloud }, icon('play'), 'Read aloud'),
    h('button', { class: 'chip-btn', id: 'feynman-btn', title: 'Feynman Technique: Explain in your own words', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}/feynman`) }, icon('brain'), 'Feynman'),
    h('button', { class: 'chip-btn', id: 'focus-btn', title: 'Focus concentration mode (maximizes reading canvas)', onclick: (e) => {
      const st = document.querySelector('.study');
      if (st) {
        const isF = st.classList.toggle('focus-mode');
        e.currentTarget.setAttribute('aria-pressed', String(isF));
      }
    } }, icon('focus'), 'Focus'),
    h('button', { class: 'chip-btn', 'aria-pressed': String(S.follow), id: 'follow-btn', title: 'Scroll the source to match what you are reading', onclick: (e) => { S.follow = !S.follow; prefs.set('follow', S.follow); e.currentTarget.setAttribute('aria-pressed', String(S.follow)); } }, icon('arrow'), 'Follow sources'),
    h('button', { class: 'chip-btn', 'aria-pressed': String(S.voice), title: 'Speak the tutor’s feedback after quizzes', onclick: (e) => { S.voice = !S.voice; prefs.set('voice', S.voice); e.currentTarget.setAttribute('aria-pressed', String(S.voice)); } }, icon('speaker'), 'Tutor voice'),
    h('div', { class: 'grow' }),
    h('button', { class: 'chip-btn', 'aria-label': 'Smaller text', onclick: () => fontStep(-1) }, icon('type'), '−'),
    h('button', { class: 'chip-btn', 'aria-label': 'Larger text', onclick: () => fontStep(1) }, icon('type'), '+'),
    h('button', { class: 'chip-btn', id: 'split-btn', 'aria-pressed': String(S.srcOpen), onclick: (e) => { S.srcOpen = !S.srcOpen; prefs.set('srcOpen', S.srcOpen); srcCol.hidden = !S.srcOpen; split.hidden = !S.srcOpen; e.currentTarget.setAttribute('aria-pressed', String(S.srcOpen)); } }, icon('split'), 'Sources'));
  const ctx = { entries, diagrams: data.diagrams };
  const article = h('article', { class: 'lesson' });
  article.append(renderMarkdown(data.markdown || '', ctx));
  const after = h('div', { class: 'after' });
  const needsCal = lesson.type === 'overview_and_calibration' && !meta.calibration.is_calibrated && lesson.state === 'current';
  if (needsCal) {
    const choose = async (fb) => {
      try { const m = await api(`/topics/${meta.topic_slug}/calibrate`, { method: 'POST', body: { feedback: fb } }); if (fb === 'too_advanced') toast('Added a short warm-up lesson before the next one.'); S.meta = m; route(); }
      catch (e) { toast(e.message, true); }
    };
    after.append(h('div', { class: 'card' }, h('h3', { text: 'How did that feel?' }), h('p', { text: 'Be honest. Your answer sets the depth of every lesson that follows.' }),
      h('div', { class: 'feel' },
        h('button', { onclick: () => choose('too_basic') }, icon('down'), 'Too basic', h('small', { text: 'I knew most of this' })),
        h('button', { onclick: () => choose('about_right') }, icon('smile'), 'About right', h('small', { text: 'Keep this pace' })),
        h('button', { onclick: () => choose('too_advanced') }, icon('up'), 'Too hard', h('small', { text: 'I need more groundwork' })))));
  } else if (lesson.state === 'current') {
    after.append(h('div', { class: 'card' }, h('h3', { text: 'Ready to check your understanding?' }), h('p', { text: 'Five quick questions. Your result decides what comes next.' }),
      h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' },
        h('button', { class: 'btn accent', id: 'quiz-btn', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}/quiz`) }, 'Take the quiz', icon('arrow')),
        h('button', { class: 'btn ghost', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}/feynman`) }, icon('brain'), 'Feynman Practice'))));
  } else {
    const next = meta.lessons.find((l) => l.state === 'current');
    after.append(h('div', { class: 'card' }, h('h3', { text: `You scored ${pct(lesson.quiz_score)}% here` }), h('p', { text: 'You can reread this lesson or practice explaining it anytime.' }),
      h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' },
        h('button', { class: 'btn ghost', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}/result`) }, 'Review answers'),
        h('button', { class: 'btn', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}/feynman`) }, icon('brain'), 'Feynman Practice'),
        next ? h('button', { class: 'btn accent', onclick: () => nav(`#/t/${meta.topic_slug}/${next.id}`) }, 'Continue', icon('arrow')) : null)));
  }
  const scroller = h('div', { class: 'lesson-scroll' }, article, after);
  col.replaceChildren(toolbar, scroller);
  observeStamps(scroller);
}
function fontStep(d) {
  const cur = prefs.get('read', 19); const n = Math.min(26, Math.max(15, cur + d));
  prefs.set('read', n); document.documentElement.style.setProperty('--read', n + 'px');
}

/* — quiz — */
function renderQuiz(col, meta, lesson, data) {
  const qs = (data.quiz && data.quiz.questions) || [];
  const answers = {}; let idx = 0;
  const host = h('div', { class: 'quiz-wrap' });
  col.replaceChildren(h('div', { class: 'toolbar' }, h('button', { class: 'chip-btn', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}`) }, icon('back'), 'Back to the lesson'), h('div', { class: 'grow' }), h('span', { class: 'hint', text: lesson.title })), h('div', { class: 'lesson-scroll', style: 'padding:0' }, host));
  function draw() {
    const q = qs[idx]; const last = idx === qs.length - 1;
    const opts = h('div', { class: 'opts', role: 'radiogroup', 'aria-label': q.prompt }, q.options.map((o, n) => h('button', { class: 'opt', role: 'radio', 'aria-checked': String(answers[q.id] === o.id), 'data-k': o.id, onclick: () => { answers[q.id] = o.id; [...opts.children].forEach((c) => c.setAttribute('aria-checked', String(c.dataset.k === o.id))); nextBtn.disabled = false; } }, h('span', { class: 'k', text: 'ABCDE'[n] }), h('span', { text: o.text }))));
    const nextBtn = h('button', { class: 'btn accent', id: 'next-btn', disabled: !answers[q.id], onclick: async () => {
      if (!last) { idx++; draw(); return; }
      nextBtn.disabled = true;
      try {
        const b = busy('Marking your answers', 'Checking each one');
        let res; try { res = await api(`/topics/${meta.topic_slug}/lessons/${lesson.id}/quiz`, { method: 'POST', body: { answers } }); } finally { b.close(); }
        window.__lastResult = { ...res, _lid: lesson.id }; nav(`#/t/${meta.topic_slug}/${lesson.id}/result`);
      } catch (e) { toast(e.message, true); nextBtn.disabled = false; }
    } }, last ? 'Submit answers' : 'Next', icon('arrow'));
    host.replaceChildren(h('div', { class: 'dots' }, qs.map((_, n) => h('i', { class: n < idx ? 'on' : n === idx ? 'cur' : '' }))),
      h('div', { class: 'qcard' }, h('div', { class: 'qnum', text: `Question ${idx + 1} of ${qs.length} · ${q.concept_tag.replace(/-/g, ' ')}` }), h('h2', { class: 'qprompt', text: q.prompt }), opts,
        h('div', { class: 'qfoot' }, h('span', { class: 'hint' }, 'Press ', h('kbd', { text: 'A' }), '–', h('kbd', { text: 'D' }), ' then ', h('kbd', { text: 'Enter' })), nextBtn)));
  }
  if (!qs.length) { host.append(h('p', { text: 'No quiz is available for this lesson yet.' })); return; }
  draw();
  const key = (e) => {
    if (!document.body.contains(host)) { document.removeEventListener('keydown', key); return; }
    const q = qs[idx]; const k = e.key.toLowerCase();
    const opt = q.options.find((o, n) => o.id === k || String(n + 1) === k);
    if (opt) host.querySelector(`.opt[data-k="${opt.id}"]`).click();
    else if (e.key === 'Enter') { const b = document.getElementById('next-btn'); if (b && !b.disabled) b.click(); }
  };
  document.addEventListener('keydown', key);
}

function renderResult(col, meta, lesson, data, _unused) {
  const res = window.__lastResult && window.__lastResult._lid === lesson.id ? window.__lastResult : null;
  const stored = data.result;
  const graded = res ? res.graded : stored ? stored.answers : [];
  const score = res ? res.score : stored ? stored.score : lesson.quiz_score || 0;
  const decision = res ? res.decision : stored ? stored.decision : null;
  const qmap = Object.fromEntries(((data.quiz && data.quiz.questions) || []).map((q) => [q.id, q]));
  const tone = score >= 0.8 ? ['good', 'Solid'] : score >= 0.6 ? ['mid', 'Getting there'] : ['low', 'Needs another pass'];
  const dash = 440 - 440 * score;
  const ring = h('div', { class: 'ring' }, (() => { const s = document.createElementNS(SVGNS, 'svg'); s.setAttribute('viewBox', '0 0 160 160');
    for (const [cls, ] of [['bg'], ['fg']]) { const c = document.createElementNS(SVGNS, 'circle'); c.setAttribute('class', cls); c.setAttribute('cx', '80'); c.setAttribute('cy', '80'); c.setAttribute('r', '70'); s.append(c); } return s; })(), h('div', { class: 'num', text: pct(score) + '%' }));
  requestAnimationFrame(() => requestAnimationFrame(() => { const fg = ring.querySelector('.fg'); if (fg) fg.style.strokeDashoffset = String(dash); }));

  let banner = null;
  if (decision) {
    if (decision.action === 'insert_remedial_lesson') { const l = res && res.inserted_lesson_id ? meta.lessons.find((x) => x.id === res.inserted_lesson_id) : meta.lessons.find((x) => x.type === 'remedial' && x.state !== 'completed');
      banner = h('div', { class: 'decision adapt' }, icon('spark'), h('div', {}, h('b', { text: 'Your course just adapted. ' }), l ? `I added “${l.title}” right before the next lesson, focused on what tripped you up.` : 'A focused lesson was added.')); }
    else if (decision.action === 'adjust_depth') banner = h('div', { class: 'decision adapt' }, icon('spark'), h('div', {}, h('b', { text: 'Pace changed. ' }), `Upcoming lessons are now ${decision.direction === 'up' ? 'deeper' : 'gentler'} (${decision.new_depth}).`));
    else banner = h('div', { class: 'decision' }, icon('check'), h('div', {}, h('b', { text: 'On track. ' }), 'Your plan stays as it was.' + (res && res.review_notes ? ' ' + res.review_notes : '')));
  }
  const review = graded.map((g, i) => { const q = qmap[g.id]; const sel = q && q.options.find((o) => o.id === g.selected); const cor = q && q.options.find((o) => o.id === g.correct_option_id);
    return h('div', { class: 'rq' + (g.is_correct ? '' : ' wrong'), style: `animation-delay:${i * 80}ms` }, h('b', { text: q ? q.prompt : g.id }),
      !g.is_correct ? h('div', { class: 'you', text: `You chose: ${sel ? sel.text : 'no answer'}` }) : null,
      h('div', {}, (g.is_correct ? '✓ ' : 'Answer: ') + (cor ? cor.text : '')), g.explanation ? h('div', { class: 'you', text: g.explanation }) : null); });
  const next = meta.lessons.find((l) => l.state === 'current');
  const done = meta.status === 'completed';
  const feynmanPrompt = h('div', { class: 'card', style: 'text-align:left;border-color:var(--teal);margin:18px 0;background:color-mix(in srgb, var(--teal) 8%, var(--card));display:flex;align-items:center;gap:14px;justify-content:space-between;flex-wrap:wrap' },
    h('div', {},
      h('h3', { style: 'display:flex;align-items:center;gap:8px;font-size:17px;margin:0 0 4px' }, icon('brain'), 'Lock it in: Feynman Technique'),
      h('p', { style: 'margin:0;font-size:13.5px;color:var(--ink-soft)' }, 'Explain the core idea in your own natural words. Akira will listen, buffer your thinking pauses, and flag any subtle misconceptions.')),
    h('button', { class: 'btn accent', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}/feynman`) }, icon('mic'), 'Explain to Akira'));

  col.replaceChildren(h('div', { class: 'toolbar' }, h('button', { class: 'chip-btn', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}`) }, icon('back'), 'Lesson'), h('div', { class: 'grow' }), h('span', { class: 'hint', text: lesson.title })),
    h('div', { class: 'lesson-scroll', style: 'padding:0' }, h('div', { class: 'quiz-wrap' }, h('div', { class: 'result' }, ring, h('div', { class: 'verdict ' + tone[0], text: tone[1] }), res && res.spoken_feedback ? h('p', { class: 'lede', style: 'margin:0 auto 22px', text: res.spoken_feedback }) : null, banner),
      feynmanPrompt,
      h('div', { class: 'review' }, review),
      h('div', { style: 'display:flex;gap:12px;justify-content:center;flex-wrap:wrap' },
        h('button', { class: 'btn', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}/feynman`) }, icon('brain'), 'Feynman Practice'),
        done ? h('button', { class: 'btn accent', onclick: () => nav(`#/t/${meta.topic_slug}/journal`) }, 'Course complete — see your journal', icon('arrow'))
          : next ? h('button', { class: 'btn accent', id: 'continue-btn', onclick: () => nav(`#/t/${meta.topic_slug}/${next.id}`) }, `Continue to “${next.title}”`, icon('arrow')) : null,
        h('button', { class: 'btn ghost', onclick: () => nav('#/') }, 'Back to shelf')))));
  if (res && res.spoken_feedback && S.voice) speakText(res.spoken_feedback);
}

/* — feynman studio (voice explanation with thinking buffer) — */
function renderFeynman(col, meta, lesson, data) {
  stopSpeech();
  const feynmanRec = data.feynman && data.feynman.evaluation;
  let activeEval = feynmanRec || null;
  let transcript = (data.feynman && data.feynman.transcript) || '';

  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  let isListening = false;
  let bufferTimer = null;
  let progressInterval = null;
  const BUFFER_MS = 4000; // 4 seconds thinking pause buffer!

  const wrap = h('div', { class: 'feynman-wrap' });
  col.replaceChildren(
    h('div', { class: 'toolbar' },
      h('button', { class: 'chip-btn', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}`) }, icon('back'), 'Back to Lesson'),
      h('div', { class: 'grow' }),
      h('span', { class: 'hint', text: lesson.title })),
    h('div', { class: 'lesson-scroll', style: 'padding:0' }, wrap)
  );

  function draw() {
    const concepts = lesson.key_concepts || [];
    const tagsRow = h('div', { class: 'concept-tags-row' },
      concepts.map(c => h('span', { class: 'tag', style: 'font-size:13px;padding:4px 10px', text: c.replace(/-/g, ' ') }))
    );

    const hero = h('div', { class: 'feynman-hero' },
      h('div', { class: 'kicker', text: 'The Feynman Technique' }, icon('brain')),
      h('h2', { text: 'Explain it in your own words' }),
      h('p', { text: 'The ultimate test of true understanding: pretend you are explaining this to a curious beginner or friend. Speak naturally in your own everyday terms or analogies. Akira will listen, buffer your thinking pauses so you are never rushed, and flag any subtle gaps.' }),
      tagsRow
    );

    const textarea = h('textarea', {
      placeholder: 'Speak aloud or type your explanation here...',
      value: transcript,
      oninput: (e) => { transcript = e.target.value; }
    });

    const orb = h('span', { class: 'voice-orb' + (isListening ? '' : ' paused') });
    const waveBars = h('span', { class: 'voice-waves', style: isListening ? '' : 'opacity:0.3' },
      h('span', { class: 'voice-wave-bar' }),
      h('span', { class: 'voice-wave-bar' }),
      h('span', { class: 'voice-wave-bar' }),
      h('span', { class: 'voice-wave-bar' })
    );

    const statusText = h('span', { text: isListening ? 'Listening (4s thinking buffer active)...' : 'Microphone idle (click Speak to begin)' });
    const bufferProgressBar = h('div', { class: 'thinking-buffer-progress', style: 'width:0%' });
    const bufferBarWrap = h('div', { class: 'thinking-buffer-bar', style: isListening ? '' : 'display:none' }, bufferProgressBar);
    const distractionBox = h('div', { class: 'distraction-notice', style: 'display:none' });

    function setBuffer(pct, msg) {
      bufferProgressBar.style.width = (pct * 100) + '%';
      if (msg) statusText.textContent = msg;
    }

    function stopVoice() {
      if (rec) {
        try { rec.stop(); } catch (e) {}
      }
      isListening = false;
      clearTimeout(bufferTimer);
      clearInterval(progressInterval);
      orb.className = 'voice-orb paused';
      waveBars.style.opacity = '0.3';
      micBtn.replaceChildren(icon('mic'), 'Speak Explanation');
      micBtn.setAttribute('aria-pressed', 'false');
      bufferBarWrap.style.display = 'none';
      statusText.textContent = 'Microphone paused.';
    }

    function startVoice() {
      if (!SpeechRec) {
        toast('Speech recognition not supported in this browser. You can type in the box below!', true);
        return;
      }
      try {
        rec = new SpeechRec();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = navigator.language || 'en-US';
      } catch (err) {
        toast('Could not start microphone: ' + err.message, true);
        return;
      }

      isListening = true;
      orb.className = 'voice-orb';
      waveBars.style.opacity = '1';
      micBtn.replaceChildren(icon('pause'), 'Pause Listening');
      micBtn.setAttribute('aria-pressed', 'true');
      bufferBarWrap.style.display = 'block';
      distractionBox.style.display = 'none';
      setBuffer(1.0, 'Listening... (Speak whenever you are ready)');

      let localAccum = transcript ? (transcript.trim() + ' ') : '';

      rec.onresult = async (ev) => {
        clearTimeout(bufferTimer);
        clearInterval(progressInterval);
        setBuffer(1.0, 'Listening to you...');
        orb.className = 'voice-orb';

        let interim = '';
        let finalized = '';
        for (let i = ev.resultIndex; i < ev.results.length; ++i) {
          if (ev.results[i].isFinal) finalized += ev.results[i][0].transcript + ' ';
          else interim += ev.results[i][0].transcript;
        }

        const chunk = (finalized + interim).trim();
        // Check for common interruption/distraction phrases
        const distractions = ['wait a sec', 'hang on', 'hold on', 'mom is calling', 'one second', 'brb', 'give me a minute'];
        const low = chunk.toLowerCase();
        if (distractions.some(d => low.includes(d))) {
          stopVoice();
          distractionBox.style.display = 'flex';
          distractionBox.replaceChildren(
            icon('pause'),
            h('div', { text: 'Interruption detected: paused listening so you can take care of it. Click Resume or say "continue" when ready.' }),
            h('button', { class: 'btn ghost', style: 'padding:4px 10px;font-size:12px;margin-left:auto', onclick: startVoice }, 'Resume')
          );
          return;
        }

        if (finalized) localAccum = (localAccum + finalized).trim() + ' ';
        transcript = (localAccum + interim).trim();
        textarea.value = transcript;
      };

      rec.onspeechend = () => {
        if (!isListening) return;
        // Start the 4-second thinking buffer countdown
        orb.className = 'voice-orb buffering';
        const startT = Date.now();
        progressInterval = setInterval(() => {
          const left = Math.max(0, BUFFER_MS - (Date.now() - startT));
          setBuffer(left / BUFFER_MS, `Thinking buffer: ${(left / 1000).toFixed(1)}s (take your time)...`);
          if (left <= 0) clearInterval(progressInterval);
        }, 100);

        bufferTimer = setTimeout(() => {
          clearInterval(progressInterval);
          orb.className = 'voice-orb';
          setBuffer(0, 'Finished thought (ready to evaluate)');
        }, BUFFER_MS);
      };

      rec.onerror = (e) => {
        if (e.error === 'no-speech') return; // Silence during thinking pause!
        console.warn('Speech error:', e.error);
      };

      rec.onend = () => {
        if (isListening) {
          try { rec.start(); } catch (e) {}
        }
      };

      try { rec.start(); } catch (e) { console.warn(e); }
    }

    const micBtn = h('button', {
      class: 'btn', id: 'feynman-mic-btn',
      onclick: () => { if (isListening) stopVoice(); else startVoice(); }
    }, icon('mic'), 'Speak Explanation');

    const submitBtn = h('button', {
      class: 'btn accent', id: 'feynman-submit-btn',
      onclick: async () => {
        stopVoice();
        const text = textarea.value.trim();
        if (text.length < 10) {
          toast('Please speak or type a little more explaining the topic!', true);
          return;
        }
        submitBtn.disabled = true;
        const b = busy('Akira is evaluating your explanation', 'Applying the Feynman Technique');
        try {
          const res = await api(`/topics/${meta.topic_slug}/lessons/${lesson.id}/feynman`, {
            method: 'POST', body: { explanation: text }
          });
          activeEval = res;
          data.feynman = { transcript: text, evaluation: res };
          draw();
          if (res.spoken_feedback) speakText(res.spoken_feedback);
        } catch (err) {
          toast(err.message, true);
        } finally {
          b.close(); submitBtn.disabled = false;
        }
      }
    }, icon('spark'), 'Evaluate My Explanation');

    const clearBtn = h('button', {
      class: 'btn ghost',
      onclick: () => {
        stopVoice();
        transcript = '';
        textarea.value = '';
        activeEval = null;
        draw();
      }
    }, icon('trash'), 'Clear');

    const statusRow = h('div', { class: 'feynman-status-badge' }, orb, waveBars, statusText);
    const controls = h('div', { class: 'feynman-controls' },
      h('div', { style: 'display:flex;gap:10px;align-items:center;flex-wrap:wrap' }, micBtn, submitBtn, clearBtn),
      statusRow
    );

    const inputBox = h('div', { class: 'feynman-input-box' },
      textarea, bufferBarWrap, distractionBox, controls
    );

    // Results card
    let resultSection = null;
    if (activeEval) {
      const score = activeEval.mastery_score || 0.75;
      const level = activeEval.mastery_level || 'Proficient';
      const strengths = activeEval.strengths || [];
      const flags = activeEval.flags || [];

      resultSection = h('div', { class: 'feynman-result-card' },
        h('div', { class: 'feynman-header-split' },
          h('div', {},
            h('span', { class: 'kicker', text: 'Evaluation' }),
            h('h3', { style: 'margin:2px 0 0;font-size:22px;display:flex;align-items:center;gap:10px' },
              `Feynman Mastery: ${pct(score)}%`,
              h('span', { class: `mastery-badge ${level}`, text: level })
            )),
          activeEval.spoken_feedback ? h('button', {
            class: 'chip-btn',
            onclick: () => speakText(activeEval.spoken_feedback)
          }, icon('speaker'), 'Hear Akira') : null
        ),
        activeEval.verdict ? h('p', { class: 'lede', style: 'margin:0 0 20px', text: activeEval.verdict }) : null,
        strengths.length ? h('div', { class: 'feynman-section' },
          h('h4', { style: 'color:var(--good)' }, icon('check'), 'What You Understood Accurately:'),
          strengths.map(s => h('div', { class: 'feynman-strength-pill', text: s }))
        ) : null,
        flags.length ? h('div', { class: 'feynman-section' },
          h('h4', { style: 'color:var(--gold)' }, icon('feather'), 'Akira’s Clarification Flags (Gaps & Misconceptions):'),
          flags.map(f => h('div', { class: 'feynman-flag-pill' + (f.severity === 'misconception' ? ' misconception' : '') },
            f.concept ? h('span', { class: 'flag-concept-tag', text: f.concept.replace(/-/g, ' ') }) : null,
            document.createTextNode(f.note || '')
          ))
        ) : h('div', { class: 'feynman-strength-pill', style: 'color:var(--good);border-left-color:var(--good)', text: 'Zero misconceptions flagged! Your mental model is remarkably clear.' }),
        h('div', { style: 'display:flex;gap:12px;margin-top:24px;justify-content:center;flex-wrap:wrap' },
          h('button', {
            class: 'btn accent',
            onclick: () => {
              const next = meta.lessons.find(l => l.state === 'current');
              if (next) nav(`#/t/${meta.topic_slug}/${next.id}`);
              else nav(`#/t/${meta.topic_slug}`);
            }
          }, 'Continue Course', icon('arrow')),
          h('button', { class: 'btn ghost', onclick: () => nav(`#/t/${meta.topic_slug}/${lesson.id}`) }, 'Back to Lesson')
        )
      );
    }

    wrap.replaceChildren(hero, inputBox, resultSection || null);
  }

  draw();
}

/* — journal — */
async function viewJournal(meta) {
  stopSpeech(); S.meta = meta;
  const scored = meta.lessons.filter((l) => typeof l.quiz_score === 'number');
  const log = [...(meta.revision_log || [])].reverse();
  page(meta.topic, h('div', { class: 'journal' },
    h('button', { class: 'chip-btn', onclick: () => nav('#/t/' + meta.topic_slug) }, icon('back'), 'Back to course'),
    h('div', { class: 'kicker', style: 'margin-top:24px', text: 'Course journal' }), h('h1', { class: 'h-display', style: 'font-size:38px' }, 'How your course ', h('em', { text: 'adapted' })),
    scored.length ? h('div', { class: 'spark', role: 'img', 'aria-label': 'Quiz scores by lesson' }, scored.map((l, i) => h('div', { style: `height:${Math.max(6, pct(l.quiz_score))}%;animation-delay:${i * 90}ms`, title: l.title }, h('span', { text: pct(l.quiz_score) + '%' })))) : h('p', { class: 'lede', text: 'Finish a quiz and your results will appear here.' }),
    h('ul', { class: 'tl' }, log.map((r, i) => h('li', { class: ['inserted_remedial_lesson', 'adjust_depth', 'inserted_prerequisite_lesson'].includes(r.action) ? 'adapt' : '', style: `animation-delay:${i * 60}ms` },
      h('time', { text: ago(r.at) }), h('h4', { text: ({ roadmap_created: 'Roadmap drafted', confirmed_depth: 'Level confirmed', adjust_depth: 'Pace adjusted', inserted_remedial_lesson: 'Extra lesson added', inserted_prerequisite_lesson: 'Warm-up lesson added', proceed: 'Quiz passed', source_skipped: 'Source skipped' })[r.action] || r.action }), h('p', { text: r.detail }))))));
}

/* ── router ──────────────────────────────────────────────── */
async function route() {
  if (!TOKEN) { gate(); return; }
  if (observer) { observer.disconnect(); observer = null; }
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  if (!parts.length) return viewShelf();
  if (parts[0] === 'new') return viewNew();
  if (parts[0] !== 't' || !parts[1]) return viewShelf();
  const slug = parts[1];
  let meta;
  try { meta = await api('/topics/' + slug); } catch (e) { toast(e.message, true); return viewShelf(); }
  if (parts[2] === 'journal') return viewJournal(meta);
  if (meta.status === 'draft') return viewNew(slug);
  if (meta.status === 'planned') return viewRoadmap(meta);
  const cur = meta.lessons.find((l) => l.state === 'current') || meta.lessons[meta.lessons.length - 1];
  const lid = /^lesson_\d+$/.test(parts[2] || '') ? parts[2] : cur.id;
  const mode = parts[3] === 'quiz' ? 'quiz' : parts[3] === 'result' ? 'result' : parts[3] === 'feynman' ? 'feynman' : 'lesson';
  return viewStudy(meta, lid, mode);
}
window.addEventListener('hashchange', route);
route();
})();
