/* Client workspace: one renderer per tab, all driven by the JSON API. */
currency = CLIENT.currency || 'AUD';
let days = 30;
const view = $('#view');
const TABS = ['monthly', 'trial', 'local', 'performance', 'engagement', 'audience', 'organic', 'seo', 'email', 'attribution', 'people', 'companies', 'audiences', 'budget', 'alerts', 'upload', 'connections', 'settings'];
let base = `/api/clients/${CLIENT.id}`;
function setClient(c) { Object.keys(CLIENT).forEach(k => delete CLIENT[k]); Object.assign(CLIENT, c); base = `/api/clients/${c.id}`; currency = c.currency || 'AUD'; }

function gotoTab(t) { const h = location.hash.slice(1); location.hash = /^c\d+-/.test(h) ? h.replace(/-[a-z]+$/, '-' + t) : t; return false; }
function tab() { const h = location.hash.slice(1).split(/[/-]/).pop(); return TABS.includes(h) ? h : 'monthly'; }
async function route() {
  const t = tab();
  $$('#tabs a').forEach(a => { const h = a.getAttribute('href'); a.classList.toggle('on', h === '#' + t || h.endsWith('/' + t) || h.endsWith('-' + t)); });
  view.innerHTML = '<div class="empty">Loading…</div>';
  try { await R[t](); } catch (e) { view.innerHTML = `<div class="callout warn">${fmt.esc(e.message)}</div>`; }
}
if (!window.__DEMO_SHELL__) window.addEventListener('hashchange', route);
$$('#range button').forEach(b => b.onclick = () => { $$('#range button').forEach(x => x.classList.remove('on')); b.classList.add('on'); days = +b.dataset.d; route(); });

function kpi(label, value, change, goodUp = true, hint = '') {
  return `<div class="kpi"><div class="l">${label}</div><div class="v">${value}</div><div class="d">${change === undefined ? `<span class="muted">${hint}</span>` : delta(change, goodUp) + ' <span class="muted">vs prev.</span>'}</div></div>`;
}
function setPeriod(p) { $('#periodLabel').textContent = p ? `${fmt.date(p[0])} – ${fmt.date(p[1])} · compared with the previous ${days} days` : ''; }
function pivotDaily(rows, key, val) {
  const dates = [...new Set(rows.map(r => r.date))].sort();
  const keys = [...new Set(rows.map(r => r[key]))];
  const m = {}; rows.forEach(r => { m[r[key] + '|' + r.date] = r[val]; });
  return { dates, series: keys.map(k => ({ key: k, values: dates.map(d => m[k + '|' + d] || 0) })) };
}
const PLAT_LABEL = { meta_ads: 'Meta Ads', google_ads: 'Google Ads', tiktok_ads: 'TikTok Ads', linkedin_ads: 'LinkedIn Ads', x_ads: 'X Ads', pinterest_ads: 'Pinterest Ads', snapchat_ads: 'Snapchat Ads', reddit_ads: 'Reddit Ads', amazon_ads: 'Amazon Ads' };

const R = {};

/* ---------------- paid performance ---------------- */
R.performance = async () => {
  const d = await api(`${base}/performance?days=${days}`);
  setPeriod(d.period);
  const t = d.totals, c = d.changes;
  const tgt = CLIENT.target_roas ? `Target ${fmt.x(CLIENT.target_roas)}` : CLIENT.target_cpa ? `Target CPA ${fmt.money(CLIENT.target_cpa)}` : '';
  view.innerHTML = `
    <div class="kpis">${kpi('Spend', fmt.money(t.spend), c.spend)}${kpi('Revenue', fmt.money(t.revenue), c.revenue)}${kpi('ROAS', fmt.x(t.roas), c.roas)}
      ${kpi('Conversions', fmt.num(t.conversions), c.conversions)}${kpi('CPA', fmt.money2(t.cpa), c.cpa, false)}${kpi('CTR', fmt.pct(t.ctr, 2), c.ctr)}</div>
    ${tgt ? `<div class="callout small" style="margin-bottom:14px">${tgt} · Current ${CLIENT.target_roas ? fmt.x(t.roas) : fmt.money2(t.cpa)}</div>` : ''}
    <div class="grid g2">
      <div class="card"><h2>Daily spend by platform</h2><div id="lg1"></div><div class="chart-box"><canvas id="c1"></canvas></div></div>
      <div class="card"><h2>Daily revenue by platform</h2><div id="lg2"></div><div class="chart-box"><canvas id="c2"></canvas></div></div>
    </div>
    <div class="card" style="margin-top:14px"><h2>By platform</h2><div class="tw"><table>
      <thead><tr><th>Platform</th><th class="r">Spend</th><th class="r">Share</th><th class="r">Impr.</th><th class="r">Clicks</th><th class="r">CTR</th><th class="r">CPC</th><th class="r">Conv.</th><th class="r">CPA</th><th class="r">Revenue</th><th class="r">ROAS</th></tr></thead>
      <tbody>${d.by_platform.map(p => `<tr><td><div class="row" style="gap:8px"><span class="dot" style="background:${colorFor(p.platform)}"></span>${fmt.esc(p.label)}</div></td>
        <td class="r">${fmt.money(p.spend)}<div class="small">${delta(p.spend_change)}</div></td>
        <td class="r"><div class="bar-track" style="width:70px;display:inline-block"><div class="bar-fill" style="width:${(p.spend / t.spend * 100).toFixed(0)}%;background:${colorFor(p.platform)}"></div></div> ${fmt.pct(p.spend / t.spend, 0)}</td>
        <td class="r">${fmt.compact(p.impressions)}</td><td class="r">${fmt.num(p.clicks)}</td><td class="r">${fmt.pct(p.ctr, 2)}</td><td class="r">${fmt.money2(p.cpc)}</td>
        <td class="r">${fmt.num(p.conversions, 1)}</td><td class="r">${fmt.money2(p.cpa)}<div class="small">${delta(p.cpa_change, false)}</div></td>
        <td class="r">${fmt.money(p.revenue)}</td><td class="r"><b>${fmt.x(p.roas)}</b><div class="small">${delta(p.roas_change)}</div></td></tr>`).join('')}</tbody></table></div></div>
    <div class="card" style="margin-top:14px"><div class="row" style="justify-content:space-between"><h2>Campaigns</h2><input id="campFilter" placeholder="Filter campaigns…" style="width:220px"></div>
      <div class="tw"><table id="campTbl"></table></div></div>`;
  const stacks = (val, id, lg, f) => {
    const pv = pivotDaily(d.daily, 'platform', val);
    $('#' + lg).innerHTML = legendHTML(pv.series.map(s => ({ label: PLAT_LABEL[s.key] || s.key, color: colorFor(s.key) })));
    drawChart(id, { type: 'bar', data: { labels: pv.dates.map(fmt.date), datasets: pv.series.map(s => ({ label: PLAT_LABEL[s.key] || s.key, data: s.values,
      backgroundColor: colorFor(s.key), borderColor: cssVar('--surface'), borderWidth: { top: 2 }, borderSkipped: false, stack: 's', borderRadius: 2 })) },
      options: { scales: { x: { stacked: true, grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { stacked: true, ...axis(f) } },
        plugins: { tooltip: { ...tooltipStyle(), callbacks: { label: x => ` ${x.dataset.label}: ${fmt.money(x.raw)}` } } } } });
  };
  stacks('spend', 'c1', 'lg1', fmt.compact); stacks('revenue', 'c2', 'lg2', fmt.compact);
  const camp = q => {
    const rows = d.campaigns.filter(r => !q || (r.campaign_name + r.label).toLowerCase().includes(q.toLowerCase()));
    $('#campTbl').innerHTML = `<thead><tr><th>Campaign</th><th>Platform</th><th class="r">Spend</th><th class="r">Clicks</th><th class="r">Conv.</th><th class="r">CPA</th><th class="r">Revenue</th><th class="r">ROAS</th></tr></thead><tbody>` +
      rows.map(r => `<tr><td>${fmt.esc(r.campaign_name)}</td><td><span class="dot" style="display:inline-block;background:${colorFor(r.platform)}"></span> <span class="small">${fmt.esc(PLAT_LABEL[r.platform] || r.label)}</span></td>
        <td class="r">${fmt.money(r.spend)}</td><td class="r">${fmt.num(r.clicks)}</td><td class="r">${fmt.num(r.conversions, 1)}</td><td class="r">${fmt.money2(r.cpa)}</td><td class="r">${fmt.money(r.revenue)}</td>
        <td class="r">${r.roas != null && CLIENT.target_roas && r.roas < CLIENT.target_roas ? `<span class="badge warn">${fmt.x(r.roas)}</span>` : fmt.x(r.roas)}</td></tr>`).join('') + '</tbody>';
  };
  camp(''); $('#campFilter').oninput = e => camp(e.target.value);
};

/* ---------------- ad engagement (attention) ---------------- */
R.engagement = async () => {
  const d = await api(`${base}/engagement?days=${days}`);
  setPeriod(d.period);
  const tot = d.platforms.reduce((a, p) => { ['impressions', 'video_views', 'watch_sec', 'completions', 'engagements', 'shares', 'saves', 'comments'].forEach(k => a[k] = (a[k] || 0) + (p[k] || 0)); return a; }, {});
  const secs = v => v == null ? '—' : v.toFixed(1) + 's';
  view.innerHTML = `
    <div class="callout small" style="margin-bottom:14px">${fmt.esc(d.note)} To see what <i>individuals</i> did after clicking, use the <a href="#people" onclick="return gotoTab('people')">People</a> tab (opted-in visitors) and <a href="#companies" onclick="return gotoTab('companies')">Companies</a> (B2B visitors).</div>
    <div class="kpis">${kpi('Impressions', fmt.compact(tot.impressions), undefined, true, 'times ads were shown')}
      ${kpi('Video views', fmt.compact(tot.video_views), undefined, true, 'per each platform\'s definition')}
      ${kpi('Avg watch time', secs(tot.video_views ? tot.watch_sec / tot.video_views : null), undefined, true, 'seconds per video play')}
      ${kpi('Watched to the end', fmt.pct(tot.video_views ? tot.completions / tot.video_views : null), undefined, true, 'completions ÷ plays')}
      ${kpi('Engagements', fmt.compact(tot.engagements), undefined, true, `${fmt.compact(tot.shares)} shares · ${fmt.compact(tot.saves)} saves · ${fmt.compact(tot.comments)} comments`)}</div>
    <div class="grid g2">
      <div class="card"><h2>Average watch time by platform</h2><div class="chart-box" style="height:${Math.max(160, d.platforms.filter(p => p.avg_watch_sec).length * 44)}px"><canvas id="e1"></canvas></div></div>
      <div class="card"><h2>Thumb-stop rate by platform</h2><p class="small muted" style="margin-top:-6px">Share of impressions that turned into a video view — how well the first second stops the scroll.</p>
        <div class="chart-box" style="height:${Math.max(140, d.platforms.filter(p => p.thumb_stop_rate).length * 44)}px"><canvas id="e2"></canvas></div></div>
    </div>
    <div class="card" style="margin-top:14px"><h2>By platform</h2><div class="tw"><table><thead><tr><th>Platform</th><th class="r">Impressions</th><th class="r">Daily reach</th><th class="r">Frequency</th><th class="r">Video views</th><th class="r">Avg watch</th><th class="r">Completion</th><th class="r">Engagements</th><th class="r">Eng. rate</th></tr></thead><tbody>
      ${d.platforms.map(p => `<tr><td><div class="row" style="gap:8px"><span class="dot" style="background:${colorFor(p.platform)}"></span>${fmt.esc(p.label)}</div></td>
        <td class="r">${fmt.compact(p.impressions)}</td><td class="r">${p.reach ? fmt.compact(p.reach) : '—'}</td><td class="r">${p.avg_daily_frequency ? fmt.num(p.avg_daily_frequency, 2) : '—'}</td>
        <td class="r">${p.video_views ? fmt.compact(p.video_views) : '—'}</td><td class="r">${secs(p.avg_watch_sec)}</td><td class="r">${fmt.pct(p.completion_rate)}</td>
        <td class="r">${p.engagements ? fmt.compact(p.engagements) : '—'}</td><td class="r">${fmt.pct(p.engagement_rate, 2)}</td></tr>`).join('') || '<tr><td colspan=9 class="empty">No engagement data yet</td></tr>'}
    </tbody></table></div><p class="small muted">Search and shopping ads have no watch or reach figures — people see a text or product listing, so clicks and CTR (on Paid performance) are the attention measure there.</p></div>
    <div class="card" style="margin-top:14px"><h2>Video campaigns, longest watched first</h2><div class="tw"><table><thead><tr><th>Campaign</th><th>Platform</th><th class="r">Views</th><th class="r">Thumb-stop</th><th class="r">Avg watch</th><th class="r">Completion</th><th class="r">Cost / view</th><th class="r">Shares</th><th class="r">Saves</th></tr></thead><tbody>
      ${d.video_campaigns.map(c => `<tr><td>${fmt.esc(c.campaign_name)}</td><td class="small"><span class="dot" style="display:inline-block;background:${colorFor(c.platform)}"></span> ${fmt.esc(PLAT_LABEL[c.platform] || c.label)}</td>
        <td class="r">${fmt.compact(c.video_views)}</td><td class="r">${fmt.pct(c.thumb_stop_rate)}</td><td class="r"><b>${secs(c.avg_watch_sec)}</b></td><td class="r">${fmt.pct(c.completion_rate)}</td>
        <td class="r">${fmt.money(c.cost_per_view, 3)}</td><td class="r">${fmt.num(c.shares)}</td><td class="r">${fmt.num(c.saves)}</td></tr>`).join('') || '<tr><td colspan=9 class="empty">No video campaigns</td></tr>'}
    </tbody></table></div></div>`;
  const hbar = (id, rows, val, f) => drawChart(id, { type: 'bar', data: { labels: rows.map(p => PLAT_LABEL[p.platform] || p.label), datasets: [{ data: rows.map(val),
    backgroundColor: rows.map(p => colorFor(p.platform)), borderRadius: 4, barThickness: 18 }] },
    options: { indexAxis: 'y', interaction: { mode: 'nearest', intersect: true }, scales: { x: axis(f), y: { grid: { display: false }, ticks: { color: cssVar('--text-2') } } },
      plugins: { tooltip: { ...tooltipStyle(), callbacks: { label: x => ' ' + f(x.raw) } } } } });
  hbar('e1', d.platforms.filter(p => p.avg_watch_sec), p => p.avg_watch_sec, v => v.toFixed(1) + 's');
  hbar('e2', d.platforms.filter(p => p.thumb_stop_rate), p => p.thumb_stop_rate, v => (v * 100).toFixed(0) + '%');
};

/* ---------------- organic web + social ---------------- */
R.organic = async () => {
  const d = await api(`${base}/organic?days=${days}`);
  setPeriod(d.period);
  const tot = d.channels.reduce((a, c) => a + (c.sessions || 0), 0);
  view.innerHTML = `
    <div class="grid g2">
      <div class="card"><h2>Website sessions (GA4)</h2><div class="chart-box"><canvas id="s1"></canvas></div></div>
      <div class="card"><h2>Sessions by channel</h2><div class="tw"><table><thead><tr><th>Channel</th><th class="r">Sessions</th><th class="r">Change</th><th class="r">Key events</th><th class="r">Revenue</th></tr></thead><tbody>
        ${d.channels.map(c => `<tr><td><div class="row" style="gap:8px"><span class="dot" style="background:${colorFor(c.channel)}"></span>${fmt.esc(c.channel)}</div>
          <div class="bar-track" style="margin-top:4px"><div class="bar-fill" style="width:${(c.sessions / tot * 100).toFixed(1)}%;background:${colorFor(c.channel)}"></div></div></td>
          <td class="r">${fmt.num(c.sessions)}</td><td class="r">${delta(c.sessions_change)}</td><td class="r">${fmt.num(c.key_events)}</td><td class="r">${fmt.money(c.revenue)}</td></tr>`).join('') || '<tr><td colspan=5 class="empty">Connect GA4 to see website data</td></tr>'}
      </tbody></table></div></div>
    </div>
    <div class="card" style="margin-top:14px"><h2>Organic social &amp; local</h2><div class="tw"><table><thead><tr><th>Profile</th><th class="r">Followers</th><th class="r">Growth</th><th class="r">Reach</th><th class="r">Engagements</th><th class="r">Eng. rate</th><th class="r">Posts</th></tr></thead><tbody>
      ${d.social.map(s => s.platform === 'google_business'
        ? `<tr><td>${fmt.esc(s.label)}</td><td colspan=6 class="small muted">Profile views ${fmt.num(s.metrics.profile_views)} · Calls ${fmt.num(s.metrics.calls)} · Directions ${fmt.num(s.metrics.direction_requests)} · Website clicks ${fmt.num(s.metrics.website_clicks)}</td></tr>`
        : `<tr><td>${fmt.esc(s.label)}</td><td class="r">${fmt.num(s.followers)}</td><td class="r ${s.follower_growth >= 0 ? 'up' : 'down'}">${s.follower_growth >= 0 ? '+' : ''}${fmt.num(s.follower_growth)}</td>
          <td class="r">${fmt.compact(s.metrics.reach)}</td><td class="r">${fmt.compact(s.metrics.engagements)}</td><td class="r">${fmt.pct(s.engagement_rate, 2)}</td><td class="r">${fmt.num(s.metrics.posts)}</td></tr>`).join('') || '<tr><td colspan=7 class="empty">No organic social profiles connected</td></tr>'}
    </tbody></table></div></div>`;
  drawChart('s1', { type: 'line', data: { labels: d.daily_sessions.map(r => fmt.date(r.date)), datasets: [{ label: 'Sessions', data: d.daily_sessions.map(r => r.sessions),
    borderColor: cssVar('--s1'), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: .3, fill: false }] },
    options: { scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: axis(fmt.compact) }, plugins: { tooltip: { ...tooltipStyle(), callbacks: { label: x => ` Sessions: ${fmt.num(x.raw)}` } } } } });
};

