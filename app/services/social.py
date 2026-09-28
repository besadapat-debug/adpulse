"""Social media presence audit for prospects.

What's automatic vs manual (and why):
- Profile *discovery* is automatic: we read the links a business publishes on its own website.
- YouTube stats are automatic when a Google API key with the YouTube Data API is set
  (YOUTUBE_API_KEY, or PAGESPEED_API_KEY if YouTube Data API v3 is enabled on the same key).
- Facebook, Instagram, TikTok, LinkedIn, X and Google Business don't allow automated
  reading of other businesses' profiles without special approval, and their terms forbid
  scraping. So their numbers (followers, recent posts, engagement, reviews) are entered by
  you from the public profile — about a minute per platform — and scored here.
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

PLATFORMS = {
    # key: label, target posts per 30 days, benchmark engagement rate (engagements per post / followers)
    "google_business": {"label": "Google Business Profile", "posts_target": 4, "er": None},
    "facebook": {"label": "Facebook", "posts_target": 8, "er": 0.003},
    "instagram": {"label": "Instagram", "posts_target": 8, "er": 0.015},
    "tiktok": {"label": "TikTok", "posts_target": 8, "er": 0.04},
    "linkedin": {"label": "LinkedIn", "posts_target": 4, "er": 0.02},
    "youtube": {"label": "YouTube", "posts_target": 2, "er": None},
    "x": {"label": "X (Twitter)", "posts_target": 8, "er": 0.005},
    "pinterest": {"label": "Pinterest", "posts_target": 8, "er": 0.003},
    "threads": {"label": "Threads", "posts_target": 8, "er": 0.01},
}

# Industry catalogue. "expected" = platforms customers in this industry actually use to choose a business.
# "mult" = relative competitiveness/value used by pricing. "health" = AHPRA-regulated health service advertising.
INDUSTRIES = {
    "pharmacy": {"label": "Pharmacy", "expected": ["google_business", "facebook", "instagram"], "mult": 1.0, "health": True},
    "dental": {"label": "Dental clinic", "expected": ["google_business", "facebook", "instagram"], "mult": 1.25, "health": True},
    "physio": {"label": "Physiotherapy", "expected": ["google_business", "facebook", "instagram"], "mult": 1.0, "health": True},
    "gp": {"label": "GP / medical clinic", "expected": ["google_business", "facebook"], "mult": 1.1, "health": True},
    "chiro": {"label": "Chiropractic / osteopathy", "expected": ["google_business", "facebook", "instagram"], "mult": 1.0, "health": True},
    "psych": {"label": "Psychology / counselling", "expected": ["google_business", "facebook", "linkedin"], "mult": 1.0, "health": True},
    "allied": {"label": "Other allied health (podiatry, OT, dietetics…)", "expected": ["google_business", "facebook", "instagram"], "mult": 0.95, "health": True},
    "cosmetic": {"label": "Cosmetic / aesthetics clinic", "expected": ["instagram", "google_business", "tiktok", "facebook"], "mult": 1.3, "health": True},
    "fitness": {"label": "Gym / fitness studio", "expected": ["instagram", "google_business", "facebook", "tiktok"], "mult": 0.9, "health": False},
    "beauty": {"label": "Beauty / hair salon", "expected": ["instagram", "google_business", "facebook", "tiktok"], "mult": 0.85, "health": False},
    "trades": {"label": "Trades & home services", "expected": ["google_business", "facebook", "instagram"], "mult": 1.0, "health": False},
    "hospitality": {"label": "Café / restaurant / bar", "expected": ["google_business", "instagram", "facebook", "tiktok"], "mult": 0.85, "health": False},
    "retail": {"label": "Retail store", "expected": ["google_business", "instagram", "facebook"], "mult": 0.9, "health": False},
    "ecommerce": {"label": "E-commerce", "expected": ["instagram", "facebook", "tiktok", "pinterest"], "mult": 1.15, "health": False},
    "real_estate": {"label": "Real estate", "expected": ["google_business", "facebook", "instagram", "linkedin"], "mult": 1.3, "health": False},
    "legal": {"label": "Legal", "expected": ["google_business", "linkedin", "facebook"], "mult": 1.4, "health": False},
    "accounting": {"label": "Accounting / finance", "expected": ["google_business", "linkedin", "facebook"], "mult": 1.15, "health": False},
    "professional": {"label": "Other professional services", "expected": ["google_business", "linkedin", "facebook"], "mult": 1.1, "health": False},
    "education": {"label": "Education / childcare", "expected": ["google_business", "facebook", "instagram"], "mult": 1.0, "health": False},
    "automotive": {"label": "Automotive", "expected": ["google_business", "facebook", "instagram"], "mult": 1.0, "health": False},
    "other": {"label": "Other", "expected": ["google_business", "facebook", "instagram"], "mult": 1.0, "health": False},
}

SIZES = {
    # key: label, audience benchmark (followers a healthy business this size typically has), reviews benchmark
    "sole": {"label": "Sole trader / 1 person", "followers": 300, "reviews": 20},
    "small": {"label": "Small (2–9 staff)", "followers": 1000, "reviews": 50},
    "medium": {"label": "Medium (10–49 staff)", "followers": 4000, "reviews": 150},
    "large": {"label": "Large (50–199 staff)", "followers": 15000, "reviews": 400},
    "enterprise": {"label": "Enterprise (200+ staff)", "followers": 50000, "reviews": 1000},
}

PATTERNS = {
    "facebook": r"https?://(?:www\.|m\.|web\.)?(?:facebook|fb)\.com/(?!sharer|share\.php|dialog|plugins|tr\b|tr\?|policies|privacy|help|login)[\w.\-/%?=&]+",
    "instagram": r"https?://(?:www\.)?instagram\.com/(?!p/|reel/|explore/|accounts/)[\w.\-]+/?",
    "tiktok": r"https?://(?:www\.)?tiktok\.com/@[\w.\-]+/?",
    "linkedin": r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in|school)/[\w\-%.]+/?",
    "youtube": r"https?://(?:www\.)?youtube\.com/(?:@[\w.\-]+|channel/[\w\-]+|c/[\w.\-]+|user/[\w.\-]+)/?",
    "x": r"https?://(?:www\.)?(?:twitter|x)\.com/(?!intent|share|home|i/)[A-Za-z0-9_]{1,15}/?",
    "pinterest": r"https?://(?:www\.|[a-z]{2}\.)?pinterest\.(?:com|com\.au)/(?!pin/)[\w.\-]+/?",
    "threads": r"https?://(?:www\.)?threads\.(?:net|com)/@[\w.\-]+/?",
    "google_business": r"https?://(?:(?:www\.)?google\.[a-z.]+/maps/(?:place|search)?[^\s\"'<>]*|maps\.app\.goo\.gl/[\w]+|g\.page/[\w\-/]+|goo\.gl/maps/[\w]+|share\.google/[\w]+)",
}
_JUNK = re.compile(r"(\.(js|css|png|jpg|svg|gif|webp)(\?|$))|/plugins/|/tr\?|/embed", re.I)


def detect_links(html: str, base_url: str = "") -> dict[str, str]:
    """Find a business's own social profile links in its website HTML (links, JSON-LD sameAs, etc.)."""
    text = html.replace("\\/", "/")
    found: dict[str, str] = {}
    for plat, rx in PATTERNS.items():
        counts: dict[str, int] = {}
        for m in re.finditer(rx, text, re.I):
            u = m.group(0).rstrip("\"'>)/.,;").split("#")[0]
            if _JUNK.search(u):
                continue
            if plat != "google_business":
                u = u.split("?")[0]
            counts[u] = counts.get(u, 0) + 1
        if counts:
            found[plat] = max(counts, key=lambda k: (counts[k], -len(k)))  # most-linked, shortest
    return found


