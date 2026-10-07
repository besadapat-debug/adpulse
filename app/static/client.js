/* Client workspace: one renderer per tab, all driven by the JSON API. */
currency = CLIENT.currency || 'AUD';
let days = 30;
const view = $('#view');
const TABS = ['monthly', 'trial', 'details', 'campaigns', 'local', 'performance', 'engagement', 'audience', 'organic', 'seo', 'email', 'attribution', 'people', 'companies', 'audiences', 'budget', 'alerts', 'upload', 'connections', 'settings'];
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
  ${conns.some(c => c.is_demo) ? `<div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn" onclick="clearDemo(this)">🗑 Remove all demo data</button></div>` : ''}
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
    : `<div class="callout warn small"><b>Don't use this for a real client.</b> ${pl.oauth_provider} isn't set up on this server yet, so connecting now would only fill their reports with <b>made-up numbers</b>. Set it up first (DEPLOY.md), then come back. Click Cancel.</div>`;
  body += `<label class="row small"><input type="checkbox" name="demo" ${!pl.live || (pl.auth === 'oauth' && !pl.oauth_ready) ? 'checked disabled' : ''}> Use demo data</label>`;
  $('#connBody').innerHTML = body;
  $('#connDlg').dataset.platform = p;
  $('#connDlg').showModal();
}
async function submitConn(e) {
  e.preventDefault();
  const p = $('#connDlg').dataset.platform, pl = PLATS.find(x => x.platform === p), fd = new FormData(e.target);
  const demo = e.target.querySelector('[name=demo]').checked;
  if (demo && !confirm('This adds MADE-UP sample numbers to ' + CLIENT.name + ' (for testing only). Continue?')) return false;
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
async function clearDemo(btn) {
  if (!confirm('Remove every demo connection and all the made-up numbers for ' + CLIENT.name + '? Anything typed in or uploaded stays.')) return;
  btn.disabled = true;
  try { const r = await api(`${base}/demo/clear`, { method: 'POST' }); toast(`Removed ${r.removed} demo connection(s) and their sample data`); const b = $('#demoBanner'); if (b) b.remove(); route(); }
  catch (e) { toast(e.message); btn.disabled = false; }
}
async function delConn(id) { if (confirm('Remove this connection? For a real account its past data stays; for a demo one the sample numbers are removed too.')) { await api(`/api/connections/${id}`, { method: 'DELETE' }); route(); } }

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



/* ---------------- business details & photos (the owner can fill this in) ---------------- */
async function shrinkImage(file, max = 1600) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = url; });
    const k = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement('canvas'); c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    return await new Promise(ok => c.toBlob(ok, 'image/jpeg', 0.85));
  } finally { URL.revokeObjectURL(url); }
}
R.details = async () => {
  const d = await api(`${base}/details`);
  setPeriod(null); $('#periodLabel').textContent = 'Business details & photos';
  const v = d.details;
  const field = ([k, label, typ, help]) => `<label class="f">${fmt.esc(label)}
    ${typ === 'textarea' ? `<textarea name="${k}" rows="${k === 'description' || k === 'services' || k === 'hours' ? 4 : 2}">${fmt.esc(v[k] || '')}</textarea>`
      : typ === 'select' ? `<select name="${k}"><option value=""></option>${d.platforms.map(p => `<option ${p === v[k] ? 'selected' : ''}>${fmt.esc(p)}</option>`).join('')}</select>`
      : `<input name="${k}" value="${fmt.esc(v[k] || '')}">`}
    ${help ? `<span class="small muted">${fmt.esc(help)}</span>` : ''}</label>`;
  view.innerHTML = `
    <div class="callout small" style="margin-bottom:12px">${IS_CLIENT
      ? `<b>Help us set up your Google listing, website and ads.</b> Fill in what you can, including the <b>About your customers &amp; ads</b> questions further down, and upload a few photos. It saves as you go, and you can come back any time.`
      : `The owner can fill this in from their own login (Client settings → Client login). Everything you need for their Google profile and website in one place. <a href="${base}/photos.zip">⬇ Download all photos &amp; details (zip)</a>`}
      ${d.updated_at ? `<div class="muted" style="margin-top:4px">Last updated ${fmt.esc(d.updated_at)}${d.updated_by ? ' by ' + fmt.esc(d.updated_by) : ''}</div>` : ''}</div>
    <div class="grid g2">
      <form class="card" id="detForm"><div class="row" style="justify-content:space-between"><h2>Business details</h2><span class="badge ${d.filled === d.total ? 'good' : ''}">${d.filled} of ${d.total} filled in</span></div>
        <div style="display:grid;gap:12px">${d.fields.map(f => (f[0] === d.ad_start ? `<h2 style="margin:14px 0 0">About your customers &amp; ads</h2><p class="small muted" style="margin:0">${IS_CLIENT ? 'This is what we use to write ads that sound like your business and reach the right people.' : 'Used by the campaign builder: priority services, reasons to choose them and offers go straight into the ad drafts.'}</p>` : '') + field(f)).join('')}</div>
        <div style="margin-top:12px"><button class="btn primary">Save details</button></div></form>
      <div>
        <div class="card"><h2>Access for the agency <span class="badge ${d.access_done === d.access.length ? 'good' : 'warn'}">${d.access_done} of ${d.access.length}</span></h2>
          ${d.access.map(([k, label, help]) => `<label class="row small" style="gap:8px;align-items:flex-start;flex-wrap:nowrap;margin:8px 0"><input type="checkbox" data-acc="${k}" ${v[k] ? 'checked' : ''} style="margin-top:3px">
            <span><b>${fmt.esc(label)}</b>${help ? `<div class="muted">${fmt.esc(help)}</div>` : ''}</span></label>`).join('')}</div>
        <div class="card" style="margin-top:14px"><h2>Photos <span class="small muted">${d.photos.length} uploaded</span></h2>
          <p class="small muted">Real photos beat stock photos. Good ones to add: ${d.photo_types.slice(0, 6).map(([, l]) => l.toLowerCase()).join(', ')}. Take them in landscape, in good light. Please no photos of customers or patients.</p>
          <div class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
            <label class="f">What's in the photo<select id="phCat">${d.photo_types.map(([k, l]) => `<option value="${k}">${fmt.esc(l)}</option>`).join('')}</select></label>
            <label class="btn primary" style="cursor:pointer">📷 Choose photos<input type="file" id="phFiles" accept="image/*" multiple hidden></label></div>
          <div id="phStatus" class="small" style="margin-top:6px"></div>
          <div class="photos">${d.photos.map(p => `<div class="ph"><a href="${base}/photos/${p.id}" target="_blank" rel="noopener"><img loading="lazy" src="${base}/photos/${p.id}" alt="${fmt.esc(p.caption || p.category)}"></a>
            <div class="small"><span class="badge">${fmt.esc((d.photo_types.find(t => t[0] === p.category) || [, p.category])[1])}</span></div>
            <button class="btn sm ghost" data-delph="${p.id}" type="button">Delete</button></div>`).join('') || '<div class="empty small">No photos yet</div>'}</div></div>
      </div>
    </div>`;
  const saveDetails = async (body, msg) => { try { await api(`${base}/details`, { method: 'PUT', json: body }); if (msg) toast(msg); } catch (e) { toast(e.message, 6000); } };
  $('#detForm').onsubmit = async e => { e.preventDefault(); await saveDetails(Object.fromEntries(new FormData(e.target)), 'Details saved'); route(); };
  $$('#detForm input, #detForm textarea, #detForm select').forEach(i => i.onchange = () => saveDetails({ [i.name]: i.value }));
  $$('[data-acc]').forEach(cb => cb.onchange = async () => { await saveDetails({ [cb.dataset.acc]: cb.checked }, 'Saved'); route(); });
  $$('[data-delph]').forEach(b => b.onclick = async () => { if (!confirm('Delete this photo?')) return; await api(`${base}/photos/${b.dataset.delph}`, { method: 'DELETE' }); route(); });
  $('#phFiles').onchange = async e => {
    const files = [...e.target.files]; const st = $('#phStatus'); let ok = 0;
    for (const [i, f] of files.entries()) {
      st.textContent = `Uploading ${i + 1} of ${files.length}…`;
      try {
        const blob = await shrinkImage(f);
        const fd = new FormData(); fd.append('file', blob, f.name.replace(/\.[^.]+$/, '') + '.jpg'); fd.append('category', $('#phCat').value);
        await api(`${base}/photos`, { method: 'POST', body: fd }); ok++;
      } catch (err) { toast(`${f.name}: ${err.message}`, 6000); }
    }
    toast(`${ok} photo${ok === 1 ? '' : 's'} uploaded`); route();
  };
};


