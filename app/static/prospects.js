/* Prospects: audit a business's website and social media, price a proposal, send the pitch. */
const STATUSES = [['new', 'New'], ['contacted', 'Contacted'], ['meeting', 'Meeting booked'], ['won', 'Won'], ['lost', 'Lost']];
const AREA_ORDER = ['Tracking', 'Conversion', 'SEO', 'Trust', 'Compliance'];
const gradeOf = s => s == null ? '–' : s >= 85 ? 'A' : s >= 70 ? 'B' : s >= 55 ? 'C' : s >= 40 ? 'D' : 'E';
const gradeClass = g => g === 'A' || g === 'B' ? 'good' : g === 'C' ? 'warn' : g === '–' ? '' : 'bad';
const PTABS = [['overview', 'Overview'], ['social', 'Social media'], ['website', 'Website'], ['competitors', 'Competitors'], ['proposal', 'Proposal & fees'], ['pitch', 'Pitch email']];
let OPTS = null, curTab = 'overview', curId = null, curReport = null;

async function prospectsInit() {
  const root = $('#prospectsApp');
  root.innerHTML = `
    <form class="card" id="auditForm" style="margin-bottom:14px"><h2>Audit a business</h2>
      <div class="row"><input id="auditUrl" placeholder="e.g. bayside-plumbing.com.au" style="flex:1;min-width:220px" required>
        <button class="btn primary" id="auditBtn">Run audit</button></div>
      <p class="small muted" style="margin:8px 0 0">Checks their website, finds their social profiles, scores their online presence against similar businesses, and prices a proposal. Takes 5–30 seconds.</p></form>
    <div class="grid" style="grid-template-columns:minmax(0,.8fr) minmax(0,1.6fr);align-items:start" id="pGrid">
      <div class="card"><h2>Pipeline</h2><div class="tw"><table id="pTbl"></table></div></div>
      <div class="card" id="pCard"><div class="empty">Run an audit or pick a prospect.</div></div></div>`;
  $('#auditForm').onsubmit = async e => {
    e.preventDefault();
    const btn = $('#auditBtn'); btn.disabled = true; btn.textContent = 'Auditing…';
    try { const r = await api('/api/prospects', { json: { url: $('#auditUrl').value } }); $('#auditUrl').value = ''; curTab = 'overview'; await loadPipeline(); showProspect(r.id); }
    catch (err) { toast(err.message, 6000); }
    btn.disabled = false; btn.textContent = 'Run audit';
  };
  OPTS = await api('/api/prospects/options');
  await loadPipeline();
  const first = $('#pTbl tr[data-id]'); if (first) showProspect(+first.dataset.id);
}

async function loadPipeline() {
  const rows = await api('/api/prospects');
  $('#pTbl').innerHTML = `<thead><tr><th>Business</th><th class="r">Score</th><th>Stage</th></tr></thead><tbody>` + (rows.map(p => `<tr class="link" data-id="${p.id}">
    <td><b>${fmt.esc(p.name || p.domain)}</b>${p.is_example ? ' <span class="badge">example</span>' : ''}<div class="small muted">${fmt.esc(p.domain)} · ${fmt.esc(String(p.created_at).slice(0, 10))}</div></td>
    <td class="r"><span class="badge ${gradeClass(gradeOf(p.score))}">${gradeOf(p.score)} · ${p.score}</span></td>
    <td class="small">${(STATUSES.find(s => s[0] === p.status) || STATUSES[0])[1]}</td></tr>`).join('') || '<tr><td colspan=3 class="empty">No audits yet</td></tr>') + '</tbody>';
  $$('#pTbl tr[data-id]').forEach(tr => tr.onclick = () => showProspect(+tr.dataset.id));
  if (curId) $$('#pTbl tr').forEach(tr => tr.classList.toggle('sel', +tr.dataset.id === curId));
}

