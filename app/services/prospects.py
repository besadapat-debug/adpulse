"""Prospect audit: score any business's website from the outside and draft a pitch.

Everything here is public: the page's HTML, robots.txt/sitemap, optional Google PageSpeed,
and links to the public ad transparency libraries."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import quote, urlparse

import httpx

from .. import db

UA = "Mozilla/5.0 (compatible; AdPulseAudit/1.0; +https://adpulse.example/audit)"

TRACKERS = {
    "Google Analytics 4": [r"gtag/js\?id=G-", r"['\"]G-[A-Z0-9]{6,}['\"]"],
    "Google Tag Manager": [r"googletagmanager\.com/gtm\.js", r"GTM-[A-Z0-9]{4,}"],
    "Google Ads conversion tag": [r"['\"/=]AW-\d{6,}"],
    "Meta Pixel": [r"connect\.facebook\.net/[^\"']*/fbevents\.js", r"fbq\(['\"]init"],
    "TikTok Pixel": [r"analytics\.tiktok\.com"],
    "LinkedIn Insight Tag": [r"snap\.licdn\.com", r"_linkedin_partner_id"],
    "Microsoft Clarity / Hotjar": [r"clarity\.ms", r"static\.hotjar\.com"],
}
CONSENT = [r"cookiebot", r"onetrust", r"cookieyes", r"iubenda", r"termly", r"complianz", r"cookie-consent", r"usercentrics"]
CTA_WORDS = re.compile(r"\b(book|call|quote|contact|get started|enquire|enquiry|buy|shop|free trial|demo|schedule|appointment)\b", re.I)


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in = None
        self.meta: dict[str, str] = {}
        self.h1: list[str] = []
        self.links: list[str] = []
        self.imgs = 0
        self.imgs_no_alt = 0
        self.forms = 0
        self.inputs_email = 0
        self.jsonld: list[str] = []
        self.canonical = ""
        self.lang = ""
        self.buttons: list[str] = []
        self.text_len = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title":
            self._in = "title"
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "h1":
            self._in = "h1"
            self.h1.append("")
        elif tag == "a":
            self.links.append(a.get("href", ""))
            self._in = "a"
            self.buttons.append("")
        elif tag == "button":
            self._in = "a"
            self.buttons.append("")
        elif tag == "img":
            self.imgs += 1
            if not a.get("alt", "").strip():
                self.imgs_no_alt += 1
        elif tag == "form":
            self.forms += 1
        elif tag == "input" and a.get("type", "") == "email":
            self.inputs_email += 1
        elif tag == "link" and "canonical" in a.get("rel", "").lower():
            self.canonical = a.get("href", "")
        elif tag == "script" and a.get("type", "") == "application/ld+json":
            self._in = "jsonld"
            self.jsonld.append("")

    def handle_endtag(self, tag):
        if tag in ("title", "h1", "a", "button", "script"):
            self._in = None

    def handle_data(self, data):
        self.text_len += len(data.strip())
        if self._in == "title":
            self.title += data
        elif self._in == "h1":
            self.h1[-1] += data
        elif self._in == "a" and self.buttons:
            self.buttons[-1] += data
        elif self._in == "jsonld":
            self.jsonld[-1] += data


def _safe_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    host = urlparse(url).hostname or ""
    if not host or "." not in host:
        raise ValueError("Enter a full website address, e.g. example.com.au")
    if os.getenv("ALLOW_PRIVATE_AUDIT") != "1":  # SSRF guard: never fetch internal addresses
        try:
            for info in socket.getaddrinfo(host, None):
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise ValueError("That address points to a private network")
        except socket.gaierror:
            raise ValueError(f"Couldn't find the website {host}")
    return url


GENERIC_TITLES = {"home", "homepage", "welcome", "index", "untitled", "home page"}


def _business_name(site_name: str, title: str, domain: str) -> str:
    if site_name.strip():
        return site_name.strip()[:80]
    first = re.split(r"\s[|–—-]\s|\s\|\s?|\|", title or "")[0].strip()
    if first and first.lower() not in GENERIC_TITLES and len(first) <= 40:
        return first
    label = domain.split(".")[0].replace("-", " ").replace("_", " ")
    return label.title() if label else domain


def fetch(url: str) -> dict:
    url = _safe_url(url)
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as h:
        t0 = time.time()
        r = h.get(url)
        elapsed = time.time() - t0
        extras = {}
        base = f"{r.url.scheme}://{r.url.host}"
        for path in ("/robots.txt", "/sitemap.xml"):
            try:
                x = h.get(base + path, timeout=8)
                extras[path] = x.status_code == 200 and len(x.text) > 20
            except Exception:
                extras[path] = False
    return {"requested": url, "final_url": str(r.url), "status": r.status_code, "html": r.text[:3_000_000], "bytes": len(r.content),
            "seconds": round(elapsed, 2), "robots": extras.get("/robots.txt", False), "sitemap": extras.get("/sitemap.xml", False)}


def pagespeed(url: str) -> dict | None:
    key = os.getenv("PAGESPEED_API_KEY", "")
    try:
        r = httpx.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                      params={"url": url, "strategy": "mobile", "category": "performance", **({"key": key} if key else {})}, timeout=60)
        if r.status_code != 200:
            return None
        lh = r.json()["lighthouseResult"]
        a = lh["audits"]
        return {"score": round(lh["categories"]["performance"]["score"] * 100),
                "lcp": a.get("largest-contentful-paint", {}).get("displayValue"), "cls": a.get("cumulative-layout-shift", {}).get("displayValue")}
    except Exception:
        return None


def analyse(page: dict, speed: dict | None = None) -> dict:
    html = page["html"]
    p = _Parser()
    try:
        p.feed(html)
    except Exception:
        pass
    final = urlparse(page["final_url"])
    domain = (final.hostname or "").removeprefix("www.")
    trackers = {name: any(re.search(rx, html, re.I) for rx in rxs) for name, rxs in TRACKERS.items()}
    has_consent = any(re.search(rx, html, re.I) for rx in CONSENT)
    tel = [h for h in p.links if h.lower().startswith("tel:")]
    ctas = [b.strip() for b in p.buttons if b.strip() and CTA_WORDS.search(b)]
    types = set()
    for block in p.jsonld:
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
            for it in items:
                t = it.get("@type") if isinstance(it, dict) else None
                types.update(t if isinstance(t, list) else [t] if t else [])
        except Exception:
            continue
    name = _business_name(p.meta.get("og:site_name", ""), p.title, domain)

    checks = []

    def add(key, ok, weight, title, fix, impact, area):
        checks.append({"key": key, "ok": bool(ok), "weight": weight, "title": title, "fix": fix, "impact": impact, "area": area})

    ads_tracking = trackers["Google Ads conversion tag"] or trackers["Meta Pixel"] or trackers["Google Tag Manager"]
    add("https", final.scheme == "https", 8, "Secure (HTTPS) website", "Install an SSL certificate and redirect all traffic to https.",
        "Browsers label http sites 'Not secure', which scares off enquiries and hurts Google rankings.", "Trust")
    add("analytics", trackers["Google Analytics 4"] or trackers["Google Tag Manager"], 10, "Website analytics installed",
        "Install Google Analytics 4 (ideally via Tag Manager).", "Without analytics they can't tell which marketing brings customers.", "Tracking")
    add("ads_tracking", ads_tracking, 12, "Ad conversion tracking (Google Ads tag / Meta Pixel)",
        "Add the Meta Pixel and Google Ads conversion tag, then track enquiries and sales.",
        "Any ads they run can't optimise toward real customers, so they're paying for clicks blindly.", "Tracking")
    add("meta_pixel", trackers["Meta Pixel"], 6, "Meta Pixel for retargeting", "Install the Meta Pixel with a consent banner.",
        "They can't retarget visitors on Facebook/Instagram — usually the cheapest customers to win back.", "Tracking")
    add("consent", has_consent or not any(trackers.values()), 4, "Cookie consent banner",
        "Add a consent banner (e.g. Cookiebot / CookieYes) before marketing tags fire.", "Needed for privacy compliance, and for Google Consent Mode.", "Compliance")
    add("viewport", "viewport" in p.meta, 8, "Mobile-friendly layout", "Add a responsive viewport and mobile layout.",
        "Most local searches happen on phones; a desktop-only page loses them.", "Conversion")
    add("click_to_call", bool(tel), 8, "Click-to-call phone link", "Make the phone number a tap-to-call link in the header.",
        "Mobile visitors who want to call can't do it in one tap.", "Conversion")
    add("cta", len(ctas) >= 1, 8, "Clear call-to-action buttons", "Add a prominent 'Get a quote' / 'Book now' button above the fold.",
        "Visitors don't know the next step, so they leave.", "Conversion")
    add("form", p.forms > 0 or p.inputs_email > 0, 6, "Enquiry or email capture form", "Add a short enquiry form and an email sign-up with a clear offer.",
        "No way to capture people who aren't ready to call yet.", "Conversion")
    add("title", 20 <= len(p.title.strip()) <= 65, 6, "Search title (20–65 chars)", f"Rewrite the page title to include the main service and location. Now: “{p.title.strip()[:70]}”",
        "The title is the headline in Google results; weak titles get fewer clicks.", "SEO")
    add("description", 70 <= len(p.meta.get("description", "")) <= 165, 5, "Meta description (70–165 chars)",
        "Write a meta description with the offer and a call to action.", "Google shows random page text instead, lowering click-through.", "SEO")
    add("h1", len(p.h1) == 1 and len(p.h1[0].strip()) > 3, 4, "One clear H1 heading", "Use exactly one H1 stating what they do and where.",
        "Search engines and visitors can't tell the page's main topic.", "SEO")
    add("schema", bool(types & {"LocalBusiness", "Organization", "Store", "ProfessionalService", "Restaurant", "MedicalBusiness", "Plumber", "Electrician", "Dentist", "LegalService", "AccountingService"}) or any("Business" in (t or "") for t in types),
        5, "Business structured data (schema.org)", "Add LocalBusiness/Organization JSON-LD with address, hours and phone.",
        "Missing out on rich results and the local map pack signals.", "SEO")
    add("social_share", bool(p.meta.get("og:title") and p.meta.get("og:image")), 3, "Social share preview (Open Graph)", "Add og:title, og:description and og:image tags.",
        "Links shared on Facebook/LinkedIn show a blank or ugly preview.", "SEO")
    add("alt", p.imgs == 0 or p.imgs_no_alt / p.imgs <= 0.2, 3, "Image alt text", f"{p.imgs_no_alt} of {p.imgs} images lack alt text — add short descriptions.",
        "Hurts accessibility and image search visibility.", "SEO")
    add("sitemap", page["sitemap"], 3, "XML sitemap", "Publish /sitemap.xml and submit it in Search Console.", "Google finds new pages slowly.", "SEO")
    add("speed", (speed["score"] >= 60) if speed else page["seconds"] < 2.5 and page["bytes"] < 3_000_000, 8,
        "Fast loading on mobile", "Compress images, defer scripts, use caching/CDN.",
        "Every extra second of load time loses a share of visitors before they see anything.", "Conversion")

    total = sum(c["weight"] for c in checks)
    score = round(100 * sum(c["weight"] for c in checks if c["ok"]) / total)
    fails = sorted([c for c in checks if not c["ok"]], key=lambda c: -c["weight"])
    return {
        "name": name[:80], "domain": domain, "url": page["final_url"], "status": page["status"], "score": score,
        "grade": "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "E",
        "load_seconds": page["seconds"], "page_kb": round(page["bytes"] / 1024), "pagespeed": speed,
        "trackers": trackers, "consent_banner": has_consent, "schema_types": sorted(t for t in types if t), "title": p.title.strip()[:120],
        "h1": [h.strip()[:120] for h in p.h1][:3], "ctas": ctas[:6], "phone_links": tel[:3],
        "checks": checks, "top_issues": fails[:5],
        "ad_library": {
            "meta": f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=AU&q={quote(name or domain)}&search_type=keyword_unordered",
            "google": f"https://adstransparency.google.com/?region=AU&domain={quote(domain)}",
            "linkedin": "https://www.linkedin.com/ad-library/",
            "tiktok": "https://library.tiktok.com/ads",
        },
    }


def _second_person(text: str) -> str:
    for a, b in (("They can't", "you can't"), ("they can't", "you can't"), ("they're", "you're"), ("Any ads they run", "any ads you run"),
                 ("They ", "you "), (" they ", " you "), ("Visitors don't", "visitors don't"), ("Search engines", "search engines"),
                 ("Most local", "most local"), ("Browsers", "browsers"), ("Google", "Google"), ("No way", "there's no way"),
                 ("Every extra", "every extra"), ("Links shared", "links shared"), ("Missing out", "you're missing out"),
                 ("Hurts", "it hurts"), ("Needed for", "it's needed for"), ("Mobile visitors", "mobile visitors"), ("Without analytics", "without analytics")):
        text = text.replace(a, b)
    return text


def pitch_email(report: dict, agency: str, sender: str = "") -> dict:
    issues = report["top_issues"][:3]
    bullets = "\n".join(f"• {i['title'].split(' (')[0]}: {_second_person(i['impact'])}" for i in issues)
    name = report["name"] or report["domain"]
    subject = f"{len(issues)} quick wins for {name}'s website" if issues else f"An idea for {name}'s marketing"
    body = (f"Hi {name} team,\n\n"
            f"I had a look at {report['domain']} and spotted a few things that are likely costing you enquiries:\n\n{bullets}\n\n"
            f"Each is a fairly quick fix, and together they'd make any advertising you run measurably more effective. "
            f"I've put the full audit together (it scored {report['score']}/100) and I'm happy to walk you through it in 15 minutes, no obligation.\n\n"
            f"Would Tuesday or Thursday this week suit?\n\n"
            f"Regards,\n{sender or '[Your name]'}\n{agency}\n\n"
            f"—\nI'm contacting you because your business address is publicly listed. Reply 'unsubscribe' and I won't contact you again.")
    return {"subject": subject, "body": body}


def run_audit(url: str, save: bool = True) -> dict:
    page = fetch(url)
    report = analyse(page, pagespeed(page["final_url"]))
    agency = db.one("SELECT name FROM agency WHERE id=1")["name"]
    report["pitch"] = pitch_email(report, agency)
    if save:
        report["id"] = db.execute("INSERT INTO prospects (url, domain, name, score, report) VALUES (?,?,?,?,?)",
                                  (report["url"], report["domain"], report["name"], report["score"], json.dumps(report)))
    return report

