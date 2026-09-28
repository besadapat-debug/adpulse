/* Prospects: audit a website, track the pipeline, send the pitch. */
const STATUSES = [['new', 'New'], ['contacted', 'Contacted'], ['meeting', 'Meeting booked'], ['won', 'Won'], ['lost', 'Lost']];
const AREA_ORDER = ['Tracking', 'Conversion', 'SEO', 'Trust', 'Compliance'];
const gradeClass = g => g === 'A' || g === 'B' ? 'good' : g === 'C' ? 'warn' : 'bad';

async function prospectsInit() {
  const root = $('#prospectsApp');
  root.innerHTML = `
    <form class="card" id="auditForm" style="margin-bottom:14px"><h2>Audit a business</h2>
      <div class="row"><input id="auditUrl" placeholder="e.g. bayside-plumbing.com.au" style="flex:1;min-width:220px" required>
        <button class="btn primary" id="auditBtn">Run audit</button></div>
      <p class="small muted" style="margin:8px 0 0">Checks their tracking pixels, mobile readiness, calls-to-action, SEO basics and speed, links to their live ads in the public ad libraries, and drafts a pitch. Takes 5–30 seconds.</p></form>
    <div class="grid" style="grid-template-columns:minmax(0,.9fr) minmax(0,1.4fr);align-items:start" id="pGrid">
      <div class="card"><h2>Pipeline</h2><div class="tw"><table id="pTbl"></table></div></div>
      <div class="card" id="pCard"><div class="empty">Run an audit or pick a prospect.</div></div></div>`;
  $('#auditForm').onsubmit = async e => {
    e.preventDefault();
    const btn = $('#auditBtn'); btn.disabled = true; btn.textContent = 'Auditing…';
    try { const r = await api('/api/prospects', { json: { url: $('#auditUrl').value } }); $('#auditUrl').value = ''; await loadPipeline(); showProspect(r.id); }
    catch (err) { toast(err.message, 6000); }
    btn.disabled = false; btn.textContent = 'Run audit';
  };
  await loadPipeline();
  const first = $('#pTbl tr[data-id]'); if (first) showProspect(+first.dataset.id);
}

async function loadPipeline() {
  const rows = await api('/api/prospects');
  const grade = s => s >= 85 ? 'A' : s >= 70 ? 'B' : s >= 55 ? 'C' : s >= 40 ? 'D' : 'E';
  $('#pTbl').innerHTML = `<thead><tr><th>Business</th><th class="r">Score</th><th>Stage</th></tr></thead><tbody>` + (rows.map(p => `<tr class="link" data-id="${p.id}">
    <td><b>${fmt.esc(p.name || p.domain)}</b>${p.is_example ? ' <span class="badge">example</span>' : ''}<div class="small muted">${fmt.esc(p.domain)} · ${fmt.esc(p.created_at.slice(0, 10))}</div></td>
    <td class="r"><span class="badge ${gradeClass(grade(p.score))}">${grade(p.score)} · ${p.score}</span></td>
    <td class="small">${(STATUSES.find(s => s[0] === p.status) || STATUSES[0])[1]}</td></tr>`).join('') || '<tr><td colspan=3 class="empty">No audits yet</td></tr>') + '</tbody>';
  $$('#pTbl tr[data-id]').forEach(tr => tr.onclick = () => showProspect(+tr.dataset.id));
}