async function showProspect(id, data) {
  if (id !== curId) curTab = curTab || 'overview';
  curId = id;
  $$('#pTbl tr').forEach(tr => tr.classList.toggle('sel', +tr.dataset.id === id));
  const r = data || await api('/api/prospects/' + id);
  curReport = r;
  const o = r.overall || { score: r.score, grade: r.grade, website: r.score, social: null };
  const ss = r.social_summary || {};
  $('#pCard').innerHTML = `
    <div class="row" style="justify-content:space-between;align-items:flex-start;gap:14px">
      <div style="min-width:0"><h2 style="margin:0">${fmt.esc(r.name || r.domain)}</h2><a class="small" href="${fmt.esc(r.url)}" target="_blank" rel="noopener">${fmt.esc(r.domain)} ↗</a>
        ${r.is_example ? '<div class="small muted">Example audit of a fictional business</div>' : ''}
        <div class="small muted">${fmt.esc((OPTS.industries.find(i => i.key === r.business?.industry) || {}).label || '')} · ${fmt.esc((OPTS.sizes.find(s => s.key === r.business?.size) || {}).label || '')}</div></div>
      <div class="rings">
        <div class="ringbox"><div class="score-ring ${gradeClass(gradeOf(o.score))}"><b>${o.score}</b><span>${gradeOf(o.score)}</span></div><div class="small">Overall</div></div>
        <div class="ringbox"><div class="score-ring sm ${gradeClass(gradeOf(o.website))}"><b>${o.website}</b></div><div class="small">Website</div></div>
        <div class="ringbox"><div class="score-ring sm ${gradeClass(gradeOf(o.social))}"><b>${o.social ?? '–'}</b></div><div class="small">Social</div></div>
      </div></div>
    <div class="row" style="margin:10px 0 0;justify-content:flex-end"><a class="btn sm" href="/prospects/${r.id}/print" target="_blank" rel="noopener">🖨 Print leave-behind</a></div>
    <div class="row" style="margin:12px 0"><label class="f">Stage<select id="pStatus">${STATUSES.map(([k, l]) => `<option value="${k}" ${k === r.status ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="f" style="flex:1">Notes<input id="pNotes" value="${fmt.esc(r.notes || '')}" placeholder="Who you spoke to, next step…"></label></div>
    <div class="ptabs" role="tablist">${PTABS.map(([k, l]) => `<button type="button" data-t="${k}" class="${k === curTab ? 'on' : ''}">${l}${k === 'social' && ss.unassessed?.length ? ` <span class="dotwarn" title="Figures needed"></span>` : ''}</button>`).join('')}</div>
    <div id="pBody"></div>`;
  $$('.ptabs button').forEach(b => b.onclick = () => { curTab = b.dataset.t; $$('.ptabs button').forEach(x => x.classList.toggle('on', x === b)); renderTab(r); });
  const save = async () => { try { await api('/api/prospects/' + id, { method: 'PATCH', json: { status: $('#pStatus').value, notes: $('#pNotes').value } }); toast('Saved'); loadPipeline(); } catch (e) { toast(e.message); } };
  $('#pStatus').onchange = save; $('#pNotes').onchange = save;
  renderTab(r);
}

async function patchProspect(body, msg = 'Saved') {
  try { const r = await api('/api/prospects/' + curId, { method: 'PATCH', json: body }); toast(msg); await loadPipeline(); showProspect(curId, r); }
  catch (e) { toast(e.message, 5000); }
}

function renderTab(r) {
  const el = $('#pBody');
  ({ overview: tabOverview, social: tabSocial, website: tabWebsite, competitors: tabCompetitors, proposal: tabProposal, pitch: tabPitch })[curTab](el, r);
}

/* ---------- Overview ---------- */
function tabOverview(el, r) {
  const b = r.business || {}, ss = r.social_summary || {}, rk = r.rank || {};
  const socialIssues = Object.values(ss.platforms || {}).flatMap(p => (p.notes || []).filter(n => !n.startsWith('Enter a few')).map(n => ({ label: p.label, n, score: p.score ?? 0 })))
    .sort((a, b2) => a.score - b2.score).slice(0, 3);
  el.innerHTML = `
    <form id="bizForm" class="bizform">
      <label class="f">Industry<select name="industry">${OPTS.industries.map(i => `<option value="${i.key}" ${i.key === b.industry ? 'selected' : ''}>${fmt.esc(i.label)}</option>`).join('')}</select></label>
      <label class="f">Business size<select name="size">${OPTS.sizes.map(s => `<option value="${s.key}" ${s.key === b.size ? 'selected' : ''}>${fmt.esc(s.label)}</option>`).join('')}</select></label>
      <label class="f">Locations<input name="locations" type="number" min="1" max="50" value="${b.locations || 1}" style="width:90px"></label>
      <label class="f">Suburb / area<input name="area" value="${fmt.esc(b.area || '')}" placeholder="e.g. Berwick VIC" style="width:160px"></label>
      <button class="btn">Update</button>
    </form>
    <p class="small muted" style="margin-top:6px">${r.industry_guess && r.industry_guess !== 'other' && r.industry_guess === b.industry && !b.industry_set ? 'Industry was detected from their website. ' : b.industry === 'other' ? '<b>Choose their industry</b> so prices and benchmarks fit. ' : ''}These set the benchmarks for scoring and the fees in the proposal.</p>
    ${rk.overall_count > 1 ? `<div class="callout small" style="margin:10px 0">Ranks <b>#${rk.industry_rank} of ${rk.industry_count}</b> ${fmt.esc((OPTS.industries.find(i => i.key === b.industry) || {}).label || '')} businesses you've audited, and <b>#${rk.overall_rank} of ${rk.overall_count}</b> overall. Lower-ranked businesses have the most room to improve.</div>` : ''}
    ${compCallout(r)}
    ${ss.missing?.length ? `<div class="callout warn small" style="margin:10px 0">No ${ss.missing.join(', ')} found. For this industry, that's where customers look before choosing.</div>` : ''}
    ${ss.unassessed?.length ? `<div class="callout small" style="margin:10px 0">${ss.unassessed.join(', ')} ${ss.unassessed.length > 1 ? 'aren\'t' : 'isn\'t'} scored yet. Add a few figures in <a href="#" onclick="curTab='social';showProspect(curId);return false">Social media</a> for an exact score (scored as average until then).</div>` : ''}
    <h3 style="margin-top:14px">Biggest opportunities</h3>
    ${r.top_issues.slice(0, 3).map(i => `<div class="issue"><div class="t">Website · ${fmt.esc(i.problem || i.title)}</div><div class="small">${fmt.esc(i.impact)}</div></div>`).join('')}
    ${socialIssues.map(s => `<div class="issue"><div class="t">${fmt.esc(s.label)}</div><div class="small">${fmt.esc(s.n)}</div></div>`).join('')}
    ${(r.compliance || []).length ? `<h3 style="margin-top:14px">Health advertising rules</h3><div class="callout small">${r.compliance.map(c => `<div style="margin:3px 0">• ${fmt.esc(c)}</div>`).join('')}</div>` : ''}`;
  $('#bizForm').onsubmit = e => { e.preventDefault(); const fd = Object.fromEntries(new FormData(e.target)); fd.locations = +fd.locations || 1; patchProspect({ business: fd }, 'Updated'); };
}

/* ---------- Social media ---------- */
const FIELD_HELP = {
  followers: 'Followers / page likes shown on the profile',
  posts_30d: 'Count their posts dated in the last 30 days',
  days_since_post: 'Days since their most recent post',
  avg_engagement: 'Average likes + comments on their last ~5 posts',
  rating: 'Star rating shown on Google',
  reviews: 'Total number of Google reviews',
};
function tabSocial(el, r) {
  const ss = r.social_summary || { platforms: {}, expected: [] };
  const plats = ss.platforms || {};
  const order = [...(ss.expected || []), ...Object.keys(plats).filter(p => !(ss.expected || []).includes(p))];
  const others = OPTS.platforms.filter(p => !order.includes(p.key));
  const field = (plat, k, v, w = 96) => `<label class="f" title="${FIELD_HELP[k]}">${{ followers: 'Followers', posts_30d: 'Posts (30d)', days_since_post: 'Days since post', avg_engagement: 'Avg likes+comments', rating: 'Rating ★', reviews: 'Reviews' }[k]}
    <input data-p="${plat}" data-k="${k}" type="number" step="${k === 'rating' ? '0.1' : '1'}" min="0" value="${v ?? ''}" style="width:${w}px" placeholder="?"></label>`;
  el.innerHTML = `
    <p class="small muted">Profiles linked from their website are found automatically. Platforms like Facebook and Instagram don't allow other businesses' figures to be read automatically, so open each profile and copy a few public numbers (about a minute each).${plats.youtube ? ' YouTube fills in automatically when a Google API key with YouTube Data API is set.' : ''}</p>
    <div id="socList">${order.map(p => {
      const s = plats[p] || { label: (OPTS.platforms.find(x => x.key === p) || {}).label, exists: false, notes: [] };
      const d = (r.social || {})[p] || {};
      const isG = p === 'google_business';
      const search = isG ? `https://www.google.com/maps/search/${encodeURIComponent(r.name || r.domain)}` : `https://www.google.com/search?q=${encodeURIComponent((r.name || r.domain) + ' ' + s.label)}`;
      return `<div class="plat">
        <div class="row" style="justify-content:space-between;gap:8px">
          <div><b>${fmt.esc(s.label)}</b> ${(ss.expected || []).includes(p) ? '<span class="badge accent">key for this industry</span>' : ''} ${d.detected ? '<span class="badge">found on website</span>' : ''} ${d.auto ? '<span class="badge good">auto</span>' : ''}</div>
          <span class="badge ${s.exists ? gradeClass(s.grade || '–') : 'bad'}">${s.exists ? (s.score == null ? 'needs figures' : `${s.grade} · ${s.score}`) : 'not found'}</span></div>
        <div class="row" style="margin-top:8px;gap:8px;align-items:flex-end">
          <label class="f" style="flex:1;min-width:200px">${isG ? 'Google Maps link (optional)' : 'Profile link'}<input data-p="${p}" data-k="url" value="${fmt.esc(d.url || '')}" placeholder="${isG ? 'Paste the Maps link, or tick “Has a profile”' : 'https://…'}"></label>
          ${d.url ? `<a class="btn sm" href="${fmt.esc(d.url)}" target="_blank" rel="noopener">Open ↗</a>` : `<a class="btn sm ghost" href="${search}" target="_blank" rel="noopener">Search ↗</a>`}
          ${isG ? `<label class="row small" style="gap:4px"><input type="checkbox" data-p="${p}" data-k="exists" ${d.exists || d.url ? 'checked' : ''}> Has a profile</label>` : ''}
        </div>
        <div class="row" style="margin-top:6px;gap:8px">${isG ? field(p, 'rating', d.rating, 80) + field(p, 'reviews', d.reviews) + field(p, 'posts_30d', d.posts_30d)
          : field(p, 'followers', d.followers, 110) + field(p, 'posts_30d', d.posts_30d) + field(p, 'days_since_post', d.days_since_post) + (p === 'youtube' ? '' : field(p, 'avg_engagement', d.avg_engagement, 130))}</div>
        ${s.parts?.length > 1 ? `<div class="small muted" style="margin-top:6px">${s.parts.slice(1).map(x => `${fmt.esc(x.name)}: ${fmt.esc(x.note)} (${Math.round(x.points)}/${x.max})`).join(' · ')}</div>` : ''}
        ${(s.notes || []).map(n => `<div class="small" style="margin-top:4px">→ ${fmt.esc(n)}</div>`).join('')}
      </div>`;
    }).join('')}</div>
    <div class="row" style="margin-top:12px;justify-content:space-between">
      <div class="row">${others.length ? `<select id="addPlat"><option value="">Add another platform…</option>${others.map(o => `<option value="${o.key}">${fmt.esc(o.label)}</option>`).join('')}</select>` : ''}</div>
      <button class="btn primary" id="socSave">Save &amp; score</button></div>`;
  const collect = () => {
    const out = {};
    $$('#socList [data-p]').forEach(i => {
      const p = i.dataset.p, k = i.dataset.k; out[p] = out[p] || {};
      out[p][k] = i.type === 'checkbox' ? i.checked : i.value.trim();
    });
    return out;
  };
  $('#socSave').onclick = () => patchProspect({ social: collect() }, 'Scored');
  const add = $('#addPlat');
  if (add) add.onchange = () => { if (add.value) patchProspect({ social: { ...collect(), [add.value]: { exists: true } } }, 'Added'); };
}

/* ---------- Website (original audit) ---------- */
function tabWebsite(el, r) {
  const byArea = AREA_ORDER.map(a => [a, r.checks.filter(c => c.area === a)]).filter(([, cs]) => cs.length);
  el.innerHTML = `
    <div class="row" style="justify-content:space-between"><h3 style="margin:0">Website score: ${r.score}/100 (${r.grade})</h3><button class="btn sm" id="rescan">↻ Re-scan website</button></div>
    ${r.top_issues.length ? r.top_issues.map(i => `<div class="issue"><div class="t">${fmt.esc(i.title)}</div><div class="small">${fmt.esc(i.impact)}</div><div class="small muted">Fix: ${fmt.esc(i.fix)}</div></div>`).join('') : '<div class="callout small">No major website gaps.</div>'}
    <h3 style="margin-top:16px">Their live ads (public ad libraries)</h3>
    <div class="row">${[['meta', 'Meta Ad Library'], ['google', 'Google Ads Transparency'], ['linkedin', 'LinkedIn Ad Library'], ['tiktok', 'TikTok Ad Library']]
      .map(([k, l]) => `<a class="btn sm" href="${fmt.esc(r.ad_library[k])}" target="_blank" rel="noopener">${l} ↗</a>`).join('')}</div>
    <p class="small muted">If they run ads but have no conversion tracking, lead with that: they're spending without being able to measure results.</p>
    <h3 style="margin-top:16px">Tracking found on their site</h3>
    <div class="row">${Object.entries(r.trackers).map(([k, v]) => `<span class="badge ${v ? 'good' : 'bad'}">${v ? '✓' : '✕'} ${fmt.esc(k)}</span>`).join('')}
      <span class="badge ${r.consent_banner ? 'good' : 'warn'}">${r.consent_banner ? '✓' : '✕'} Cookie consent</span></div>
    <h3 style="margin-top:16px">All checks</h3>
    <div class="grid g2">${byArea.map(([a, cs]) => `<div><div class="small" style="font-weight:600;margin-bottom:4px">${a}</div>${cs.map(c =>
      `<div class="chk ${c.ok ? 'ok' : 'no'}"><span>${c.ok ? '✓' : '✕'}</span>${fmt.esc(c.title)}</div>`).join('')}</div>`).join('')}</div>
    <div class="small muted" style="margin-top:8px">Load time ${r.load_seconds}s · page size ${fmt.num(r.page_kb)} KB${r.pagespeed ? ` · PageSpeed mobile ${r.pagespeed.score}/100 (LCP ${fmt.esc(r.pagespeed.lcp || '—')})` : ''}${r.title ? ` · title “${fmt.esc(r.title)}”` : ''}</div>`;
  $('#rescan').onclick = async () => {
    const b = $('#rescan'); b.disabled = true; b.textContent = 'Scanning…';
    try { const d = await api(`/api/prospects/${curId}/rescan`, { method: 'POST' }); toast('Website re-scanned'); await loadPipeline(); showProspect(curId, d); }
    catch (e) { toast(e.message, 5000); b.disabled = false; b.textContent = '↻ Re-scan website'; }
  };
}

/* ---------- Competitors ---------- */
function compCallout(r) {
  const cs = r.competitor_summary; if (!cs) return '';
  const me = cs.my_reviews == null ? 'their review count isn\'t known yet (add it in Social media → Google Business Profile)'
    : `they have <b>${cs.my_reviews}</b> reviews${cs.my_rating ? ` (★${cs.my_rating})` : ''}, ranking <b>#${cs.rank} of ${cs.of}</b> nearby`;
  return `<div class="callout ${cs.behind ? 'warn' : ''} small" style="margin:10px 0">Nearby competitors: typical business has <b>${cs.median_reviews}</b> Google reviews${cs.avg_rating ? ` (avg ★${cs.avg_rating})` : ''};
    ${me}. Most reviewed: <b>${fmt.esc(cs.top.name)}</b> with ${cs.top.reviews}.</div>`;
}
function tabCompetitors(el, r) {
  const b = r.business || {}, comp = (r.competitors || {}).list || [];
  const gbp = (r.social || {}).google_business || {};
  const maps = `https://www.google.com/maps/search/${encodeURIComponent(((b.search_term || '') + ' near ' + (b.area || '')).trim())}`;
  const rows = [...comp.map((c, i) => ({ ...c, i })), ...(comp.some(c => c.is_self) ? [] : [{ name: (r.name || r.domain) + ' (them)', rating: gbp.rating, reviews: gbp.reviews, is_self: true, virtual: true }])]
    .sort((a, b2) => (+b2.reviews || 0) - (+a.reviews || 0));
  el.innerHTML = `
    <p class="small muted">Similar businesses near them, compared on Google rating and number of reviews: the two things people check before they call. Public listing data only.</p>
    <form id="compForm" class="payform">
      <label class="f">What they do<input name="search_term" value="${fmt.esc(b.search_term || '')}" placeholder="e.g. plumber" style="width:160px"></label>
      <label class="f">Suburb / area<input name="area" value="${fmt.esc(b.area || '')}" placeholder="e.g. Berwick VIC" style="width:170px"></label>
      ${OPTS.places_enabled ? '<button class="btn primary">Find competitors</button>' : '<button class="btn">Save</button>'}
      <a class="btn ghost" href="${maps}" target="_blank" rel="noopener">Open in Google Maps ↗</a>
      ${OPTS.places_enabled ? '' : `<div class="small muted" style="flex:1 1 100%">Automatic search needs a Google Places API key (see DEPLOY.md). Until then, open Google Maps and add the top few by hand below.</div>`}
    </form>
    ${compCallout(r)}
    ${rows.length > 1 || comp.length ? `<div class="tw"><table><thead><tr><th>Business</th><th class="r">Rating</th><th class="r">Reviews</th><th>Website</th><th></th></tr></thead><tbody>
      ${rows.map(c => `<tr class="${c.is_self ? 'sel' : ''}"><td>${c.maps ? `<a href="${fmt.esc(c.maps)}" target="_blank" rel="noopener">${fmt.esc(c.name)}</a>` : fmt.esc(c.name)}${c.is_self ? ' <span class="badge accent">them</span>' : ''}${c.address ? `<div class="small muted">${fmt.esc(c.address)}</div>` : ''}</td>
        <td class="r">${c.rating ? '★' + c.rating : '–'}</td><td class="r">${c.reviews ?? '–'}</td>
        <td class="small">${c.website ? `<a href="${fmt.esc(c.website)}" target="_blank" rel="noopener">${fmt.esc(c.website.replace(/^https?:\/\/(www\.)?/, '').slice(0, 30))}</a>` : '<span class="muted">none</span>'}</td>
        <td class="r">${c.virtual ? '' : `<button class="btn sm ghost" data-del="${c.i}" title="Remove">✕</button>`}</td></tr>`).join('')}
    </tbody></table></div>` : ''}
    <form id="compAdd" class="row" style="margin-top:12px;gap:8px;align-items:flex-end">
      <label class="f" style="flex:1;min-width:180px">Add a competitor by hand<input name="name" placeholder="Business name" required></label>
      <label class="f">Rating ★<input name="rating" type="number" step="0.1" min="0" max="5" style="width:80px"></label>
      <label class="f">Reviews<input name="reviews" type="number" min="0" style="width:90px"></label>
      <label class="f">Website<input name="website" placeholder="optional" style="width:160px"></label>
      <button class="btn">Add</button></form>
    <p class="small muted" style="margin-top:10px">Use this in the pitch: “${fmt.esc(r.competitor_summary?.top?.name || 'The busiest competitor near you')} has ${r.competitor_summary?.top?.reviews ?? 'far more'} Google reviews. Let's close that gap.” The review gap also appears on the leave-behind and in the pitch email.</p>`;
  $('#compForm').onsubmit = async e => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(e.target));
    if (!OPTS.places_enabled) return patchProspect({ business: fd }, 'Saved');
    toast('Searching Google…');
    try { const res = await api(`/api/prospects/${curId}/competitors`, { method: 'POST', json: fd }); toast('Competitors found'); showProspect(curId, res); }
    catch (err) { toast(err.message, 7000); }
  };
  $('#compAdd').onsubmit = e => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(e.target));
    patchProspect({ competitors: [...comp, { name: fd.name, rating: fd.rating ? +fd.rating : null, reviews: fd.reviews ? +fd.reviews : null, website: fd.website, manual: true }] }, 'Added');
  };
  $$('[data-del]').forEach(btn => btn.onclick = () => patchProspect({ competitors: comp.filter((_, i) => i !== +btn.dataset.del) }, 'Removed'));
}

