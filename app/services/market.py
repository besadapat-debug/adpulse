"""What else the business could pay for: typical Australian market prices, with sources.

Shown on the Proposal tab so the owner can see where your prices sit. Figures were researched in
September 2026 from published price guides (AUD). Prices change, so re-check the source before
quoting a figure to a client, and update this file when they move.
"""
from __future__ import annotations

AS_OF = "September 2026"

SOURCES = {
    "gbp": ("GetDigitalMarketingHelp: Google Business Profile costs", "https://getdigitalmarketinghelp.com.au/google-business-profile/cost/"),
    "seo": ("This Jay: local SEO cost in Australia (2026)", "https://thisjay.com/blog/how-much-does-local-seo-cost-australia/"),
    "social": ("CodeQy: social media management cost Australia (2026)", "https://codeqy.com.au/blog/how-much-does-social-media-management-cost-australia"),
    "ads": ("Grove Foundry: Google Ads management cost Australia (2026)", "https://www.grovefoundry.com.au/blog/google-ads-management-cost-australia/"),
    "agency": ("WME: digital marketing agency cost Australia (2026)", "https://wmegroup.com.au/blog/digital-marketing-agency-cost-australia/"),
    "hipages": ("KingTradie: hipages cost 2026", "https://kingtradie.com/hipages-review/"),
    "oneflare": ("KingTradie: Oneflare closed 30 June 2026", "https://kingtradie.com/oneflare-review/"),
    "tradie_site": ("Loudachris: tradie website + SEO subscription", "https://free-websites.com.au/industries/tradies"),
}

# service → (label, low, high, unit, note, source)
GENERAL = [
    ("gbp_setup", "Google Business Profile setup (one-off, per location)", 300, 1500, "once", "claiming, categories, services, photos", "gbp"),
    ("gbp_monthly", "Google Business Profile management", 150, 1200, "month", "consultant $150–800, agency $400–1,200+", "gbp"),
    ("seo", "Local SEO", 500, 3500, "month", "freelancer $500–2,000, small agency $1,500–3,500", "seo"),
    ("social", "Social media management", 500, 3500, "month", "freelancer $500–1,500, agency $1,500–3,500+", "social"),
    ("ads", "Google Ads management", 800, 2500, "month", "plus $750–2,000 setup; ad spend $1,000–2,000+/month recommended", "ads"),
    ("agency", "Agency small-business package", 1500, 3500, "month", "“starter” tier; growth tiers $3,500–10,000", "agency"),
]

# what businesses in this industry often already pay for instead of an agency
INDUSTRY = {
    "trades": [
        ("hipages lead subscription", 139, 649, "month", "+GST · plans $139 / $249 / $449 / $649 · 6-month first term, then 12-month auto-renew · "
         "each job is shared with up to 3 tradies", "hipages"),
        ("Tradie website + SEO subscription", 297, 297, "month", "incl. GST · $0 setup · 12-month term", "tradie_site"),
        ("Oneflare", None, None, "", "closed 30 June 2026 (now redirects to Airtasker): lead platforms can disappear, "
         "your own Google profile and website can't", "oneflare"),
    ],
    "automotive": [
        ("hipages lead subscription (some auto services)", 139, 649, "month", "+GST · 6-month first term, then 12-month auto-renew", "hipages"),
    ],
}

TALKING_POINTS = {
    "trades": "Most tradies compare you to hipages, not to other agencies. Local Lite costs about the same as a mid hipages plan, "
              "but the calls come straight to them, aren't shared with 3 other tradies, and there's no lock-in.",
    "pharmacy": "Ask whether they belong to a banner group (e.g. Amcal, Priceline, Chemist Warehouse, TerryWhite Chemmart). "
                "Groups often run the brand marketing, so pitch what they don't do: the store's own Google profile, reviews and local bookings.",
    "_health": "Online booking platforms (HotDoc, HealthEngine) are booking tools, not marketing. Pitch working alongside them: "
               "more people finding the practice on Google, then booking through the tool they already use.",
    "_default": "Your packages are priced below typical agency rates. The owner's real comparison is usually doing it themselves, "
                "so lead with the small one-off Starter job and the time it saves them.",
}


def _range(lo, hi, unit):
    if lo is None:
        return "—"
    s = f"${lo:,}" if lo == hi else f"${lo:,}–${hi:,}"
    return s + ("/mo" if unit == "month" else " once" if unit == "once" else "")


def comparison(industry: str, quote: dict, health: bool = False) -> dict:
    """Market price rows plus a few 'you vs them' lines built from this prospect's quote."""
    tiers = {t["name"]: t for t in quote.get("tiers", [])}
    rows = []
    items = [(True, *r) for r in INDUSTRY.get(industry, [])] + [(False, *g[1:]) for g in GENERAL]
    for specific, label, lo, hi, unit, note, src in items:
        rows.append({"label": label, "price": _range(lo, hi, unit), "note": note, "source": SOURCES[src][0], "url": SOURCES[src][1],
                     "industry_specific": specific})
    you = []
    lite, starter, growth = tiers.get("Local Lite"), tiers.get("Starter"), tiers.get("Growth")
    if lite and industry in INDUSTRY and INDUSTRY[industry][0][1]:
        you.append(f"Local Lite ${lite['monthly_total']:,}/mo (no lock-in) vs {INDUSTRY[industry][0][0]} ${INDUSTRY[industry][0][1]:,}–${INDUSTRY[industry][0][2]:,}/mo")
    if lite:
        you.append(f"Local Lite ${lite['monthly_total']:,}/mo vs Google profile management elsewhere $150–1,200/mo")
    if starter:
        you.append(f"Starter ${starter['setup_total']:,} once vs Google profile setup elsewhere $300–1,500")
    if growth:
        you.append(f"Growth ${growth['monthly_total']:,}/mo vs typical agency packages $1,500–3,500/mo (starter tier)")
    tip = TALKING_POINTS.get(industry) or (TALKING_POINTS["_health"] if health else TALKING_POINTS["_default"])
    return {"as_of": AS_OF, "rows": rows, "you": you, "tip": tip}
