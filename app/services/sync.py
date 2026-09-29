"""Sync engine: pulls each connection over a window and upserts into normalised tables."""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone

from .. import db
from ..config import settings
from ..connectors import build
from ..security import decrypt_json, encrypt_json

log = logging.getLogger("adpulse.sync")

UPSERTS = {
    "ad_metrics": ("INSERT INTO ad_metrics (client_id, platform, account_id, campaign_id, campaign_name, campaign_type, date, spend, impressions, clicks, conversions, revenue) "
                   "VALUES (:client_id,:platform,:account_id,:campaign_id,:campaign_name,:campaign_type,:date,:spend,:impressions,:clicks,:conversions,:revenue) "
                   "ON CONFLICT(platform, account_id, campaign_id, date) DO UPDATE SET campaign_name=excluded.campaign_name, spend=excluded.spend, "
                   "impressions=excluded.impressions, clicks=excluded.clicks, conversions=excluded.conversions, revenue=excluded.revenue",
                   {"campaign_type": ""}),
    "organic_metrics": ("INSERT INTO organic_metrics (client_id, platform, dimension, metric, date, value) VALUES (:client_id,:platform,:dimension,:metric,:date,:value) "
                        "ON CONFLICT(client_id, platform, dimension, metric, date) DO UPDATE SET value=excluded.value", {"dimension": ""}),
    "seo_queries": ("INSERT INTO seo_queries (client_id, source, date, query, page, clicks, impressions, position) VALUES (:client_id,:source,:date,:query,:page,:clicks,:impressions,:position) "
                    "ON CONFLICT(client_id, source, date, query, page) DO UPDATE SET clicks=excluded.clicks, impressions=excluded.impressions, position=excluded.position", {"page": ""}),
    "email_metrics": ("INSERT INTO email_metrics (client_id, platform, campaign_id, campaign_name, date, sends, opens, clicks, conversions, revenue) "
                      "VALUES (:client_id,:platform,:campaign_id,:campaign_name,:date,:sends,:opens,:clicks,:conversions,:revenue) "
                      "ON CONFLICT(client_id, platform, campaign_id, date) DO UPDATE SET sends=excluded.sends, opens=excluded.opens, clicks=excluded.clicks, "
                      "conversions=excluded.conversions, revenue=excluded.revenue", {}),
    "engagement_metrics": ("INSERT INTO engagement_metrics (client_id, platform, account_id, campaign_id, date, reach, video_views, video_watch_seconds, video_completions, engagements, shares, saves, comments) "
                           "VALUES (:client_id,:platform,:account_id,:campaign_id,:date,:reach,:video_views,:video_watch_seconds,:video_completions,:engagements,:shares,:saves,:comments) "
                           "ON CONFLICT(platform, account_id, campaign_id, date) DO UPDATE SET reach=excluded.reach, video_views=excluded.video_views, "
                           "video_watch_seconds=excluded.video_watch_seconds, video_completions=excluded.video_completions, engagements=excluded.engagements, "
                           "shares=excluded.shares, saves=excluded.saves, comments=excluded.comments",
                           {"reach": 0, "video_views": 0, "video_watch_seconds": 0, "video_completions": 0, "engagements": 0, "shares": 0, "saves": 0, "comments": 0}),
    "demographics": (("INSERT INTO demographics (client_id, platform, dimension, segment, date_from, date_to, impressions, reach, clicks, spend, conversions, users, sessions, source) "
                     "VALUES (:client_id,:platform,:dimension,:segment,:date_from,:date_to,:impressions,:reach,:clicks,:spend,:conversions,:users,:sessions,:source) "
                     "ON CONFLICT(client_id, platform, dimension, segment, date_from, date_to) DO UPDATE SET impressions=excluded.impressions, reach=excluded.reach, "
                     "clicks=excluded.clicks, spend=excluded.spend, conversions=excluded.conversions, users=excluded.users, sessions=excluded.sessions, source=excluded.source"),
                     {"impressions": 0, "reach": 0, "clicks": 0, "spend": 0, "conversions": 0, "users": 0, "sessions": 0, "source": "api"}),
}


def sync_connection(connection_id: int, full: bool = False) -> dict:
    conn = db.one("SELECT * FROM connections WHERE id=?", (connection_id,))
    if not conn:
        raise ValueError("connection not found")
    client = db.one("SELECT * FROM clients WHERE id=?", (conn["client_id"],))
    end = date.today()
    days = settings.BACKFILL_DAYS if (full or not conn["last_synced_at"]) else settings.TRAILING_WINDOW_DAYS
    start = end - timedelta(days=days - 1)
    started = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    try:
        creds = decrypt_json(conn["credentials_enc"])
        result = build(conn, creds, client).fetch(start, end)
        n = 0
        with db.tx() as c:
            for table, (sql, defaults) in UPSERTS.items():
                batch = []
                for r in getattr(result, table):
                    row = {**defaults, **r, "client_id": conn["client_id"]}
                    row.setdefault("platform", conn["platform"])
                    batch.append(row)
                if batch:
                    c.executemany(sql, batch)
                    n += len(batch)
            if result.updated_credentials:
                c.execute("UPDATE connections SET credentials_enc=? WHERE id=?", (encrypt_json(result.updated_credentials), conn["id"]))
            c.execute("UPDATE connections SET last_synced_at=?, status='active', last_error='' WHERE id=?",
                      (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"), conn["id"]))
            c.execute("INSERT INTO sync_log (connection_id, started_at, finished_at, rows, status) VALUES (?,?,?,?, 'ok')",
                      (conn["id"], started, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"), n))
        return {"ok": True, "rows": n, "window": [str(start), str(end)]}
    except Exception as e:  # keep going for other connections; surface via sync_failure alert
        log.exception("sync failed for connection %s", connection_id)
        msg = str(e)[:500]
        db.execute("UPDATE connections SET status='error', last_error=? WHERE id=?", (msg, conn["id"]))
        db.execute("INSERT INTO sync_log (connection_id, started_at, finished_at, rows, status, message) VALUES (?,?,?,0,'error',?)",
                   (conn["id"], started, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"), msg))
        return {"ok": False, "error": msg}


def sync_client(client_id: int, full: bool = False) -> list[dict]:
    from .alerts import evaluate_client
    out = []
    for c in db.rows("SELECT id FROM connections WHERE client_id=? AND status!='paused'", (client_id,)):
        out.append({"connection_id": c["id"], **sync_connection(c["id"], full)})
    evaluate_client(client_id)
    return out


def sync_all() -> None:
    for cl in db.rows("SELECT id FROM clients"):
        sync_client(cl["id"])
    from .compliance import purge_expired_events
    purge_expired_events()


class Scheduler:
    """Tiny in-process scheduler. For multi-instance deploys, run `python -m app.cli sync`
    from cron instead and set SYNC_INTERVAL_MINUTES=0."""

    def __init__(self):
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def start(self):
        if settings.SYNC_INTERVAL_MINUTES <= 0 or self._t:
            return
        self._t = threading.Thread(target=self._run, daemon=True, name="adpulse-sync")
        self._t.start()

    def _run(self):
        while not self._stop.wait(settings.SYNC_INTERVAL_MINUTES * 60):
            try:
                sync_all()
            except Exception:
                log.exception("scheduled sync failed")

    def stop(self):
        self._stop.set()


scheduler = Scheduler()