/* ---------- Proposal & fees ---------- */
const VERDICT = { good: ['good', '✓ Good fit'], stretch: ['warn', 'Stretch'], too_expensive: ['bad', 'Too expensive for them'], too_cheap: ['warn', 'Too cheap for you'], unknown: ['', '?'] };
function offerBox(r) {
  const q = r.quote, pc = q.price_check || {}, b = r.business || {};
  const money = v => '$' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  const by = n => q.tiers.find(t => t.name === n);
  const starter = q.tiers.find(t => t.starter);
  let next = pc.best && pc.best !== 'Starter' ? by(pc.best) : null;
  if (!next) next = q.tiers.find(t => t.lite) || by('Essentials');
  const gaps = [...(r.social_summary?.missing || []).map(m => 'no ' + m), ...(r.top_issues || []).slice(0, 2).map(i => (i.problem || i.title).toLowerCase())].slice(0, 3);
  return `<div class="offer-box">
    <div style="font-size:15px"><b>What to offer</b> ${pc.best ? '<span class="badge good">based on their numbers</span>' : '<span class="badge">fill in the 3 boxes below to check it fits their budget</span>'}</div>
    <div class="offer-steps">
      <div><span class="n">1</span><div><b>Now: ${fmt.esc(starter.name)}, ${money(starter.setup_total)} once.</b> No contract.<div class="small muted">Fixes their biggest gaps${gaps.length ? ': ' + fmt.esc(gaps.join(', ')) : ''}.</div></div></div>
      ${next ? `<div><span class="n">2</span><div><b>After 4–6 weeks: ${fmt.esc(next.name)}, ${money(next.monthly_total)}/month${next.setup_total ? ` + ${money(next.setup_total)} setup` : ''}.</b>${next.lite ? ' Month to month.' : ''}
        <div class="small muted">Once they can see more calls and directions on your dashboard.</div></div></div>` : ''}
    </div>
    <div class="small muted">You can ignore the other packages for this business unless they ask for more. Details of each package are further down.</div>
  </div>`;
}

