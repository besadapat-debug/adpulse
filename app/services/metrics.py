"""Read-side queries powering dashboards and reports."""
from __future__ import annotations

from datetime import date, timedelta

from .. import db
from ..connectors import label


def period(days: int = 30, end: date | None = None) -> tuple[str, str, str, str]:
    end = end or date.today()
    start = end - timedelta(days=days - 1)
    pend = start - timedelta(days=1)
    pstart = pend - timedelta(days=days - 1)
    return str(start), str(end), str(pstart), str(pend)


def _ratio(a, b):
    return round(a / b, 4) if b else None


def _kpis(r: dict) -> dict:
    r = {k: (v or 0) for k, v in r.items()}
    return {**r, "roas": _ratio(r["revenue"], r["spend"]), "cpa": _ratio(r["spend"], r["conversions"]),
            "ctr": _ratio(r["clicks"], r["impressions"]), "cpc": _ratio(r["spend"], r["clicks"])}


PAID_SUM = "SUM(spend) spend, SUM(impressions) impressions, SUM(clicks) clicks, SUM(conversions) conversions, SUM(revenue) revenue"


def paid_totals(client_id: int, start: str, end: str) -> dict:
    return _kpis(db.one(f"SELECT {PAID_SUM} FROM ad_metrics WHERE client_id=? AND date BETWEEN ? AND ?", (client_id, start, end)))


def change(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / prev, 4)


def agency_overview(days: int = 30) -> list[dict]:
    s, e, ps, pe = period(days)
    out = []
    for c in db.rows("SELECT * FROM clients ORDER BY name"):
        cur, prev = paid_totals(c["id"], s, e), paid_totals(c["id"], ps, pe)
        sessions = db.one("SELECT SUM(value) v FROM organic_metrics WHERE client_id=? AND platform='ga4' AND metric='sessions' AND date BETWEEN ? AND ?",
                          (c["id"], s, e))["v"] or 0
        out.append({
            "client": c, "spend": cur["spend"], "revenue": cur["revenue"], "conversions": cur["conversions"],
            "roas": cur["roas"], "cpa": cur["cpa"], "sessions": sessions,
            "spend_change": change(cur["spend"], prev["spend"]), "roas_change": change(cur["roas"], prev["roas"]),
            "cpa_change": change(cur["cpa"], prev["cpa"]),
            "open_alerts": db.one("SELECT COUNT(*) n FROM alerts WHERE client_id=? AND acknowledged=0", (c["id"],))["n"],
            "connections": db.one("SELECT COUNT(*) n FROM connections WHERE client_id=?", (c["id"],))["n"],
            "errors": db.one("SELECT COUNT(*) n FROM connections WHERE client_id=? AND status='error'", (c["id"],))["n"],
            "spark": [r["spend"] for r in db.rows(
                "SELECT date, SUM(spend) spend FROM ad_metrics WHERE client_id=? AND date BETWEEN ? AND ? GROUP BY date ORDER BY date", (c["id"], s, e))],
        })
    return out


def client_performance(client_id: int, days: int = 30) -> dict:
    s, e, ps, pe = period(days)
    cur, prev = paid_totals(client_id, s, e), paid_totals(client_id, ps, pe)
    by_platform = []
    for r in db.rows(f"SELECT platform, {PAID_SUM} FROM ad_metrics WHERE client_id=? AND date BETWEEN ? AND ? GROUP BY platform ORDER BY spend DESC",
                     (client_id, s, e)):
        p = db.one(f"SELECT {PAID_SUM} FROM ad_metrics WHERE client_id=? AND platform=? AND date BETWEEN ? AND ?", (client_id, r["platform"], ps, pe))
        k, pk = _kpis(r), _kpis(p)
        by_platform.append({**k, "label": label(r["platform"]), "spend_change": change(k["spend"], pk["spend"]),
                            "roas_change": change(k["roas"], pk["roas"]), "cpa_change": change(k["cpa"], pk["cpa"])})
    campaigns = [dict(_kpis(r), label=label(r["platform"])) for r in db.rows(
        f"SELECT platform, campaign_id, MAX(campaign_name) campaign_name, {PAID_SUM} FROM ad_metrics WHERE client_id=? AND date BETWEEN ? AND ? "
        "GROUP BY platform, campaign_id ORDER BY spend DESC", (client_id, s, e))]
    daily = db.rows("SELECT date, platform, SUM(spend) spend, SUM(revenue) revenue, SUM(conversions) conversions FROM ad_metrics "
                    "WHERE client_id=? AND date BETWEEN ? AND ? GROUP BY date, platform ORDER BY date", (client_id, s, e))
    return {"period": [s, e], "prev_period": [ps, pe], "totals": cur, "prev_totals": prev,
            "changes": {k: change(cur[k], prev[k]) for k in ("spend", "revenue", "conversions", "roas", "cpa", "ctr", "cpc")},
            "by_platform": by_platform, "campaigns": campaigns, "daily": daily}


