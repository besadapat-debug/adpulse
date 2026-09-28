"""Proposal & fee calculator.

Turns an audit (website gaps + social gaps) and the business's industry, size and number of
locations into three packages with a one-off setup fee, a monthly fee and a suggested ad budget.
All prices come from the agency's rate card (Settings → Rate card), so they're yours to set.
Amounts are AUD excluding GST.
"""
from __future__ import annotations

import json

from .. import db
from .social import INDUSTRIES, PLATFORMS, SIZES

DEFAULT_RATE_CARD = {
    "tracking_setup": 750,          # one-off: GA4, Tag Manager, Meta Pixel + CAPI, Google Ads conversions, consent banner
    "website_fixes": 900,           # one-off: click-to-call, CTAs, forms, mobile/speed fixes, SEO basics
    "gbp_setup": 450,               # one-off: Google Business Profile clean-up and optimisation
    "social_setup": 350,            # one-off per platform: profile clean-up, branding, bio, highlights
    "social_monthly": 450,          # per platform per month: ~8 posts, community management
    "seo_monthly": 990,             # local SEO + Google Business posts/reviews programme
    "ads_min_monthly": 600,         # paid ads management minimum per month
    "ads_pct": 15,                  # or this % of ad spend, whichever is higher
    "reporting_monthly": 150,       # AdPulse live dashboard + monthly report
    "ad_spend_small": 1500,         # suggested monthly ad spend for a small business (scaled by size/industry)
    "starter_gbp": 290,             # Starter, one-off: Google Business Profile clean-up (hours, photos, categories, services)
    "starter_fixes": 390,           # Starter, one-off: fix the top 3 website problems from the audit
    "starter_monthly": 290,         # Starter, optional month-to-month: Google posts + review requests
}
SIZE_MULT = {"sole": 0.7, "small": 1.0, "medium": 1.4, "large": 2.0, "enterprise": 3.0}
SPEND_MULT = {"sole": 0.4, "small": 1.0, "medium": 2.5, "large": 6.0, "enterprise": 12.0}


def rate_card() -> dict:
    row = db.one("SELECT rate_card FROM agency WHERE id=1") or {}
    try:
        saved = json.loads(row.get("rate_card") or "{}")
    except Exception:
        saved = {}
    return {k: float(saved.get(k, v)) for k, v in DEFAULT_RATE_CARD.items()}


def save_rate_card(values: dict) -> dict:
    clean = {k: float(values[k]) for k in DEFAULT_RATE_CARD if k in values and str(values[k]).strip() != ""}
    db.execute("UPDATE agency SET rate_card=? WHERE id=1", (json.dumps(clean),))
    return rate_card()


def _r(x: float, step: int = 10) -> int:
    return int(round(x / step) * step)


def payback(tier: dict, customer_value: float) -> dict | None:
    """How many new regular customers a package needs to cover its first-year cost.

    customer_value is the profit one new regular customer brings in a year (the business owner's own figure).
    Year-one cost = one-off fees + 12 months of fees + 12 months of suggested ad spend (Starter: one-off only).
    """
    if not customer_value or customer_value <= 0:
        return None
    monthly = 0 if tier.get("starter") else tier["monthly_total"] + tier["ad_spend"]
    year_cost = tier["setup_total"] + 12 * monthly
    per_year = year_cost / customer_value
    return {"year_cost": _r(year_cost, 1), "customers_per_year": round(per_year, 1),
            "customers_per_month": round(per_year / 12, 1)}


def _starter(report: dict, social_summary: dict, m: float, rc: dict) -> dict:
    """Small, low-risk first job for walk-in prospects: a few fixed one-offs, then optional month-to-month."""
    scale = m ** 0.5                                  # gentle: small jobs shouldn't balloon for bigger businesses
    setup = []
    gbp = (social_summary.get("platforms") or {}).get("google_business") or {}
    if not gbp.get("exists"):
        setup.append(("Google Business Profile set-up", _r(rc["starter_gbp"] * scale), "hours, photos, categories, services, booking link"))
    else:
        setup.append(("Google Business Profile clean-up", _r(rc["starter_gbp"] * scale), "hours, photos, categories, services, booking link"))
    fixes = [c.get("problem") or c.get("title") for c in report.get("top_issues", [])][:3]
    if fixes:
        setup.append((f"Fix the top {len(fixes)} website problem{'s' if len(fixes) > 1 else ''}", _r(rc["starter_fixes"] * scale * (0.5 + len(fixes) / 6)),
                      "; ".join(f for f in fixes if f)))
    monthly = [("Google posts & review requests (optional)", _r(rc["starter_monthly"] * scale), "month to month, cancel any time")]
    setup_total = sum(i[1] for i in setup)
    return {"name": "Starter", "starter": True, "tagline": "One-off quick wins. No lock-in contract.",
            "setup": [{"item": a, "amount": b, "detail": c} for a, b, c in setup],
            "monthly": [{"item": a, "amount": b, "detail": c} for a, b, c in monthly],
            "setup_total": setup_total, "monthly_total": monthly[0][1], "ad_spend": 0, "first_year": setup_total}


