"""Nearby competitors: similar businesses in the same area, compared on Google rating and reviews.

Finding them automatically uses Google's Places API (New) Text Search with an API key
(GOOGLE_PLACES_API_KEY, or the PageSpeed key if Places API (New) is enabled on the same Google Cloud project).
Without a key, open the Google Maps search link and add competitors by hand.
Only public business listings are used: names, star ratings, review counts and websites.
"""
from __future__ import annotations

import os
import re
from statistics import median
from urllib.parse import quote_plus, urlparse

import httpx

SEARCH_TERMS = {
    "pharmacy": "pharmacy", "dental": "dentist", "physio": "physiotherapist", "gp": "medical centre", "chiro": "chiropractor",
    "psych": "psychologist", "allied": "podiatrist", "cosmetic": "cosmetic clinic", "fitness": "gym", "beauty": "hair salon",
    "trades": "", "hospitality": "cafe", "retail": "", "ecommerce": "", "real_estate": "real estate agent", "legal": "lawyer",
    "accounting": "accountant", "professional": "", "education": "childcare", "automotive": "mechanic", "other": "",
}
TRADE_WORDS = [
    (r"plumb", "plumber"), (r"electric|sparky", "electrician"), (r"roof", "roofer"), (r"carpent|joiner", "carpenter"),
    (r"paint", "painter"), (r"landscap|garden", "landscaper"), (r"air ?con|hvac|heating|cooling", "air conditioning"),
    (r"build|renovat", "builder"), (r"tile|tiling", "tiler"), (r"lock ?smith", "locksmith"), (r"clean", "cleaner"),
    (r"pest", "pest control"), (r"fenc", "fencing"), (r"concret", "concreter"), (r"glaz|glass", "glazier"),
]


def api_key() -> str:
    return os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("PAGESPEED_API_KEY") or ""


def guess_term(report: dict, industry: str) -> str:
    term = SEARCH_TERMS.get(industry, "")
    if term:
        return term
    text = " ".join([report.get("name") or "", report.get("title") or "", " ".join(report.get("h1") or []), report.get("domain") or ""]).lower()
    for rx, word in TRADE_WORDS:
        if re.search(rx, text):
            return word
    return ""


def maps_link(term: str, area: str) -> str:
    return "https://www.google.com/maps/search/" + quote_plus(f"{term} near {area}".strip())


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _host(u: str) -> str:
    try:
        return (urlparse(u if "//" in u else "//" + u).hostname or "").removeprefix("www.")
    except Exception:
        return ""


def find(term: str, area: str, own_domain: str = "", own_name: str = "") -> list[dict]:
    """Search Google Places for '<term> in <area>'. Raises ValueError with a plain-English reason on failure."""
    key = api_key()
    if not key:
        raise ValueError("No Google Places API key set (GOOGLE_PLACES_API_KEY). Use the Google Maps link and add competitors by hand.")
    if not term or not area:
        raise ValueError("Enter what they do (e.g. plumber) and their suburb first.")
    fields = "places.displayName,places.rating,places.userRatingCount,places.websiteUri,places.formattedAddress,places.googleMapsUri"
    try:
        r = httpx.post("https://places.googleapis.com/v1/places:searchText", timeout=20,
                       headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": fields, "Content-Type": "application/json"},
                       json={"textQuery": f"{term} in {area}", "regionCode": "AU", "languageCode": "en", "pageSize": 12})
    except httpx.HTTPError as e:
        raise ValueError(f"Couldn't reach Google: {e}")
    if r.status_code != 200:
        msg = (r.json().get("error") or {}).get("message", r.text[:200]) if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        if "not been used" in msg or "disabled" in msg or r.status_code == 403:
            msg = "Places API (New) isn't enabled for this key. In Google Cloud Console → APIs & Services → Library, enable “Places API (New)”."
        raise ValueError(msg)
    own_host, own = _host(own_domain), (own_name or "").strip().lower()
    out = []
    for p in r.json().get("places", []):
        name = (p.get("displayName") or {}).get("text", "")
        site = p.get("websiteUri", "")
        is_self = bool((own_host and _host(site) == own_host) or (own and name.strip().lower() == own))
        out.append({"name": name, "rating": p.get("rating"), "reviews": p.get("userRatingCount") or 0, "website": site,
                    "address": p.get("formattedAddress", ""), "maps": p.get("googleMapsUri", ""), "is_self": is_self})
    return out


def summary(report: dict) -> dict | None:
    comp = report.get("competitors") or {}
    lst = [c for c in comp.get("list", []) if not c.get("is_self") and _num(c.get("reviews")) is not None]
    if not lst:
        return None
    gbp = (report.get("social") or {}).get("google_business") or {}
    selfrow = next((c for c in comp.get("list", []) if c.get("is_self")), None)
    my_reviews = _num(gbp.get("reviews")) if _num(gbp.get("reviews")) is not None else _num((selfrow or {}).get("reviews"))
    my_rating = _num(gbp.get("rating")) if _num(gbp.get("rating")) is not None else _num((selfrow or {}).get("rating"))
    reviews = [_num(c["reviews"]) for c in lst]
    ratings = [_num(c.get("rating")) for c in lst if _num(c.get("rating")) is not None]
    top = max(lst, key=lambda c: _num(c["reviews"]))
    rank = None
    if my_reviews is not None:
        rank = 1 + sum(1 for v in reviews if v > my_reviews)
    return {"count": len(lst), "median_reviews": round(median(reviews)), "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
            "top": {"name": top["name"], "reviews": int(_num(top["reviews"])), "rating": _num(top.get("rating"))},
            "my_reviews": None if my_reviews is None else int(my_reviews), "my_rating": my_rating,
            "rank": rank, "of": len(lst) + 1, "behind": my_reviews is not None and my_reviews < median(reviews)}