def client_organic(client_id: int, days: int = 30) -> dict:
    s, e, ps, pe = period(days)
    channels = db.rows("SELECT dimension channel, SUM(CASE WHEN metric='sessions' THEN value END) sessions, "
                       "SUM(CASE WHEN metric='keyEvents' THEN value END) key_events, SUM(CASE WHEN metric='totalRevenue' THEN value END) revenue "
                       "FROM organic_metrics WHERE client_id=? AND platform='ga4' AND date BETWEEN ? AND ? GROUP BY dimension ORDER BY sessions DESC",
                       (client_id, s, e))
    for ch in channels:
        p = db.one("SELECT SUM(value) v FROM organic_metrics WHERE client_id=? AND platform='ga4' AND metric='sessions' AND dimension=? AND date BETWEEN ? AND ?",
                   (client_id, ch["channel"], ps, pe))["v"]
        ch["sessions_change"] = change(ch["sessions"], p)
    daily_sessions = db.rows("SELECT date, SUM(value) sessions FROM organic_metrics WHERE client_id=? AND platform='ga4' AND metric='sessions' "
                             "AND date BETWEEN ? AND ? GROUP BY date ORDER BY date", (client_id, s, e))
    social = []
    for p in db.rows("SELECT DISTINCT platform FROM organic_metrics WHERE client_id=? AND platform!='ga4'", (client_id,)):
        pl = p["platform"]
        agg = {r["metric"]: r["v"] for r in db.rows(
            "SELECT metric, SUM(value) v FROM organic_metrics WHERE client_id=? AND platform=? AND date BETWEEN ? AND ? GROUP BY metric", (client_id, pl, s, e))}
        first = db.one("SELECT value FROM organic_metrics WHERE client_id=? AND platform=? AND metric='followers' AND date>=? ORDER BY date LIMIT 1", (client_id, pl, s))
        last = db.one("SELECT value FROM organic_metrics WHERE client_id=? AND platform=? AND metric='followers' AND date<=? ORDER BY date DESC LIMIT 1", (client_id, pl, e))
        social.append({"platform": pl, "label": label(pl), "metrics": agg,
                       "followers": last["value"] if last else None,
                       "follower_growth": (last["value"] - first["value"]) if first and last else None,
                       "engagement_rate": _ratio(agg.get("engagements", 0), agg.get("reach", 0))})
    return {"period": [s, e], "channels": channels, "daily_sessions": daily_sessions, "social": social}


def client_seo(client_id: int, days: int = 28) -> dict:
    s, e, ps, pe = period(days)
    q = ("SELECT query, SUM(clicks) clicks, SUM(impressions) impressions, "
         "SUM(position*impressions)/NULLIF(SUM(impressions),0) position FROM seo_queries WHERE client_id=? AND source=? AND date BETWEEN ? AND ? GROUP BY query")
    cur = {r["query"]: r for r in db.rows(q, (client_id, "gsc", s, e))}
    prev = {r["query"]: r for r in db.rows(q, (client_id, "gsc", ps, pe))}
    # last 7 vs previous 7 days for position movement (what alerts watch)
    recent = {r["query"]: r for r in db.rows(q, (client_id, "gsc", str(date.today() - timedelta(days=6)), str(date.today())))}
    before = {r["query"]: r for r in db.rows(q, (client_id, "gsc", str(date.today() - timedelta(days=13)), str(date.today() - timedelta(days=7))))}
    queries = []
    for k, r in cur.items():
        r = dict(r)
        r["ctr"] = _ratio(r["clicks"], r["impressions"])
        r["clicks_change"] = change(r["clicks"], (prev.get(k) or {}).get("clicks"))
        if k in recent and k in before and recent[k]["position"] and before[k]["position"]:
            r["position_7d_delta"] = round(recent[k]["position"] - before[k]["position"], 1)
        else:
            r["position_7d_delta"] = None
        r["intent"] = classify_intent(k)
        queries.append(r)
    queries.sort(key=lambda r: -(r["clicks"] or 0))
    tot = db.one("SELECT SUM(clicks) clicks, SUM(impressions) impressions, SUM(position*impressions)/NULLIF(SUM(impressions),0) position "
                 "FROM seo_queries WHERE client_id=? AND source='gsc' AND date BETWEEN ? AND ?", (client_id, s, e))
    ptot = db.one("SELECT SUM(clicks) clicks FROM seo_queries WHERE client_id=? AND source='gsc' AND date BETWEEN ? AND ?", (client_id, ps, pe))
    daily = db.rows("SELECT date, SUM(clicks) clicks, SUM(impressions) impressions FROM seo_queries WHERE client_id=? AND source='gsc' "
                    "AND date BETWEEN ? AND ? GROUP BY date ORDER BY date", (client_id, s, e))
    ranks = db.rows("SELECT query, position, date FROM seo_queries WHERE client_id=? AND source='rank' AND date=(SELECT MAX(date) FROM seo_queries WHERE client_id=? AND source='rank') ORDER BY position",
                    (client_id, client_id))
    return {"period": [s, e], "totals": {**tot, "ctr": _ratio(tot["clicks"] or 0, tot["impressions"] or 0),
                                         "clicks_change": change(tot["clicks"], ptot["clicks"])},
            "queries": queries[:100], "daily": daily, "rank_tracking": ranks}


