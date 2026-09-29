"""Audience: who sees and responds to the ads, and who visits the website, by age, gender and location.

Group totals only: ad platforms and Google Analytics report demographics per segment, never per person.
"""
from __future__ import annotations

from datetime import date

from .. import db
from ..connectors import label as platform_label

AGE_ORDER = ["13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
DIM_LABEL = {"age": "Age", "gender": "Gender", "age_gender": "Age & gender", "region": "State / region", "city": "Suburb / city"}


def month_cutoff(months: int) -> str:
    d = date.today().replace(day=1)
    y, m = d.year, d.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}-{m:02d}-01"


def _age_key(s: str):
    s2 = s.replace("–", "-")
    return (AGE_ORDER.index(s2) if s2 in AGE_ORDER else 99, s)


def _ratio(a, b):
    return (a / b) if b else None


def client_audience(client_id: int, months: int = 3) -> dict:
    cutoff = month_cutoff(months)
    rows = db.rows("SELECT platform, dimension, segment, SUM(impressions) impressions, SUM(reach) reach, SUM(clicks) clicks, SUM(spend) spend, "
                   "SUM(conversions) conversions, SUM(users) users, SUM(sessions) sessions, MIN(date_from) date_from, MAX(date_to) date_to, "
                   "MAX(source) source FROM demographics WHERE client_id=? AND date_from>=? GROUP BY platform, dimension, segment",
                   (client_id, cutoff))
    platforms = sorted({r["platform"] for r in rows})
    ads = [r for r in rows if r["platform"] != "ga4"]
    web = [r for r in rows if r["platform"] == "ga4"]
    out = {"months": months, "from": cutoff, "platforms": [{"key": p, "label": platform_label(p)} for p in platforms],
           "sources": sorted({r["source"] for r in rows}), "ads": {}, "web": {}, "insights": []}

    for dim in DIM_LABEL:
        seg = {}
        for r in ads:
            if r["dimension"] != dim:
                continue
            s = seg.setdefault(r["segment"], {"segment": r["segment"], "impressions": 0, "clicks": 0, "spend": 0.0, "conversions": 0.0, "reach": 0})
            for k in ("impressions", "clicks", "spend", "conversions", "reach"):
                s[k] += r[k] or 0
        if seg:
            tot = {k: sum(s[k] for s in seg.values()) for k in ("impressions", "clicks", "spend", "conversions")}
            lst = []
            for s in seg.values():
                s["ctr"] = _ratio(s["clicks"], s["impressions"])
                s["cpa"] = _ratio(s["spend"], s["conversions"])
                s["spend_share"] = _ratio(s["spend"], tot["spend"])
                s["conv_share"] = _ratio(s["conversions"], tot["conversions"])
                s["impr_share"] = _ratio(s["impressions"], tot["impressions"])
                lst.append(s)
            lst.sort(key=(lambda s: _age_key(s["segment"])) if dim == "age" else (lambda s: -(s["spend"] or s["impressions"])))
            out["ads"][dim] = {"label": DIM_LABEL[dim], "segments": lst[:25], "totals": {**tot, "cpa": _ratio(tot["spend"], tot["conversions"]),
                                                                                       "ctr": _ratio(tot["clicks"], tot["impressions"])}}
        wseg = {}
        for r in web:
            if r["dimension"] != dim:
                continue
            s = wseg.setdefault(r["segment"], {"segment": r["segment"], "users": 0.0, "sessions": 0.0, "conversions": 0.0})
            for k in ("users", "sessions", "conversions"):
                s[k] += r[k] or 0
        if wseg:
            tu = sum(s["users"] for s in wseg.values())
            lst = list(wseg.values())
            for s in lst:
                s["share"] = _ratio(s["users"], tu)
            lst.sort(key=(lambda s: _age_key(s["segment"])) if dim == "age" else (lambda s: -s["users"]))
            out["web"][dim] = {"label": DIM_LABEL[dim], "segments": lst[:25], "total_users": tu}
    out["insights"] = insights(out)
    return out


def _nice(seg: str, dim: str) -> str:
    if dim == "age":
        return f"people aged {seg}"
    if dim == "gender":
        return {"Female": "women", "Male": "men"}.get(seg, seg.lower())
    if dim == "age_gender":
        a, _, g = seg.partition(" · ")
        return f"{ {'Female': 'women', 'Male': 'men'}.get(g, g.lower())} aged {a}"
    return f"people in {seg}"


def insights(a: dict) -> list[dict]:
    """Plain-English findings: where results are cheap, where money is wasted, who visits the site."""
    out = []
    for dim in ("age_gender", "age", "gender", "region", "city"):
        d = a["ads"].get(dim)
        if not d or not d["totals"]["conversions"]:
            continue
        avg = d["totals"]["cpa"]
        segs = [s for s in d["segments"] if s["segment"] != "Unknown" and (s["spend_share"] or 0) >= 0.05]
        good = [s for s in segs if s["cpa"] and s["cpa"] <= avg * 0.75 and s["conversions"] >= 2]
        if good:
            b = min(good, key=lambda s: s["cpa"])
            out.append({"kind": "good", "dimension": dim,
                        "text": f"{_nice(b['segment'], dim).capitalize()} are your cheapest customers: ${b['cpa']:,.0f} per result, "
                                f"{(1 - b['cpa'] / avg) * 100:.0f}% below the ${avg:,.0f} average. Put more of the budget here."})
        waste = [s for s in segs if (s["spend_share"] or 0) >= 0.1 and (s["conv_share"] or 0) < (s["spend_share"] or 0) * 0.5]
        if waste:
            w = max(waste, key=lambda s: s["spend_share"])
            out.append({"kind": "bad", "dimension": dim,
                        "text": f"{_nice(w['segment'], dim).capitalize()} took {w['spend_share'] * 100:.0f}% of the spend but brought only "
                                f"{(w['conv_share'] or 0) * 100:.0f}% of results. Consider lowering the budget or excluding them."})
        if sum(1 for o in out if o["kind"] == "good") >= 2 and sum(1 for o in out if o["kind"] == "bad") >= 1:
            break
    # one finding per kind per group: drop a broad finding when a narrower one already says the same thing
    seen, dedup = set(), []
    for o in out:
        key = (o["kind"], o["text"].split(" are ")[0].split(" took ")[0].split()[0].lower())
        if key in seen:
            continue
        seen.add(key)
        dedup.append(o)
    out = dedup[:4]
    for dim in ("age", "gender", "city"):
        d = a["web"].get(dim)
        if d and d["segments"]:
            known = [s for s in d["segments"] if s["segment"].lower() not in ("unknown", "(not set)")]
            if known:
                top = max(known, key=lambda s: s["users"])
                out.append({"kind": "info", "dimension": dim, "text": f"Most website visitors are {_nice(top['segment'], dim)} "
                                                                        f"({(top['share'] or 0) * 100:.0f}% of visitors)."})
    if not a["ads"] and not a["web"]:
        out.append({"kind": "info", "dimension": "", "text": "No audience data yet. Upload an age & gender breakdown from Meta Ads Manager, "
                                                             "Google Ads or Google Analytics (Upload data tab), or connect the accounts."})
    return out[:6]