function priceCheckBox(q) {
  const pc = q.price_check; if (!pc) return '';
  const money = v => '$' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  return `<div class="pcheck">
    <div class="row" style="justify-content:space-between;gap:8px"><b>Price check</b>
      ${pc.best ? `<span>Best fit for them: <b>${fmt.esc(pc.best)}</b></span>` : '<span class="small muted">Add their rough yearly turnover above to see which package they can afford</span>'}</div>
    <div class="tw"><table><thead><tr><th>Package</th><th class="r">Your time</th><th class="r">You earn</th><th class="r">Year one for them</th><th class="r">% of turnover</th><th>Verdict</th></tr></thead><tbody>
    ${pc.rows.map(x => `<tr><td>${fmt.esc(x.name)}</td>
      <td class="r small">${x.hours_month ? `~${x.hours_month} h/mo` : `~${x.hours_setup} h once`}</td>
      <td class="r ${x.per_hour != null && x.per_hour < pc.target_hourly ? 'neg' : ''}">${x.per_hour != null ? money(x.per_hour) + '/h' : '–'}</td>
      <td class="r">${money(x.year_cost)}</td>
      <td class="r">${x.pct_revenue != null ? x.pct_revenue + '%' : '–'}</td>
      <td>${x.verdict === 'unknown' ? '<span class="small muted">needs turnover</span>' : `<span class="badge ${VERDICT[x.verdict][0]}">${VERDICT[x.verdict][1]}</span>`}</td></tr>
      ${x.flags.length ? `<tr class="flagrow"><td colspan="6" class="small">${x.flags.map(f => '→ ' + fmt.esc(f)).join('<br>')}</td></tr>` : ''}`).join('')}
    </tbody></table></div>
    <div class="small muted">Rules: small businesses typically spend ${pc.comfy_pct}% or less of turnover on marketing (incl. ad spend); up to ${pc.ok_pct}% is the usual guideline, over ${pc.high_pct}% is a likely no.
      “You earn” = fees ÷ your estimated hours, against your ${money(pc.target_hourly)}/h target (change it in <a href="/settings#rates">Rate card</a>).</div>
  </div>`;
}
function aiBox(r) {
  const a = r.ai_review;
  const list = (t, xs) => xs && xs.length ? `<div class="small" style="margin-top:6px"><b>${t}</b>${xs.map(x => `<div>• ${fmt.esc(x)}</div>`).join('')}</div>` : '';
  if (!OPTS.ai_enabled && !a) return `<div class="aibox"><div class="row" style="justify-content:space-between;gap:8px"><b>🤖 Free AI second opinion</b>
      <button class="btn sm primary" id="aiCopy" type="button">Copy for Claude</button></div>
    <div class="small muted" style="margin-top:4px">Click the button, open <a href="https://claude.ai/new" target="_blank" rel="noopener">claude.ai</a> (free account), press Ctrl+V and Enter.
      Claude reads this proposal and suggests which package to lead with and what to say. The price check above already works without it.</div></div>`;
  return `<div class="aibox">
    <div class="row" style="justify-content:space-between;gap:8px"><b>🤖 AI price review</b>
      ${OPTS.ai_enabled ? `<button class="btn sm ${a ? '' : 'primary'}" id="aiRun" type="button">${a ? 'Run again' : 'Ask AI to review these prices'}</button>` : ''}</div>
    ${a ? `${a.stale ? '<div class="callout warn small" style="margin:6px 0">Prices or details changed since this review. Run it again.</div>' : ''}
      ${a.lead_with ? `<div style="margin-top:6px">Lead with <b>${fmt.esc(a.lead_with)}</b>${a.suggested_monthly ? ` at about <b>$${Number(a.suggested_monthly).toLocaleString()}/month</b>` : ''}${a.suggested_setup ? ` + $${Number(a.suggested_setup).toLocaleString()} setup` : ''}</div>` : ''}
      ${a.why ? `<div class="small" style="margin-top:4px">${fmt.esc(a.why)}</div>` : ''}
      ${a.say_this ? `<div class="callout small" style="margin-top:8px"><b>Say this:</b> “${fmt.esc(a.say_this)}”</div>` : ''}
      ${list('Change', a.change)}${list('Ask them', a.ask_them)}${list('Watch out', a.watch_out)}
      <div class="small muted" style="margin-top:6px">AI suggestion from ${fmt.esc(a.date || '')}. It doesn't change your prices, you decide.</div>`
    : '<div class="small muted" style="margin-top:4px">Reads the audit, packages, price check and market prices, then suggests which package to lead with, what to change and what to say. Costs a few cents per review.</div>'}
  </div>`;
}

function marketBox(m) {
  if (!m) return '';
  return `<details class="market"><summary><b>What else they could pay for</b> <span class="small muted">· Australian market prices, researched ${fmt.esc(m.as_of)}</span></summary>
    ${m.you.length ? `<div class="mk-you">${m.you.map(y => `<div>✓ ${fmt.esc(y)}</div>`).join('')}</div>` : ''}
    <div class="callout small" style="margin:8px 0">${fmt.esc(m.tip)}</div>
    <div class="tw"><table><thead><tr><th>Option</th><th class="r">Price (AUD)</th><th>Notes</th></tr></thead><tbody>
      ${m.rows.map(x => `<tr${x.industry_specific ? ' class="sel"' : ''}><td>${fmt.esc(x.label)}${x.industry_specific ? ' <span class="badge accent">their industry</span>' : ''}</td>
        <td class="r" style="white-space:nowrap">${fmt.esc(x.price)}</td><td class="small">${fmt.esc(x.note)} · <a href="${fmt.esc(x.url)}" target="_blank" rel="noopener">source</a></td></tr>`).join('')}
    </tbody></table></div>
    <p class="small muted">Prices change. Open the source before quoting a competitor's price to a client.</p></details>`;
}

