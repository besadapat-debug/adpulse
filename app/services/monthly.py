"""Plain-English monthly report for the business owner: what happened, what it cost, and what we'll do next.

Written to be read in two minutes. Every sentence comes from the client's own numbers; sections with no data are left out.
"""
from __future__ import annotations

import calendar
from datetime import date

from .. import db
from . import audience, local


def _bounds(month: str) -> tuple[str, str]:
    y, m = int(month[:4]), int(month[5:])
    return f"{month}-01", f"{month}-{calendar.monthrange(y, m)[1]:02d}"


def _label(month: str) -> str:
    return date(int(month[:4]), int(month[5:]), 1).strftime("%B %Y")


def _pct(a, b):
    return (a - b) / b if a is not None and b else None


def _chg(a, b, good_up=True, unit=""):
    p = _pct(a, b)
    if p is None:
        return ""
    if abs(p) < 0.03:
        return "about the same as last month"
    word = "up" if p > 0 else "down"
    return f"{word} {abs(p) * 100:.0f}% on last month"


def _money(v):
    return f"${v:,.0f}" if v is not None else "–"


def _ads(client_id: int, month: str) -> dict | None:
    s, e = _bounds(month)
    ps, pe = _bounds(local.prev_month(month))
    q = ("SELECT SUM(spend) spend, SUM(clicks) clicks, SUM(impressions) impressions, SUM(conversions) conversions, SUM(revenue) revenue "
         "FROM ad_metrics WHERE client_id=? AND date BETWEEN ? AND ?")
    cur, prev = db.one(q, (client_id, s, e)), db.one(q, (client_id, ps, pe))
    if not cur or not cur["spend"]:
        return None
    camps = db.rows("SELECT MAX(campaign_name) name, platform, SUM(spend) spend, SUM(conversions) conversions FROM ad_metrics "
                    "WHERE client_id=? AND date BETWEEN ? AND ? GROUP BY platform, campaign_id", (client_id, s, e))
    cpa = cur["spend"] / cur["conversions"] if cur["conversions"] else None
    pcpa = prev["spend"] / prev["conversions"] if prev and prev["conversions"] else None
    good = [c for c in camps if c["conversions"] and c["conversions"] >= 2]
    best = min(good, key=lambda c: c["spend"] / c["conversions"]) if good else None
    waste = [c for c in camps if c["spend"] >= 0.1 * cur["spend"] and (c["conversions"] or 0) < 1]
    return {"spend": cur["spend"], "conversions": cur["conversions"] or 0, "clicks": cur["clicks"] or 0, "revenue": cur["revenue"] or 0,
            "cpa": cpa, "prev_cpa": pcpa, "prev_conversions": (prev or {}).get("conversions"), "prev_spend": (prev or {}).get("spend"),
            "best": best, "waste": waste[:2], "campaigns": len(camps)}


def _web(client_id: int, month: str) -> dict | None:
    s, e = _bounds(month)
    ps, pe = _bounds(local.prev_month(month))
    q = ("SELECT SUM(CASE WHEN metric='sessions' THEN value END) sessions, SUM(CASE WHEN metric='keyEvents' THEN value END) key_events "
         "FROM organic_metrics WHERE client_id=? AND platform='ga4' AND date BETWEEN ? AND ?")
    cur, prev = db.one(q, (client_id, s, e)), db.one(q, (client_id, ps, pe))
    if not cur or not cur["sessions"]:
        return None
    return {"sessions": cur["sessions"], "key_events": cur["key_events"] or 0, "prev_sessions": (prev or {}).get("sessions")}


