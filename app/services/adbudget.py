"""Ad budget calculator for one campaign: how much to spend, what a customer will cost, and whether it pays.

The maths (all per month):
    enquiries needed = new customers wanted ÷ close rate
    clicks needed    = enquiries ÷ conversion rate (click → enquiry/booking)
    ad budget        = clicks × cost per click
    cost per customer = ad budget ÷ customers
It works backwards too: from a budget to the customers it should bring.

Default cost-per-click and conversion rates are industry benchmarks (US data, USD, converted to AUD
with the rate card's usd_to_aud). They're a starting point: for real accuracy, replace the cost per click
with the figure Google Keyword Planner shows for their keywords and suburb.
"""
from __future__ import annotations

import math

SOURCES = {
    "google": ("WordStream: Google Ads benchmarks 2026 (US search campaigns, Apr 2025–Mar 2026)",
               "https://www.wordstream.com/blog/2026-google-ads-benchmarks"),
    "meta": ("WordStream: Facebook Ads benchmarks 2025 (US lead campaigns, Apr 2024–Jun 2025)",
             "https://www.wordstream.com/blog/facebook-ads-benchmarks-2025"),
    "min_clicks": ("20 Minute Marketing: Google Ads cost in Australia (15–20 clicks a day, 60–90 days)",
                   "https://www.20minutemarketing.com.au/blog/how-much-do-google-ads-cost-in-australia-real-benchmarks"),
}

# category: (label, google (cpc USD, conversion %), meta (cpc USD, conversion %) or None)
BENCH = {
    "all": ("All industries (average)", (5.42, 8.18), (1.92, 7.72)),
    "dentists": ("Dentists & dental services", (8.00, 10.67), (9.78, 6.38)),
    "physicians": ("Physicians & surgeons", (4.76, 12.43), (2.23, 4.51)),
    "health_fitness": ("Health & fitness", (6.17, 6.94), (2.64, 5.63)),
    "home": ("Home & home improvement", (8.33, 8.05), (2.23, 5.22)),
    "auto": ("Automotive repair, service & parts", (4.35, 15.51), None),
    "restaurants": ("Restaurants & food", (2.05, 8.05), (0.74, 18.25)),
    "beauty": ("Beauty & personal care", (4.62, 10.35), (3.06, 5.29)),
    "legal": ("Attorneys & legal services", (9.87, 5.55), (4.10, 10.53)),
    "real_estate": ("Real estate", (3.22, 3.70), (1.57, 9.53)),
    "finance": ("Finance & insurance", (3.39, 2.64), None),
    "business": ("Business services", (5.87, 4.85), None),
    "education": ("Education & instruction", (4.81, 13.14), (1.65, 10.08)),
    "shopping": ("Shopping, collectibles & gifts", (4.14, 4.01), None),
    "personal": ("Personal services", (7.17, 12.34), (2.08, 6.51)),
}
INDUSTRY_MAP = {
    "pharmacy": "all", "dental": "dentists", "gp": "physicians", "physio": "physicians", "chiro": "physicians", "psych": "physicians",
    "allied": "physicians", "cosmetic": "beauty", "fitness": "health_fitness", "beauty": "beauty", "trades": "home",
    "hospitality": "restaurants", "retail": "shopping", "ecommerce": "shopping", "real_estate": "real_estate", "legal": "legal",
    "accounting": "finance", "professional": "business", "education": "education", "automotive": "auto", "other": "all",
}
PLATFORMS = {"google": "Google Search ads", "meta": "Facebook & Instagram ads"}

# Campaign ideas per industry: (name, best platform, why)
PRESETS = {
    "pharmacy": [("Flu & COVID vaccinations", "google", "people search 'flu shot near me' when they're ready to book"),
                 ("Webster / blister packs", "meta", "reach carers and families of older people locally"),
                 ("New customers moving to the area", "meta", "new residents choose a regular pharmacy early")],
    "trades": [("Emergency call-outs", "google", "urgent searches, people call the first good result"),
               ("Hot water system replacement", "google", "high-value jobs searched when it breaks"),
               ("Seasonal maintenance offer", "meta", "reminds local homeowners before they need you")],
    "dental": [("New patient check-up & clean", "google", ""), ("Emergency dentist", "google", ""), ("Teeth whitening", "meta", "")],
    "physio": [("Sports injury appointments", "google", ""), ("Back & neck pain", "google", ""), ("Pilates / rehab classes", "meta", "")],
    "hospitality": [("Weekend brunch", "meta", ""), ("Functions & group bookings", "google", "")],
    "beauty": [("New client offer", "meta", ""), ("Bridal / events", "google", "")],
    "fitness": [("Free trial week", "meta", ""), ("Personal training", "google", "")],
    "_default": [("New customer enquiries", "google", "people searching for what they sell, nearby"),
                 ("Local awareness", "meta", "reach people in their suburb")],
}
DEFAULT_CLOSE = 50          # % of enquiries that become paying customers: a guess until the owner tells you


def _num(v, default=None):
    try:
        f = float(str(v).replace(",", "").replace("$", "").replace("%", "").strip())
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def defaults(industry: str, platform: str, usd_to_aud: float) -> dict:
    key = INDUSTRY_MAP.get(industry, "all")
    _, g, m = BENCH[key]
    if platform == "google":
        bench, used = g, key
    else:
        bench, used = (m, key) if m else (BENCH["all"][2], "all")
    src = SOURCES["google" if platform == "google" else "meta"]
    return {"cpc": round(bench[0] * usd_to_aud, 2), "conv": bench[1], "close": DEFAULT_CLOSE,
            "benchmark": BENCH[used][0], "exact_match": used != "all", "source": src[0], "url": src[1]}


