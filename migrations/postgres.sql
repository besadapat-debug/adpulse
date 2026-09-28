-- Postgres / Supabase version of the schema (app/db.py is the SQLite source of truth).
-- To move to Postgres: apply this file, swap app/db.py's sqlite3 calls for psycopg
-- (the SQL uses ? placeholders — change to %s) and copy data across with pgloader.
-- On Supabase, enable Row Level Security per table if you expose it to client-side keys.


CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',          -- owner | member | viewer
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agency (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL DEFAULT 'Your Agency',
  brand_color TEXT DEFAULT '#4f46e5',
  logo_url TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS clients (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  industry TEXT DEFAULT '',
  currency TEXT DEFAULT 'AUD',
  brand_color TEXT DEFAULT '#0f766e',
  logo_url TEXT DEFAULT '',
  report_title TEXT DEFAULT 'Marketing Performance Report',
  report_footer TEXT DEFAULT '',
  monthly_budget DOUBLE PRECISION DEFAULT 0,
  target_cpa DOUBLE PRECISION DEFAULT 0,
  target_roas DOUBLE PRECISION DEFAULT 0,
  region TEXT DEFAULT 'AU',                      -- drives compliance defaults (AU/EU/US-CA/...)
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS connections (
  id BIGSERIAL PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  account_name TEXT DEFAULT '',
  credentials_enc TEXT DEFAULT '',                -- Fernet-encrypted JSON (tokens / api keys)
  is_demo INTEGER DEFAULT 0,
  status TEXT DEFAULT 'active',                  -- active | error | paused
  last_synced_at TEXT,
  last_error TEXT DEFAULT '',
  UNIQUE (client_id, platform, account_id)
);

-- Paid media, one row per campaign per day. Re-pulled over a trailing window (upsert).
CREATE TABLE IF NOT EXISTS ad_metrics (
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  campaign_name TEXT,
  campaign_type TEXT DEFAULT '',
  date TEXT NOT NULL,
  spend DOUBLE PRECISION DEFAULT 0,
  impressions INTEGER DEFAULT 0,
  clicks INTEGER DEFAULT 0,
  conversions DOUBLE PRECISION DEFAULT 0,
  revenue DOUBLE PRECISION DEFAULT 0,
  PRIMARY KEY (platform, account_id, campaign_id, date)
);
CREATE INDEX IF NOT EXISTS ix_ad_client_date ON ad_metrics(client_id, date);

-- Organic social + web analytics: long/narrow so any platform metric fits.
CREATE TABLE IF NOT EXISTS organic_metrics (
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  dimension TEXT NOT NULL DEFAULT '',            -- e.g. channel group, post id
  metric TEXT NOT NULL,
  date TEXT NOT NULL,
  value DOUBLE PRECISION DEFAULT 0,
  PRIMARY KEY (client_id, platform, dimension, metric, date)
);

CREATE TABLE IF NOT EXISTS seo_queries (
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  source TEXT NOT NULL DEFAULT 'gsc',
  date TEXT NOT NULL,
  query TEXT NOT NULL,
  page TEXT NOT NULL DEFAULT '',
  clicks INTEGER DEFAULT 0,
  impressions INTEGER DEFAULT 0,
  position DOUBLE PRECISION DEFAULT 0,
  PRIMARY KEY (client_id, source, date, query, page)
);

CREATE TABLE IF NOT EXISTS email_metrics (
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  campaign_name TEXT,
  date TEXT NOT NULL,
  sends INTEGER DEFAULT 0,
  opens INTEGER DEFAULT 0,
  clicks INTEGER DEFAULT 0,
  conversions DOUBLE PRECISION DEFAULT 0,
  revenue DOUBLE PRECISION DEFAULT 0,
  PRIMARY KEY (client_id, platform, campaign_id, date)
);

CREATE TABLE IF NOT EXISTS alert_rules (
  id BIGSERIAL PRIMARY KEY,
  client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,  -- NULL = applies to all clients
  kind TEXT NOT NULL,           -- cpa_spike | roas_drop | spend_spike | zero_conversions | ranking_drop | traffic_drop | sync_failure
  platform TEXT DEFAULT '',     -- '' = all platforms
  threshold DOUBLE PRECISION NOT NULL,
  window_days INTEGER DEFAULT 3,
  enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerts (
  id BIGSERIAL PRIMARY KEY,
  client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
  rule_id INTEGER REFERENCES alert_rules(id) ON DELETE SET NULL,
  dedupe_key TEXT UNIQUE,
  severity TEXT DEFAULT 'warning',               -- info | warning | critical
  title TEXT NOT NULL,
  detail TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT now(),
  acknowledged INTEGER DEFAULT 0
);

-- First-party contacts. Only rows with consent_marketing=1 and deleted_at IS NULL
-- may ever be uploaded to an ad platform.
CREATE TABLE IF NOT EXISTS contacts (
  id BIGSERIAL PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  external_id TEXT DEFAULT '',
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  first_name TEXT DEFAULT '',
  last_name TEXT DEFAULT '',
  country TEXT DEFAULT '',
  postcode TEXT DEFAULT '',
  consent_marketing INTEGER DEFAULT 0,
  consent_source TEXT DEFAULT '',
  consent_at TEXT,
  is_customer INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_contact_email ON contacts(client_id, email) WHERE email <> '';

-- First-party behavioural events from the tracking snippet / CRM / email webhooks.
CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
  anon_id TEXT DEFAULT '',
  event TEXT NOT NULL,          -- page_view | pricing_view | product_view | add_to_cart | form_start | lead | email_click | purchase ...
  url TEXT DEFAULT '',
  value DOUBLE PRECISION DEFAULT 0,
  source TEXT DEFAULT '',       -- utm_source / referrer-derived channel
  medium TEXT DEFAULT '',
  campaign TEXT DEFAULT '',
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_client_ts ON events(client_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_anon ON events(client_id, anon_id);

CREATE TABLE IF NOT EXISTS audiences (
  id BIGSERIAL PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  definition TEXT NOT NULL,     -- JSON: {"min_score":70,"max_score":100,"include_customers":false,"lookback_days":30,"events":[...]}
  size INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audience_syncs (
  id BIGSERIAL PRIMARY KEY,
  audience_id INTEGER NOT NULL REFERENCES audiences(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  external_id TEXT DEFAULT '',
  uploaded INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending',
  detail TEXT DEFAULT '',
  synced_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sync_log (
  id BIGSERIAL PRIMARY KEY,
  connection_id INTEGER REFERENCES connections(id) ON DELETE CASCADE,
  started_at TEXT,
  finished_at TEXT,
  rows INTEGER DEFAULT 0,
  status TEXT,
  message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  user_email TEXT DEFAULT '',
  action TEXT NOT NULL,
  detail TEXT DEFAULT '',
  ts TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,
  client_id INTEGER,
  platform TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO agency (id, name) VALUES (1, 'Your Agency') ON CONFLICT DO NOTHING;
