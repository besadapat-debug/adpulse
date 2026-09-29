"""Connector framework.

Every connector returns a SyncResult with rows for one or more of the normalised tables.
The sync engine upserts them, so re-pulling a trailing window is idempotent and picks up
platforms' late conversion restatements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import httpx


@dataclass
class SyncResult:
    ad_metrics: list[dict] = field(default_factory=list)
    organic_metrics: list[dict] = field(default_factory=list)
    seo_queries: list[dict] = field(default_factory=list)
    email_metrics: list[dict] = field(default_factory=list)
    engagement_metrics: list[dict] = field(default_factory=list)
    demographics: list[dict] = field(default_factory=list)
    updated_credentials: dict | None = None   # e.g. refreshed OAuth tokens

    def count(self) -> int:
        return len(self.ad_metrics) + len(self.organic_metrics) + len(self.seo_queries) + len(self.email_metrics) + len(self.engagement_metrics) + len(self.demographics)


class ConnectorError(Exception):
    pass


class Connector:
    platform: str = ""
    label: str = ""
    category: str = ""          # paid | organic | seo | analytics | email
    auth: str = "oauth"         # oauth | api_key
    account_hint: str = ""      # what to put in "account id"
    implemented: bool = True    # live API implemented (vs demo-only placeholder)

    def __init__(self, account_id: str, credentials: dict):
        self.account_id = account_id
        self.creds = credentials or {}

    def fetch(self, start: date, end: date) -> SyncResult:  # pragma: no cover - abstract
        raise NotImplementedError

    # helpers
    @staticmethod
    def http() -> httpx.Client:
        return httpx.Client(timeout=60, follow_redirects=True)

    @staticmethod
    def check(resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            raise ConnectorError(f"{resp.status_code}: {resp.text[:400]}")
        try:
            return resp.json()
        except Exception as e:
            raise ConnectorError(f"Non-JSON response: {resp.text[:200]}") from e


def demographic_months(end: date) -> list[tuple[date, date]]:
    """Previous and current calendar month (current one up to `end`): demographics are stored per whole month."""
    from datetime import timedelta
    cur = end.replace(day=1)
    prev = (cur - timedelta(days=1)).replace(day=1)
    return [(prev, cur - timedelta(days=1)), (cur, end)]


def month_end(d: date) -> date:
    import calendar
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def merge_segments(rows: list[dict]) -> list[dict]:
    """Add up rows that share (dimension, segment, month): API rows are per ad group / sub-segment."""
    out: dict[tuple, dict] = {}
    for r in rows:
        k = (r["dimension"], r["segment"], r["date_from"])
        if k not in out:
            out[k] = dict(r)
        else:
            for f in ("spend", "impressions", "reach", "clicks", "conversions", "users", "sessions"):
                if f in r:
                    out[k][f] = out[k].get(f, 0) + r[f]
    return list(out.values())