def build(client_id: int, month: str | None = None) -> dict:
    c = db.one("SELECT * FROM clients WHERE id=?", (client_id,))
    month = month or local.last_full_month()
    series = {r["month"]: r for r in local.monthly_series(client_id, 24)}
    g, gp = series.get(month, {}), series.get(local.prev_month(month), {})
    comp = local.competitors(client_id, month)
    ads, web = _ads(client_id, month), _web(client_id, month)
    aud = audience.client_audience(client_id, 3)
    wins, sections, next_steps, kpis = [], [], [], []

    # --- Google listing
    if any(g.get(k) is not None for k, _ in local.ACTIVITY):
        lines = []
        calls, dirs, web_clicks = g.get("calls"), g.get("direction_requests"), g.get("website_clicks")
        if calls is not None:
            kpis.append({"label": "Calls from Google", "value": f"{calls:,}", "change": _pct(calls, gp.get("calls"))})
            lines.append(f"{calls:,} people called you straight from Google ({_chg(calls, gp.get('calls')) or 'first month tracked'}).")
        if dirs is not None:
            kpis.append({"label": "Direction requests", "value": f"{dirs:,}", "change": _pct(dirs, gp.get("direction_requests"))})
            lines.append(f"{dirs:,} asked Google Maps for directions to you ({_chg(dirs, gp.get('direction_requests')) or 'first month tracked'}).")
        if web_clicks is not None:
            lines.append(f"{web_clicks:,} clicked through to your website from your Google listing.")
        if g.get("bookings"):
            lines.append(f"{g['bookings']:,} booked through your Google listing.")
        if g.get("searches"):
            lines.append(f"You appeared in {g['searches']:,} Google searches.")
        total = sum(g.get(k) or 0 for k in ("calls", "direction_requests", "website_clicks", "bookings"))
        ptotal = sum(gp.get(k) or 0 for k in ("calls", "direction_requests", "website_clicks", "bookings"))
        if total and ptotal and total > ptotal * 1.05:
            wins.append(f"{total - ptotal:,} more people contacted or visited you from Google than last month")
        sections.append({"title": "Your Google listing", "lines": lines})
        if ptotal and total < ptotal * 0.9:
            next_steps.append("Google activity dipped, so we'll post weekly updates and fresh photos on your Google listing to stay near the top of Maps.")

    # --- Reviews
    if g.get("reviews_total") is not None:
        lines = [f"You have {g['reviews_total']:,} Google reviews" + (f" at {g['rating']}★" if g.get("rating") else "") + "."]
        nr = g.get("new_reviews")
        if nr is None and gp.get("reviews_total") is not None:
            nr = g["reviews_total"] - gp["reviews_total"]
        if nr is not None:
            lines.append(f"{max(nr, 0):,} new review{'s' if nr != 1 else ''} this month.")
            kpis.append({"label": "New Google reviews", "value": f"{max(nr, 0):,}", "change": None})
            if nr >= 3:
                wins.append(f"{nr} new Google reviews")
            else:
                next_steps.append("Only a few new reviews came in. We'll set up review requests (a counter QR card and a follow-up text) so happy customers leave one.")
        if comp["list"]:
            ranking = sorted([{"name": "You", "reviews": g["reviews_total"], "me": True}, *comp["list"]], key=lambda r: -(r["reviews"] or 0))
            rank = next(i + 1 for i, r in enumerate(ranking) if r.get("me"))
            top = next(r for r in ranking if not r.get("me"))
            lines.append(f"You rank #{rank} of {len(ranking)} nearby businesses we track by number of reviews.")
            if (top["reviews"] or 0) > g["reviews_total"]:
                lines.append(f"{top['name']} leads with {top['reviews']:,}, {top['reviews'] - g['reviews_total']:,} more than you.")
                if rank > 1:
                    next_steps.append(f"Close the review gap with {top['name']}: at 10 new reviews a month you'd pass them in about "
                                      f"{max(1, -(-(top['reviews'] - g['reviews_total']) // 10))} months.")
        sections.append({"title": "Your reviews", "lines": lines})

    # --- Ads
    if ads:
        lines = [f"You spent {_money(ads['spend'])} on ads, which brought {ads['conversions']:,.0f} enquiries or sales"
                 + (f", about {_money(ads['cpa'])} each." if ads["cpa"] else ".")]
        kpis.append({"label": "Ad spend", "value": _money(ads["spend"]), "change": _pct(ads["spend"], ads["prev_spend"])})
        kpis.append({"label": "Results from ads", "value": f"{ads['conversions']:,.0f}", "change": _pct(ads["conversions"], ads["prev_conversions"])})
        if ads["cpa"] and ads["prev_cpa"]:
            p = _pct(ads["cpa"], ads["prev_cpa"])
            if p is not None and p <= -0.1:
                wins.append(f"each result from ads cost {abs(p) * 100:.0f}% less than last month")
                lines.append(f"That's {abs(p) * 100:.0f}% cheaper per result than last month ({_money(ads['prev_cpa'])}).")
            elif p is not None and p >= 0.15:
                lines.append(f"That's {p * 100:.0f}% dearer per result than last month ({_money(ads['prev_cpa'])}).")
                next_steps.append("Cost per result went up, so we'll pause the weakest ads and move that money to the best performer.")
        if ads["best"]:
            b = ads["best"]
            lines.append(f"Best campaign: “{b['name']}” at {_money(b['spend'] / b['conversions'])} per result.")
        for w in ads["waste"]:
            lines.append(f"“{w['name']}” spent {_money(w['spend'])} without results.")
            next_steps.append(f"Stop or rework “{w['name']}”, which spent {_money(w['spend'])} last month without results.")
        if ads["revenue"] and ads["spend"]:
            lines.append(f"Reported sales value from ads: {_money(ads['revenue'])} ({ads['revenue'] / ads['spend']:.1f}× the ad spend).")
        sections.append({"title": "Your ads", "lines": lines})

    # --- Website
    if web:
        lines = [f"{web['sessions']:,.0f} visits to your website ({_chg(web['sessions'], web['prev_sessions']) or 'first month tracked'})."]
        if web["key_events"]:
            lines.append(f"{web['key_events']:,.0f} visitors took an action that matters (called, booked or enquired).")
        kpis.append({"label": "Website visits", "value": f"{web['sessions']:,.0f}", "change": _pct(web["sessions"], web["prev_sessions"])})
        sections.append({"title": "Your website", "lines": lines})

    # --- Audience
    ins = [i for i in aud["insights"] if i["kind"] in ("good", "bad", "info") and "No audience data" not in i["text"]]
    if ins:
        sections.append({"title": "Who's responding", "lines": [i["text"] for i in ins[:3]]})
        good = next((i for i in ins if i["kind"] == "good"), None)
        if good:
            next_steps.append("Shift more of the ad budget towards the group that's responding best (see “Who's responding”).")

    if not next_steps:
        next_steps.append("Keep doing what's working: steady Google posts, review requests and the current best ads.")
    headline = (f"In {_label(month)}: " + "; ".join(wins) + ".") if wins else f"Here's how {_label(month)} went."
    return {"client": {"id": c["id"], "name": c["name"], "brand_color": c["brand_color"], "logo_url": c["logo_url"]},
            "month": month, "month_label": _label(month), "headline": headline, "kpis": kpis[:6], "sections": sections,
            "next_steps": next_steps[:5], "has_data": bool(sections),
            "months": sorted(set(list(series)[-12:] + [local.last_full_month()]), reverse=True)}