/* ---------------- SEO ---------------- */
R.seo = async () => {
  const d = await api(`${base}/seo?days=${Math.min(days, 90)}`);
  setPeriod(d.period);
  const t = d.totals;
  const intentBadge = i => `<span class="badge ${i === 'transactional' ? 'good' : i === 'commercial' ? 'accent' : ''}">${i}</span>`;
  view.innerHTML = `
    <div class="kpis">${kpi('Organic clicks (GSC)', fmt.num(t.clicks), t.clicks_change)}${kpi('Impressions', fmt.compact(t.impressions), undefined, true, 'Google Search')}
      ${kpi('CTR', fmt.pct(t.ctr, 2), undefined, true, 'clicks ÷ impressions')}${kpi('Avg position', fmt.num(t.position, 1), undefined, true, 'impression-weighted')}</div>
    <div class="grid g2">
      <div class="card"><h2>Clicks from Google Search</h2><div class="chart-box"><canvas id="g1"></canvas></div></div>
      <div class="card"><h2>Tracked keyword rankings</h2>${d.rank_tracking.length ? `<div class="tw"><table><thead><tr><th>Keyword</th><th class="r">Position</th></tr></thead><tbody>
        ${d.rank_tracking.map(r => `<tr><td>${fmt.esc(r.query)}</td><td class="r">${r.position > 100 ? '<span class="muted">not in top 100</span>' : '<b>' + fmt.num(r.position) + '</b>'}</td></tr>`).join('')}</tbody></table></div>`
        : '<div class="empty">Connect rank tracking (DataForSEO) to monitor a keyword list daily.</div>'}</div>
    </div>
    <div class="card" style="margin-top:14px"><h2>Search queries</h2><div class="tw"><table><thead><tr><th>Query</th><th>Intent</th><th class="r">Clicks</th><th class="r">Change</th><th class="r">Impr.</th><th class="r">CTR</th><th class="r">Position</th><th class="r">7-day move</th></tr></thead><tbody>
      ${d.queries.map(q => `<tr><td>${fmt.esc(q.query)}</td><td>${intentBadge(q.intent)}</td><td class="r">${fmt.num(q.clicks)}</td><td class="r">${delta(q.clicks_change)}</td><td class="r">${fmt.num(q.impressions)}</td>
        <td class="r">${fmt.pct(q.ctr, 1)}</td><td class="r">${fmt.num(q.position, 1)}</td>
        <td class="r">${q.position_7d_delta == null ? '—' : q.position_7d_delta >= 3 ? `<span class="badge bad">▼ ${q.position_7d_delta}</span>` : q.position_7d_delta <= -1 ? `<span class="up">▲ ${-q.position_7d_delta}</span>` : `<span class="flat">${q.position_7d_delta > 0 ? '+' : ''}${q.position_7d_delta}</span>`}</td></tr>`).join('')}
    </tbody></table></div></div>`;
  drawChart('g1', { type: 'line', data: { labels: d.daily.map(r => fmt.date(r.date)), datasets: [{ label: 'Clicks', data: d.daily.map(r => r.clicks), borderColor: cssVar('--s6'), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: .3 }] },
    options: { scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: axis(fmt.compact) } } });
};

/* ---------------- email ---------------- */
R.email = async () => {
  const d = await api(`${base}/email?days=${days}`);
  setPeriod(d.period);
  const t = d.totals;
  view.innerHTML = `
    <div class="kpis">${kpi('Emails sent', fmt.compact(t.sends), undefined, true, 'all campaigns')}${kpi('Open rate', fmt.pct(t.open_rate), undefined, true, 'Apple MPP inflates opens')}
      ${kpi('Click rate', fmt.pct(t.click_rate, 2), undefined, true, 'unique clicks ÷ sends')}${kpi('Conversions', fmt.num(t.conversions))}${kpi('Revenue', fmt.money(t.revenue))}${kpi('Revenue / send', fmt.money(t.rev_per_send, 3))}</div>
    <div class="card"><h2>Campaigns</h2><div class="tw"><table><thead><tr><th>Campaign</th><th>Platform</th><th>Sent</th><th class="r">Sends</th><th class="r">Open rate</th><th class="r">Click rate</th><th class="r">Conv.</th><th class="r">Revenue</th></tr></thead><tbody>
      ${d.campaigns.map(c => `<tr><td>${fmt.esc(c.campaign_name)}</td><td class="small">${c.platform}</td><td class="small">${fmt.date(c.date)}</td><td class="r">${fmt.num(c.sends)}</td>
        <td class="r">${fmt.pct(c.opens / c.sends)}</td><td class="r">${fmt.pct(c.clicks / c.sends, 2)}</td><td class="r">${fmt.num(c.conversions, 1)}</td><td class="r">${fmt.money(c.revenue)}</td></tr>`).join('') || '<tr><td colspan=8 class="empty">Connect Klaviyo, Mailchimp or HubSpot</td></tr>'}
    </tbody></table></div></div>`;
};