/* ---------------- campaigns: build Google / Meta ads in AdPulse ---------------- */
let campId = null;
const STATUS_BADGE = { draft: '', awaiting_approval: 'warn', approved: 'good', changes_requested: 'bad', exported: 'accent', sent: 'accent', live: 'good', paused: '' };
R.campaigns = async () => {
  const L = await api(`${base}/campaigns`);
  setPeriod(null); $('#periodLabel').textContent = 'Campaigns: write, check and launch ads';
  if (campId && !L.campaigns.some(c => c.id === campId)) campId = null;
  view.innerHTML = `<div class="camp-layout">
    <div class="card camp-list"><h2>Campaigns</h2>
      ${L.campaigns.map(c => `<a href="#" class="camp-item ${c.id === campId ? 'on' : ''}" data-open="${c.id}">
        <div class="row" style="justify-content:space-between;gap:6px"><b>${fmt.esc(c.name)}</b><span class="small muted">${c.platform === 'google' ? 'Google' : 'Meta'}</span></div>
        <div class="row" style="justify-content:space-between;gap:6px;margin-top:3px"><span class="badge ${STATUS_BADGE[c.status] || ''}">${fmt.esc(c.status_label)}</span>
        <span class="small muted">${c.monthly_budget ? fmt.money(c.monthly_budget) + '/mo' : ''}</span></div></a>`).join('') || '<div class="small muted">No campaigns yet.</div>'}
      ${IS_CLIENT ? '' : `<div class="newcamp"><h3>New campaign</h3>
        <div class="seg" id="ncPlat"><button data-p="google" class="on">Google Search</button><button data-p="meta">Facebook &amp; Instagram</button></div>
        <label class="f" style="margin-top:8px">What to advertise<input id="ncService" list="ncServices" placeholder="e.g. Flu vaccinations"><datalist id="ncServices">${L.services.map(x => `<option value="${fmt.esc(x)}">`).join('')}</datalist></label>
        <div class="row" style="gap:8px"><label class="f" style="flex:1">Monthly ad spend ($)<input id="ncBudget" type="number" min="0" step="50" value="600"></label>
          <label class="f" style="width:100px">Radius (km)<input id="ncRadius" type="number" min="1" max="80" value="5"></label></div>
        <button class="btn primary" id="ncGo" style="margin-top:8px;width:100%">Write the campaign</button>
        <p class="small muted" style="margin-top:6px">AdPulse writes a first version from their Business details. You can change everything.</p></div>`}
    </div>
    <div id="campEditor">${campId ? '<div class="empty">Loading…</div>' : `<div class="card"><div class="empty">${IS_CLIENT ? 'Pick a campaign to see the ad.' : 'Pick a campaign, or write a new one on the left.'}</div>
      ${IS_CLIENT ? '' : `<div class="small muted" style="padding:0 16px 16px">How it works: <b>1</b> write the campaign → <b>2</b> fix anything in red → <b>3</b> ask the owner to approve → <b>4</b> launch it: download the Google Ads Editor file, use the Meta copy kit, or send it straight to their ad account once connected (it arrives paused).</div>`}</div>`}</div>
  </div>`;
  $$('[data-open]').forEach(a => a.onclick = e => { e.preventDefault(); campId = +a.dataset.open; R.campaigns(); });
  const plat = { v: 'google' };
  $$('#ncPlat button').forEach(b => b.onclick = () => { plat.v = b.dataset.p; $$('#ncPlat button').forEach(x => x.classList.toggle('on', x === b)); });
  const go = $('#ncGo');
  if (go) go.onclick = async () => {
    go.disabled = true;
    try { const c = await api(`${base}/campaigns`, { json: { platform: plat.v, service: $('#ncService').value, monthly_budget: +$('#ncBudget').value, radius_km: +$('#ncRadius').value } });
      campId = c.id; toast('Campaign written. Check it over.'); R.campaigns(); }
    catch (e) { toast(e.message, 6000); go.disabled = false; }
  };
  if (campId) renderCampaign(await api(`${base}/campaigns/${campId}`), L);
};

