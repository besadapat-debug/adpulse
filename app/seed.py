"""Demo seed: an agency with three clients, demo connections across every platform,
first-party contacts + behavioural journeys, audiences and alert rules."""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from . import db
from .connectors import PLATFORMS
from .security import encrypt_json, hash_password
from .services.alerts import ensure_default_rules
from .services.sync import sync_client

CLIENTS = [
    dict(name="Stride Running Co", slug="stride-running", industry="ecommerce", brand_color="#e4572e", monthly_budget=42000, target_roas=2.5, region="AU",
         platforms=["meta_ads", "google_ads", "tiktok_ads", "pinterest_ads", "amazon_ads", "ga4", "gsc", "dataforseo", "klaviyo", "instagram",
                    "facebook_page", "tiktok_organic", "youtube", "google_business"]),
    dict(name="Harbour Accounting", slug="harbour-accounting", industry="services", brand_color="#1d4ed8", monthly_budget=9000, target_cpa=85, region="AU",
         platforms=["google_ads", "meta_ads", "linkedin_ads", "ga4", "gsc", "bing_webmaster", "google_business", "mailchimp", "facebook_page", "linkedin_page"]),
    dict(name="Planwise Software", slug="planwise", industry="b2b", brand_color="#7c3aed", monthly_budget=28000, target_cpa=240, region="EU",
         platforms=["google_ads", "linkedin_ads", "meta_ads", "reddit_ads", "x_ads", "ga4", "gsc", "dataforseo", "hubspot", "linkedin_page", "x_organic", "youtube"]),
]
FIRST = ["Olivia", "Jack", "Mia", "Noah", "Charlotte", "Liam", "Amelia", "William", "Isla", "Oliver", "Ava", "Thomas", "Grace", "Lucas", "Chloe",
         "Henry", "Zoe", "James", "Ruby", "Ethan", "Sophie", "Leo", "Emily", "Harry", "Lily", "Mason", "Ella", "Max", "Harper", "Archie"]
LAST = ["Smith", "Nguyen", "Jones", "Williams", "Brown", "Wilson", "Taylor", "Johnson", "White", "Martin", "Anderson", "Thompson", "Tran", "Walker",
        "Harris", "Lee", "Ryan", "Robinson", "Kelly", "King", "Chen", "Patel", "Singh", "Murphy", "Wright"]
TOUCHES = [("google", "cpc", 0.24), ("facebook", "paid", 0.18), ("instagram", "paid", 0.10), ("google", "organic", 0.20), ("", "", 0.08),
           ("klaviyo", "email", 0.08), ("tiktok", "paid", 0.05), ("linkedin", "paid", 0.04), ("instagram", "social", 0.03)]