def client_email(client_id: int, days: int = 30) -> dict:
    s, e, _, _ = period(days)
    camps = db.rows("SELECT platform, campaign_name, date, sends, opens, clicks, conversions, revenue FROM email_metrics "
                    "WHERE client_id=? AND date BETWEEN ? AND ? ORDER BY date DESC", (client_id, s, e))
    t = db.one("SELECT SUM(sends) sends, SUM(opens) opens, SUM(clicks) clicks, SUM(conversions) conversions, SUM(revenue) revenue "
               "FROM email_metrics WHERE client_id=? AND date BETWEEN ? AND ?", (client_id, s, e))
    t = {k: v or 0 for k, v in t.items()}
    return {"period": [s, e], "campaigns": camps,
            "totals": {**t, "open_rate": _ratio(t["opens"], t["sends"]), "click_rate": _ratio(t["clicks"], t["sends"]),
                       "rev_per_send": _ratio(t["revenue"], t["sends"])}}


# ---- keyword intent (used for SEO view and for targeting suggestions) ----
TRANSACTIONAL = ("buy", "price", "pricing", "cost", "discount", "coupon", "deal", "sale", "order", "near me", "hire", "quote", "book", "cheap")
COMMERCIAL = ("best", "top", "review", "reviews", " vs ", "compare", "comparison", "alternative", "alternatives")
INFORMATIONAL = ("how", "what", "why", "when", "guide", "tips", "ideas", "plan", "learn", "tutorial")


def classify_intent(q: str) -> str:
    ql = f" {q.lower()} "
    if any(t in ql for t in TRANSACTIONAL):
        return "transactional"
    if any(t in ql for t in COMMERCIAL):
        return "commercial"
    if any(ql.strip().startswith(t) or f" {t} " in ql for t in INFORMATIONAL):
        return "informational"
    return "navigational" if len(q.split()) <= 2 else "commercial"


# ---- attention & engagement (campaign-level aggregates) ----
ENG_SUM = ("SUM(e.reach) reach, SUM(e.video_views) video_views, SUM(e.video_watch_seconds) watch_sec, SUM(e.video_completions) completions, "
           "SUM(e.engagements) engagements, SUM(e.shares) shares, SUM(e.saves) saves, SUM(e.comments) comments")


def _eng_row(r: dict) -> dict:
    r = {k: (v if v is not None else 0) for k, v in r.items()}
    imp = r.get("impressions") or 0
    return {**r,
            "avg_daily_frequency": _ratio(imp, r["reach"]) if r["reach"] else None,
            "thumb_stop_rate": _ratio(r["video_views"], imp) if r["video_views"] else None,     # video views ÷ impressions
            "avg_watch_sec": round(r["watch_sec"] / r["video_views"], 1) if r["video_views"] else None,
            "completion_rate": _ratio(r["completions"], r["video_views"]) if r["video_views"] else None,
            "engagement_rate": _ratio(r["engagements"], imp) if r["engagements"] else None}


def client_engagement(client_id: int, days: int = 30) -> dict:
    s, e, _, _ = period(days)
    imp = {(r["platform"], r["campaign_id"]): r for r in db.rows(
        "SELECT platform, campaign_id, MAX(campaign_name) campaign_name, SUM(impressions) impressions, SUM(clicks) clicks, SUM(spend) spend FROM ad_metrics "
        "WHERE client_id=? AND date BETWEEN ? AND ? GROUP BY platform, campaign_id", (client_id, s, e))}
    camps = []
    for r in db.rows(f"SELECT e.platform, e.campaign_id, {ENG_SUM} FROM engagement_metrics e WHERE e.client_id=? AND e.date BETWEEN ? AND ? "
                     "GROUP BY e.platform, e.campaign_id", (client_id, s, e)):
        base = imp.get((r["platform"], r["campaign_id"]), {})
        row = _eng_row({**r, "impressions": base.get("impressions", 0), "campaign_name": base.get("campaign_name", r["campaign_id"]),
                        "spend": base.get("spend", 0), "label": label(r["platform"])})
        row["cost_per_view"] = _ratio(row["spend"], row["video_views"]) if row["video_views"] else None
        camps.append(row)
    by_p: dict[str, dict] = {}
    for c in camps:
        p = by_p.setdefault(c["platform"], {"platform": c["platform"], "label": c["label"], **{k: 0 for k in
                           ("impressions", "reach", "video_views", "watch_sec", "completions", "engagements", "shares", "saves", "comments", "spend")}})
        for k in ("impressions", "reach", "video_views", "watch_sec", "completions", "engagements", "shares", "saves", "comments", "spend"):
            p[k] += c[k] or 0
    platforms = sorted((_eng_row(p) for p in by_p.values()), key=lambda p: -p["impressions"])
    video = sorted([c for c in camps if c["video_views"]], key=lambda c: -(c["avg_watch_sec"] or 0))
    return {"period": [s, e], "platforms": platforms, "video_campaigns": video,
            "note": "Platforms report attention as campaign totals. None of them reveal which individual saw, clicked or watched an ad."}
