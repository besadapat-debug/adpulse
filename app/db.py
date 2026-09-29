"""Storage: a local SQLite file by default, or Postgres/Supabase when DATABASE_URL is set."""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',          -- owner | member | viewer | client (sees only users.client_id)
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agency (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL DEFAULT 'Your Agency',
  brand_color TEXT DEFAULT '#4f46e5',
  logo_url TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  industry TEXT DEFAULT '',
  currency TEXT DEFAULT 'AUD',
  brand_color TEXT DEFAULT '#0f766e',
  logo_url TEXT DEFAULT '',
  report_title TEXT DEFAULT 'Marketing Performance Report',
  report_footer TEXT DEFAULT '',
  monthly_budget REAL DEFAULT 0,
  target_cpa REAL DEFAULT 0,
  target_roas REAL DEFAULT 0,
  region TEXT DEFAULT 'AU',                      -- drives compliance defaults (AU/EU/US-CA/...)
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS connections (
  id INTEGER PRIMARY KEY,
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
  spend REAL DEFAULT 0,
  impressions INTEGER DEFAULT 0,
  clicks INTEGER DEFAULT 0,
  conversions REAL DEFAULT 0,
  revenue REAL DEFAULT 0,
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
  value REAL DEFAULT 0,
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
  position REAL DEFAULT 0,
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
  conversions REAL DEFAULT 0,
  revenue REAL DEFAULT 0,
  PRIMARY KEY (client_id, platform, campaign_id, date)
);

CREATE TABLE IF NOT EXISTS alert_rules (
  id INTEGER PRIMARY KEY,
  client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,  -- NULL = applies to all clients
  kind TEXT NOT NULL,           -- cpa_spike | roas_drop | spend_spike | zero_conversions | ranking_drop | traffic_drop | sync_failure
  platform TEXT DEFAULT '',     -- '' = all platforms
  threshold REAL NOT NULL,
  window_days INTEGER DEFAULT 3,
  enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY,
  client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
  rule_id INTEGER REFERENCES alert_rules(id) ON DELETE SET NULL,
  dedupe_key TEXT UNIQUE,
  severity TEXT DEFAULT 'warning',               -- info | warning | critical
  title TEXT NOT NULL,
  detail TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  acknowledged INTEGER DEFAULT 0
);

-- First-party contacts. Only rows with consent_marketing=1 and deleted_at IS NULL
-- may ever be uploaded to an ad platform.
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY,
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
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_contact_email ON contacts(client_id, email) WHERE email <> '';

-- First-party behavioural events from the tracking snippet / CRM / email webhooks.
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
  anon_id TEXT DEFAULT '',
  event TEXT NOT NULL,          -- page_view | pricing_view | product_view | add_to_cart | form_start | lead | email_click | purchase ...
  url TEXT DEFAULT '',
  value REAL DEFAULT 0,
  source TEXT DEFAULT '',       -- utm_source / referrer-derived channel
  medium TEXT DEFAULT '',
  campaign TEXT DEFAULT '',
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_client_ts ON events(client_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_anon ON events(client_id, anon_id);

CREATE TABLE IF NOT EXISTS audiences (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  definition TEXT NOT NULL,     -- JSON: {"min_score":70,"max_score":100,"include_customers":false,"lookback_days":30,"events":[...]}
  size INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audience_syncs (
  id INTEGER PRIMARY KEY,
  audience_id INTEGER NOT NULL REFERENCES audiences(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  external_id TEXT DEFAULT '',
  uploaded INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending',
  detail TEXT DEFAULT '',
  synced_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY,
  connection_id INTEGER REFERENCES connections(id) ON DELETE CASCADE,
  started_at TEXT,
  finished_at TEXT,
  rows INTEGER DEFAULT 0,
  status TEXT,
  message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY,
  user_email TEXT DEFAULT '',
  action TEXT NOT NULL,
  detail TEXT DEFAULT '',
  ts TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,
  client_id INTEGER,
  platform TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Attention/engagement per campaign per day (aggregates only — platforms never expose individuals).
CREATE TABLE IF NOT EXISTS engagement_metrics (
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  date TEXT NOT NULL,
  reach INTEGER DEFAULT 0,               -- unique people reached that day (not additive across days)
  video_views INTEGER DEFAULT 0,          -- platform's own definition (Meta 3s plays, TikTok 2s+ plays, YouTube TrueView views)
  video_watch_seconds REAL DEFAULT 0,     -- total seconds watched (= avg watch time × plays)
  video_completions INTEGER DEFAULT 0,    -- 100% / ThruPlay-style completions
  engagements INTEGER DEFAULT 0,          -- likes + comments + shares + saves + clicks on the post
  shares INTEGER DEFAULT 0,
  saves INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  PRIMARY KEY (platform, account_id, campaign_id, date)
);

-- Businesses (not people) identified from website visits via an IP-to-company provider.
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  name TEXT DEFAULT '',
  industry TEXT DEFAULT '',
  employees TEXT DEFAULT '',
  city TEXT DEFAULT '',
  first_seen TEXT,
  last_seen TEXT,
  UNIQUE (client_id, domain)
);

-- IP lookups are cached by a salted hash; raw IP addresses are never stored.
CREATE TABLE IF NOT EXISTS ip_company_cache (
  ip_hash TEXT PRIMARY KEY,
  company_json TEXT,
  looked_up_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prospects (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL,
  domain TEXT NOT NULL,
  name TEXT DEFAULT '',
  score INTEGER DEFAULT 0,
  report TEXT NOT NULL,                  -- JSON audit result
  status TEXT DEFAULT 'new',             -- new | contacted | meeting | won | lost
  notes TEXT DEFAULT '',
  is_example INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Who saw/clicked the ads and who visited the site: group totals only (age, gender, region, city), never individuals.
-- One row per segment per period (usually a calendar month). Filled by connectors or uploaded reports.
CREATE TABLE IF NOT EXISTS demographics (
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,                -- meta_ads | google_ads | ga4
  dimension TEXT NOT NULL,               -- age | gender | age_gender | region | city
  segment TEXT NOT NULL,                 -- e.g. 25-34, female, Victoria, Bentleigh East
  date_from TEXT NOT NULL,
  date_to TEXT NOT NULL,
  impressions INTEGER DEFAULT 0,
  reach INTEGER DEFAULT 0,
  clicks INTEGER DEFAULT 0,
  spend REAL DEFAULT 0,
  conversions REAL DEFAULT 0,
  users REAL DEFAULT 0,
  sessions REAL DEFAULT 0,
  source TEXT DEFAULT 'api',             -- api | upload | demo
  PRIMARY KEY (client_id, platform, dimension, segment, date_from, date_to)
);

-- Monthly snapshot of nearby competitors' Google rating and review count.
CREATE TABLE IF NOT EXISTS local_competitors (
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  month TEXT NOT NULL,                   -- YYYY-MM
  name TEXT NOT NULL,
  rating REAL,
  reviews INTEGER,
  PRIMARY KEY (client_id, month, name)
);

CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  filename TEXT DEFAULT '',
  kind TEXT DEFAULT '',
  platform TEXT DEFAULT '',
  rows INTEGER DEFAULT 0,
  period_from TEXT DEFAULT '',
  period_to TEXT DEFAULT '',
  created_by TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO agency (id, name) VALUES (1, 'Your Agency');
"""

# additive column migrations for databases created by earlier versions
MIGRATIONS = [
    "ALTER TABLE events ADD COLUMN duration_sec REAL DEFAULT 0",
    "ALTER TABLE events ADD COLUMN company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_events_company ON events(client_id, company_id)",
    "CREATE INDEX IF NOT EXISTS ix_events_contact ON events(contact_id)",
    "ALTER TABLE agency ADD COLUMN rate_card TEXT DEFAULT ''",
    "ALTER TABLE agency ADD COLUMN contact_name TEXT DEFAULT ''",
    "ALTER TABLE agency ADD COLUMN phone TEXT DEFAULT ''",
    "ALTER TABLE agency ADD COLUMN email TEXT DEFAULT ''",
    "ALTER TABLE agency ADD COLUMN website TEXT DEFAULT ''",
    "ALTER TABLE clients ADD COLUMN area TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE",
]

_lock = threading.RLock()
_initialised: set[str] = set()

# ---------------------------------------------------------------------------
# Backend selection: SQLite file by default; Postgres (e.g. Supabase) when
# DATABASE_URL is set. All app SQL is written once, SQLite-style with "?"
# placeholders, and translated here for Postgres.
# ---------------------------------------------------------------------------
IS_PG = bool(settings.DATABASE_URL)

# tables with an auto "id" column: INSERTs into these get RETURNING id on Postgres
_ID_TABLES = {"users", "clients", "connections", "alert_rules", "alerts", "contacts", "events", "audiences",
              "audience_syncs", "sync_log", "audit_log", "companies", "prospects"}


def _pg_schema() -> str:
    sql = re.sub(r"PRAGMA[^\n]*\n", "", SCHEMA)
    sql = re.sub(r"\bid INTEGER PRIMARY KEY\b(?! CHECK)", "id BIGSERIAL PRIMARY KEY", sql)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)
    sql = sql.replace("INSERT OR IGNORE INTO agency (id, name) VALUES (1, 'Your Agency');",
                      "INSERT INTO agency (id, name) VALUES (1, 'Your Agency') ON CONFLICT DO NOTHING;")
    return sql


def _pg_sql(sql: str, named: bool = False) -> str:
    sql = sql.replace("%", "%%")
    if named:
        sql = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", r"%(\1)s", sql)
    else:
        sql = sql.replace("?", "%s")
    m = re.match(r"\s*INSERT OR REPLACE INTO (\w+) \(([^)]*)\)(.*)$", sql, re.S)
    if m:  # upsert on the table's first column (its primary key)
        cols = [c.strip() for c in m.group(2).split(",")]
        sets = ", ".join(f"{c}=excluded.{c}" for c in cols[1:])
        sql = f"INSERT INTO {m.group(1)} ({m.group(2)}){m.group(3)} ON CONFLICT ({cols[0]}) DO UPDATE SET {sets}"
    elif re.match(r"\s*INSERT OR IGNORE", sql):
        sql = sql.replace("INSERT OR IGNORE", "INSERT", 1) + " ON CONFLICT DO NOTHING"
    return sql


class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid = cur, lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _PgConn:
    """Minimal sqlite3.Connection look-alike over a pooled psycopg connection."""

    def __init__(self, pool):
        self._pool = pool
        self._c = pool.getconn()

    def execute(self, sql, params=()):
        named = isinstance(params, dict)
        q = _pg_sql(sql, named)
        m = re.match(r"\s*INSERT INTO (\w+)", q)
        want_id = bool(m and m.group(1) in _ID_TABLES and "RETURNING" not in q.upper())
        if want_id:
            q += " RETURNING id"
        cur = self._c.execute(q, params if params else None)
        rid = None
        if want_id:
            row = cur.fetchone()
            rid = row["id"] if row else None
        return _PgCursor(cur, rid)

    def executemany(self, sql, seq):
        seq = list(seq)
        if not seq:
            return
        named = isinstance(seq[0], dict)
        with self._c.cursor() as cur:
            cur.executemany(_pg_sql(sql, named), seq)

    def executescript(self, script):
        self._c.execute(script)

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        if self._c is not None:
            try:
                self._c.rollback()
            except Exception:
                pass
            self._pool.putconn(self._c)
            self._c = None


_pg_pool = None


def _pool():
    global _pg_pool
    if _pg_pool is None:
        with _lock:
            if _pg_pool is None:
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool
                schema = re.sub(r"\W", "", os.getenv("DB_SCHEMA", "adpulse")) or "adpulse"

                # Private schema: Supabase's auto-generated web API only exposes "public".
                import psycopg
                from .config import redact
                try:
                    with psycopg.connect(settings.DATABASE_URL, autocommit=True, prepare_threshold=None) as c0:
                        c0.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                except Exception as e:  # never print the database password into logs
                    raise RuntimeError(f"Could not connect to the database: {redact(e)}") from None

                def configure(conn):
                    conn.execute(f"SET search_path TO {schema}")
                    conn.commit()

                _pg_pool = ConnectionPool(
                    settings.DATABASE_URL, min_size=1, max_size=int(os.getenv("DB_POOL_SIZE", "5")), open=True,
                    configure=configure,
                    # prepare_threshold=None keeps it compatible with Supabase's connection poolers
                    kwargs={"row_factory": dict_row, "prepare_threshold": None, "autocommit": False})
    return _pg_pool


def _path() -> str:
    p = settings.DATABASE_PATH
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect_pg():
    conn = _PgConn(_pool())
    if "pg" not in _initialised:
        with _lock:
            if "pg" not in _initialised:
                conn.executescript(_pg_schema())
                for m in MIGRATIONS:
                    conn.execute(m.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS").replace(" REAL ", " DOUBLE PRECISION "))
                conn.commit()
                _initialised.add("pg")
    return conn


def connect():
    if IS_PG:
        return _connect_pg()
    path = _path()
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if path not in _initialised:
        with _lock:
            conn.executescript(SCHEMA)
            for m in MIGRATIONS:
                try:
                    conn.execute(m)
                except sqlite3.OperationalError:
                    pass  # already applied
            conn.commit()
            _initialised.add(path)
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(sql: str, params: tuple | list = ()) -> list[dict]:
    with tx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict | None:
    with tx() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql: str, params: tuple | list = ()) -> int:
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def audit(user_email: str, action: str, detail: str = "") -> None:
    execute("INSERT INTO audit_log (user_email, action, detail) VALUES (?,?,?)", (user_email, action, detail))
