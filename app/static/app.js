/* Shared front-end helpers: API, formatting, charts. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

async function api(path, opts = {}) {
  if (window.__DEMO_API__) return window.__DEMO_API__(path, opts);   // used by the static demo build
  const init = { credentials: 'same-origin', ...opts };
  if (opts.json !== undefined) { init.method = init.method || 'POST'; init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(opts.json); }
  const r = await fetch(path, init);
  if (r.status === 401) { location.href = '/login'; return; }
  const body = r.headers.get('content-type')?.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body?.detail || r.statusText);
  return body;
}

function toast(msg, ms = 3200) {
  const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg; document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

const CUR = { AUD: 'A$', USD: '$', EUR: '€', GBP: '£', NZD: 'NZ$' };
let currency = 'AUD';
const fmt = {
  money: (v, d = 0) => v == null ? '—' : (CUR[currency] || '$') + Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }),
  money2: v => fmt.money(v, 2),
  num: (v, d = 0) => v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }),
  compact: v => v == null ? '—' : Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(v),
  pct: (v, d = 1) => v == null ? '—' : (v * 100).toFixed(d) + '%',
  x: v => v == null ? '—' : Number(v).toFixed(2) + '×',
  date: s => new Date(s + 'T00:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' }),
  esc: s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
};

/* change badge. goodWhenUp=false for costs (CPA, CPC) */
function delta(v, goodWhenUp = true) {
  if (v == null || !isFinite(v)) return '<span class="flat">—</span>';
  const up = v > 0, good = Math.abs(v) < 0.005 ? null : (up === goodWhenUp);
  const cls = good == null ? 'flat' : good ? 'up' : 'down';
  return `<span class="${cls}">${up ? '▲' : v < 0 ? '▼' : ''} ${Math.abs(v * 100).toFixed(1)}%</span>`;
}

/* colour follows the entity (platform/channel), never its rank */
const ENTITY_SLOT = {
  meta_ads: 1, google_ads: 2, tiktok_ads: 3, linkedin_ads: 7, pinterest_ads: 8, amazon_ads: 4, reddit_ads: 5, x_ads: 6,
  'Meta Ads': 1, 'Google Ads': 2, 'TikTok Ads': 3, 'LinkedIn Ads': 7, 'Organic Search': 6, 'Email': 4, 'Direct': 0, 'Organic Social': 5, 'Paid Search': 2,
  'Paid Social': 1, 'Referral': 8, 'Other': 0,
};
function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function colorFor(key) { const s = ENTITY_SLOT[key]; return s ? cssVar('--s' + s) : cssVar('--s-other'); }

const charts = {};
function chartDefaults() {
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = cssVar('--text-3');
  Chart.defaults.borderColor = cssVar('--grid');
}
function tooltipStyle() {
  return { backgroundColor: cssVar('--surface'), titleColor: cssVar('--text'), bodyColor: cssVar('--text-2'), borderColor: cssVar('--border-strong'),
    borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true };
}
function drawChart(id, cfg) {
  chartDefaults();
  if (charts[id]) charts[id].destroy();
  const el = document.getElementById(id);
  if (!el) return;
  const o = cfg.options || {};
  cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false } }, o,
    { plugins: Object.assign({ legend: { display: false }, tooltip: tooltipStyle() }, o.plugins || {}) });
  charts[id] = new Chart(el, cfg);
  return charts[id];
}
function legendHTML(items) {
  return '<div class="legend">' + items.map(i => `<span><i class="dot" style="background:${i.color}"></i>${fmt.esc(i.label)}</span>`).join('') + '</div>';
}
function axis(tickFmt) {
  return { grid: { color: cssVar('--grid') }, border: { display: false }, ticks: { callback: v => tickFmt ? tickFmt(v) : v, maxTicksLimit: 6 } };
}
function sparkline(values, color) {
  if (!values || values.length < 2) return '';
  const w = 110, h = 28, max = Math.max(...values), min = Math.min(...values), rng = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1) * w).toFixed(1)},${(h - 3 - (v - min) / rng * (h - 6)).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="${pts}"/></svg>`;
}

async function createClient(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const r = await api('/api/clients', { method: 'POST', body: fd });
    location.href = '/clients/' + r.id + '#local';
  } catch (err) { toast(err.message); }
  return false;
}
function toggleMenu() { $('#side')?.classList.toggle('open'); }