PAGES = {
    "ecommerce": {"landing": ["/", "/collections/trail", "/collections/road", "/blog/choosing-running-shoes", "/sale"],
                  "product": ["/products/trailblazer-gtx", "/products/tempo-lite", "/products/cloudrun-wide", "/products/marathon-pro"], "pricing": "/sale"},
    "services": {"landing": ["/", "/services/tax-returns", "/services/bookkeeping", "/services/small-business", "/about"],
                 "product": ["/services/tax-returns", "/services/business-structure", "/case-studies"], "pricing": "/pricing"},
    "b2b": {"landing": ["/", "/features", "/integrations", "/blog/capacity-planning", "/customers"],
            "product": ["/features/resource-planning", "/features/time-tracking", "/demo", "/security"], "pricing": "/pricing"},
}
CAMPAIGNS = {
    ("google", "cpc"): ["search-nonbrand", "search-brand", "pmax", "shopping-top-sellers"],
    ("facebook", "paid"): ["prospecting-broad", "retargeting-30d", "lead-gen-instant-form"],
    ("instagram", "paid"): ["prospecting-broad", "advantage-shopping"],
    ("tiktok", "paid"): ["spark-ugc", "smart-plus-conversions"],
    ("linkedin", "paid"): ["abm-decision-makers", "webinar-lead-gen"],
    ("klaviyo", "email"): ["weekly-newsletter", "mid-season-sale"],
}
# Fictional demo businesses (".example" domains) for the B2B company-visitor view
COMPANIES = {
    "b2b": [("Brightline Logistics", "brightline-logistics.example", "Logistics", "200–500", "Melbourne"),
            ("Kestrel Creative", "kestrel-creative.example", "Marketing agency", "20–50", "Sydney"),
            ("Harbourview Health", "harbourview-health.example", "Healthcare", "500–1,000", "Brisbane"),
            ("Southgate Engineering", "southgate-eng.example", "Engineering", "50–200", "Adelaide"),
            ("Tidewater Legal", "tidewater-legal.example", "Legal", "20–50", "Perth"),
            ("Northwind Studios", "northwind-studios.example", "Architecture", "10–20", "Melbourne"),
            ("Copperleaf Retail Group", "copperleaf.example", "Retail", "1,000+", "Sydney"),
            ("Meridian Build", "meridian-build.example", "Construction", "200–500", "Geelong"),
            ("Aster Consulting", "aster-consulting.example", "Consulting", "50–200", "Canberra"),
            ("Lumen EdTech", "lumen-edtech.example", "Education", "20–50", "Hobart")],
    "services": [("Coastal Cafés Pty Ltd", "coastal-cafes.example", "Hospitality", "20–50", "Frankston"),
                 ("Ridgeway Plumbing", "ridgeway-plumbing.example", "Trades", "10–20", "Dandenong"),
                 ("Bayside Physio", "bayside-physio.example", "Healthcare", "10–20", "Brighton"),
                 ("Greenfield Landscapes", "greenfield-landscapes.example", "Trades", "5–10", "Ringwood"),
                 ("Parkline Dental", "parkline-dental.example", "Healthcare", "10–20", "Box Hill"),
                 ("Summit Electrical", "summit-electrical.example", "Trades", "20–50", "Werribee")],
}


EXCLUDE = {"ecommerce": {"linkedin"}, "services": {"tiktok"}, "b2b": {"tiktok", "klaviyo"}}


def _pick(r, industry="ecommerce"):
    x, acc = r.random(), 0
    touches = [t for t in TOUCHES if t[0] not in EXCLUDE.get(industry, set())]
    tot = sum(t[2] for t in touches)
    x *= tot
    for s, m, p in touches:
        acc += p
        if x <= acc:
            return s, m
    return "", ""


