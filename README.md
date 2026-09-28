# AdPulse — cross-platform ad tracking & audience intelligence for agencies

One website for every client's paid, organic, SEO and email performance, plus a consent-safe
audience engine that scores first-party intent and pushes hashed audiences to Meta, Google,
TikTok and LinkedIn.

## Run it (2 minutes)

**Windows, easiest:** double-click `start.bat`. It installs the requirements, starts the site and opens http://localhost:8000.

Or from a terminal:

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate      Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
python -m uvicorn app.main:app --reload
```

(Use `python -m uvicorn` rather than plain `uvicorn` — on Windows the Microsoft Store Python doesn't put `uvicorn` on your PATH.)

Open http://localhost:8000 and sign in with **demo@agency.test / demo1234**.

Upgrading from an earlier version? Just run it — new tables and columns are added automatically on start-up.
With `DEMO_MODE=true` the first start seeds an agency with three clients, ~20 demo connections,
120 days of data, 2,100 contacts with behavioural journeys, audiences and alert rules.

Tests: `pip install pytest && python -m pytest tests`

**Put it online for free:** see **[DEPLOY.md](DEPLOY.md)** (Render free plan + Supabase, no command line).

Docker: `docker build -t adpulse . && docker run -p 8000:8000 -v adpulse:/data --env-file .env adpulse`

## What's in it

| Area | Where | Notes |
|---|---|---|
| Multi-client dashboard | `/` | Spend, revenue, ROAS, CPA with period-over-period change, spend sparklines, health, alert feed |
| Paid performance | Client → Paid performance | Daily spend/revenue by platform, platform and campaign tables, target ROAS/CPA flags |
| Web & social | Client → Web & social | GA4 sessions by channel, organic social followers/reach/engagement, Google Business Profile actions |
| SEO | Client → SEO | Search Console queries with intent classification and 7-day position moves; DataForSEO rank tracking |
| Email | Client → Email | Klaviyo / Mailchimp campaign results |
| Attribution | Client → Attribution | Last/first click, linear, position-based, time-decay from **first-party** journeys; platform over-claim ratio |
| Audiences | Client → Audiences | Intent scoring (0–100), segment builder, one-click sync to 4 platforms, hashed CSV export, paid-search gap finder, pixel audience rule templates |
| Budget | Client → Budget | Diminishing-returns curves per channel → reallocation to equalise marginal return, capped per channel |
| Alerts | Client → Alerts, Settings | CPA spike, ROAS drop, spend spike, zero conversions, ranking drop, traffic drop, sync failure → Slack/email |
| White-label reports | "Share report" | Signed 90-day link, client logo/colour/footer, print-to-PDF |
| Compliance | Client → Client settings | Region policy notes, access & erasure requests, audit trail, event retention purge |
| Ad engagement | Client → Ad engagement | Reach, frequency, video views, average watch time, completion rate, thumb-stop rate, shares/saves/comments — per platform and campaign |
| People | Client → People | Full journey for visitors who opted in and identified themselves: which ad/campaign brought them, every page, time on each page, visits, value |
| Companies (B2B) | Client → Companies | Businesses visiting the site (IP → company via IPinfo; set `IPINFO_TOKEN`), pages viewed, time, pricing interest, intent score |
| Prospects & audits | `/prospects` | Website audit + social media audit (profiles auto-found on their site; per-platform scores vs industry/size benchmarks), overall digital score, rank vs businesses you've audited, 3-tier proposal priced from your rate card, AHPRA notes for health businesses, pitch email, pipeline |
| Rate card | Settings → Rate card | Your prices for proposals; scaled by business size, industry and locations |
| Tracking snippet | `/t.js` | Consent-gated first-party events + UTMs + engaged time on page + identify-on-opt-in |

## Connectors

| Platform | Status | Auth |
|---|---|---|
| Meta Ads | **Live** (Insights API, campaign/day) | OAuth, long-lived token |
| Google Ads | **Live** (GAQL searchStream) | OAuth + developer token |
| TikTok Ads | **Live** (integrated report) | OAuth |
| LinkedIn Ads | **Live** (adAnalytics) | OAuth |
| GA4 | **Live** (Data API) | OAuth (Google) |
| Search Console | **Live** (Search Analytics) | OAuth (Google) |
| DataForSEO rank tracking | **Live** | API login |
| Mailchimp, Klaviyo | **Live** | API key |
| X, Pinterest, Snapchat, Reddit, Amazon Ads, Bing Webmaster, Business Profile, organic social, YouTube, HubSpot | Demo data (roadmap) | — |

Each connector is ~50 lines in `app/connectors/`: implement `fetch(start, end)` returning rows for the
normalised tables and register it in `connectors/__init__.py`. Every sync re-pulls a trailing window
(`TRAILING_WINDOW_DAYS`, default 28) and upserts, so platforms' late conversion restatements are picked up.

## Going live — do these first (approvals take weeks)

1. **Google**: Cloud project → OAuth consent screen (External, **In production**) → complete **brand verification**
   (Branding tab: domain, privacy policy, terms) → OAuth client (Web) with redirect `{BASE_URL}/oauth/google/callback` →
   enable Google Ads, Analytics Data and Search Console APIs → on the **Google Ads API page in Cloud Console**, request
   Basic access. (Since Sept 2026 access belongs to the Cloud project; developer tokens are no longer used.)
2. **Meta**: Business app with Marketing API; complete **Business Verification** and **App Review** for
   `ads_read`, `ads_management` (needed for Custom Audiences), `business_management`.
3. **TikTok for Business**: Marketing API developer app (approval required).
4. **LinkedIn**: Advertising API access via the Marketing Developer Platform application.
5. Set `SECRET_KEY`, `BASE_URL` (https), `DEMO_MODE=false`, create your owner via `/setup`.
6. Customer Match / Custom Audience uploads also have **platform-side eligibility rules** (account history,
   policy compliance, accepted customer-list terms). Accept those terms in each ad account before syncing.

API versions (`GOOGLE_ADS_API_VERSION`, `META_API_VERSION`, `LINKEDIN_API_VERSION`) are env vars because every
platform sunsets versions — bump them when you get deprecation emails.

## What you can and can't know about the people who see your ads

- **Ad platforms (Google, Meta, TikTok, LinkedIn):** campaign totals only — impressions, reach, clicks, watch time,
  engagements. None of them reveal which person saw, clicked or watched, or what else they searched. There is no
  lawful way around this, and AdPulse doesn't attempt one.
- **After the click, on your client's site:** with consent, the snippet records pages, time on page and actions. If the
  visitor later identifies themselves with an opt-in, their earlier visits link to them (People tab). Everyone else stays anonymous.
- **B2B:** the business network a visit came from (Companies tab) — the company, never the employee. ISP/mobile/home
  connections are discarded and raw IPs are never stored. Mention company identification in the client's privacy policy.

## The audience engine — what it does and doesn't do

- **Does:** score *consented first-party* contacts (your clients' CRM, checkout opt-ins, forms, and site behaviour
  captured by `/t.js` after consent) by recent high-intent actions; build segments; hash identifiers with SHA-256
  using each platform's normalisation rules; sync to Meta Custom Audiences, Google Customer Match, TikTok and
  LinkedIn Matched Audiences; remove people who withdraw consent or are erased on the next sync.
- **Also does (no personal data):** find high-intent search queries you rank poorly for (paid search coverage) and
  generate pixel/GA4 audience rules the platforms build themselves from anonymous visitors.
- **Doesn't, by design:** scrape or import people from other accounts' followers/commenters, or anyone without a
  consent record. `audiences.members()` enforces `consent_marketing=1 AND deleted_at IS NULL` for every export and
  sync, and a test guards it.

## Architecture

```
app/
  main.py              FastAPI routes: pages, JSON API, OAuth, tracking endpoint
  config.py            env settings        security.py  Fernet vault, PBKDF2 passwords, signed tokens
  db.py                schema + storage layer: SQLite file or Postgres/Supabase via DATABASE_URL
  oauth.py             Google / Meta / TikTok / LinkedIn OAuth + refresh
  connectors/          paid.py, other.py (live) · demo.py (synthetic) · base.py
  services/
    sync.py            windowed upsert sync + in-process scheduler
    metrics.py         dashboard queries, keyword intent classifier
    alerts.py          rules engine + Slack/SMTP
    audiences.py       intent scoring, hashing, platform audience sync, targeting suggestions
    attribution.py     5 attribution models over first-party journeys
    budget.py          response-curve fit + marginal-return allocator
    compliance.py      consent upsert, DSAR access/erasure, retention purge
  templates/, static/  server-rendered shell + vanilla JS views, Chart.js (vendored)
```

Storage is a local SQLite file by default. Set `DATABASE_URL` to a Postgres connection string (e.g. Supabase) and the same
code runs on Postgres. Tables go in a private `adpulse` schema (change with `DB_SCHEMA`), and `SECRET_KEY` becomes mandatory.
For multiple web instances, set `SYNC_INTERVAL_MINUTES=0` and call `/tasks/sync?key=CRON_SECRET` from a scheduler.

## Roadmap suggestions

1. Remaining paid connectors (Pinterest, Reddit, X, Snapchat, Amazon Ads) — same pattern as `paid.py`.
2. Server-side conversions (Meta CAPI, Google Enhanced Conversions, TikTok Events API) fed from `/collect`.
3. Marketing-mix model export (daily spend/outcome CSV for Google Meridian or Meta Robyn) to validate budget advice.
4. Scheduled PDF report emails; client portal logins (viewer role already exists).
5. Competitor visibility via DataForSEO Labs / Semrush API.