# ---------------- YouTube (automatic, optional) ----------------
def youtube_stats(url: str) -> dict | None:
    key = os.getenv("YOUTUBE_API_KEY") or os.getenv("PAGESPEED_API_KEY") or ""
    if not key or not url:
        return None
    path = urlparse(url).path.strip("/")
    params = {"part": "statistics,contentDetails,snippet", "key": key}
    if path.startswith("@"):
        params["forHandle"] = path.split("/")[0]
    elif path.startswith("channel/"):
        params["id"] = path.split("/")[1]
    elif path.startswith("user/"):
        params["forUsername"] = path.split("/")[1]
    else:
        return None
    try:
        with httpx.Client(timeout=15) as h:
            r = h.get("https://www.googleapis.com/youtube/v3/channels", params=params)
            items = r.json().get("items") or []
            if r.status_code != 200 or not items:
                return None
            ch = items[0]
            st = ch.get("statistics", {})
            out = {"followers": int(st.get("subscriberCount", 0) or 0), "videos": int(st.get("videoCount", 0) or 0),
                   "views": int(st.get("viewCount", 0) or 0), "auto": True}
            uploads = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            if uploads:
                pr = h.get("https://www.googleapis.com/youtube/v3/playlistItems",
                           params={"part": "contentDetails", "playlistId": uploads, "maxResults": 50, "key": key}).json()
                dates = [datetime.fromisoformat(i["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00"))
                         for i in pr.get("items", []) if i.get("contentDetails", {}).get("videoPublishedAt")]
                if dates:
                    now = datetime.now(timezone.utc)
                    out["days_since_post"] = (now - max(dates)).days
                    out["posts_30d"] = sum(1 for d in dates if (now - d).days <= 30)
            return out
    except Exception:
        return None


