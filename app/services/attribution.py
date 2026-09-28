"""Cross-channel attribution from first-party journeys (tracking snippet + UTMs).

Platforms each claim credit for the same sale; this gives a neutral, de-duplicated view
using your own event stream, under several models side by side."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .. import db

CONVERSION_EVENTS = ("purchase", "lead")


def channel_of(source: str, medium: str) -> str:
    s, m = (source or "").lower(), (medium or "").lower()
    paid = m in ("cpc", "ppc", "paid", "paid_social", "paidsocial", "display", "cpm", "video")
    if not s and not m:
        return "Direct"
    if s in ("google", "adwords") and paid:
        return "Google Ads"
    if s in ("bing", "microsoft") and paid:
        return "Microsoft Ads"
    if s in ("facebook", "instagram", "meta", "fb", "ig"):
        return "Meta Ads" if paid else "Organic Social"
    if s == "tiktok":
        return "TikTok Ads" if paid else "Organic Social"
    if s == "linkedin":
        return "LinkedIn Ads" if paid else "Organic Social"
    if s in ("pinterest", "snapchat", "reddit", "x", "twitter"):
        return f"{s.title()} Ads" if paid else "Organic Social"
    if m == "email" or s in ("klaviyo", "mailchimp", "hubspot", "newsletter"):
        return "Email"
    if m == "organic" or s in ("google", "bing", "duckduckgo", "yahoo"):
        return "Organic Search"
    if m in ("referral", "affiliate", "influencer"):
        return m.title()
    return "Other"


def _credit(path: list[str], model: str, ts: list[datetime], conv_ts: datetime) -> dict[str, float]:
    n = len(path)
    w = [0.0] * n
    if model == "last_click":
        w[-1] = 1
    elif model == "first_click":
        w[0] = 1
    elif model == "linear":
        w = [1 / n] * n
    elif model == "position_based":  # 40/20/40
        if n == 1:
            w = [1]
        elif n == 2:
            w = [0.5, 0.5]
        else:
            w = [0.4] + [0.2 / (n - 2)] * (n - 2) + [0.4]
    elif model == "time_decay":  # 7-day half-life
        raw = [0.5 ** ((conv_ts - t).total_seconds() / 86400 / 7) for t in ts]
        tot = sum(raw)
        w = [r / tot for r in raw]
    out: dict[str, float] = defaultdict(float)
    for ch, x in zip(path, w):
        out[ch] += x
    return out


MODELS = ["last_click", "first_click", "linear", "position_based", "time_decay"]


def attribution(client_id: int, days: int = 30, lookback_days: int = 30) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(days=days)
    evs = db.rows("SELECT contact_id, anon_id, event, value, source, medium, ts FROM events WHERE client_id=? AND ts>=? ORDER BY ts",
                  ((client_id), (since - timedelta(days=lookback_days)).isoformat()))
    journeys: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        key = f"c{e['contact_id']}" if e["contact_id"] else f"a{e['anon_id']}"
        journeys[key].append(e)

    credit = {m: defaultdict(lambda: {"conversions": 0.0, "revenue": 0.0}) for m in MODELS}
    paths: dict[str, int] = defaultdict(int)
    touches, lags, n_conv = [], [], 0
    for evlist in journeys.values():
        touch: list[tuple[str, datetime]] = []
        for e in evlist:
            t = datetime.fromisoformat(e["ts"][:19])
            if e["event"] in CONVERSION_EVENTS:
                if t < since:
                    touch = []
                    continue
                window = [(c, tt) for c, tt in touch if (t - tt).days <= lookback_days] or [("Direct", t)]
                path, ts = [c for c, _ in window], [tt for _, tt in window]
                for m in MODELS:
                    for ch, x in _credit(path, m, ts, t).items():
                        credit[m][ch]["conversions"] += x
                        credit[m][ch]["revenue"] += x * (e["value"] or 0)
                paths[" → ".join(path[-5:])] += 1
                touches.append(len(path))
                lags.append((t - ts[0]).total_seconds() / 86400)
                n_conv += 1
                touch = []
            elif e["source"] or e["medium"]:
                ch = channel_of(e["source"], e["medium"])
                if not touch or touch[-1][0] != ch:   # collapse consecutive same-channel hits
                    touch.append((ch, t))
    channels = sorted({ch for m in MODELS for ch in credit[m]})
    table = [{"channel": ch, **{m: {k: round(v, 2) for k, v in credit[m][ch].items()} for m in MODELS}} for ch in channels]
    table.sort(key=lambda r: -r["position_based"]["revenue"])
    platform_reported = db.one("SELECT SUM(conversions) c FROM ad_metrics WHERE client_id=? AND date>=?", (client_id, since.date().isoformat()))["c"] or 0
    return {
        "days": days, "conversions": n_conv, "table": table, "models": MODELS,
        "top_paths": sorted(({"path": p, "count": c} for p, c in paths.items()), key=lambda r: -r["count"])[:12],
        "avg_touches": round(sum(touches) / len(touches), 2) if touches else 0,
        "avg_days_to_convert": round(sum(lags) / len(lags), 1) if lags else 0,
        "platform_reported_conversions": round(platform_reported, 1),
    }