function tabProposal(el, r) {
  const q = r.quote; if (!q) { el.innerHTML = '<div class="empty">No proposal yet.</div>'; return; }
  const money = v => '$' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  const b = r.business || {};
  const pb = t => {
    if (!t.payback) return '';
    const n = t.starter ? t.payback.customers_per_year : t.payback.customers_per_month;
    return `<div class="payback">Pays for itself with <b>${n}</b> new regular${n === 1 ? '' : 's'} ${t.starter ? 'in total' : 'a month'}<br><span class="muted">${t.starter ? '' : 'Year one: fees + ad spend '}${money(t.payback.year_cost)}</span></div>`;
  };
  const pcRow = n => ((q.price_check || {}).rows || []).find(x => x.name === n);
  const chip = t => { const x = pcRow(t.name); if (!x || x.verdict === 'unknown') return ''; const [c, l] = VERDICT[x.verdict]; return `<span class="badge ${c}" title="${fmt.esc(x.flags.join(' '))}">${l}</span>`; };
  const card = t => t.starter ? `<div class="ptier starter">
      <div class="badge good" style="margin-bottom:6px">Easy yes · no contract</div>
      <h3 style="margin:0 0 4px;color:var(--text)">${t.name} ${chip(t)}</h3>
      <div class="price">${money(t.setup_total)}<span> once</span></div>
      <div class="small muted">${fmt.esc(t.tagline)}</div>
      <div class="small" style="margin-top:10px;font-weight:600">One-off jobs</div>
      ${t.setup.map(i => `<div class="li"><span>${fmt.esc(i.item)}<br><span class="muted">${fmt.esc(i.detail)}</span></span><b>${money(i.amount)}</b></div>`).join('')}
      <div class="small" style="margin-top:10px;font-weight:600">Optional afterwards</div>
      ${t.monthly.map(i => `<div class="li"><span>${fmt.esc(i.item.replace(' (optional)', ''))}<br><span class="muted">${fmt.esc(i.detail)}</span></span><b>${money(i.amount)}/mo</b></div>`).join('')}
      ${pb(t)}
    </div>` : `<div class="ptier ${t.recommended ? 'rec' : ''} ${t.lite ? 'lite' : ''}">
      ${t.recommended || t.lite ? `<div class="row" style="gap:6px;margin-bottom:6px">${t.recommended ? '<span class="badge accent">Recommended</span>' : ''}${t.lite ? '<span class="badge good">No lock-in</span>' : ''}</div>` : ''}
      <h3 style="margin:0 0 4px;color:var(--text)">${t.name} ${chip(t)}</h3>
      <div class="price">${money(t.monthly_total)}<span>/month</span></div>
      ${t.tagline ? `<div class="small muted">${fmt.esc(t.tagline)}</div>` : ''}
      <div class="small muted">${t.setup_total ? money(t.setup_total) + ' one-off setup' : 'No setup fee'}${t.ad_spend ? ` · suggested ad spend ${money(t.ad_spend)}/mo` : ''}</div>
      <div class="small" style="margin-top:10px;font-weight:600">Monthly</div>
      ${t.monthly.map(i => `<div class="li"><span>${fmt.esc(i.item)}<br><span class="muted">${fmt.esc(i.detail)}</span></span><b>${money(i.amount)}</b></div>`).join('')}
      ${t.setup.length ? `<div class="small" style="margin-top:10px;font-weight:600">One-off</div>${t.setup.map(i => `<div class="li"><span>${fmt.esc(i.item)}</span><b>${money(i.amount)}</b></div>`).join('')}` : ''}
      <div class="small muted" style="margin-top:10px">First-year fees: ${money(t.first_year)}</div>
      ${pb(t)}
    </div>`;
  el.innerHTML = `
    ${offerBox(r)}
    <p class="small muted">Priced for a <b>${fmt.esc(q.size)}</b> ${fmt.esc(q.industry)} business with ${q.locations} location${q.locations > 1 ? 's' : ''}, from your <a href="/settings#rates">rate card</a>. ${fmt.esc(q.gst_note)}</p>
    <form id="payForm" class="payform">
      <div style="flex:1 1 100%"><b>Pays for itself &amp; price check</b>
        <div class="small muted">Ask the owner: “Roughly what does a regular customer spend with you in a year, what's your margin, and roughly what's your yearly turnover?” Use their numbers, not guesses. Any one of them helps.</div></div>
      <label class="f">A regular spends per year ($)<input name="customer_spend" type="number" min="0" step="10" value="${b.customer_spend || ''}" placeholder="e.g. 600" style="width:150px"></label>
      <label class="f">Their profit margin (%)<input name="margin_pct" type="number" min="1" max="100" step="1" value="${b.margin_pct || ''}" placeholder="e.g. 35" style="width:130px"></label>
      <label class="f">Their yearly turnover, rough ($)<input name="revenue" type="number" min="0" step="1000" value="${b.revenue || ''}" placeholder="e.g. 250000" style="width:170px"></label>
      <button class="btn primary">Work it out</button>
      ${q.customer_value ? `<div class="small" style="align-self:center">Each new regular ≈ <b>${money(q.customer_value)}</b> profit a year</div>` : ''}
    </form>
    ${priceCheckBox(q)}
    ${aiBox(r)}
    <div class="ptiers">${q.tiers.map(card).join('')}</div>
    ${marketBox(r.market)}
    <div class="row" style="margin-top:12px;justify-content:space-between">
      <label class="row small" style="gap:6px"><input type="checkbox" id="mentionPrice" ${b.mention_pricing ? 'checked' : ''}> Mention prices in the pitch email</label>
      <div class="row"><a class="btn" href="/prospects/${r.id}/print" target="_blank" rel="noopener">🖨 Print leave-behind</a><button class="btn" id="copyProp">Copy proposal text</button></div></div>`;
  $('#payForm').onsubmit = e => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(e.target));
    patchProspect({ business: { customer_spend: +fd.customer_spend || 0, margin_pct: +fd.margin_pct || 100, revenue: +fd.revenue || 0 } }, 'Calculated');
  };
  const aiCopy = $('#aiCopy');
  if (aiCopy) aiCopy.onclick = async () => {
    try { const d = await api(`/api/prospects/${curId}/ai-prompt`); await navigator.clipboard.writeText(d.text);
      toast('Copied. Now open claude.ai, press Ctrl+V and Enter', 6000); }
    catch (err) { toast('Copy failed: ' + err.message, 6000); }
  };
  const aiBtn = $('#aiRun');
  if (aiBtn) aiBtn.onclick = async () => {
    aiBtn.disabled = true; aiBtn.textContent = 'Thinking… (about 20 seconds)';
    try { const res = await api(`/api/prospects/${curId}/ai-review`, { method: 'POST' }); toast('AI review ready'); showProspect(curId, res); }
    catch (err) { toast(err.message, 8000); aiBtn.disabled = false; aiBtn.textContent = 'Ask AI to review these prices'; }
  };
  $('#mentionPrice').onchange = e => patchProspect({ business: { mention_pricing: e.target.checked } }, e.target.checked ? 'Prices added to pitch' : 'Prices removed from pitch');
  $('#copyProp').onclick = async () => {
    const txt = [`Proposal for ${r.name || r.domain}`, `(${q.gst_note})`, ''].concat(q.tiers.flatMap(t => t.starter ? [
      `${t.name}: ${money(t.setup_total)} once, no contract`, ...t.setup.map(i => `  • ${i.item} — ${money(i.amount)}`),
      ...t.monthly.map(i => `  • Optional: ${i.item.replace(' (optional)', '')} — ${money(i.amount)}/mo, cancel any time`),
      ...(t.payback ? [`  Pays for itself with ${t.payback.customers_per_year} new regular customers`] : []), ''] : [
      `${t.name}${t.recommended ? ' (recommended)' : ''}: ${money(t.monthly_total)}/month${t.setup_total ? ` + ${money(t.setup_total)} setup` : ''}${t.ad_spend ? `, suggested ad spend ${money(t.ad_spend)}/month` : ''}`,
      ...t.monthly.map(i => `  • ${i.item} — ${money(i.amount)}/mo`), ...t.setup.map(i => `  • ${i.item} — ${money(i.amount)} one-off`),
      ...(t.payback ? [`  Pays for itself with about ${t.payback.customers_per_month} new regular customers a month`] : []), ''])).join('\n');
    try { await navigator.clipboard.writeText(txt); toast('Proposal copied'); } catch { toast('Copy not available in this browser'); }
  };
}