# ---------------- Scoring ----------------
def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _grade(score):
    return None if score is None else "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "E"


def score_platform(platform: str, data: dict, size: str) -> dict:
    """Score one platform 0–100 from whatever figures are known. Unknown figures are left out, not guessed."""
    spec = PLATFORMS[platform]
    sz = SIZES.get(size, SIZES["small"])
    url = (data or {}).get("url", "")
    exists = bool(url) or bool(data.get("exists"))
    parts: list[tuple[str, float, float, str]] = []   # (name, points, max, note)
    notes: list[str] = []
    if not exists:
        return {"platform": platform, "label": spec["label"], "exists": False, "score": 0, "grade": "E", "assessed": True,
                "parts": [], "notes": [f"No {spec['label']} found. Add the link if they have one."]}
    parts.append(("Profile exists", 20, 20, "Linked from their website" if data.get("detected") else "Profile provided"))

    if platform == "google_business":
        rating, reviews = _num(data.get("rating")), _num(data.get("reviews"))
        if rating is not None:
            pts = max(0.0, min(1.0, (rating - 3.5) / 1.3)) * 30
            parts.append(("Star rating", pts, 30, f"{rating:.1f}★"))
            if rating < 4.3:
                notes.append(f"{rating:.1f}★ is below the ~4.5★ that most people filter for when choosing a local business.")
        if reviews is not None:
            ratio = reviews / sz["reviews"]
            pts = min(1.0, math.log1p(ratio * 9) / math.log(10)) * 30
            parts.append(("Number of reviews", pts, 30, f"{int(reviews):,} reviews (typical for size: ~{sz['reviews']:,})"))
            if ratio < 0.5:
                notes.append(f"Only {int(reviews)} reviews; similar-sized competitors typically have {sz['reviews']}+. A simple review-request routine fixes this.")
        posts = _num(data.get("posts_30d"))
        if posts is not None:
            parts.append(("Posts/updates (30 days)", min(1.0, posts / spec["posts_target"]) * 20, 20, f"{int(posts)} in last 30 days"))
            if posts == 0:
                notes.append("No Google Business posts in the last month. Posts and offers help them stand out in Maps.")
    else:
        followers, posts, days = _num(data.get("followers")), _num(data.get("posts_30d")), _num(data.get("days_since_post"))
        eng = _num(data.get("avg_engagement"))
        if followers is not None:
            ratio = followers / sz["followers"]
            pts = min(1.0, math.log1p(ratio * 9) / math.log(10)) * 25
            parts.append(("Audience size", pts, 25, f"{int(followers):,} followers (healthy for size: ~{sz['followers']:,})"))
            if ratio < 0.3:
                notes.append(f"Small audience for a business this size ({int(followers):,} vs ~{sz['followers']:,}).")
        if posts is not None or days is not None:
            act = 0.0
            if posts is not None:
                act = min(1.0, posts / spec["posts_target"])
            if days is not None:
                recency = 1.0 if days <= 7 else 0.7 if days <= 14 else 0.4 if days <= 30 else 0.15 if days <= 90 else 0.0
                act = recency if posts is None else (act * 0.6 + recency * 0.4)
                if days > 30:
                    notes.append(f"Last post was {int(days)} days ago; an inactive page makes the business look closed.")
            parts.append(("Posting activity", act * 30, 30,
                          ", ".join(x for x in [f"{int(posts)} posts in 30 days" if posts is not None else "",
                                                 f"last post {int(days)} days ago" if days is not None else ""] if x)))
            if posts is not None and posts < spec["posts_target"] / 2 and (days is None or days <= 30):
                notes.append(f"Posting {int(posts)}×/month; around {spec['posts_target']}×/month is typical for steady reach on {spec['label']}.")
        if spec["er"] and eng is not None and followers:
            er = eng / followers
            pts = min(1.0, er / spec["er"]) * 25
            parts.append(("Engagement rate", pts, 25, f"{er * 100:.2f}% per post (typical: ~{spec['er'] * 100:.1f}%)"))
            if er < spec["er"] * 0.5:
                notes.append(f"Engagement is {er * 100:.2f}% per post, under half the ~{spec['er'] * 100:.1f}% typical on {spec['label']}. Content isn't landing.")
        elif platform == "youtube" and data.get("views") and data.get("videos"):
            avg = data["views"] / max(1, data["videos"])
            parts.append(("Views per video", min(1.0, avg / max(200, sz["followers"] * 0.5)) * 25, 25, f"~{int(avg):,} views per video"))

    got = sum(p[1] for p in parts)
    mx = sum(p[2] for p in parts)
    assessed = mx > 20   # more than just "exists"
    score = round(100 * got / mx) if assessed else None
    if not assessed:
        notes.append("Enter a few figures from the public profile to score it.")
    return {"platform": platform, "label": spec["label"], "exists": True, "score": score, "grade": _grade(score), "assessed": assessed,
            "parts": [{"name": n, "points": round(p, 1), "max": m, "note": note} for n, p, m, note in parts], "notes": notes}