/* ---------------- attribution ---------------- */
R.attribution = async () => {
  const d = await api(`${base}/attribution?days=${days}`);
  setPeriod(null);
  let model = 'position_based';
  const names = { last_click: 'Last click', first_click: 'First click', linear: 'Linear', position_based: 'Position-based (40/20/40)', time_decay: 'Time decay (7d half-life)' };
  view.innerHTML = `
    <div class="kpis">${kpi('Conversions (first-party)', fmt.num(d.conversions), undefined, true, `tracked on-site, last ${d.days} days`)}
      ${kpi('Platform-reported conversions', fmt.num(d.platform_reported_conversions), undefined, true, 'sum across ad platforms')}
      ${kpi('Over-claim ratio', d.conversions ? fmt.x(d.platform_reported_conversions / d.conversions) : '—', undefined, true, 'platforms double-count shared sales')}
      ${kpi('Avg touchpoints', fmt.num(d.avg_touches, 1), undefined, true, 'before converting')}${kpi('Avg days to convert', fmt.num(d.avg_days_to_convert, 1), undefined, true, 'first touch → conversion')}</div>
    <div class="card"><div class="row" style="justify-content:space-between"><h2>Credit by channel</h2><select id="model">${d.models.map(m => `<option value="${m}" ${m === model ? 'selected' : ''}>${names[m]}</option>`).join('')}</select></div>
      <div class="chart-box" style="height:${Math.max(180, d.table.length * 34)}px"><canvas id="a1"></canvas></div>
      <div class="tw" style="margin-top:12px"><table id="attrTbl"></table></div></div>
    <div class="card" style="margin-top:14px"><h2>Most common converting paths</h2><div class="tw"><table><thead><tr><th>Path</th><th class="r">Conversions</th></tr></thead><tbody>
      ${d.top_paths.map(p => `<tr><td>${p.path.split(' → ').map(s => `<span class="badge"><i class="dot" style="background:${colorFor(s)}"></i>${fmt.esc(s)}</span>`).join(' <span class="muted">→</span> ')}</td><td class="r">${p.count}</td></tr>`).join('')}
    </tbody></table></div>
    <p class="small muted">Built from your own tracking snippet + UTMs, so each sale is counted once. Journeys only include people who consented to tracking; treat this as the neutral referee between platforms' self-reported numbers.</p></div>`;
  const draw = () => {
    const rows = d.table.slice().sort((a, b) => b[model].conversions - a[model].conversions);
    drawChart('a1', { type: 'bar', data: { labels: rows.map(r => r.channel), datasets: [{ label: 'Conversions', data: rows.map(r => r[model].conversions),
      backgroundColor: rows.map(r => colorFor(r.channel)), borderRadius: 4, barThickness: 18 }] },
      options: { indexAxis: 'y', interaction: { mode: 'nearest', intersect: true }, scales: { x: axis(), y: { grid: { display: false }, ticks: { color: cssVar('--text-2') } } },
        plugins: { tooltip: { ...tooltipStyle(), callbacks: { label: x => ` ${fmt.num(x.raw, 1)} conversions · ${fmt.money(rows[x.dataIndex][model].revenue)}` } } } } });
    $('#attrTbl').innerHTML = `<thead><tr><th>Channel</th>${d.models.map(m => `<th class="r">${names[m].split(' (')[0]}</th>`).join('')}</tr></thead><tbody>` +
      rows.map(r => `<tr><td><div class="row" style="gap:8px"><span class="dot" style="background:${colorFor(r.channel)}"></span>${fmt.esc(r.channel)}</div></td>${d.models.map(m => `<td class="r" ${m === model ? 'style="font-weight:600"' : ''}>${fmt.num(r[m].conversions, 1)}</td>`).join('')}</tr>`).join('') + '</tbody>';
  };
  draw(); $('#model').onchange = e => { model = e.target.value; draw(); };
};

/* ---------------- people (opted-in, identified visitors) ---------------- */
const dur = s => { s = Math.round(s || 0); return s < 60 ? s + 's' : s < 3600 ? Math.floor(s / 60) + 'm ' + String(s % 60).padStart(2, '0') + 's' : (s / 3600).toFixed(1) + 'h'; };
const when = ts => { const d = new Date(ts.replace(' ', 'T') + 'Z'); return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }); };
const EVT = { page_view: 'Viewed', product_view: 'Viewed product', pricing_view: 'Viewed pricing', add_to_cart: 'Added to cart', begin_checkout: 'Started checkout',
  form_start: 'Started a form', lead: 'Submitted enquiry', purchase: 'Purchased', email_click: 'Clicked an email', email_open: 'Opened an email' };