/* ---------- Pitch ---------- */
function tabPitch(el, r) {
  el.innerHTML = `
    <label class="f">Subject<input id="pSubj" value="${fmt.esc(r.pitch.subject)}"></label>
    <textarea id="pText" rows="16" style="width:100%;margin-top:8px">${fmt.esc(r.pitch.body)}</textarea>
    <div class="row" style="margin-top:8px"><button class="btn primary" id="pCopy">Copy email</button><button class="btn ghost" id="pDel">Delete audit</button></div>
    <p class="small muted">Australian Spam Act: B2B cold email is OK to a conspicuously published business address when it relates to their business, identifies you, and has a working unsubscribe.</p>`;
  $('#pCopy').onclick = async () => {
    const text = `Subject: ${$('#pSubj').value}\n\n${$('#pText').value}`;
    try { await navigator.clipboard.writeText(text); toast('Email copied'); } catch { $('#pText').select(); toast('Selected. Press Ctrl+C to copy'); }
  };
  let armed = false;
  $('#pDel').onclick = async () => {
    if (!armed) { armed = true; $('#pDel').textContent = 'Click again to delete'; return; }
    try { await api('/api/prospects/' + curId, { method: 'DELETE' }); $('#pCard').innerHTML = '<div class="empty">Deleted.</div>'; curId = null; loadPipeline(); } catch (e) { toast(e.message); }
  };
}

if (!window.__DEMO_SHELL__) prospectsInit();