def social_summary(social: dict, industry: str, size: str) -> dict:
    ind = INDUSTRIES.get(industry, INDUSTRIES["other"])
    expected = ind["expected"]
    results = {}
    for plat in PLATFORMS:
        d = dict((social or {}).get(plat) or {})
        if plat in expected or d.get("url") or d.get("exists"):
            results[plat] = score_platform(plat, d, size)
    # overall: expected platforms count fully (missing = 0); extra active platforms can only add a small bonus
    exp_scores = [results[p]["score"] if results[p]["score"] is not None else 50 for p in expected]
    base = sum(exp_scores) / len(exp_scores) if exp_scores else 0
    extras = [r["score"] for p, r in results.items() if p not in expected and r["score"] is not None]
    bonus = min(5, sum(1 for s in extras if s >= 60) * 2.5)
    unassessed = [results[p]["label"] for p in expected if results[p]["exists"] and not results[p]["assessed"]]
    missing = [results[p]["label"] for p in expected if not results[p]["exists"]]
    score = round(min(100, base + bonus))
    return {"score": score, "grade": _grade(score), "platforms": results, "expected": expected,
            "missing": missing, "unassessed": unassessed, "estimated": bool(unassessed)}


def overall(website_score: int, social: dict) -> dict:
    score = round(website_score * 0.5 + social["score"] * 0.5)
    return {"score": score, "grade": _grade(score), "website": website_score, "social": social["score"]}


def health_compliance_notes(industry: str) -> list[str]:
    if not INDUSTRIES.get(industry, {}).get("health"):
        return []
    return [
        "Regulated health service: advertising must follow AHPRA's advertising guidelines (Health Practitioner Regulation National Law, s133).",
        "No testimonials or reviews about clinical care in their own ads, website or social posts. Reviews left on Google by patients are fine, but they can't be reposted or featured.",
        "No misleading claims, no creating unreasonable expectations of treatment outcomes, and gifts/discounts need clear terms.",
        "This is a selling point: many agencies get this wrong, and a compliant, specialist approach reduces their regulatory risk.",
    ]