const tierBadge = (t, s) => `<span class="badge ${t === 'hot' ? 'bad' : t === 'warm' ? 'warn' : t === 'cool' ? 'accent' : ''}">${t} · ${s}</span>`;
let peopleQ = '';
R.people = async () => {
  const d = await api(`${base}/people?q=${encodeURIComponent(peopleQ)}`);
  setPeriod(null);
  view.innerHTML = `
    <div class="callout small" style="margin-bottom:14px">${fmt.esc(d.note)} Anyone who hasn't opted in stays anonymous and is never shown here.</div>
    <div class="grid" style="grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);align-items:start" id="pplGrid">
      <div class="card"><div class="row" style="justify-content:space-between"><h2>People · last ${d.days} days</h2>
        <input id="pq" placeholder="Search name, email, postcode…" value="${fmt.esc(peopleQ)}" style="width:230px"></div>
        <div class="tw"><table><thead><tr><th>Person</th><th>Came from</th><th class="r">Pages</th><th class="r">Time on site</th><th>Intent</th><th class="r">Last seen</th></tr></thead><tbody>
        ${d.people.map(p => `<tr class="link" data-id="${p.id}"><td><b>${fmt.esc(p.name)}</b>${p.is_customer ? ' <span class="badge good">customer</span>' : ''}<div class="small muted">${fmt.esc(p.email)}${p.postcode ? ' · ' + fmt.esc(p.postcode) : ''}</div></td>
          <td class="small">${p.first_touch ? `<span class="dot" style="display:inline-block;background:${colorFor(p.first_touch.channel)}"></span> ${fmt.esc(p.first_touch.channel)}<div class="muted">${fmt.esc(p.first_touch.campaign || '')}</div>` : '<span class="muted">Direct</span>'}</td>
          <td class="r">${p.pageviews}</td><td class="r">${dur(p.time_sec)}</td><td>${tierBadge(p.tier, p.score)}</td><td class="r small muted">${when(p.last_seen)}</td></tr>`).join('') || '<tr><td colspan=6 class="empty">No opted-in visitors yet. Add the tracking snippet (Audiences tab) and an opt-in form.</td></tr>'}
        </tbody></table></div></div>
      <div class="card" id="personCard"><div class="empty">Select a person to see their full journey.</div></div>
    </div>`;
  let tmr; $('#pq').oninput = e => { clearTimeout(tmr); tmr = setTimeout(() => { peopleQ = e.target.value; R.people().then(() => { const i = $('#pq'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 300); };
  $$('#pplGrid tr[data-id]').forEach(tr => tr.onclick = () => { $$('#pplGrid tr.sel').forEach(x => x.classList.remove('sel')); tr.classList.add('sel'); showPerson(+tr.dataset.id); });
  const first = $('#pplGrid tr[data-id]'); if (first) first.click();
};
async function showPerson(id) {
  const p = await api(`${base}/people/${id}`), c = p.contact, t = p.totals;
  $('#personCard').innerHTML = `
    <div class="row" style="justify-content:space-between;align-items:flex-start"><div><h2 style="margin:0">${fmt.esc((c.first_name + ' ' + c.last_name).trim() || c.email)}</h2>
      <div class="small muted">${fmt.esc(c.email)}${c.phone ? ' · ' + fmt.esc(c.phone) : ''}${c.postcode ? ' · postcode ' + fmt.esc(c.postcode) : ''}</div>
      <div class="small muted">Opted in via ${fmt.esc(c.consent_source || '—')}${c.consent_at ? ' on ' + fmt.esc(c.consent_at.slice(0, 10)) : ''}</div></div>${tierBadge(p.tier, p.score)}</div>
    <div class="kpis" style="margin:14px 0;grid-template-columns:repeat(4,minmax(0,1fr))">
      <div class="kpi"><div class="l">Visits</div><div class="v">${t.sessions}</div></div><div class="kpi"><div class="l">Pages</div><div class="v">${t.pageviews}</div></div>
      <div class="kpi"><div class="l">Time on site</div><div class="v">${dur(t.time_sec)}</div></div><div class="kpi"><div class="l">Value</div><div class="v">${fmt.money(t.value)}</div></div></div>
    <div class="small" style="margin-bottom:12px"><b>First came from:</b> ${p.first_touch ? `${fmt.esc(p.first_touch.channel)}${p.first_touch.campaign ? ' · ' + fmt.esc(p.first_touch.campaign) : ''} (${when(p.first_touch.ts)})` : 'Direct / unknown'}
      ${p.last_touch && p.first_touch && p.last_touch.ts !== p.first_touch.ts ? `<br><b>Most recent ad/source:</b> ${fmt.esc(p.last_touch.channel)}${p.last_touch.campaign ? ' · ' + fmt.esc(p.last_touch.campaign) : ''} (${when(p.last_touch.ts)})` : ''}</div>
    <h3>Journey (newest first)</h3>
    <div class="tl">${p.timeline.map((e, i) => {
      const newSession = i === p.timeline.length - 1 || p.timeline[i + 1].session !== e.session; const s = p.sessions[e.session];
      return `<div class="tl-row ${['purchase', 'lead'].includes(e.event) ? 'conv' : ''}"><div class="tl-dot"></div><div><div><b>${EVT[e.event] || e.event}</b> <span class="muted">${fmt.esc(e.url)}</span>${e.value ? ` <span class="badge good">${fmt.money(e.value)}</span>` : ''}</div>
        <div class="small muted">${when(e.ts)}${e.duration_sec ? ' · ' + dur(e.duration_sec) + ' on page' : ''}</div></div></div>` +
        (newSession ? `<div class="tl-sess">Visit ${e.session + 1} · from ${fmt.esc(s.channel)}${s.campaign ? ' · ' + fmt.esc(s.campaign) : ''} · ${s.events} actions · ${dur(s.time_sec)}</div>` : '');
    }).join('')}</div>`;
}

/* ---------------- companies (B2B visitors) ---------------- */
R.companies = async () => {
  const d = await api(`${base}/companies?days=${Math.max(days, 30)}`);
  setPeriod(null);
  view.innerHTML = `
    <div class="callout small" style="margin-bottom:14px">Businesses whose office networks visited ${fmt.esc(CLIENT.name)}'s site, matched by IP-to-company lookup. You see the company and what it looked at — not which employee.
      ${d.provider_configured ? '' : ' <b>Set IPINFO_TOKEN in .env to switch this on for live traffic</b> (demo data shown).'}</div>
    <div class="grid" style="grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);align-items:start" id="coGrid">
      <div class="card"><h2>Companies visiting · last ${d.days} days</h2><div class="tw"><table><thead><tr><th>Company</th><th class="r">Visitors</th><th class="r">Pages</th><th class="r">Time</th><th class="r">Pricing views</th><th>Intent</th></tr></thead><tbody>
        ${d.companies.map(c => `<tr class="link" data-id="${c.id}"><td><b>${fmt.esc(c.name)}</b><div class="small muted">${fmt.esc(c.domain)}${c.industry ? ' · ' + fmt.esc(c.industry) : ''}${c.city ? ' · ' + fmt.esc(c.city) : ''}</div></td>
          <td class="r">${c.visitors}</td><td class="r">${c.pageviews}</td><td class="r">${dur(c.time_sec)}</td><td class="r">${c.pricing_views ? `<b>${c.pricing_views}</b>` : '0'}</td><td>${tierBadge(c.tier, c.score)}</td></tr>`).join('') || '<tr><td colspan=6 class="empty">No company visits identified yet</td></tr>'}
      </tbody></table></div></div>
      <div class="card" id="coCard"><div class="empty">Select a company.</div></div></div>`;
  $$('#coGrid tr[data-id]').forEach(tr => tr.onclick = () => { $$('#coGrid tr.sel').forEach(x => x.classList.remove('sel')); tr.classList.add('sel'); showCompany(+tr.dataset.id); });
  const first = $('#coGrid tr[data-id]'); if (first) first.click();
};
async function showCompany(id) {
  const d = await api(`${base}/companies/${id}`), c = d.company;
  const li = `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(c.name)}`;
  $('#coCard').innerHTML = `<h2 style="margin:0">${fmt.esc(c.name)}</h2><div class="small muted">${fmt.esc(c.domain)} · ${fmt.esc(c.industry || '')} · ${fmt.esc(c.employees || '')} staff · ${fmt.esc(c.city || '')}</div>
    <div class="row" style="margin:12px 0"><a class="btn sm" href="${li}" target="_blank" rel="noopener">Find decision-makers on LinkedIn ↗</a><span class="small muted">${d.visitors} different visitors</span></div>
    <h3>What they looked at most</h3><div class="tw"><table><tbody>${d.top_pages.map(p => `<tr><td>${fmt.esc(p.url)}</td><td class="r">${p.views} views</td><td class="r">${dur(p.time_sec)}</td></tr>`).join('')}</tbody></table></div>
    <h3 style="margin-top:14px">Recent activity</h3><div class="tl">${d.timeline.slice(0, 25).map(e => `<div class="tl-row ${['lead'].includes(e.event) ? 'conv' : ''}"><div class="tl-dot"></div><div>
      <div><b>${EVT[e.event] || e.event}</b> <span class="muted">${fmt.esc(e.url)}</span></div><div class="small muted">${fmt.esc(e.visitor)} · ${when(e.ts)}${e.duration_sec ? ' · ' + dur(e.duration_sec) : ''}${e.channel ? ' · via ' + fmt.esc(e.channel) + (e.campaign ? ' (' + fmt.esc(e.campaign) + ')' : '') : ''}</div></div></div>`).join('')}</div>
    <p class="small muted">Reach out with a relevant, role-based message (Spam Act: publicly listed business address, clear sender identity and an unsubscribe).</p>`;
}

/* ---------------- audiences ---------------- */
R.audiences = async () => {
  const [d, s] = await Promise.all([api(`${base}/audiences`), api(`${base}/targeting`)]);
  setPeriod(null);
  const dist = d.distribution, tiers = dist.tiers, maxT = Math.max(1, ...Object.values(tiers));
  const tcol = { hot: '--s8', warm: '--s2', cool: '--s4', cold: '--s-other' };
  view.innerHTML = `
    <div class="kpis">${kpi('Contacts', fmt.num(dist.total_contacts), undefined, true, 'first-party CRM / site')}${kpi('Marketing consent', fmt.num(dist.consented), undefined, true, fmt.pct(dist.consented / (dist.total_contacts || 1), 0) + ' of contacts — only these sync')}
      ${kpi('Customers', fmt.num(dist.customers), undefined, true, 'for exclusions & lookalikes')}${kpi('High intent now', fmt.num(tiers.hot), undefined, true, 'score 70+ (last 30 days)')}</div>
    <div class="grid g2">
      <div class="card"><h2>Intent distribution (consented, non-customers)</h2>
        ${Object.entries(tiers).map(([k, v]) => `<div class="tier"><span style="text-transform:capitalize">${k}</span><div class="bar-track"><div class="bar-fill" style="width:${v / maxT * 100}%;background:var(${tcol[k]})"></div></div><span class="r num">${v}</span></div>`).join('')}
        <p class="small muted">Score = recency-weighted behaviour (pricing views, add-to-cart, form starts, email clicks…) with a 7-day half-life, scaled 0–100.</p></div>
      <div class="card"><h2>Import contacts</h2><p class="small muted">CSV columns: <code>email, phone, first_name, last_name, country, postcode, consent, is_customer</code>. Rows without an explicit <code>consent</code> of yes/true/1 are stored but never uploaded to ad platforms.</p>
        <form id="imp" class="row"><input type="file" name="file" accept=".csv" required><button class="btn">Upload</button></form>
        <h3 style="margin-top:16px">Site tracking snippet</h3><pre>&lt;script src="${location.origin}/t.js" data-client="${CLIENT.slug}" async&gt;&lt;/script&gt;
&lt;!-- after opt-in: adpulse.consent(true) · adpulse.track('add_to_cart',{value:59}) · adpulse.identify({email, consent:true}) --&gt;</pre></div>
    </div>
    <div class="card" style="margin-top:14px"><div class="row" style="justify-content:space-between"><h2>Audiences</h2><button class="btn primary" onclick="$('#audDlg').showModal()">＋ New audience</button></div>
      <div class="tw"><table><thead><tr><th>Audience</th><th class="r">Size</th><th>Platforms</th><th class="r">Actions</th></tr></thead><tbody>
      ${d.audiences.map(a => `<tr><td><b>${fmt.esc(a.name)}</b><div class="small muted">${a.definition.customers_only ? 'Customers only' : `Score ${a.definition.min_score ?? 0}–${a.definition.max_score ?? 100}`} · ${a.definition.lookback_days || 30}d lookback${a.definition.required_events?.length ? ' · requires ' + a.definition.required_events.join(', ') : ''}</div></td>
        <td class="r num">${fmt.num(a.size)}</td>
        <td>${Object.entries(d.sync_targets).map(([p, lbl]) => { const sy = a.syncs.find(x => x.platform === p); const ok = d.connected.includes(p);
          return `<button class="btn sm ${sy?.status === 'ok' ? '' : 'ghost'}" ${ok ? '' : 'disabled title="Connect this platform first"'} onclick="syncAud(${a.id},'${p}',this)" title="${fmt.esc(sy?.detail || lbl)}">${sy?.status === 'ok' ? '✓' : sy?.status === 'error' ? '⚠' : '↑'} ${PLAT_LABEL[p]}</button>`; }).join(' ')}</td>
        <td class="r"><select onchange="if(this.value){location.href='${base}/audiences/${a.id}/export/'+this.value+'.csv';this.value=''}"><option value="">Export hashed CSV…</option><option value="meta_ads">Meta format</option><option value="google_ads">Google format</option><option value="tiktok_ads">TikTok / LinkedIn</option></select>
          <button class="btn sm ghost" onclick="delAud(${a.id})">✕</button></td></tr>`).join('')}
      </tbody></table></div>
      <p class="small muted">Sync sends SHA-256 hashed identifiers only. Contacts who withdraw consent or are erased are removed from platform audiences on the next sync.</p></div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h2>Paid search gaps</h2><p class="small muted">High-intent queries you already get impressions for but rank below position 5 — candidates for Search / PMax search themes.</p>
        <div class="tw"><table><thead><tr><th>Query</th><th class="r">Impr.</th><th class="r">Position</th></tr></thead><tbody>${s.keyword_gaps.map(q => `<tr><td>${fmt.esc(q.query)}</td><td class="r">${fmt.num(q.impressions)}</td><td class="r">${fmt.num(q.pos, 1)}</td></tr>`).join('') || '<tr><td colspan=3 class="empty">No gaps found</td></tr>'}</tbody></table></div></div>
      <div class="card"><h2>Platform-built website audiences</h2><p class="small muted">Anonymous visitors can't be exported as people — but each platform can build these from its own pixel/tag. Copy into Ads Manager or GA4.</p>
        ${s.website_audience_rules.map(r => `<h3>${fmt.esc(r.name)}</h3><div class="small">${fmt.esc(r.ga4_audience)}</div>${r.meta_rule ? `<details><summary class="small">Meta rule JSON</summary><pre>${fmt.esc(JSON.stringify(r.meta_rule, null, 1))}</pre></details>` : ''}<p class="small muted">${fmt.esc(r.why)}</p>`).join('')}</div>
    </div>`;
  $('#imp').onsubmit = async e => { e.preventDefault(); try { const r = await api(`${base}/contacts/import`, { method: 'POST', body: new FormData(e.target) }); toast(`Imported ${r.imported} contacts (${r.consented} with consent)`); route(); } catch (err) { toast(err.message); } };
};
async function syncAud(id, p, btn) {
  btn.disabled = true; btn.textContent = '…';
  try { const r = await api(`/api/audiences/${id}/sync/${p}`, { method: 'POST' }); toast(r.ok ? r.detail : 'Sync failed: ' + r.error, 5000); } catch (e) { toast(e.message); }
  route();
}
async function delAud(id) { if (confirm('Delete this audience? (Platform copies are not deleted.)')) { await api(`/api/audiences/${id}`, { method: 'DELETE' }); route(); } }
function audDef(f) {
  const fd = new FormData(f), d = { min_score: +fd.get('min_score'), max_score: +fd.get('max_score'), lookback_days: +fd.get('lookback_days'),
    customers_only: fd.get('customers_only') === 'on', include_customers: fd.get('include_customers') === 'on' };
  if (fd.get('required_event')) d.required_events = [fd.get('required_event')];
  return d;
}
async function previewAudience() {
  const r = await api(`${base}/audiences/preview`, { json: audDef($('#audDlg form')) });
  $('#audPreview').innerHTML = `<b>${fmt.num(r.size)}</b> consented contacts match.` + (r.sample.length ? '<br>Top: ' + r.sample.slice(0, 5).map(s => `${fmt.esc(s.name)} (${s.score})`).join(', ') : '');
}
async function saveAudience(e) {
  e.preventDefault();
  const f = e.target, d = audDef(f); d.name = new FormData(f).get('name');
  await api(`${base}/audiences`, { json: d }); $('#audDlg').close(); f.reset(); route();
  return false;
}

/* ---------------- budget ---------------- */
R.budget = async (opts = {}) => {
  const b = opts.budget ?? (CLIENT.monthly_budget || '');
  const obj = opts.objective || 'revenue', shift = opts.shift || 0.3;
  const d = await api(`${base}/budget?objective=${obj}&max_shift=${shift}` + (b ? `&budget=${b}` : ''));
  setPeriod(null);
  const unit = obj === 'revenue' ? fmt.money : v => fmt.num(v, 0);
  view.innerHTML = `
    <div class="card" style="margin-bottom:14px"><div class="row">
      <label class="f">Monthly budget<input id="bBudget" type="number" step="500" value="${b || Math.round(d.monthly_budget || 0)}" style="width:140px"></label>
      <label class="f">Optimise for<select id="bObj"><option value="revenue" ${obj === 'revenue' ? 'selected' : ''}>Revenue</option><option value="conversions" ${obj !== 'revenue' ? 'selected' : ''}>Conversions</option></select></label>
      <label class="f">Max change per channel<select id="bShift">${[0.1, 0.2, 0.3, 0.5].map(v => `<option value="${v}" ${v == shift ? 'selected' : ''}>±${v * 100}%</option>`).join('')}</select></label>
      <button class="btn primary" style="align-self:flex-end" id="bGo">Recalculate</button></div></div>
    ${d.channels.length ? `<div class="kpis">${kpi('Monthly budget', fmt.money(d.monthly_budget))}${kpi('Expected at current mix', unit(d.expected_at_current_mix), undefined, true, obj)}
      ${kpi('Expected with recommended mix', unit(d.expected_total), undefined, true, obj)}${kpi('Projected uplift', `<span class="${d.uplift_pct >= 0 ? 'up' : 'down'}">${fmt.pct(d.uplift_pct)}</span>`, undefined, true, 'same total spend')}</div>
    <div class="card"><h2>Recommended allocation</h2><div id="blg"></div><div class="chart-box"><canvas id="b1"></canvas></div>
      <div class="tw" style="margin-top:12px"><table><thead><tr><th>Channel</th><th class="r">Current / mo</th><th class="r">Recommended / mo</th><th class="r">Change</th><th class="r">Expected ${obj}</th><th class="r">Marginal return</th><th>Saturation</th><th>Confidence</th></tr></thead><tbody>
      ${d.channels.map(c => `<tr><td><div class="row" style="gap:8px"><span class="dot" style="background:${colorFor(c.platform)}"></span>${fmt.esc(c.label)}</div></td><td class="r">${fmt.money(c.current_monthly)}</td><td class="r"><b>${fmt.money(c.recommended_monthly)}</b></td>
        <td class="r">${delta(c.change_pct)}</td><td class="r">${unit(c.expected_now)} → ${unit(c.expected_new)}</td><td class="r">${obj === 'revenue' ? fmt.money2(c.marginal_return) : fmt.num(c.marginal_return, 3)} <span class="small muted">per $1</span></td>
        <td><div class="bar-track" style="width:80px"><div class="bar-fill" style="width:${c.saturation * 100}%;background:var(--s2)"></div></div></td>
        <td><span class="badge ${c.confidence === 'high' ? 'good' : c.confidence === 'medium' ? 'accent' : 'warn'}">${c.confidence}</span></td></tr>`).join('')}</tbody></table></div>
      <p class="small muted">${fmt.esc(d.note)} Uses platform-reported ${obj}; for big budgets, validate with a marketing-mix model (Meridian / Robyn) and holdout tests.</p></div>` : `<div class="empty">${d.note}</div>`}`;
  if (d.channels.length) {
    $('#blg').innerHTML = legendHTML([{ label: 'Current', color: cssVar('--s-other') }, { label: 'Recommended', color: cssVar('--s1') }]);
    drawChart('b1', { type: 'bar', data: { labels: d.channels.map(c => c.label.split(' (')[0]), datasets: [
      { label: 'Current', data: d.channels.map(c => c.current_monthly), backgroundColor: cssVar('--s-other'), borderRadius: 4, maxBarThickness: 28 },
      { label: 'Recommended', data: d.channels.map(c => c.recommended_monthly), backgroundColor: cssVar('--s1'), borderRadius: 4, maxBarThickness: 28 }] },
      options: { scales: { x: { grid: { display: false } }, y: axis(fmt.compact) }, plugins: { tooltip: { ...tooltipStyle(), callbacks: { label: x => ` ${x.dataset.label}: ${fmt.money(x.raw)}` } } } } });
  }
  $('#bGo').onclick = () => R.budget({ budget: +$('#bBudget').value, objective: $('#bObj').value, shift: +$('#bShift').value });
};

/* ---------------- alerts ---------------- */
R.alerts = async () => {
  const a = await api(`${base}/alerts?include_ack=true`);
  setPeriod(null);
  const open = a.filter(x => !x.acknowledged);
  view.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between"><h2>Alerts</h2><div class="row"><button class="btn sm" onclick="reEval()">Re-check now</button><a class="btn sm" href="/settings#rules">Edit rules</a></div></div>
    ${a.length ? a.map(x => `<div class="alert-item" style="${x.acknowledged ? 'opacity:.55' : ''}"><div class="sev ${x.severity}">${x.severity === 'critical' ? '!' : '⚑'}</div>
      <div><div class="t">${fmt.esc(x.title)} <span class="badge ${x.severity === 'critical' ? 'bad' : 'warn'}">${x.severity}</span></div><div class="small muted">${fmt.esc(x.detail)} · ${x.created_at.slice(0, 16)}</div></div>
      ${x.acknowledged ? '<span class="small muted">Resolved</span>' : `<button class="btn sm" onclick="ack(${x.id})">Mark resolved</button>`}</div>`).join('') : '<div class="empty">No alerts</div>'}</div>`;
  updateAlertCount(open.length);
};
async function ack(id) { await api(`/api/alerts/${id}/ack`, { method: 'POST' }); route(); }
async function reEval() { const r = await api(`${base}/alerts/evaluate`, { method: 'POST' }); toast(`${r.length} new alert(s)`); route(); }
function updateAlertCount(n) { const el = $('#alertCount'); el.hidden = !n; el.textContent = n; }

/* ---------------- connections ---------------- */
let PLATS = [];
R.connections = async () => {
  const [conns, plats] = await Promise.all([api(`${base}/connections`), api('/api/platforms')]);
  PLATS = plats;
  setPeriod(null);
  const cats = { paid: 'Paid advertising', analytics: 'Web analytics', seo: 'SEO', organic: 'Organic social & local', email: 'Email' };
  const params = new URLSearchParams(location.search);
  view.innerHTML = `${params.get('error') ? `<div class="callout warn" style="margin-bottom:12px">Connection cancelled: ${fmt.esc(params.get('error'))}</div>` : ''}
  <div class="card"><h2>Connected accounts</h2><div class="tw"><table><thead><tr><th>Platform</th><th>Account</th><th>Status</th><th>Last sync</th><th class="r"></th></tr></thead><tbody>
    ${conns.map(c => `<tr><td>${fmt.esc(c.label)} ${c.is_demo ? '<span class="badge">demo</span>' : '<span class="badge accent">live</span>'}</td><td class="small">${fmt.esc(c.account_id)}</td>
      <td>${c.status === 'error' ? `<span class="badge bad" title="${fmt.esc(c.last_error)}">Error</span><div class="small muted">${fmt.esc(c.last_error.slice(0, 90))}</div>` : '<span class="badge good">Active</span>'}</td>
      <td class="small muted">${c.last_synced_at ? c.last_synced_at.replace('T', ' ') + ' UTC' : 'never'}</td>
      <td class="r"><button class="btn sm" onclick="syncConn(${c.id},this)">Sync</button> <button class="btn sm ghost" onclick="delConn(${c.id})">Remove</button></td></tr>`).join('') || '<tr><td colspan=5 class="empty">Nothing connected yet</td></tr>'}
  </tbody></table></div></div>
  <div class="card" style="margin-top:14px"><h2>Add a connection</h2>
    ${Object.entries(cats).map(([k, lbl]) => `<h3 style="margin-top:14px">${lbl}</h3><div class="row">${plats.filter(p => p.category === k).map(p =>
      `<button class="btn sm" onclick="openConn('${p.platform}')">${fmt.esc(p.label)}${p.live ? '' : ' <span class="muted small">(demo)</span>'}</button>`).join('')}</div>`).join('')}
    <p class="small muted" style="margin-top:14px">OAuth platforms need your agency's approved developer app (Settings shows which are configured). Platforms marked “demo” don't have a live connector yet — they're on the roadmap and use generated data.</p></div>`;
};
function openConn(p) {
  const pl = PLATS.find(x => x.platform === p);
  $('#connTitle').textContent = 'Connect ' + pl.label;
  const keyFields = { mailchimp: [['api_key', 'API key (ends in -usXX)']], klaviyo: [['api_key', 'Private API key'], ['conversion_metric_id', 'Conversion metric id (optional)']],
    dataforseo: [['login', 'DataForSEO login'], ['password', 'DataForSEO password'], ['keywords', 'Keywords, comma-separated'], ['location_code', 'Location code (2036 = Australia)']],
    bing_webmaster: [['api_key', 'Bing Webmaster API key']] };
  const hint = { meta_ads: 'Ad account id (digits)', google_ads: 'Customer id, e.g. 123-456-7890', ga4: 'GA4 property id (digits)', gsc: 'sc-domain:example.com', tiktok_ads: 'Advertiser id (optional — picked up on authorise)', linkedin_ads: 'Ad account id (digits)', dataforseo: 'Your domain, e.g. example.com.au' }[p] || 'Account / profile id';
  let body = `<label class="f">Account<input name="account_id" placeholder="${hint}"></label>`;
  if (pl.live && pl.auth === 'api_key') body += (keyFields[p] || [['api_key', 'API key']]).map(([k, l]) => `<label class="f">${l}<input name="cred_${k}" ${k === 'api_key' || k === 'password' ? 'type="password"' : ''}></label>`).join('');
  if (pl.live && pl.auth === 'oauth') body += pl.oauth_ready ? `<div class="callout small">You'll be sent to ${pl.oauth_provider} to authorise read access. Tokens are stored encrypted.</div>`
    : `<div class="callout warn small">${pl.oauth_provider} app credentials aren't configured on this server yet, so only a demo connection is possible.</div>`;
  body += `<label class="row small"><input type="checkbox" name="demo" ${!pl.live || (pl.auth === 'oauth' && !pl.oauth_ready) ? 'checked disabled' : ''}> Use demo data</label>`;
  $('#connBody').innerHTML = body;
  $('#connDlg').dataset.platform = p;
  $('#connDlg').showModal();
}
async function submitConn(e) {
  e.preventDefault();
  const p = $('#connDlg').dataset.platform, pl = PLATS.find(x => x.platform === p), fd = new FormData(e.target);
  const demo = e.target.querySelector('[name=demo]').checked;
  const account = fd.get('account_id') || '';
  if (!demo && pl.auth === 'oauth') { location.href = `/oauth/${pl.oauth_provider}/start?client_id=${CLIENT.id}&platform=${p}&account_id=${encodeURIComponent(account)}`; return false; }
  const creds = {}; for (const [k, v] of fd.entries()) if (k.startsWith('cred_')) creds[k.slice(5)] = v;
  $('#connSubmit').disabled = true;
  try { const r = await api(`${base}/connections`, { json: { platform: p, account_id: account || undefined, demo, credentials: creds } });
    toast(r.sync.ok ? `Connected · ${r.sync.rows} rows synced` : 'Connected, but sync failed: ' + r.sync.error, 5000); $('#connDlg').close(); route();
  } catch (err) { toast(err.message); }
  $('#connSubmit').disabled = false;
  return false;
}
async function syncConn(id, btn) { btn.disabled = true; btn.textContent = '…'; const r = await api(`/api/connections/${id}/sync`, { method: 'POST' }); toast(r.ok ? `${r.rows} rows updated` : r.error, 5000); route(); }
async function delConn(id) { if (confirm('Remove this connection? Historical data stays until you delete the client.')) { await api(`/api/connections/${id}`, { method: 'DELETE' }); route(); } }

/* ---------------- client settings, branding, privacy ---------------- */
R.settings = async () => {
  const p = await api(`${base}/privacy`);
  setPeriod(null);
  const c = CLIENT;
  view.innerHTML = `<div class="grid g2">
    <form class="card" id="cset"><h2>Client details &amp; report branding</h2><div class="db" style="padding:0;display:grid;gap:12px">
      <label class="f">Name<input name="name" value="${fmt.esc(c.name)}"></label>
      <div class="row"><label class="f" style="flex:1">Brand colour<input name="brand_color" type="color" value="${c.brand_color}"></label><label class="f" style="flex:3">Logo URL<input name="logo_url" value="${fmt.esc(c.logo_url)}" placeholder="https://…/logo.png"></label></div>
      <label class="f">Report title<input name="report_title" value="${fmt.esc(c.report_title)}"></label>
      <label class="f">Report footer<input name="report_footer" value="${fmt.esc(c.report_footer)}"></label>
      <div class="row"><label class="f" style="flex:1">Monthly budget<input name="monthly_budget" type="number" value="${c.monthly_budget}"></label><label class="f" style="flex:1">Target ROAS<input name="target_roas" type="number" step="0.1" value="${c.target_roas}"></label><label class="f" style="flex:1">Target CPA<input name="target_cpa" type="number" value="${c.target_cpa}"></label></div>
      <div class="row"><label class="f" style="flex:1">Currency<select name="currency">${['AUD', 'NZD', 'USD', 'EUR', 'GBP'].map(x => `<option ${x === c.currency ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
        <label class="f" style="flex:1">Privacy region<select name="region">${['AU', 'NZ', 'EU', 'UK', 'US-CA', 'US'].map(x => `<option ${x === c.region ? 'selected' : ''}>${x}</option>`).join('')}</select></label></div>
      <label class="f">Suburb / area (for competitor & review tracking)<input name="area" value="${fmt.esc(c.area || '')}" placeholder="e.g. East Bentleigh VIC"></label>
      <div><button class="btn primary">Save</button></div></div></form>
    <div class="card"><h2>Client login</h2>
      <p class="small muted">Give the business owner their own login. They see only their business: the monthly report, Google &amp; reviews, ads, audience and website results. They can't change anything or see other clients.</p>
      <div id="logins"><div class="small muted">Loading…</div></div>
      <form class="row" style="gap:8px;margin-top:10px;flex-wrap:wrap;align-items:flex-end" onsubmit="return addLogin(event)">
        <label class="f" style="flex:1;min-width:160px">Their email<input name="email" type="email" required></label>
        <label class="f" style="flex:1;min-width:120px">Name<input name="name"></label>
        <label class="f" style="flex:1;min-width:140px">Password (8+ characters)<input name="password" type="text" minlength="8" required></label>
        <button class="btn primary">Create login</button></form></div>
    <div class="card"><h2>Privacy &amp; compliance · ${fmt.esc(p.region)}</h2>
      <div class="small"><b>${fmt.esc(p.policy.law)}</b><br>${fmt.esc(p.policy.basis)}<br><span class="muted">${fmt.esc(p.policy.notes)}</span></div>
      <p class="small muted">Behavioural events are kept ${p.retention_days} days. Erased contacts are excluded immediately, removed from platform audiences on next sync, and their details wiped after 30 days.</p>
      <h3>Data subject requests</h3><div class="row"><input id="dsEmail" type="email" placeholder="person@example.com" style="flex:1"><button class="btn" onclick="dsAccess()">Access</button><button class="btn" onclick="dsErase()">Erase</button></div>
      <pre id="dsOut" hidden></pre>
      <h3 style="margin-top:14px">Audit trail</h3><div class="tw"><table><tbody>${p.audit.map(x => `<tr><td class="small muted">${x.ts}</td><td class="small">${fmt.esc(x.action)}</td><td class="small muted">${fmt.esc(x.detail)}</td></tr>`).join('') || '<tr><td class="empty">No activity yet</td></tr>'}</tbody></table></div></div></div>`;
  $('#cset').onsubmit = async e => { e.preventDefault(); const b = Object.fromEntries(new FormData(e.target));
    ['monthly_budget', 'target_roas', 'target_cpa'].forEach(k => b[k] = +b[k] || 0);
    Object.assign(CLIENT, await api(base, { method: 'PATCH', json: b })); currency = CLIENT.currency; toast('Saved'); };
  loadLogins();
};
async function dsAccess() { const r = await api(`${base}/privacy/access?email=${encodeURIComponent($('#dsEmail').value)}`); $('#dsOut').hidden = false; $('#dsOut').textContent = JSON.stringify(r, null, 1); }
async function dsErase() { if (!confirm('Erase this person\'s data? This cannot be undone.')) return; const r = await api(`${base}/privacy/erase`, { json: { email: $('#dsEmail').value } }); toast(r.found ? 'Erased' : 'Not found'); }


/* ---------------- monthly report (plain English) ---------------- */
let repMonth = '';
R.monthly = async () => {
  const d = await api(`${base}/monthly${repMonth ? '?month=' + repMonth : ''}`);
  setPeriod(null); $('#periodLabel').textContent = `Monthly report · ${d.month_label}`;
  view.innerHTML = `
    <div class="row no-print" style="justify-content:space-between;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      <label class="f">Month<select id="repMonth">${d.months.map(m => `<option value="${m}" ${m === d.month ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
      <div class="row" style="gap:8px"><a class="btn" href="/clients/${CLIENT.id}/monthly?month=${d.month}" target="_blank" rel="noopener">🖨 Printable page</a>
        ${IS_CLIENT ? '' : '<button class="btn primary" id="repShare">Copy link for the client</button>'}</div></div>
    ${d.has_data ? `
    <div class="card"><div class="headline-box">${fmt.esc(d.headline)}</div>
      ${d.kpis.length ? `<div class="kpis" style="margin-top:12px">${d.kpis.map(k => `<div class="kpi"><div class="l">${fmt.esc(k.label)}</div><div class="v">${fmt.esc(k.value)}</div>
        <div class="d">${k.change == null ? '<span class="muted">this month</span>' : delta(k.change) + ' <span class="muted">vs last month</span>'}</div></div>`).join('')}</div>` : ''}
      <div class="grid g2" style="margin-top:6px">${d.sections.map(sec => `<div><h3>${fmt.esc(sec.title)}</h3><ul class="plain">${sec.lines.map(l => `<li>${fmt.esc(l)}</li>`).join('')}</ul></div>`).join('')}</div>
      <h3 style="margin-top:14px">What we'll do next month</h3>
      <ol class="plain next-steps">${d.next_steps.map(n => `<li>${fmt.esc(n)}</li>`).join('')}</ol></div>`
    : `<div class="card"><div class="empty">No results recorded for ${fmt.esc(d.month_label)} yet.${IS_CLIENT ? '' : `<br><br>To fill it in: add this month's figures in <a href="#local" onclick="return gotoTab('local')">Google &amp; reviews</a>, and/or upload an ad report in <a href="#upload" onclick="return gotoTab('upload')">Upload data</a>.`}</div></div>`}`;
  $('#repMonth').onchange = e => { repMonth = e.target.value; route(); };
  const sh = $('#repShare');
  if (sh) sh.onclick = async () => { const r = await api(`${base}/monthly-link?month=${d.month}`, { method: 'POST' });
    try { await navigator.clipboard.writeText(r.url); toast('Link copied (works for 120 days). Paste it into an email or text to the owner.', 6000); } catch { prompt('Report link:', r.url); } };
};


/* ---------------- 7-day trial ---------------- */
R.trial = async () => {
  const t = await api(`${base}/trial`);
  setPeriod(null); $('#periodLabel').textContent = '7-day trial';
  const ro = IS_CLIENT ? 'disabled' : '';
  if (!t.started) {
    view.innerHTML = `<div class="card"><h2>7-day trial</h2>
      ${IS_CLIENT ? '<div class="empty">No trial running.</div>' : `
      <p>A ready-made plan for a one-week trial: what to do each day, a before/after snapshot, and a one-page results report to show the owner on day 7.</p>
      <p class="small muted">It focuses on things that visibly change in a week: a complete Google profile, new photos and posts, a review system bringing in new reviews, and website quick wins. Sales and calls build over the weeks after.</p>
      <div class="row" style="gap:8px;align-items:flex-end;margin-top:10px"><label class="f">Trial starts<input type="date" id="tStart" value="${new Date().toISOString().slice(0, 10)}"></label>
        <button class="btn primary" id="tGo">Start 7-day trial</button></div>`}</div>`;
    const go = $('#tGo'); if (go) go.onclick = async () => { await api(`${base}/trial/start`, { json: { start_date: $('#tStart').value } }); toast('Trial started'); route(); };
    return;
  }
  const pct = Math.round(100 * t.done / t.total);
  const days = [1, 2, 3, 4, 5, 6, 7];
  const DAY_TITLE = { 1: 'Set up & measure', 2: 'Fix the Google profile', 3: 'Photos & first post', 4: 'Reviews system', 5: 'Website quick wins', 6: 'Second post & FAQs', 7: 'Measure & report' };
  view.innerHTML = `
    <div class="card"><div class="row" style="justify-content:space-between;gap:10px;flex-wrap:wrap">
      <div><h2 style="margin:0">Day ${t.day} of 7 <span class="small muted">· ${t.start_date} → ${t.end_date}</span></h2>
        <div class="row" style="gap:8px;margin-top:6px"><div class="bar-track" style="width:220px"><div class="bar-fill" style="width:${pct}%;background:${cssVar('--good')}"></div></div><span class="small">${t.done} of ${t.total} tasks done</span></div></div>
      <div class="row" style="gap:8px;flex-wrap:wrap"><a class="btn primary" href="/clients/${CLIENT.id}/trial-report" target="_blank" rel="noopener">📄 End-of-trial report</a>
        ${IS_CLIENT ? '' : '<button class="btn" id="tLink">Copy report link</button><button class="btn ghost" id="tRestart">Restart</button>'}</div></div>
      <label class="f" style="margin-top:12px">Goal for the week<input id="tGoal" value="${fmt.esc(t.goal || '')}" placeholder="e.g. more flu vaccination bookings and new Google reviews" ${ro}></label></div>

    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h2>Before &amp; after numbers</h2>
        <p class="small muted">Fill in <b>Day 1</b> now and <b>Day 7</b> at the end. Reviews, rating and photos are on their Google Maps listing; posts, calls and directions are in their Google Business Profile → Performance (needs Manager access). Leave blank what you can't see.</p>
        <table class="snap"><thead><tr><th></th><th class="r">Day 1</th><th class="r">Day 7</th></tr></thead><tbody>
          ${t.fields.map(([k, l]) => `<tr><td>${l}</td><td class="r"><input data-s="baseline" data-k="${k}" type="number" step="${k === 'rating' ? '0.1' : '1'}" min="0" value="${t.baseline[k] ?? ''}" ${ro}></td>
            <td class="r"><input data-s="after" data-k="${k}" type="number" step="${k === 'rating' ? '0.1' : '1'}" min="0" value="${t.after[k] ?? ''}" ${ro}></td></tr>`).join('')}
        </tbody></table></div>
      <div class="card"><h2>Google profile checklist</h2>
        <p class="small muted">Tick what's already done on day 1, then again on day 7. The report shows the % complete before and after.</p>
        <table class="snap"><thead><tr><th></th><th class="r">Day 1</th><th class="r">Day 7</th></tr></thead><tbody>
          ${t.profile_checks.map(([k, l]) => `<tr><td>${l}</td><td class="r"><input type="checkbox" data-c="checks_before" data-k="${k}" ${t.checks_before[k] ? 'checked' : ''} ${ro}></td>
            <td class="r"><input type="checkbox" data-c="checks_after" data-k="${k}" ${t.checks_after[k] ? 'checked' : ''} ${ro}></td></tr>`).join('')}
          <tr><td><b>Complete</b></td><td class="r"><b>${t.completeness_before ?? '–'}${t.completeness_before != null ? '%' : ''}</b></td><td class="r"><b>${t.completeness_after ?? '–'}${t.completeness_after != null ? '%' : ''}</b></td></tr>
        </tbody></table></div>
    </div>
    ${IS_CLIENT ? '' : '<div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn primary" id="tSave">Save numbers</button></div>'}

    <div class="card" style="margin-top:14px"><h2>Day-by-day plan</h2>
      ${days.map(d => `<div class="tday ${d === t.day ? 'today' : ''}"><div class="tdh">Day ${d} · ${DAY_TITLE[d]} ${d === t.day ? '<span class="badge accent">today</span>' : ''}</div>
        ${t.tasks.filter(x => x.day === d).map(x => `<div class="ttask ${x.done ? 'done' : ''}"><label class="row" style="gap:10px;align-items:flex-start;flex-wrap:nowrap">
          <input type="checkbox" data-task="${x.id}" ${x.done ? 'checked' : ''} ${ro} style="margin-top:3px"><span><b>${fmt.esc(x.title)}</b>${x.help ? `<div class="small muted">${fmt.esc(x.help)}</div>` : ''}</span></label>
          ${IS_CLIENT ? (x.note ? `<div class="small" style="margin-left:26px">${fmt.esc(x.note)}</div>` : '') : `<input class="tnote" data-note="${x.id}" value="${fmt.esc(x.note || '')}" placeholder="Note (optional), e.g. uploaded 14 photos">`}</div>`).join('')}</div>`).join('')}
      ${IS_CLIENT ? '' : `<form id="tAdd" class="row" style="gap:8px;margin-top:10px;align-items:flex-end"><label class="f" style="flex:1">Add your own task<input name="title" required placeholder="e.g. Set up a flu-shot booking page"></label>
        <label class="f">Day<select name="day">${days.map(d => `<option ${d === t.day ? 'selected' : ''}>${d}</option>`).join('')}</select></label><button class="btn">Add</button></form>`}
    </div>`;
  if (IS_CLIENT) return;
  const put = (body, msg) => api(`${base}/trial`, { method: 'PUT', json: body }).then(() => { if (msg) toast(msg); });
  $$('[data-task]').forEach(cb => cb.onchange = async () => { await put({ tasks: [{ id: cb.dataset.task, done: cb.checked, note: $(`[data-note="${cb.dataset.task}"]`).value }] }); route(); });
  $$('[data-note]').forEach(inp => inp.onchange = () => put({ tasks: [{ id: inp.dataset.note, done: $(`[data-task="${inp.dataset.note}"]`).checked, note: inp.value }] }, 'Note saved'));
  $('#tGoal').onchange = e => put({ goal: e.target.value }, 'Goal saved');
  $('#tSave').onclick = async () => {
    const body = { baseline: {}, after: {}, checks_before: {}, checks_after: {} };
    $$('[data-s]').forEach(i => { body[i.dataset.s][i.dataset.k] = i.value; });
    $$('[data-c]').forEach(i => { body[i.dataset.c][i.dataset.k] = i.checked; });
    try { await put(body, 'Saved'); route(); } catch (e) { toast(e.message); }
  };
  $$('[data-c]').forEach(i => i.onchange = () => $('#tSave').click());
  $('#tAdd').onsubmit = async e => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target)); await put({ tasks: [{ new: true, title: f.title, day: +f.day }] }, 'Task added'); route(); };
  $('#tLink').onclick = async () => { const r = await api(`${base}/trial-link`, { method: 'POST' });
    try { await navigator.clipboard.writeText(r.url); toast('Report link copied: paste it into a text or email to the owner', 6000); } catch { prompt('Report link:', r.url); } };
  $('#tRestart').onclick = async () => { if (!confirm('Start the trial again from scratch? All ticks and numbers are cleared.')) return; await api(`${base}/trial/start`, { json: {} }); route(); };
};

/* ---------------- Google Maps & reviews ---------------- */
const GBP_HELP = 'Where to find these: open business.google.com (or search the business name on Google while signed in) → Performance → choose the month.';
R.local = async () => {
  const d = await api(`${base}/local`);
  setPeriod(null); $('#periodLabel').textContent = 'Google Maps listing & reviews';
  const L = d.latest || {}, P = d.previous || {};
  const labels = Object.fromEntries(d.activity);
  const editMonth = d.suggest_month;
  const cur = d.series.find(x => x.month === editMonth) || {};
  const comp = d.competitors;
  view.innerHTML = `
    ${d.series.length ? `<div class="kpis">${['calls', 'direction_requests', 'website_clicks', 'profile_views'].filter(k => L[k] != null).map(k =>
      kpi(labels[k], fmt.num(L[k]), P[k] ? (L[k] - P[k]) / P[k] : undefined, true, L.month)).join('')}
      ${L.reviews_total != null ? kpi('Google reviews', fmt.num(L.reviews_total) + (L.rating ? ` <span class="small">★${L.rating}</span>` : ''), undefined, true, L.new_reviews != null ? `+${L.new_reviews} this month` : L.month) : ''}
      ${d.rank ? kpi('Rank by reviews', `#${d.rank} <span class="small">of ${d.of}</span>`, undefined, true, 'vs nearby competitors') : ''}</div>` : ''}
    <div class="grid g2">
      <div class="card"><h2>Calls &amp; directions from Google, by month</h2>
        ${d.series.length ? `<div id="lgl"></div><div class="chart-box"><canvas id="loc1"></canvas></div>` : '<div class="empty">No months recorded yet.</div>'}</div>
      <div class="card"><h2>Reviews vs nearby competitors ${comp.month ? `<span class="small muted">· ${comp.month}</span>` : ''}</h2>
        ${d.ranking.length ? `<div class="tw"><table><thead><tr><th>Business</th><th class="r">Rating</th><th class="r">Reviews</th><th class="r">New</th></tr></thead><tbody>
          ${d.ranking.map((r, i) => `<tr class="${r.is_self ? 'sel' : ''}"><td>${i + 1}. ${r.is_self ? `<b>${fmt.esc(CLIENT.name)}</b> <span class="badge accent">you</span>` : fmt.esc(r.name)}</td>
            <td class="r">${r.rating ? '★' + r.rating : '–'}</td><td class="r">${fmt.num(r.reviews)}</td><td class="r">${r.new_reviews != null ? '+' + r.new_reviews : '–'}</td></tr>`).join('')}</tbody></table></div>
          ${d.top_competitor && L.reviews_total != null && d.top_competitor.reviews > L.reviews_total ? `<div class="callout small" style="margin-top:8px">${fmt.esc(d.top_competitor.name)} has ${fmt.num(d.top_competitor.reviews - L.reviews_total)} more reviews. At 10 new reviews a month you'd catch up in about ${Math.ceil((d.top_competitor.reviews - L.reviews_total) / 10)} months.</div>` : ''}`
        : `<div class="empty">No competitors added yet.${IS_CLIENT ? '' : ' Add them below.'}</div>`}</div>
    </div>
    ${IS_CLIENT ? '' : `
    <div class="card" style="margin-top:14px"><h2>Add a month's figures</h2>
      <p class="small muted">${GBP_HELP} Takes about 2 minutes a month. Leave a box empty if Google doesn't show it.</p>
      <form id="gbpForm" class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
        <label class="f">Month<input name="month" type="month" value="${editMonth}" style="width:150px"></label>
        ${d.activity.map(([k, l]) => `<label class="f">${l}<input name="${k}" type="number" min="0" value="${cur[k] ?? ''}" style="width:120px"></label>`).join('')}
        <label class="f">Total reviews<input name="reviews_total" type="number" min="0" value="${cur.reviews_total ?? ''}" style="width:110px"></label>
        <label class="f">Rating ★<input name="rating" type="number" min="0" max="5" step="0.1" value="${cur.rating ?? ''}" style="width:90px"></label>
        <button class="btn primary">Save month</button></form></div>
    <div class="card" style="margin-top:14px"><div class="row" style="justify-content:space-between;gap:8px;flex-wrap:wrap"><h2>Competitors to track</h2>
      <div class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
        <label class="f">What they do<input id="term" value="${fmt.esc(d.search_term)}" placeholder="e.g. pharmacy" style="width:150px"></label>
        <label class="f">Suburb<input id="area" value="${fmt.esc(d.area)}" placeholder="e.g. East Bentleigh VIC" style="width:190px"></label>
        <button class="btn" id="gMaps" type="button">Open in Google Maps ↗</button>
        ${d.places_enabled ? `<button class="btn primary" id="gFind" type="button">Find competitors automatically</button>${comp.list.length ? '<button class="btn" id="gRefresh" type="button">↻ Update their reviews</button>' : ''}` : ''}</div></div>
      <p class="small muted">${d.places_enabled
        ? 'Click “Find competitors automatically” to list the nearest similar businesses with their stars and reviews. Next month, click “Update their reviews” to see who gained how many.'
        : 'Click <b>Open in Google Maps</b>: it searches “what they do near suburb”. Type the 3–6 nearest into the rows below: name, star rating and number of reviews (shown under each name on Maps), then click Save. <span class="muted">(Automatic search needs a Google Places key: see DEPLOY.md, Step 6.)</span>'}</p>
      <div id="compRows">${(comp.list.length ? comp.list : [{}, {}, {}]).map(c => compRow(c)).join('')}</div>
      <div class="row" style="gap:8px;margin-top:8px"><button class="btn sm" type="button" id="compAddRow">＋ Add row</button><button class="btn primary" type="button" id="compSave">Save competitors for ${editMonth}</button></div></div>`}
    ${d.series.length ? `<div class="card" style="margin-top:14px"><h2>All months</h2><div class="tw"><table><thead><tr><th>Month</th>${d.activity.map(([, l]) => `<th class="r">${l}</th>`).join('')}<th class="r">Reviews</th><th class="r">New</th><th class="r">Rating</th></tr></thead><tbody>
      ${d.series.slice().reverse().map(r => `<tr><td>${r.month}${r.partial ? ' <span class="small muted">(so far)</span>' : ''}</td>${d.activity.map(([k]) => `<td class="r">${fmt.num(r[k])}</td>`).join('')}<td class="r">${fmt.num(r.reviews_total)}</td><td class="r">${r.new_reviews != null ? '+' + r.new_reviews : '–'}</td><td class="r">${r.rating ?? '–'}</td></tr>`).join('')}
    </tbody></table></div></div>` : ''}`;
  if (d.series.length) {
    const s = d.series;
    $('#lgl').innerHTML = legendHTML([{ label: 'Calls', color: cssVar('--s1') }, { label: 'Direction requests', color: cssVar('--s2') }, { label: 'Website clicks', color: cssVar('--s6') }]);
    drawChart('loc1', { type: 'bar', data: { labels: s.map(r => r.month), datasets: [
      { label: 'Calls', data: s.map(r => r.calls || 0), backgroundColor: cssVar('--s1'), borderRadius: 3 },
      { label: 'Direction requests', data: s.map(r => r.direction_requests || 0), backgroundColor: cssVar('--s2'), borderRadius: 3 },
      { label: 'Website clicks', data: s.map(r => r.website_clicks || 0), backgroundColor: cssVar('--s6'), borderRadius: 3 }] },
      options: { scales: { x: { grid: { display: false } }, y: axis(fmt.compact) } } });
  }
  if (IS_CLIENT) return;
  $('#gbpForm').onsubmit = async e => {
    e.preventDefault(); const fd = Object.fromEntries(new FormData(e.target)); const month = fd.month; delete fd.month;
    try { await api(`${base}/local/${month}`, { method: 'PUT', json: { values: fd } }); toast('Month saved'); route(); } catch (err) { toast(err.message, 6000); }
  };
  $('#compAddRow').onclick = () => $('#compRows').insertAdjacentHTML('beforeend', compRow({}));
  const saveArea = async () => {
    const a = $('#area').value.trim(), t = $('#term').value.trim();
    if (a !== (CLIENT.area || '') || t !== (CLIENT.search_term || '')) Object.assign(CLIENT, await api(base, { method: 'PATCH', json: { area: a, search_term: t } }));
  };
  $('#area').onchange = saveArea; $('#term').onchange = saveArea;
  $('#gMaps').onclick = () => {
    const a = $('#area').value.trim(), t = $('#term').value.trim() || 'business';
    if (!a) return toast('Type the suburb first');
    saveArea().catch(() => {});
    window.open('https://www.google.com/maps/search/' + encodeURIComponent(`${t} near ${a}`), '_blank', 'noopener');
  };
  const gf = $('#gFind');
  if (gf) gf.onclick = async () => { gf.disabled = true; gf.textContent = 'Searching Google…';
    try { await saveArea(); await api(`${base}/local/${editMonth}/find`, { method: 'POST' }); toast('Competitors found'); route(); }
    catch (err) { toast(err.message, 7000); gf.disabled = false; gf.textContent = 'Find competitors automatically'; } };
  $('#compSave').onclick = async () => {
    const list = $$('#compRows .comprow').map(r => ({ name: $('[name=cn]', r).value.trim(), rating: $('[name=cr]', r).value, reviews: $('[name=cv]', r).value })).filter(x => x.name);
    try { await saveArea(); await api(`${base}/local/${editMonth}`, { method: 'PUT', json: { competitors: list } }); toast('Competitors saved'); route(); } catch (err) { toast(err.message, 6000); }
  };
  const rf = $('#gRefresh');
  if (rf) rf.onclick = async () => { rf.disabled = true; rf.textContent = 'Checking Google…';
    try { await saveArea(); await api(`${base}/local/${editMonth}/refresh`, { method: 'POST' }); toast('Reviews updated'); route(); } catch (err) { toast(err.message, 7000); rf.disabled = false; rf.textContent = '↻ Update their reviews'; } };
};
function compRow(c) {
  return `<div class="row comprow" style="gap:8px;margin-top:6px"><input name="cn" placeholder="Competitor name" value="${fmt.esc(c.name || '')}" style="flex:1;min-width:180px">
    <input name="cr" type="number" step="0.1" min="0" max="5" placeholder="★ rating" value="${c.rating ?? ''}" style="width:100px">
    <input name="cv" type="number" min="0" placeholder="reviews" value="${c.reviews ?? ''}" style="width:110px">
    <button class="btn sm ghost" type="button" onclick="this.parentElement.remove()">✕</button></div>`;
}

/* ---------------- audience: age, gender, location ---------------- */
let audMonths = 3;
R.audience = async () => {
  const d = await api(`${base}/audience?months=${audMonths}`);
  setPeriod(null); $('#periodLabel').textContent = `Who sees and responds · since ${fmt.date(d.from)}`;
  const A = d.ads, W = d.web;
  const segTable = (x, withCost = true) => `<div class="tw"><table><thead><tr><th>${fmt.esc(x.label)}</th>${withCost ? '<th class="r">Spend</th><th class="r">Share of spend</th><th class="r">Clicks</th><th class="r">CTR</th><th class="r">Results</th><th class="r">Share of results</th><th class="r">Cost per result</th>' : '<th class="r">Visitors</th><th class="r">Share</th><th class="r">Sessions</th><th class="r">Actions</th>'}</tr></thead><tbody>
    ${x.segments.map(s => withCost ? `<tr><td>${fmt.esc(s.segment)}</td><td class="r">${fmt.money(s.spend)}</td>
      <td class="r"><div class="bar-track" style="width:60px;display:inline-block"><div class="bar-fill" style="width:${((s.spend_share || 0) * 100).toFixed(0)}%;background:${cssVar('--s1')}"></div></div> ${fmt.pct(s.spend_share, 0)}</td>
      <td class="r">${fmt.num(s.clicks)}</td><td class="r">${fmt.pct(s.ctr, 2)}</td><td class="r">${fmt.num(s.conversions, 1)}</td>
      <td class="r"><div class="bar-track" style="width:60px;display:inline-block"><div class="bar-fill" style="width:${((s.conv_share || 0) * 100).toFixed(0)}%;background:${cssVar('--s2')}"></div></div> ${fmt.pct(s.conv_share, 0)}</td>
      <td class="r">${s.cpa != null && x.totals.cpa && s.cpa < x.totals.cpa * 0.8 ? `<span class="badge good">${fmt.money2(s.cpa)}</span>` : s.cpa != null && x.totals.cpa && s.cpa > x.totals.cpa * 1.3 ? `<span class="badge warn">${fmt.money2(s.cpa)}</span>` : fmt.money2(s.cpa)}</td></tr>`
      : `<tr><td>${fmt.esc(s.segment)}</td><td class="r">${fmt.num(s.users)}</td><td class="r">${fmt.pct(s.share, 0)}</td><td class="r">${fmt.num(s.sessions)}</td><td class="r">${fmt.num(s.conversions)}</td></tr>`).join('')}</tbody></table></div>`;
  view.innerHTML = `
    <div class="row no-print" style="justify-content:space-between;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      <div class="seg" id="audRange">${[[1, 'This month'], [3, '3 months'], [12, '12 months']].map(([m, l]) => `<button data-m="${m}" class="${m === audMonths ? 'on' : ''}">${l}</button>`).join('')}</div>
      <div class="small muted">${d.platforms.map(p => fmt.esc(p.label)).join(' · ') || 'No sources yet'} · group totals only, never individuals</div></div>
    ${d.insights.length ? `<div class="card"><h2>What this tells you</h2>${d.insights.map(i => `<div class="insight ${i.kind}"><b style="background:var(--icb);color:var(--ic)">${i.kind === 'good' ? '✓' : i.kind === 'bad' ? '!' : 'i'}</b><span>${fmt.esc(i.text)}</span></div>`).join('')}</div>` : ''}
    ${A.age || A.gender ? `<div class="grid g2" style="margin-top:14px">
      ${A.age ? `<div class="card"><h2>Ads by age: share of spend vs share of results</h2><div id="lga"></div><div class="chart-box"><canvas id="au1"></canvas></div></div>` : ''}
      ${A.gender ? `<div class="card"><h2>Ads by gender</h2><div id="lgg"></div><div class="chart-box"><canvas id="au2"></canvas></div></div>` : ''}</div>` : ''}
    ${['age_gender', 'age', 'gender', 'region', 'city'].filter(k => A[k]).map(k => `<div class="card" style="margin-top:14px"><h2>Ads · ${fmt.esc(A[k].label)}</h2>${segTable(A[k])}</div>`).join('')}
    ${Object.keys(W).length ? `<h2 style="margin:18px 0 8px">Website visitors (Google Analytics)</h2><div class="grid g2">${['age', 'gender', 'city', 'region'].filter(k => W[k]).map(k => `<div class="card"><h2>${fmt.esc(W[k].label)}</h2>${segTable(W[k], false)}</div>`).join('')}</div>` : ''}
    ${!Object.keys(A).length && !Object.keys(W).length ? `<div class="card" style="margin-top:14px"><div class="empty">No age, gender or location data yet.${IS_CLIENT ? '' : ` Export a report broken down by Age &amp; Gender (or Region) from Meta Ads Manager, Google Ads or Google Analytics and add it in <a href="#upload" onclick="return gotoTab('upload')">Upload data</a>.`}</div></div>` : ''}`;
  $$('#audRange button').forEach(b => b.onclick = () => { audMonths = +b.dataset.m; route(); });
  const shareChart = (id, lg, x) => {
    $('#' + lg).innerHTML = legendHTML([{ label: 'Share of spend', color: cssVar('--s1') }, { label: 'Share of results', color: cssVar('--s2') }]);
    drawChart(id, { type: 'bar', data: { labels: x.segments.map(s => s.segment), datasets: [
      { label: 'Share of spend', data: x.segments.map(s => (s.spend_share || 0) * 100), backgroundColor: cssVar('--s1'), borderRadius: 3 },
      { label: 'Share of results', data: x.segments.map(s => (s.conv_share || 0) * 100), backgroundColor: cssVar('--s2'), borderRadius: 3 }] },
      options: { scales: { x: { grid: { display: false } }, y: axis(v => v + '%') }, plugins: { tooltip: { ...tooltipStyle(), callbacks: { label: t => ` ${t.dataset.label}: ${t.raw.toFixed(0)}%` } } } } });
  };
  if (A.age) shareChart('au1', 'lga', A.age);
  if (A.gender) shareChart('au2', 'lgg', A.gender);
};

/* ---------------- upload data (CSV exports) ---------------- */
const UPLOAD_HELP = [
  ['Meta Ads Manager (Facebook & Instagram)', ['Open Ads Manager → Campaigns, pick the date range (e.g. last month).', 'For results by campaign: click <b>Reports → Export table data → .csv</b>.',
    'For age & gender: click <b>Breakdown → By delivery → Age</b> and <b>Gender</b>, then export again. For location: Breakdown → <b>Region</b>.']],
  ['Google Ads', ['Open Google Ads → Campaigns, set the date range.', 'Click the <b>download icon → .csv</b>. Add “Day” under Segment first if you want daily charts.',
    'For age & gender: go to <b>Audiences, keywords and content → Demographics</b>, then download .csv. For location: <b>Locations → Matched locations</b>.']],
  ['Google Analytics (website visitors)', ['Open Reports → <b>User attributes → Demographic details</b>, pick Age, Gender or Town/City.', 'Click <b>Share this report → Download file → CSV</b>.',
    'For visitors per day: Reports → Acquisition → Traffic acquisition, then download CSV.']],
];
R.upload = async () => {
  const h = await api(`${base}/imports`);
  setPeriod(null); $('#periodLabel').textContent = 'Upload reports: works without any platform approvals';
  const today = new Date(), lm = new Date(today.getFullYear(), today.getMonth() - 1, 1), lmEnd = new Date(today.getFullYear(), today.getMonth(), 0);
  const iso = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  view.innerHTML = `
    <div class="grid g2">
      <form class="card" id="upForm"><h2>Upload a report</h2>
        <p class="small muted">Export a CSV from Meta Ads Manager, Google Ads or Google Analytics and drop it here. AdPulse recognises the columns and fills in the right tab. Uploading the same period again replaces it.</p>
        <label class="dropzone" id="drop"><input type="file" name="file" accept=".csv,.tsv,.txt" required hidden><span id="dropText">📄 Click to choose a CSV file, or drag it here</span></label>
        <div class="row" style="gap:8px;margin-top:10px;flex-wrap:wrap;align-items:flex-end">
          <label class="f">From<select name="platform"><option value="auto">Work it out for me</option>${Object.entries(h.platforms).map(([k, l]) => `<option value="${k}">${fmt.esc(l)}</option>`).join('')}</select></label>
          <label class="f">Report covers<input type="date" name="period_from" value="${iso(lm)}"></label>
          <label class="f">to<input type="date" name="period_to" value="${iso(lmEnd)}"></label></div>
        <p class="small muted" style="margin:6px 0 10px">The dates are only used if the file doesn't include them.</p>
        <button class="btn primary">Upload</button>
        <div id="upResult"></div></form>
      <div class="card"><h2>How to export the report</h2>${UPLOAD_HELP.map(([t, steps]) => `<h3>${t}</h3><ol class="plain small">${steps.map(x => `<li>${x}</li>`).join('')}</ol>`).join('')}</div>
    </div>
    <div class="card" style="margin-top:14px"><h2>Uploaded so far</h2><div class="tw"><table><thead><tr><th>When</th><th>File</th><th>From</th><th>Type</th><th>Period</th><th class="r">Rows</th></tr></thead><tbody>
      ${h.history.map(x => `<tr><td class="small muted">${fmt.esc(x.created_at)}</td><td>${fmt.esc(x.filename)}</td><td>${fmt.esc(h.platforms[x.platform] || x.platform)}</td><td>${{ ads: 'Ad results', demographics: 'Age / gender / location', traffic: 'Website visitors' }[x.kind] || x.kind}</td><td class="small">${x.period_from} → ${x.period_to}</td><td class="r">${x.rows}</td></tr>`).join('') || '<tr><td colspan=6 class="empty">Nothing uploaded yet</td></tr>'}
    </tbody></table></div></div>`;
  const inp = $('#upForm [name=file]'), drop = $('#drop');
  inp.onchange = () => { $('#dropText').textContent = inp.files[0] ? '📄 ' + inp.files[0].name : '📄 Click to choose a CSV file, or drag it here'; };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); if (e.dataTransfer.files[0]) { inp.files = e.dataTransfer.files; inp.onchange(); } };
  $('#upForm').onsubmit = async e => {
    e.preventDefault();
    if (!inp.files[0]) return toast('Choose a file first');
    const btn = $('#upForm button.primary'); btn.disabled = true; btn.textContent = 'Uploading…';
    try {
      const r = await api(`${base}/import`, { method: 'POST', body: new FormData(e.target) });
      const tabFor = { ads: 'performance', demographics: 'audience', traffic: 'organic' }[r.kind];
      $('#upResult').innerHTML = `<div class="callout small" style="margin-top:10px">✓ Added ${r.rows} rows from <b>${fmt.esc(r.platform_label)}</b> (${r.period[0]} → ${r.period[1]}). They show in <a href="#${tabFor}" onclick="return gotoTab('${tabFor}')">${fmt.esc(r.shows_in)}</a>.
        <div class="muted" style="margin-top:4px">Columns used: ${Object.entries(r.columns).map(([k, v]) => `${k} ← “${fmt.esc(v)}”`).join(', ')}</div></div>`;
      toast('Uploaded'); setTimeout(() => R.upload().catch(() => {}), 2500);
    } catch (err) { $('#upResult').innerHTML = `<div class="callout warn small" style="margin-top:10px">${fmt.esc(err.message)}</div>`; }
    btn.disabled = false; btn.textContent = 'Upload';
  };
};

/* ---------------- client logins (in Client settings) ---------------- */
async function loadLogins() {
  const el = $('#logins'); if (!el) return;
  try {
    const rows = await api(`${base}/logins`);
    el.innerHTML = rows.length ? `<table><tbody>${rows.map(u => `<tr><td>${fmt.esc(u.email)}</td><td class="small muted">${fmt.esc(u.name || '')}</td><td class="r"><button class="btn sm ghost" onclick="delLogin(${u.id})">Remove</button></td></tr>`).join('')}</tbody></table>` : '<div class="small muted">No client logins yet.</div>';
  } catch (e) { el.innerHTML = `<div class="small muted">${fmt.esc(e.message)}</div>`; }
}
async function delLogin(id) { if (!confirm('Remove this login? They will no longer be able to sign in.')) return; await api(`${base}/logins/${id}`, { method: 'DELETE' }); loadLogins(); }
async function addLogin(e) {
  e.preventDefault(); const b = Object.fromEntries(new FormData(e.target));
  try { await api(`${base}/logins`, { json: b }); toast('Login created. Send them the website address, their email and password.', 6000); e.target.reset(); loadLogins(); } catch (err) { toast(err.message, 6000); }
  return false;
}

/* ---------------- top bar actions ---------------- */
async function syncNow(btn) {
  btn.disabled = true; btn.textContent = 'Syncing…';
  try { const r = await api(`${base}/sync`, { method: 'POST' }); const bad = r.filter(x => !x.ok).length; toast(bad ? `${bad} connection(s) failed — see Connections` : `Synced ${r.length} connections`); } catch (e) { toast(e.message); }
  btn.disabled = false; btn.textContent = '↻ Sync now'; route();
}
async function shareReport() {
  const r = await api(`${base}/report-link?days=${days}`, { method: 'POST' });
  try { await navigator.clipboard.writeText(r.url); toast('Client report link copied (valid 90 days)'); } catch { prompt('Client report link:', r.url); }
  window.open(r.url, '_blank');
}

if (!window.__DEMO_SHELL__) {
  if (!IS_CLIENT) api(`${base}/alerts`).then(a => updateAlertCount(a.length)).catch(() => {});
  route();
}