def evaluate(c: dict, industry: str, rc: dict, customer_value: float | None, mgmt_fee: float = 0) -> dict:
    platform = c.get("platform") if c.get("platform") in PLATFORMS else "google"
    d = defaults(industry, platform, rc.get("usd_to_aud", 1.5))
    cpc = _num(c.get("cpc"), None) or d["cpc"]
    conv = min(max(_num(c.get("conv"), None) or d["conv"], 0.1), 100) / 100
    close = min(max(_num(c.get("close"), None) or d["close"], 1), 100) / 100
    value = _num(c.get("value"), None) or customer_value or None
    budget_in = _num(c.get("budget"), 0) or 0
    target = _num(c.get("customers"), 0) or 0
    mode = "budget" if budget_in > 0 else "target"
    if mode == "target" and target <= 0:
        target = 4
    cost_per_lead = cpc / conv
    cost_per_customer = cost_per_lead / close
    if mode == "budget":
        budget = budget_in
        customers = budget / cost_per_customer
    else:
        customers = target
        budget = customers * cost_per_customer
    clicks = budget / cpc
    leads = clicks * conv
    min_budget = rc.get("ads_min_spend", 1000)
    fast_budget = 15 * cpc * 30.4 if platform == "google" else None      # 15 clicks a day: learns within weeks
    out = {
        "platform": platform, "platform_label": PLATFORMS[platform], "mode": mode, "defaults": d,
        "used": {"cpc": round(cpc, 2), "conv": round(conv * 100, 2), "close": round(close * 100), "value": value},
        "budget": math.ceil(budget / 10) * 10, "daily": round(budget / 30.4), "clicks": round(clicks), "leads": round(leads, 1),
        "customers": round(customers, 1), "cost_per_lead": round(cost_per_lead), "cost_per_customer": round(cost_per_customer),
        "min_budget": math.ceil(min_budget / 50) * 50, "fast_budget": math.ceil(fast_budget / 50) * 50 if fast_budget else None, "mgmt_fee": round(mgmt_fee), "total_monthly": math.ceil((budget + mgmt_fee) / 10) * 10,
    }
    notes, verdict = [], "ok"
    if value:
        max_good = value / 3
        out["break_even_cpc"] = round(value * conv * close, 2)
        out["max_good_cost_per_customer"] = round(max_good)
        profit = customers * value - budget - mgmt_fee
        out["profit"] = round(profit)
        out["roas"] = round(customers * value / (budget + mgmt_fee), 2) if budget + mgmt_fee else None
        if cost_per_customer > value:
            verdict = "loses"
            notes.append(f"Each new customer would cost ${cost_per_customer:,.0f} in ads but is worth about ${value:,.0f} to them. "
                         f"At these numbers the campaign loses money: improve the landing page (conversion rate), target cheaper keywords, or pick another campaign.")
        elif cost_per_customer <= max_good:
            verdict = "strong"
            notes.append(f"Each customer costs about ${cost_per_customer:,.0f} and is worth ${value:,.0f}: roughly {value / cost_per_customer:.1f}× back. Worth running.")
        else:
            verdict = "thin"
            notes.append(f"Each customer costs about ${cost_per_customer:,.0f} and is worth ${value:,.0f}. It pays, but thinly. Aim for under ${max_good:,.0f} a customer.")
        if mgmt_fee and profit < 0 <= customers * value - budget:
            notes.append(f"The ads pay for themselves, but not your ${mgmt_fee:,.0f} management fee as well. Either raise the budget or run it as a short campaign.")
    else:
        notes.append("Add what one new customer is worth to them (profit in their first year) to see if it pays.")
    if budget < min_budget:
        if verdict != "loses":
            verdict = "too_small"
        notes.append(f"${budget:,.0f}/month is too little for the platform to learn what works. Use at least ${out['min_budget']:,.0f}/month, "
                     f"or run it for a shorter, focused period (e.g. flu season only).")
    elif fast_budget and budget < fast_budget:
        notes.append(f"At about {clicks / 30.4:.0f} clicks a day, give it 60–90 days to find what works. "
                     f"(${out['fast_budget']:,.0f}/month, about 15 clicks a day, learns faster.)")
    if customers < 1:
        notes.append("Expect less than one new customer a month at this budget, which is too few to judge whether it works.")
    out["verdict"], out["notes"] = verdict, notes
    return out


def evaluate_all(report: dict, rc: dict) -> list[dict]:
    business = report.get("business") or {}
    industry = business.get("industry") or "other"
    q = report.get("quote") or {}
    value = q.get("customer_value")
    size = business.get("size") or "small"
    fee = rc.get("ads_flat_sole", 350) if size == "sole" else rc.get("ads_min_monthly", 600)
    out = []
    for c in report.get("ad_campaigns") or []:
        calc = evaluate(c, industry, rc, value, fee if c.get("include_fee") is not False else 0)
        out.append({**c, "calc": calc})
    return out


def presets(industry: str) -> list[dict]:
    return [{"name": n, "platform": p, "why": w} for n, p, w in PRESETS.get(industry, PRESETS["_default"])]