def seed(email="demo@agency.test", password="demo1234", sync=True) -> None:
    if db.one("SELECT id FROM clients LIMIT 1"):
        return
    r = random.Random(42)
    db.execute("INSERT OR IGNORE INTO users (email, name, password_hash, role) VALUES (?,?,?, 'owner')", (email, "Demo Owner", hash_password(password)))
    db.execute("UPDATE agency SET name='Northbeam Digital', brand_color='#4f46e5' WHERE id=1")
    ensure_default_rules()
    seed_example_prospects()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for spec in CLIENTS:
        cid = db.execute("INSERT INTO clients (name, slug, industry, brand_color, monthly_budget, target_roas, target_cpa, region, report_footer) VALUES (?,?,?,?,?,?,?,?,?)",
                         (spec["name"], spec["slug"], spec["industry"], spec["brand_color"], spec["monthly_budget"], spec.get("target_roas", 0),
                          spec.get("target_cpa", 0), spec["region"], "Prepared by Northbeam Digital · hello@northbeam.example"))
        for p in spec["platforms"]:
            db.execute("INSERT INTO connections (client_id, platform, account_id, account_name, credentials_enc, is_demo) VALUES (?,?,?,?,?,1)",
                       (cid, p, f"demo-{r.randint(100000, 999999)}", f"{spec['name']} – {PLATFORMS[p]['label']}", encrypt_json({})))
        # contacts + journeys
        aov = {"ecommerce": 110, "services": 380, "b2b": 1600}[spec["industry"]]
        rows_c, rows_e = [], []
        for i in range(700):
            fn, ln = r.choice(FIRST), r.choice(LAST)
            consent = r.random() < 0.78
            rows_c.append((cid, f"{fn.lower()}.{ln.lower()}{i}@example.com", f"04{r.randint(10000000, 99999999)}", fn, ln, "AU" if spec["region"] == "AU" else "DE",
                           str(r.randint(2000, 3999)), int(consent), "checkout_optin" if consent else "", now.isoformat(timespec="seconds") if consent else None))
        with db.tx() as c:
            c.executemany("INSERT INTO contacts (client_id, email, phone, first_name, last_name, country, postcode, consent_marketing, consent_source, consent_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?)", rows_c)
            ids = [x["id"] for x in c.execute("SELECT id FROM contacts WHERE client_id=?", (cid,)).fetchall()]
        pages = PAGES[spec["industry"]]
        comp_ids = []
        if spec["industry"] in ("b2b", "services"):
            for cname, dom, ind, emp, city in COMPANIES[spec["industry"]]:
                comp_ids.append(db.execute("INSERT INTO companies (client_id, domain, name, industry, employees, city, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?)",
                                           (cid, dom, cname, ind, emp, city, now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"))))
        for n, contact_id in enumerate(ids + [None] * 900):
            anon = f"anon-{cid}-{n}"
            eagerness = r.random() ** 1.6
            company = None
            if comp_ids and contact_id is None and r.random() < 0.12:
                company = comp_ids[min(len(comp_ids) - 1, int(len(comp_ids) * r.random() ** 1.8))]  # a few companies visit a lot
                eagerness = min(1.0, eagerness + 0.25)
            t = now - timedelta(days=60 * r.random() ** 1.4, hours=r.uniform(0, 24))

            def add(ev, url, dur=0, value=0, src="", med="", camp=""):
                rows_e.append((cid, contact_id, anon, ev, url, value, src, med, camp, t.isoformat(timespec="seconds"), round(dur), company))

            for _ in range(1 + int(eagerness * 7)):
                s, m = _pick(r, spec["industry"])
                camp = r.choice(CAMPAIGNS.get((s, m), [""]))
                add("page_view", r.choice(pages["landing"]), r.uniform(8, 150), 0, s, m, camp)
                for ev, p in (("product_view", 0.6), ("pricing_view", 0.35 * eagerness + 0.05), ("add_to_cart", 0.3 * eagerness),
                              ("email_click", 0.1 if contact_id else 0), ("form_start", 0.15 * eagerness)):
                    if r.random() < p:
                        t += timedelta(minutes=r.uniform(1, 12))
                        url = {"product_view": r.choice(pages["product"]), "pricing_view": pages["pricing"], "add_to_cart": "/cart",
                               "form_start": "/contact", "email_click": r.choice(pages["landing"])}[ev]
                        dur = {"product_view": r.uniform(20, 240), "pricing_view": r.uniform(30, 320)}.get(ev, 0)
                        add(ev, url, dur)
                if r.random() < 0.05 + 0.25 * eagerness:
                    t += timedelta(minutes=r.uniform(2, 30))
                    ev = "lead" if spec["industry"] != "ecommerce" else "purchase"
                    add(ev, "/thanks", 0, round(aov * r.uniform(0.5, 1.8), 2))
                    if contact_id and ev == "purchase":
                        db.execute("UPDATE contacts SET is_customer=1 WHERE id=?", (contact_id,))
                    break
                t += timedelta(days=r.uniform(0.2, 6))
                if t > now:
                    break
        with db.tx() as c:
            c.executemany("INSERT INTO events (client_id, contact_id, anon_id, event, url, value, source, medium, campaign, ts, duration_sec, company_id) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows_e)
        for name, d in (("Hot – ready to buy (score 70+)", {"min_score": 70, "lookback_days": 30}),
                        ("Warm – nurture (40–69)", {"min_score": 40, "max_score": 69, "lookback_days": 30}),
                        ("Customers – exclusion & lookalike seed", {"customers_only": True, "lookback_days": 365})):
            db.execute("INSERT INTO audiences (client_id, name, definition) VALUES (?,?,?)", (cid, name, json.dumps(d)))
        if sync:
            sync_client(cid, full=True)


EXAMPLE_SITES = [
    ("https://www.ridgeway-plumbing.example/", 1.9, 2_400_000, False, """<html lang="en"><head><title>Home</title></head><body>
      <h1>Welcome</h1><h1>Ridgeway Plumbing</h1><p>Call us on 03 9000 0000 for all your plumbing needs.</p>
      <img src="a.jpg"><img src="b.jpg"><img src="van.jpg"><a href="/services">Services</a><a href="/about">About us</a>
      <script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC1234XYZ"></script></body></html>"""),
    ("https://www.coastalcafes.example/", 3.8, 5_900_000, True, """<html lang="en"><head><title>Coastal Cafés | Brunch &amp; Coffee on the Bayside, Frankston</title>
      <meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="Award-winning brunch and specialty coffee across three bayside cafés. Book a table or order catering online.">
      <meta property="og:title" content="Coastal Cafés"><meta property="og:image" content="/og.jpg"><meta property="og:site_name" content="Coastal Cafés">
      <script>!function(f,b,e,v,n,t,s){}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init','1234567890');</script>
      <script type="application/ld+json">{"@context":"https://schema.org","@type":"Restaurant","name":"Coastal Cafés"}</script></head>
      <body><h1>Bayside brunch, done properly</h1><a href="tel:+61390000001">03 9000 0001</a><a class="btn" href="/book">Book a table</a>
      <form><input type="email" name="email"><button>Join the newsletter</button></form><img src="x.jpg" alt="Smashed avo"></body></html>"""),
    ("https://www.summitelectrical.example/", 1.1, 900_000, True, """<html lang="en"><head><title>Summit Electrical | Licensed Electricians in Werribee &amp; Hoppers Crossing</title>
      <meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="Fast, licensed electricians in Werribee. Switchboard upgrades, EV chargers, safety checks. Get a free quote today — same-day callouts.">
      <script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABCD12"></script><script>gtag('config','AW-123456789');</script>
      <script src="https://consent.cookiebot.com/uc.js"></script>
      <script type="application/ld+json">{"@context":"https://schema.org","@type":"Electrician","name":"Summit Electrical"}</script></head>
      <body><h1>Werribee electricians, on time</h1><a href="tel:0390000002">Call now</a><a href="/quote">Get a free quote</a><form><input type="email"></form></body></html>"""),
]


def seed_example_prospects():
    from .services.prospects import analyse, pitch_email
    agency = db.one("SELECT name FROM agency WHERE id=1")["name"]
    for url, secs, size, sitemap, html in EXAMPLE_SITES:
        rep = analyse({"final_url": url, "html": html, "status": 200, "seconds": secs, "bytes": size, "sitemap": sitemap, "robots": True})
        rep["pitch"] = pitch_email(rep, agency)
        status = {"ridgeway-plumbing.example": "contacted", "coastalcafes.example": "new", "summitelectrical.example": "meeting"}.get(rep["domain"], "new")
        db.execute("INSERT INTO prospects (url, domain, name, score, report, status, is_example) VALUES (?,?,?,?,?,?,1)",
                   (url, rep["domain"], rep["name"], rep["score"], json.dumps(rep), status))


if __name__ == "__main__":
    seed()
    print("Seeded. Log in with demo@agency.test / demo1234")