async function showProspect(id) {
  $$('#pTbl tr').forEach(tr => tr.classList.toggle('sel', +tr.dataset.id === id));
  const r = await api('/api/prospects/' + id);
  const byArea = AREA_ORDER.map(a => [a, r.checks.filter(c => c.area === a)]).filter(([, cs]) => cs.length);
  const tracked = Object.entries(r.trackers);
  $('#pCard').innerHTML = `
    <div class="row" style="justify-content:space-between;align-items:flex-start">
      <div><h2 style="margin:0">${fmt.esc(r.name || r.domain)}</h2><a class="small" href="${fmt.esc(r.url)}" target="_blank" rel="noopener">${fmt.esc(r.domain)} ↗</a>
        ${r.is_example ? '<div class="small muted">Example audit of a fictional business</div>' : ''}</div>
      <div class="score-ring ${gradeClass(r.grade)}"><b>${r.score}</b><span>${r.grade}</span></div></div>
    <div class="row" style="margin:12px 0"><label class="f">Stage<select id="pStatus">${STATUSES.map(([k, l]) => `<option value="${k}" ${k === r.status ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="f" style="flex:1">Notes<input id="pNotes" value="${fmt.esc(r.notes || '')}" placeholder="Who you spoke to, next step…"></label></div>

    <h3>Biggest opportunities</h3>
    ${r.top_issues.length ? r.top_issues.map(i => `<div class="issue"><div class="t">${fmt.esc(i.title)}</div><div class="small">${fmt.esc(i.impact)}</div><div class="small muted">Fix: ${fmt.esc(i.fix)}</div></div>`).join('') : '<div class="callout small">No major gaps — pitch on scaling ads and creative testing instead.</div>'}

    <h3 style="margin-top:16px">Their live ads (public ad libraries)</h3>
    <div class="row">${[['meta', 'Meta Ad Library'], ['google', 'Google Ads Transparency'], ['linkedin', 'LinkedIn Ad Library'], ['tiktok', 'TikTok Ad Library']]
      .map(([k, l]) => `<a class="btn sm" href="${fmt.esc(r.ad_library[k])}" target="_blank" rel="noopener">${l} ↗</a>`).join('')}</div>
    <p class="small muted">If they run ads but have no conversion tracking, lead with that — they're spending without being able to measure results.</p>

    <h3 style="margin-top:16px">Tracking found on their site</h3>
    <div class="row">${tracked.map(([k, v]) => `<span class="badge ${v ? 'good' : 'bad'}">${v ? '✓' : '✕'} ${fmt.esc(k)}</span>`).join('')}
      <span class="badge ${r.consent_banner ? 'good' : 'warn'}">${r.consent_banner ? '✓' : '✕'} Cookie consent</span></div>

    <h3 style="margin-top:16px">All checks</h3>
    <div class="grid g2">${byArea.map(([a, cs]) => `<div><div class="small" style="font-weight:600;margin-bottom:4px">${a}</div>${cs.map(c =>
      `<div class="chk ${c.ok ? 'ok' : 'no'}"><span>${c.ok ? '✓' : '✕'}</span>${fmt.esc(c.title)}</div>`).join('')}</div>`).join('')}</div>
    <div class="small muted" style="margin-top:8px">Load time ${r.load_seconds}s · page size ${fmt.num(r.page_kb)} KB${r.pagespeed ? ` · PageSpeed mobile ${r.pagespeed.score}/100 (LCP ${fmt.esc(r.pagespeed.lcp || '—')})` : ''}${r.title ? ` · title “${fmt.esc(r.title)}”` : ''}</div>

    <h3 style="margin-top:16px">Pitch email</h3>
    <label class="f">Subject<input id="pSubj" value="${fmt.esc(r.pitch.subject)}"></label>
    <textarea id="pBody" rows="14" style="width:100%;margin-top:8px">${fmt.esc(r.pitch.body)}</textarea>
    <div class="row" style="margin-top:8px"><button class="btn primary" id="pCopy">Copy email</button><button class="btn ghost" id="pDel">Delete audit</button></div>
    <p class="small muted">Australian Spam Act: B2B cold email is OK to a conspicuously published business address when it relates to their business, identifies you, and has a working unsubscribe.</p>`;
  const save = async () => { try { await api('/api/prospects/' + id, { method: 'PATCH', json: { status: $('#pStatus').value, notes: $('#pNotes').value } }); toast('Saved'); loadPipeline(); } catch (e) { toast(e.message); } };
  $('#pStatus').onchange = save; $('#pNotes').onchange = save;
  $('#pCopy').onclick = async () => {
    const text = `Subject: ${$('#pSubj').value}\n\n${$('#pBody').value}`;
    try { await navigator.clipboard.writeText(text); toast('Email copied'); } catch { $('#pBody').select(); toast('Select-all done — press Ctrl+C to copy'); }
  };
  let armed = false;
  $('#pDel').onclick = async () => {
    if (!armed) { armed = true; $('#pDel').textContent = 'Click again to delete'; return; }
    try { await api('/api/prospects/' + id, { method: 'DELETE' }); $('#pCard').innerHTML = '<div class="empty">Deleted.</div>'; loadPipeline(); } catch (e) { toast(e.message); }
  };
}

if (!window.__DEMO_SHELL__) prospectsInit();