def build_quote(report: dict, business: dict, social_summary: dict, rc: dict | None = None) -> dict:
    rc = rc or rate_card()
    industry = business.get("industry") or "other"
    size = business.get("size") or "small"
    locations = max(1, int(business.get("locations") or 1))
    ind = INDUSTRIES.get(industry, INDUSTRIES["other"])
    m = SIZE_MULT.get(size, 1.0) * ind["mult"]
    loc_mult = 1 + 0.25 * min(locations - 1, 8)          # each extra location adds local SEO/GBP work
    failed = {c["key"] for c in report.get("checks", []) if not c["ok"]}

    one_off, monthly = [], []
    reasons = []
    if failed & {"analytics", "ads_tracking", "meta_pixel", "consent"}:
        one_off.append(("Tracking & analytics setup", _r(rc["tracking_setup"] * m), "GA4, Meta Pixel + Conversions API, Google Ads conversions, consent banner"))
        reasons.append("they can't currently measure which marketing brings customers")
    web_gaps = failed & {"click_to_call", "cta", "form", "viewport", "speed", "title", "description", "h1", "schema", "https"}
    if web_gaps:
        one_off.append(("Website conversion & SEO fixes", _r(rc["website_fixes"] * m * (0.6 + 0.08 * len(web_gaps))),
                        f"{len(web_gaps)} issues from the audit (e.g. {', '.join(sorted(web_gaps))[:60]})"))
    plats = social_summary.get("platforms", {})
    gbp = plats.get("google_business")
    if gbp and (not gbp["exists"] or (gbp["score"] is not None and gbp["score"] < 70)):
        one_off.append(("Google Business Profile optimisation", _r(rc["gbp_setup"] * loc_mult), f"{locations} location(s)"))
        reasons.append("their Google Business Profile is under-performing")

    expected = [p for p in social_summary.get("expected", []) if p != "google_business"]
    def is_weak(p):
        r = plats.get(p, {})
        return not r.get("exists") or (r.get("score") is not None and r["score"] < 70)
    # priority: platforms they have but are under-using, then missing ones, then healthy ones
    ordered = ([p for p in expected if plats.get(p, {}).get("exists") and is_weak(p)]
               + [p for p in expected if not plats.get(p, {}).get("exists")]
               + [p for p in expected if not is_weak(p)])
    social_rate = rc["social_monthly"] * (0.8 + 0.2 * m)
    seo_rate = rc["seo_monthly"] * m * loc_mult
    spend = rc["ad_spend_small"] * SPEND_MULT.get(size, 1.0) * ind["mult"] * (1 + 0.15 * (locations - 1))
    ads_fee = max(rc["ads_min_monthly"], spend * rc["ads_pct"] / 100)

    def tier(name, social_n, seo_f, ads, spend_f, extras_setup=True):
        items_m = []
        social_list = ordered[:social_n]
        for p in social_list:
            items_m.append((f"{PLATFORMS[p]['label']} management", _r(social_rate), "~8 posts/month + community management"))
        if seo_f:
            items_m.append(("Local SEO & Google reviews programme", _r(seo_rate * seo_f), f"{locations} location(s)"))
        if ads:
            items_m.append(("Paid ads management (Meta + Google)", _r(ads_fee * (spend_f ** 0.5)), f"{rc['ads_pct']:.0f}% of spend, min ${rc['ads_min_monthly']:,.0f}"))
        items_m.append(("Live dashboard & monthly report", _r(rc["reporting_monthly"]), "AdPulse client report"))
        setup = list(one_off) if extras_setup else one_off[:1]
        missing_social = [p for p in social_list if not plats.get(p, {}).get("exists")]
        for p in missing_social:
            setup.append((f"Set up {PLATFORMS[p]['label']} profile", _r(rc["social_setup"]), "new profile, branding, bio"))
        setup_total = sum(i[1] for i in setup)
        month_total = sum(i[1] for i in items_m)
        ad_spend = _r(spend * spend_f, 50) if ads else 0
        return {"name": name, "setup": [{"item": a, "amount": b, "detail": c} for a, b, c in setup],
                "monthly": [{"item": a, "amount": b, "detail": c} for a, b, c in items_m],
                "setup_total": setup_total, "monthly_total": month_total, "ad_spend": ad_spend,
                "first_year": setup_total + 12 * month_total}

    tiers = [
        _starter(report, social_summary, m, rc),
        tier("Essentials", 1, 0.6, False, 0, extras_setup=True),
        tier("Growth", 2, 1.0, True, 1.0),
        tier("Premium", len(expected), 1.3, True, 1.6),
    ]
    tiers[2]["recommended"] = True
    try:
        value = float(business.get("customer_spend") or 0) * float(business.get("margin_pct") or 100) / 100
    except (TypeError, ValueError):
        value = 0
    for t in tiers:
        t["payback"] = payback(t, value)
    return {"customer_value": _r(value, 1) if value else None,"currency": "AUD", "gst_note": "Prices exclude GST. Ad spend is paid directly to Google/Meta and isn't part of the fee.",
            "tiers": tiers, "industry": ind["label"], "size": SIZES.get(size, SIZES["small"])["label"], "locations": locations,
            "reasons": reasons, "multiplier": round(m, 2)}


def industry_rank(prospect_id: int, industry: str, overall_score: int) -> dict:
    """Where this business sits among the other businesses you've audited (same industry, and overall)."""
    same, allp = [], []
    for r in db.rows("SELECT id, report FROM prospects"):
        try:
            rep = json.loads(r["report"])
        except Exception:
            continue
        sc = (rep.get("overall") or {}).get("score", rep.get("score"))
        if sc is None:
            continue
        allp.append((r["id"], sc))
        if (rep.get("business") or {}).get("industry") == industry:
            same.append((r["id"], sc))

    def pos(lst):
        lst = sorted(lst, key=lambda x: -x[1])
        ids = [i for i, _ in lst]
        return (ids.index(prospect_id) + 1, len(lst)) if prospect_id in ids else (None, len(lst))

    r1, n1 = pos(same)
    r2, n2 = pos(allp)
    return {"industry_rank": r1, "industry_count": n1, "overall_rank": r2, "overall_count": n2}