function counter(v, max) { const n = (v || '').length; return `<span class="cc ${n > max ? 'over' : ''}">${n}/${max}</span>`; }
function renderCampaign(c, L) {
  const d = c.data, g = c.platform === 'google', ro = IS_CLIENT || ['sent', 'live', 'paused'].includes(c.status) ? 'disabled' : '';
  const errs = c.checks.filter(x => x.level === 'error'), warns = c.checks.filter(x => x.level === 'warn'), info = c.checks.filter(x => x.level === 'info');
  const daily = (d.monthly_budget || 0) / 30.4;
  const photoUrl = d.photo_id ? `${base}/photos/${d.photo_id}` : '';
  const host = (d.final_url || '').replace(/^https?:\/\//, '').split('/')[0];
  const preview = g ? `<div class="gad"><div class="small"><b>Sponsored</b></div><div class="gurl">${fmt.esc(host)}${d.path1 ? ' › ' + fmt.esc(d.path1) : ''}${d.path2 ? ' › ' + fmt.esc(d.path2) : ''}</div>
      <div class="ghead">${(d.headlines || []).slice(0, 3).map(fmt.esc).join(' | ')}</div><div class="gdesc">${fmt.esc((d.descriptions || [])[0] || '')} ${fmt.esc((d.descriptions || [])[1] || '')}</div></div>
      <p class="small muted">One of many combinations: Google mixes your headlines and descriptions to find what works best.</p>`
    : `<div class="mad"><div class="mhead"><span class="mark-sm">${fmt.esc((CLIENT.name || 'A')[0])}</span><div><b>${fmt.esc(CLIENT.name)}</b><div class="small muted">Sponsored</div></div></div>
      <div class="mtext">${fmt.esc(d.primary_text || '')}</div>${photoUrl ? `<img src="${photoUrl}" alt="">` : '<div class="mnoimg">Pick a photo</div>'}
      <div class="mfoot"><div><div class="small muted">${fmt.esc(host.toUpperCase())}</div><b>${fmt.esc(d.headline || '')}</b><div class="small">${fmt.esc(d.description || '')}</div></div>
      <span class="btn sm">${fmt.esc(L.ctas[d.cta] || 'Learn more')}</span></div></div>`;
  const list = (arr, key, max, n) => Array.from({ length: n }, (_, i) => arr[i] || '').map((v, i) => `<div class="li-in"><input data-list="${key}" data-i="${i}" value="${fmt.esc(v)}" ${ro} placeholder="${i < (key === 'headlines' ? 3 : 2) ? 'Required' : 'Optional'}">${counter(v, max)}</div>`).join('');
  const fields = g ? `
      <label class="f">Campaign name<input data-k="name" value="${fmt.esc(d.name || '')}" ${ro}></label>
      <label class="f">Landing page (where the ad goes)<input data-k="final_url" value="${fmt.esc(d.final_url || '')}" placeholder="https://…/book" ${ro}></label>
      <div class="row" style="gap:8px"><label class="f" style="flex:1">Show ads to people near<input data-k="location" value="${fmt.esc(d.location || '')}" placeholder="Shop address or suburb" ${ro}></label>
        <label class="f" style="width:110px">Radius (km)<input data-k="radius_km" type="number" min="1" max="80" value="${d.radius_km || 5}" ${ro}></label>
        <label class="f" style="width:150px">Monthly spend ($)<input data-k="monthly_budget" type="number" min="0" step="50" value="${d.monthly_budget || 0}" ${ro}></label></div>
      <div class="small muted">≈ ${fmt.money(daily)} a day. Paid to Google from their card, not part of your fee.</div>
      <h3>Headlines <span class="small muted">(3–15, max 30 characters each)</span></h3>${list(d.headlines || [], 'headlines', 30, 15)}
      <h3>Descriptions <span class="small muted">(2–4, max 90 characters)</span></h3>${list(d.descriptions || [], 'descriptions', 90, 4)}
      <div class="row" style="gap:8px"><label class="f" style="flex:1">Web address path 1<input data-k="path1" value="${fmt.esc(d.path1 || '')}" ${ro}></label><label class="f" style="flex:1">Path 2<input data-k="path2" value="${fmt.esc(d.path2 || '')}" ${ro}></label></div>
      <div class="row" style="gap:8px;align-items:flex-start"><label class="f" style="flex:1">Keywords (one per line)<textarea data-lines="keywords" rows="6" ${ro}>${fmt.esc((d.keywords || []).join('\n'))}</textarea></label>
        <label class="f" style="flex:1">Don't show for (negative keywords)<textarea data-lines="negatives" rows="6" ${ro}>${fmt.esc((d.negatives || []).join('\n'))}</textarea></label></div>
      <label class="f" style="width:240px">Keyword match<select data-k="match" ${ro}>${[['PHRASE', 'Phrase (recommended)'], ['EXACT', 'Exact'], ['BROAD', 'Broad']].map(([k, l]) => `<option value="${k}" ${k === d.match ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`
    : `
      <label class="f">Campaign name<input data-k="name" value="${fmt.esc(d.name || '')}" ${ro}></label>
      <label class="f">Goal<select data-k="objective" ${ro}>${Object.entries(L.objectives).map(([k, l]) => `<option value="${k}" ${k === d.objective ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="f">Landing page<input data-k="final_url" value="${fmt.esc(d.final_url || '')}" placeholder="https://…" ${ro}></label>
      <div class="row" style="gap:8px"><label class="f" style="flex:1">Show to people near<input data-k="location" value="${fmt.esc(d.location || '')}" ${ro}></label>
        <label class="f" style="width:100px">Radius (km)<input data-k="radius_km" type="number" min="1" max="80" value="${d.radius_km || 5}" ${ro}></label></div>
      <div class="row" style="gap:8px"><label class="f" style="width:100px">Age from<input data-k="age_min" type="number" min="18" max="65" value="${d.age_min || 18}" ${ro}></label>
        <label class="f" style="width:100px">to<input data-k="age_max" type="number" min="18" max="65" value="${d.age_max || 65}" ${ro}></label>
        <label class="f" style="width:150px">Monthly spend ($)<input data-k="monthly_budget" type="number" min="0" step="50" value="${d.monthly_budget || 0}" ${ro}></label></div>
      <div class="small muted">≈ ${fmt.money(daily)} a day, paid to Meta from their card.</div>
      <label class="f">Main text ${counter(d.primary_text, 125)}<textarea data-k="primary_text" rows="3" ${ro}>${fmt.esc(d.primary_text || '')}</textarea></label>
      <label class="f">Headline ${counter(d.headline, 40)}<input data-k="headline" value="${fmt.esc(d.headline || '')}" ${ro}></label>
      <label class="f">Description (optional) ${counter(d.description, 30)}<input data-k="description" value="${fmt.esc(d.description || '')}" ${ro}></label>
      <label class="f" style="width:220px">Button<select data-k="cta" ${ro}>${Object.entries(L.ctas).map(([k, l]) => `<option value="${k}" ${k === d.cta ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <h3>Photo</h3>${L.photos.length ? `<div class="pickph">${L.photos.map(p => `<label class="${p.id === d.photo_id ? 'on' : ''}"><input type="radio" name="ph" value="${p.id}" ${p.id === d.photo_id ? 'checked' : ''} ${ro} hidden><img src="${base}/photos/${p.id}" alt=""></label>`).join('')}</div>`
        : `<div class="small muted">No photos yet. Ask the owner to add some in <a href="#details" onclick="return gotoTab('details')">Business details &amp; photos</a>.</div>`}
      <label class="f" style="margin-top:8px">Facebook Page ID <span class="small muted">(only needed to send directly: their Page → About → Page transparency)</span><input data-k="page_id" value="${fmt.esc(d.page_id || '')}" ${ro}></label>`;
  const kit = !g && !IS_CLIENT ? `<div class="card" style="margin-top:14px"><h2>Meta copy kit</h2>
      <p class="small muted">In Meta Ads Manager click <b>+ Create</b>, choose <b>${fmt.esc(L.objectives[d.objective] || '')}</b> (“${d.objective === 'OUTCOME_AWARENESS' ? 'Awareness' : d.objective === 'OUTCOME_ENGAGEMENT' ? 'Engagement' : 'Traffic'}”), then copy each item below into the matching box, top to bottom.</p>
      ${[['Campaign name', d.name], ['Daily budget', (daily).toFixed(2)], ['Location', `${d.location || ''} + ${d.radius_km || 5} km`], ['Age', `${d.age_min}–${d.age_max}`],
         ['Website URL', d.final_url], ['Primary text', d.primary_text], ['Headline', d.headline], ['Description', d.description], ['Call to action', L.ctas[d.cta]]]
        .map(([l, v]) => `<div class="kit"><span class="small muted">${l}</span><span class="kv">${fmt.esc(v || '')}</span><button class="btn sm" data-copy="${fmt.esc(v || '')}" type="button">Copy</button></div>`).join('')}
      ${photoUrl ? `<div class="kit"><span class="small muted">Image</span><span class="kv">Chosen photo</span><a class="btn sm" href="${photoUrl}" download="ad-image.jpg">Download</a></div>` : ''}</div>` : '';
  const actions = IS_CLIENT
    ? (c.status === 'awaiting_approval' ? `<div class="approve"><b>Are you happy with this ad?</b><div class="row" style="gap:8px;margin-top:8px"><button class="btn primary" id="okBtn">✓ Approve</button>
        <input id="okNote" placeholder="Or tell us what to change…" style="flex:1"><button class="btn" id="noBtn">Ask for changes</button></div></div>` : '')
    : `<div class="row" style="gap:8px;flex-wrap:wrap">
        ${!ro ? '<button class="btn primary" id="cSave">Save</button>' : ''}
        ${['draft', 'changes_requested'].includes(c.status) ? '<button class="btn" id="cAsk">Ask owner to approve</button>' : ''}
        ${g ? `<a class="btn" href="${base}/campaigns/${c.id}/google-ads-editor.csv">⬇ Google Ads Editor file</a>` : ''}
        ${!['sent', 'live', 'paused'].includes(c.status) ? `<button class="btn" id="cSend" ${L.can_send[c.platform] ? '' : 'disabled title="Connect their ad account first (Connections tab)"'}>🚀 Send to ${g ? 'Google Ads' : 'Meta'} (paused)</button>` : ''}
        ${['sent', 'paused'].includes(c.status) ? '<button class="btn primary" id="cOn">▶ Turn on</button>' : ''}${c.status === 'live' ? '<button class="btn" id="cOff">⏸ Pause</button>' : ''}
        ${c.remote?.url ? `<a class="btn ghost" href="${fmt.esc(c.remote.url)}" target="_blank" rel="noopener">Open in ${g ? 'Google Ads' : 'Ads Manager'} ↗</a>` : ''}
        ${!['sent', 'live', 'paused'].includes(c.status) ? '<button class="btn ghost" id="cDel">Delete</button>' : ''}</div>
      ${!L.can_send[c.platform] && !['sent', 'live', 'paused'].includes(c.status) ? `<div class="small muted" style="margin-top:6px">${g ? 'To launch now: download the Google Ads Editor file, open Google Ads Editor → Account → Import → From file, check the changes, then Post. It arrives paused.' : 'To launch now: use the copy kit below in Meta Ads Manager.'} Direct sending switches on when their ${g ? 'Google Ads' : 'Meta ad'} account is connected (Connections tab).</div>` : ''}`;
  $('#campEditor').innerHTML = `
    <div class="card"><div class="row" style="justify-content:space-between;gap:8px;flex-wrap:wrap"><div><h2 style="margin:0">${fmt.esc(c.name)}</h2>
        <span class="badge ${STATUS_BADGE[c.status] || ''}">${fmt.esc(c.status_label)}</span> <span class="small muted">${g ? 'Google Search' : 'Facebook & Instagram'}</span></div></div>
      ${c.owner_note ? `<div class="callout ${c.status === 'changes_requested' ? 'warn' : ''} small" style="margin-top:8px"><b>Owner's note:</b> ${fmt.esc(c.owner_note)}</div>` : ''}
      <div style="margin-top:10px">${actions}</div></div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card camp-fields">${IS_CLIENT ? `<h2>The ad</h2><div class="small">${g ? `<b>Headlines:</b> ${(d.headlines || []).map(fmt.esc).join(' · ')}<br><br><b>Descriptions:</b> ${(d.descriptions || []).map(fmt.esc).join(' · ')}` : ''}</div>
          <div class="small muted" style="margin-top:8px">Shown to people within ${d.radius_km || 5} km of ${fmt.esc(d.location || 'the business')} · about ${fmt.money(daily)} a day.</div>` : fields}</div>
      <div><div class="card"><h2>Preview</h2>${preview}</div>
        <div class="card" style="margin-top:14px"><h2>Checks ${errs.length ? `<span class="badge bad">${errs.length} to fix</span>` : '<span class="badge good">✓ Ready</span>'}</h2>
          ${[...errs, ...warns, ...info].map(x => `<div class="cchk ${x.level}"><b>${x.level === 'error' ? '✕' : x.level === 'warn' ? '!' : 'i'}</b><span>${fmt.esc(x.message)}</span></div>`).join('') || '<div class="small">No problems found.</div>'}</div>
        ${kit}</div>
    </div>`;
  const reload = async () => R.campaigns();
  $$('[data-copy]').forEach(b => b.onclick = async () => { try { await navigator.clipboard.writeText(b.dataset.copy); toast('Copied'); } catch { toast('Select and copy it manually'); } });
  if (IS_CLIENT) {
    const ok = $('#okBtn'); if (!ok) return;
    ok.onclick = async () => { await api(`${base}/campaigns/${c.id}/review`, { json: { approve: true, note: $('#okNote').value } }); toast('Thanks! Approved.'); reload(); };
    $('#noBtn').onclick = async () => { if (!$('#okNote').value.trim()) return toast('Type what you\'d like changed'); await api(`${base}/campaigns/${c.id}/review`, { json: { approve: false, note: $('#okNote').value } }); toast('Sent to your agency'); reload(); };
    return;
  }
  const collect = () => {
    const b = {};
    $$('#campEditor [data-k]').forEach(i => { b[i.dataset.k] = i.type === 'number' ? +i.value : i.value; });
    ['headlines', 'descriptions'].forEach(k => { b[k] = $$(`#campEditor [data-list="${k}"]`).map(i => i.value).filter(x => x.trim()); });
    $$('#campEditor [data-lines]').forEach(t => { b[t.dataset.lines] = t.value.split('\n').map(x => x.trim()).filter(Boolean); });
    const ph = $('#campEditor input[name=ph]:checked'); if (ph) b.photo_id = +ph.value;
    return b;
  };
  $$('#campEditor [data-list], #campEditor [data-k="primary_text"], #campEditor [data-k="headline"], #campEditor [data-k="description"]').forEach(i => i.oninput = () => {
    const cc = i.parentElement.querySelector('.cc'); const max = +((cc?.textContent || '/0').split('/')[1]); if (cc) { cc.textContent = `${i.value.length}/${max}`; cc.classList.toggle('over', i.value.length > max); } });
  $$('#campEditor .pickph label').forEach(l => l.onclick = () => { $$('#campEditor .pickph label').forEach(x => x.classList.remove('on')); l.classList.add('on'); });
  const save = async (msg = 'Saved') => { const r = await api(`${base}/campaigns/${c.id}`, { method: 'PUT', json: collect() }); toast(msg); return r; };
  const btn = (id, fn) => { const b = $(id); if (b) b.onclick = async () => { b.disabled = true; try { await fn(); } catch (e) { toast(e.message, 9000); } b.disabled = false; reload(); }; };
  btn('#cSave', () => save());
  btn('#cAsk', async () => { await save(); await api(`${base}/campaigns/${c.id}/ask-approval`, { method: 'POST' }); toast('Sent to the owner. They\'ll see it when they log in.', 6000); });
  btn('#cSend', async () => { if (!confirm(`Create this campaign in their ${g ? 'Google Ads' : 'Meta'} account? It arrives PAUSED, so nothing spends until you turn it on.`)) return; await save(); await api(`${base}/campaigns/${c.id}/send`, { method: 'POST' }); toast('Created in their account (paused)', 6000); });
  btn('#cOn', async () => { if (!confirm('Turn the ads on? Their card will start being charged for ad spend.')) return; await api(`${base}/campaigns/${c.id}/switch`, { json: { on: true } }); toast('Ads are running'); });
  btn('#cOff', async () => { await api(`${base}/campaigns/${c.id}/switch`, { json: { on: false } }); toast('Paused'); });
  btn('#cDel', async () => { if (!confirm('Delete this campaign draft?')) return; await api(`${base}/campaigns/${c.id}`, { method: 'DELETE' }); campId = null; });
}

/* ---------------- 7-day trial ---------------- */
R.trial = async () => {
  const t = await api(`${base}/trial`);
  setPeriod(null); $('#periodLabel').textContent = '7-day trial';
  const ro = '', roTask = IS_CLIENT ? 'disabled' : '';
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
  view.innerHTML = `${IS_CLIENT ? '<div class="callout small" style="margin-bottom:12px">✏️ <b>Your part this week:</b> write your goal, add your website, and fill in the <b>Before &amp; after numbers</b> and <b>Google profile checklist</b> below (Day 1 now, Day 7 at the end). We tick off the day-by-day plan as we go.</div>' : ''}
    <div class="card"><div class="row" style="justify-content:space-between;gap:10px;flex-wrap:wrap">
      <div><h2 style="margin:0">Day ${t.day} of 7 <span class="small muted">· ${t.start_date} → ${t.end_date}</span></h2>
        <div class="row" style="gap:8px;margin-top:6px"><div class="bar-track" style="width:220px"><div class="bar-fill" style="width:${pct}%;background:${cssVar('--good')}"></div></div><span class="small">${t.done} of ${t.total} tasks done</span></div></div>
      <div class="row" style="gap:8px;flex-wrap:wrap"><a class="btn primary" href="/clients/${CLIENT.id}/trial-report" target="_blank" rel="noopener">📄 End-of-trial report</a>
        ${IS_CLIENT ? '' : '<button class="btn" id="tLink">Copy report link</button><button class="btn ghost" id="tRestart">Restart</button>'}</div></div>
      <label class="f" style="margin-top:12px">Goal for the week<input id="tGoal" value="${fmt.esc(t.goal || '')}" placeholder="e.g. more flu vaccination bookings and new Google reviews" ${ro}></label></div>

    ${webCard(t, ro)}
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h2>Before &amp; after numbers</h2>
        <p class="small muted">${IS_CLIENT ? 'Please fill in <b>Day 1</b> now and <b>Day 7</b> at the end of the week. Reviews, rating and photos are on your Google Maps listing; calls, directions and website clicks are in your Google Business Profile → Performance. Leave blank anything you can\'t see.' : 'Fill in <b>Day 1</b> now and <b>Day 7</b> at the end (the owner can also fill these in from their login). Reviews, rating and photos are on their Google Maps listing; posts, calls and directions are in their Google Business Profile → Performance (needs Manager access). Leave blank what you can\'t see.'}</p>
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
    <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn primary" id="tSave">Save numbers</button></div>

    <div class="card" style="margin-top:14px"><h2>Day-by-day plan</h2>
      ${days.map(d => `<div class="tday ${d === t.day ? 'today' : ''}"><div class="tdh">Day ${d} · ${DAY_TITLE[d]} ${d === t.day ? '<span class="badge accent">today</span>' : ''}</div>
        ${t.tasks.filter(x => x.day === d).map(x => `<div class="ttask ${x.done ? 'done' : ''}"><label class="row" style="gap:10px;align-items:flex-start;flex-wrap:nowrap">
          <input type="checkbox" data-task="${x.id}" ${x.done ? 'checked' : ''} ${roTask} style="margin-top:3px"><span><b>${fmt.esc(x.title)}</b>${x.help ? `<div class="small muted">${fmt.esc(x.help)}</div>` : ''}</span></label>
          ${IS_CLIENT ? (x.note ? `<div class="small" style="margin-left:26px">${fmt.esc(x.note)}</div>` : '') : `<input class="tnote" data-note="${x.id}" value="${fmt.esc(x.note || '')}" placeholder="Note (optional), e.g. uploaded 14 photos">`}</div>`).join('')}</div>`).join('')}
      ${IS_CLIENT ? '' : `<form id="tAdd" class="row" style="gap:8px;margin-top:10px;align-items:flex-end"><label class="f" style="flex:1">Add your own task<input name="title" required placeholder="e.g. Set up a flu-shot booking page"></label>
        <label class="f">Day<select name="day">${days.map(d => `<option ${d === t.day ? 'selected' : ''}>${d}</option>`).join('')}</select></label><button class="btn">Add</button></form>`}
    </div>`;
  const put = (body, msg) => api(`${base}/trial`, { method: 'PUT', json: body }).then(() => { if (msg) toast(msg); });
  $('#wUrl').onchange = e => put({ website_url: e.target.value }, 'Website saved');
  $('#tGoal').onchange = e => put({ goal: e.target.value }, 'Goal saved');
  $('#tSave').onclick = async () => {
    const body = { baseline: {}, after: {}, checks_before: {}, checks_after: {} };
    $$('[data-s]').forEach(i => { body[i.dataset.s][i.dataset.k] = i.value; });
    $$('[data-c]').forEach(i => { body[i.dataset.c][i.dataset.k] = i.checked; });
    try { await put(body, 'Saved'); route(); } catch (e) { toast(e.message); }
  };
  $$('[data-c]').forEach(i => i.onchange = () => $('#tSave').click());
  if (IS_CLIENT) return;
  $$('[data-wcheck]').forEach(btn => btn.onclick = async () => {
    const which = btn.dataset.wcheck;
    if (!$('#wUrl').value.trim()) return toast('Type their website address first');
    btn.disabled = true; btn.textContent = 'Checking… (up to a minute)';
    try { await put({ website_url: $('#wUrl').value }); await api(`${base}/trial/website/${which}`, { method: 'POST' }); toast('Website checked'); route(); }
    catch (err) { toast(err.message, 8000); btn.disabled = false; btn.textContent = which === 'before' ? 'Check website (Day 1)' : 'Check again (Day 7)'; }
  });
  $$('[data-task]').forEach(cb => cb.onchange = async () => { await put({ tasks: [{ id: cb.dataset.task, done: cb.checked, note: $(`[data-note="${cb.dataset.task}"]`).value }] }); route(); });
  $$('[data-note]').forEach(inp => inp.onchange = () => put({ tasks: [{ id: inp.dataset.note, done: $(`[data-task="${inp.dataset.note}"]`).checked, note: inp.value }] }, 'Note saved'));
  $('#tAdd').onsubmit = async e => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target)); await put({ tasks: [{ new: true, title: f.title, day: +f.day }] }, 'Task added'); route(); };
  $('#tLink').onclick = async () => { const r = await api(`${base}/trial-link`, { method: 'POST' });
    try { await navigator.clipboard.writeText(r.url); toast('Report link copied: paste it into a text or email to the owner', 6000); } catch { prompt('Report link:', r.url); } };
  $('#tRestart').onclick = async () => { if (!confirm('Start the trial again from scratch? All ticks and numbers are cleared.')) return; await api(`${base}/trial/start`, { json: {} }); route(); };
};


function webCard(t, ro) {
  const w = t.website, b = w?.before || {}, a = w?.after || {};
  const ring = (snap, label) => snap.score != null ? `<div class="wshot"><div class="small muted">${label} · ${snap.date}</div>
      <div class="wscore ${snap.score >= 70 ? 'good' : snap.score >= 50 ? 'warn' : 'bad'}">${snap.score}<span>/100</span></div>
      ${snap.screenshot ? `<img src="${snap.screenshot}" alt="${label} on a phone">` : '<div class="small muted" style="margin-top:6px">No phone screenshot (Google speed test didn\'t respond)</div>'}</div>` : '';
  return `<div class="card" style="margin-top:14px"><h2>${IS_CLIENT ? 'Your' : 'Their'} website: before &amp; after</h2>
    <p class="small muted">${IS_CLIENT ? 'Type your website address below. We scan it on day 1, fix what we can during the week, and scan it again on day 7 so you can see the difference.' : ''}</p>
    <p class="small muted" ${IS_CLIENT ? 'hidden' : ''}>Scan the site on day 1, fix what it finds during the week, then scan again on day 7. The report shows the score, a phone screenshot before and after, and everything that was fixed. You'll need access to their website (WordPress, Wix, Squarespace…) or whoever manages it.</p>
    <div class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
      <label class="f" style="flex:1;min-width:220px">${IS_CLIENT ? 'Your website' : 'Their website'}<input id="wUrl" value="${fmt.esc(t.website_url || '')}" placeholder="e.g. eastbentleighpharmacy.com.au" ${ro}></label>
      ${IS_CLIENT ? '' : `<button class="btn ${b.score == null ? 'primary' : ''}" data-wcheck="before">${b.score == null ? 'Check website (Day 1)' : 'Re-check Day 1'}</button>
        <button class="btn ${b.score != null && a.score == null ? 'primary' : ''}" data-wcheck="after" ${b.score == null ? 'disabled' : ''}>Check again (Day 7)</button>`}</div>
    ${w ? `<div class="wcompare">${ring(b, 'Before')}${a.score != null ? `<div class="warrow">→</div>${ring(a, 'After')}` : ''}</div>
      ${w.fixed.length ? `<h3>Fixed this week</h3>${w.fixed.map(c => `<div class="small" style="margin:3px 0">✓ ${fmt.esc(c.title)}</div>`).join('')}` : ''}
      ${w.todo.length ? `<h3>${a.score != null ? 'Still to fix' : 'What to fix this week'} <span class="small muted">(most important first)</span></h3>
        ${w.todo.map(c => `<div class="wtodo"><b>${fmt.esc(c.problem || c.title)}</b><div class="small">${fmt.esc(c.fix)}</div><div class="small muted">${fmt.esc(c.impact)}</div></div>`).join('')}`
        : '<div class="callout small" style="margin-top:10px">No problems found by the scan. Use the tips below to make it look more professional.</div>'}` : ''}
    <details style="margin-top:12px"><summary><b>How to make a pharmacy website look professional</b> <span class="small muted">· 8 quick wins</span></summary>
      ${t.website_tips.map(([h, d]) => `<div class="wtodo"><b>${fmt.esc(h)}</b><div class="small">${fmt.esc(d)}</div></div>`).join('')}</details>
  </div>`;
}

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
        : `<div class="empty">No competitors added yet. Add them below.</div>`}</div>
    </div>
    ${`
    <div class="card" style="margin-top:14px"><h2>Add a month's figures</h2>
      <p class="small muted">${IS_CLIENT ? '✏️ <b>Please fill this in once a month.</b> ' : ''}${GBP_HELP} Takes about 2 minutes a month. Leave a box empty if Google doesn't show it.</p>
      <form id="gbpForm" class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
        <label class="f">Month<input name="month" type="month" value="${editMonth}" style="width:150px"></label>
        ${d.activity.map(([k, l]) => `<label class="f">${l}<input name="${k}" type="number" min="0" value="${cur[k] ?? ''}" style="width:120px"></label>`).join('')}
        <label class="f">Total reviews<input name="reviews_total" type="number" min="0" value="${cur.reviews_total ?? ''}" style="width:110px"></label>
        <label class="f">Rating ★<input name="rating" type="number" min="0" max="5" step="0.1" value="${cur.rating ?? ''}" style="width:90px"></label>
        <button class="btn primary">Save month</button></form></div>
    <div class="card" style="margin-top:14px"><div class="row" style="justify-content:space-between;gap:8px;flex-wrap:wrap"><h2>Competitors to track</h2>
      <div class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
        <label class="f">${IS_CLIENT ? 'What you do' : 'What they do'}<input id="term" value="${fmt.esc(d.search_term)}" placeholder="e.g. pharmacy" style="width:150px"></label>
        <label class="f">Suburb<input id="area" value="${fmt.esc(d.area)}" placeholder="e.g. East Bentleigh VIC" style="width:190px"></label>
        <button class="btn" id="gMaps" type="button">Open in Google Maps ↗</button>
        ${d.places_enabled ? `<button class="btn primary" id="gFind" type="button">Find competitors automatically</button>${comp.list.length ? '<button class="btn" id="gRefresh" type="button">↻ Update their reviews</button>' : ''}` : ''}</div></div>
      <p class="small muted">${d.places_enabled
        ? 'Click “Find competitors automatically” to list the nearest similar businesses with their stars and reviews. Next month, click “Update their reviews” to see who gained how many.'
        : 'Click <b>Open in Google Maps</b>: it searches “' + (IS_CLIENT ? 'what you do' : 'what they do') + ' near suburb”. Type the 3–6 nearest into the rows below: name, star rating and number of reviews (shown under each name on Maps), then click Save.' + (IS_CLIENT ? '' : ' <span class="muted">(Automatic search needs a Google Places key: see DEPLOY.md, Step 6.)</span>')}</p>
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
        ${IS_CLIENT ? '<p class="small"><b>Already advertising yourself?</b> Download a report from your Facebook/Instagram ads, Google Ads or Google Analytics and upload it here so we can see what\'s worked so far. Steps are on the right.</p>' : ''}
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
