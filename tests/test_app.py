import os
import tempfile

import pytest

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DEMO_MODE"] = "true"
os.environ["SYNC_INTERVAL_MINUTES"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import audiences as aud  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/login", data={"email": "demo@agency.test", "password": "demo1234"}, follow_redirects=False)
        assert r.status_code == 303
        yield c


def test_requires_login():
    with TestClient(app) as c:
        assert c.get("/api/overview").status_code == 401
        assert c.get("/", follow_redirects=False).status_code in (302, 307)


def test_pages_render(client):
    for path in ["/", "/clients/1", "/settings"]:
        r = client.get(path)
        assert r.status_code == 200, path


def test_overview_and_tabs(client):
    ov = client.get("/api/overview").json()
    assert len(ov["clients"]) == 3 and all(c["spend"] > 0 for c in ov["clients"])
    for tab in ["performance", "organic", "seo", "email", "attribution", "budget", "alerts", "connections", "audiences", "targeting", "privacy"]:
        r = client.get(f"/api/clients/1/{tab}")
        assert r.status_code == 200, tab


def test_alerts_fire_on_seeded_problems(client):
    alerts = [a for c in (1, 2, 3) for a in client.get(f"/api/clients/{c}/alerts").json()]
    assert alerts, "demo data includes deliberate CPA blow-outs / ranking drops"


def test_consent_is_enforced():
    # withdraw consent for every contact of client 1 → nothing may be exported
    cid = 1
    total = len(aud.members(cid, {"min_score": 0}))
    assert total > 0
    first = db.one("SELECT id FROM contacts WHERE client_id=? AND consent_marketing=1 LIMIT 1", (cid,))
    db.execute("UPDATE contacts SET consent_marketing=0 WHERE id=?", (first["id"],))
    ids = {m["id"] for m in aud.members(cid, {"min_score": 0})}
    assert first["id"] not in ids
    assert all(m["consent_marketing"] == 1 and m["deleted_at"] is None for m in aud.members(cid, {"min_score": 0, "include_customers": True}))


def test_hashing_normalisation():
    assert aud.norm_email("  John.Smith+ads@Gmail.com ", google=True) == "johnsmith@gmail.com"
    assert aud.norm_email(" A@B.com ") == "a@b.com"
    assert aud.norm_phone("0412 345 678", "AU") == "+61412345678"
    assert aud.norm_phone("+1 (415) 555-0100") == "+14155550100"
    assert len(aud.sha("x")) == 64


def test_audience_sync_and_export(client):
    r = client.post("/api/audiences/1/sync/meta_ads").json()
    assert r["ok"]
    csv = client.get("/api/clients/1/audiences/1/export/google_ads.csv")
    assert csv.status_code == 200 and csv.text.startswith("Email,Phone")
    assert "@" not in csv.text  # hashed only


def test_erasure(client):
    c = db.one("SELECT email FROM contacts WHERE client_id=2 AND consent_marketing=1 LIMIT 1")
    assert client.post("/api/clients/2/privacy/erase", json={"email": c["email"]}).json()["erased"]
    row = db.one("SELECT * FROM contacts WHERE client_id=2 AND email=?", (c["email"],))
    assert row["deleted_at"] and not row["consent_marketing"]
    assert not db.one("SELECT id FROM events WHERE contact_id=?", (row["id"],))


def test_budget_conserves_total(client):
    b = client.get("/api/clients/1/budget?budget=30000").json()
    assert abs(sum(c["recommended_monthly"] for c in b["channels"]) - 30000) < 60
    for c in b["channels"]:
        assert abs(c["recommended_monthly"] / (c["current_monthly"] * 30000 / sum(x["current_monthly"] for x in b["channels"])) - 1) <= 0.31


def test_attribution_models_sum(client):
    a = client.get("/api/clients/1/attribution").json()
    for m in a["models"]:
        assert abs(sum(r[m]["conversions"] for r in a["table"]) - a["conversions"]) < 0.5


def test_tracking_collect_and_identify():
    with TestClient(app) as c:
        assert "__ENDPOINT__" not in c.get("/t.js").text
        c.post("/collect", content='{"c":"stride-running","a":"t-1","e":"pricing_view","s":"google","m":"cpc"}')
        c.post("/collect", content='{"c":"stride-running","a":"t-1","e":"identify","p":{"email":"new.person@example.com","consent":true}}')
    ct = db.one("SELECT * FROM contacts WHERE email='new.person@example.com'")
    assert ct and ct["consent_marketing"] == 1
    assert db.one("SELECT contact_id FROM events WHERE anon_id='t-1'")["contact_id"] == ct["id"]


def test_report_link(client):
    url = client.post("/api/clients/1/report-link").json()["url"]
    r = client.get(url[url.index("/r/"):])
    assert r.status_code == 200 and "Stride Running Co" in r.text
    assert client.get("/r/forged.token").status_code == 404


def test_engagement(client):
    e = client.get("/api/clients/1/engagement").json()
    assert e["platforms"] and any(p["avg_watch_sec"] for p in e["platforms"])
    assert "individual" in e["note"]


def test_people_only_consented(client):
    ppl = client.get("/api/clients/1/people").json()["people"]
    assert ppl
    ids = {p["id"] for p in ppl}
    non = db.rows("SELECT id FROM contacts WHERE client_id=1 AND (consent_marketing=0 OR deleted_at IS NOT NULL)")
    assert not ids & {r["id"] for r in non}
    d = client.get(f"/api/clients/1/people/{ppl[0]['id']}").json()
    assert d["timeline"] and d["totals"]["pageviews"] >= 1
    if non:
        assert client.get(f"/api/clients/1/people/{non[0]['id']}").status_code == 404


def test_companies(client):
    cos = client.get("/api/clients/3/companies").json()["companies"]
    assert cos and cos[0]["score"] >= cos[-1]["score"]
    d = client.get(f"/api/clients/3/companies/{cos[0]['id']}").json()
    assert all(t["visitor"].startswith("Visitor") and "anon_id" not in t for t in d["timeline"])


def test_time_on_page_folds_into_view():
    with TestClient(app) as c:
        c.post("/collect", content='{"c":"stride-running","a":"t-2","e":"page_view","u":"/sale","s":"facebook","m":"paid","cp":"prospecting-broad"}')
        c.post("/collect", content='{"c":"stride-running","a":"t-2","e":"page_leave","u":"/sale","d":42}')
        c.post("/collect", content='{"c":"stride-running","a":"t-2","e":"page_leave","u":"/sale","d":8}')
        c.post("/collect", content='{"c":"stride-running","a":"t-2","e":"identify","p":{"email":"timer@example.com","consent":true}}')
    from app.services.visitors import person_detail
    cid = db.one("SELECT id FROM contacts WHERE email='timer@example.com'")["id"]
    d = person_detail(1, cid)
    view = [t for t in d["timeline"] if t["event"] == "page_view"][0]
    assert view["duration_sec"] == 50 and d["first_touch"]["campaign"] == "prospecting-broad"


def test_prospect_analysis_and_ssrf_guard():
    from app.services import prospects
    r = prospects.analyse({"final_url": "https://www.acme-roofing.example/", "status": 200, "seconds": 1.0, "bytes": 1000, "sitemap": False, "robots": False,
                           "html": "<html><head><title>Home</title></head><body><h1>Roofs</h1></body></html>"})
    assert r["name"] == "Acme Roofing" and r["score"] < 50 and r["top_issues"][0]["key"] == "ads_tracking"
    for bad in ("http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/"):
        with pytest.raises(ValueError):
            prospects._safe_url(bad)


def test_prospects_api(client):
    rows = client.get("/api/prospects").json()
    assert len(rows) >= 3
    d = client.get(f"/api/prospects/{rows[0]['id']}").json()
    assert d["pitch"]["subject"] and "unsubscribe" in d["pitch"]["body"]
    assert client.post("/api/prospects", json={"url": "http://127.0.0.1:8000"}).status_code == 400
    assert client.get("/prospects").status_code == 200


def test_social_link_detection():
    from app.services.social import detect_links
    html = ('<a href="https://www.facebook.com/acmephysio/">f</a><a href="https://www.facebook.com/sharer/sharer.php?u=1">s</a>'
            '<img src="https://www.facebook.com/tr?id=9"><a href="https://instagram.com/acme.physio">i</a>'
            '<script>{"sameAs":["https:\\/\\/www.linkedin.com\\/company\\/acme-physio\\/"]}</script>'
            '<a href="https://twitter.com/intent/tweet?text=x">t</a><a href="https://maps.app.goo.gl/Xyz123">m</a>')
    d = detect_links(html)
    assert d["facebook"] == "https://www.facebook.com/acmephysio"
    assert d["instagram"].endswith("acme.physio") and "linkedin" in d and "google_business" in d
    assert "x" not in d  # share/intent links are ignored


def test_social_scoring_and_missing_platforms():
    from app.services.social import social_summary
    strong = social_summary({"google_business": {"exists": True, "rating": 4.8, "reviews": 90, "posts_30d": 4},
                             "facebook": {"url": "u", "followers": 1500, "posts_30d": 8, "days_since_post": 2, "avg_engagement": 8},
                             "instagram": {"url": "u", "followers": 1400, "posts_30d": 9, "days_since_post": 1, "avg_engagement": 30}}, "physio", "small")
    weak = social_summary({"facebook": {"url": "u", "followers": 90, "posts_30d": 0, "days_since_post": 120, "avg_engagement": 0}}, "physio", "small")
    assert strong["score"] >= 85 and weak["score"] < 30
    assert "Google Business Profile" in weak["missing"] and "Instagram" in weak["missing"]


def test_quote_tiers_scale_with_size():
    from app.services import pricing, social
    rep = {"checks": [{"key": "analytics", "ok": False}, {"key": "cta", "ok": False}], "score": 40}
    ss = social.social_summary({}, "dental", "small")
    small = pricing.build_quote(rep, {"industry": "dental", "size": "small", "locations": 1}, ss, pricing.DEFAULT_RATE_CARD)
    large = pricing.build_quote(rep, {"industry": "dental", "size": "large", "locations": 3}, ss, pricing.DEFAULT_RATE_CARD)
    by = lambda q: {t["name"]: t for t in q["tiers"]}
    s, l = by(small), by(large)
    assert [t["name"] for t in small["tiers"]] == ["Starter", "Local Lite", "Essentials", "Growth", "Premium"]
    assert [t["name"] for t in large["tiers"]] == ["Starter", "Essentials", "Growth", "Premium"]
    assert s["Local Lite"]["monthly_total"] < s["Essentials"]["monthly_total"] < s["Growth"]["monthly_total"] < s["Premium"]["monthly_total"]
    assert l["Growth"]["monthly_total"] > s["Growth"]["monthly_total"] and l["Growth"]["ad_spend"] > s["Growth"]["ad_spend"]
    assert s["Growth"]["recommended"] and any("Tracking" in i["item"] for i in s["Growth"]["setup"])
    assert s["Starter"]["starter"] and 0 < s["Starter"]["setup_total"] < s["Growth"]["setup_total"] + s["Growth"]["monthly_total"]
    assert s["Starter"]["payback"] is None


def test_sole_trader_pricing_and_market():
    from app.services import market, pricing, social
    rep = {"checks": [{"key": "analytics", "ok": False}], "score": 40}
    ss = social.social_summary({}, "trades", "sole")
    q = pricing.build_quote(rep, {"industry": "trades", "size": "sole", "locations": 1}, ss, pricing.DEFAULT_RATE_CARD)
    t = {x["name"]: x for x in q["tiers"]}
    assert list(t) == ["Starter", "Local Lite", "Essentials", "Growth"] and t["Local Lite"]["recommended"]
    assert t["Local Lite"]["monthly_total"] <= 300 and t["Local Lite"]["setup_total"] == 0
    assert t["Growth"]["ad_spend"] >= 1000      # never suggest ads below the minimum useful spend
    assert any(i["amount"] == 350 for i in t["Growth"]["monthly"] if "ads" in i["item"].lower())
    m = market.comparison("trades", q)
    assert any("hipages" in r["label"] and r["industry_specific"] for r in m["rows"])
    assert any("Local Lite" in y and "hipages" in y for y in m["you"])
    assert all(r["url"].startswith("https://") for r in m["rows"])


def test_competitors(client, monkeypatch):
    from app.services import competitors
    pid = next(p["id"] for p in client.get("/api/prospects").json() if p["domain"] == "ridgeway-plumbing.example")
    r = client.get(f"/api/prospects/{pid}").json()
    assert r["business"]["search_term"] == "plumber"
    # by hand
    r = client.patch(f"/api/prospects/{pid}", json={"competitors": [{"name": "Big Pipes", "rating": 4.8, "reviews": 240, "manual": True},
                                                                   {"name": "Small Drains", "rating": 4.1, "reviews": 9, "manual": True}]}).json()
    cs = r["competitor_summary"]
    assert cs["top"]["name"] == "Big Pipes" and cs["my_reviews"] == 18 and cs["rank"] == 2
    assert "Big Pipes nearby has 240 reviews" in r["pitch"]["body"]
    assert "Fewer Google reviews than nearby competitors" in client.get(f"/prospects/{pid}/print").text
    # automatic (Google Places), with the network call replaced
    monkeypatch.setattr(competitors, "api_key", lambda: "k")
    monkeypatch.setattr(competitors, "find", lambda term, area, d, n: [
        {"name": "Ridgeway Plumbing", "rating": 4.3, "reviews": 20, "website": "https://ridgeway-plumbing.example", "is_self": True},
        {"name": "Aqua Pros", "rating": 4.9, "reviews": 130, "website": "", "is_self": False}])
    r = client.post(f"/api/prospects/{pid}/competitors", json={"search_term": "plumber", "area": "Berwick VIC"}).json()
    names = [c["name"] for c in r["competitors"]["list"]]
    assert "Aqua Pros" in names and "Big Pipes" in names and r["business"]["area"] == "Berwick VIC"
    assert "maps/search/plumber+near+Berwick+VIC" in r["maps_link"]


def test_competitor_find_needs_key(monkeypatch):
    from app.services import competitors
    monkeypatch.setattr(competitors, "api_key", lambda: "")
    import pytest
    with pytest.raises(ValueError):
        competitors.find("plumber", "Berwick", "", "")


def test_payback_calculator():
    from app.services import pricing, social
    rep = {"checks": [{"key": "cta", "ok": False}], "top_issues": [{"title": "CTA", "problem": "No clear call-to-action"}], "score": 50}
    ss = social.social_summary({}, "pharmacy", "small")
    q = pricing.build_quote(rep, {"industry": "pharmacy", "size": "small", "customer_spend": 1000, "margin_pct": 30}, ss, pricing.DEFAULT_RATE_CARD)
    assert q["customer_value"] == 300
    st, g = q["tiers"][0], next(t for t in q["tiers"] if t["name"] == "Growth")
    assert st["payback"]["customers_per_year"] == round(st["setup_total"] / 300, 1)
    year = g["setup_total"] + 12 * (g["monthly_total"] + g["ad_spend"])
    assert g["payback"]["customers_per_month"] == round(year / 300 / 12, 1)
    assert "No clear call-to-action" in st["setup"][-1]["detail"]


def test_prospect_social_and_pricing_api(client):
    opts = client.get("/api/prospects/options").json()
    assert any(i["key"] == "pharmacy" and i["health"] for i in opts["industries"])
    pid = client.get("/api/prospects").json()[0]["id"]
    r = client.patch(f"/api/prospects/{pid}", json={"business": {"industry": "pharmacy", "size": "medium", "locations": 2, "mention_pricing": True},
                                                   "social": {"instagram": {"url": "https://instagram.com/x", "followers": "1,200", "posts_30d": 3,
                                                                            "days_since_post": 5, "avg_engagement": 20}}}).json()
    assert r["business"]["industry"] == "pharmacy" and r["compliance"]
    assert r["social_summary"]["platforms"]["instagram"]["score"] is not None
    assert "Growth package would be $" in r["pitch"]["body"] and "AHPRA" in r["pitch"]["body"]
    assert r["rank"]["overall_count"] >= 1


def test_rate_card_changes_prices(client):
    pid = client.get("/api/prospects").json()[0]["id"]
    before = client.get(f"/api/prospects/{pid}").json()["quote"]["tiers"][-2]["monthly_total"]
    rc = client.get("/api/rate-card").json()["rates"]
    client.put("/api/rate-card", json={**rc, "social_monthly": rc["social_monthly"] * 2, "seo_monthly": rc["seo_monthly"] * 2})
    after = client.get(f"/api/prospects/{pid}").json()["quote"]["tiers"][-2]["monthly_total"]
    assert after > before
    client.put("/api/rate-card", json=client.get("/api/rate-card").json()["defaults"])


def test_print_leave_behind(client):
    pid = client.get("/api/prospects").json()[0]["id"]
    client.patch("/api/agency", json={"phone": "0400 000 000", "email": "hello@agency.test"})
    r = client.patch(f"/api/prospects/{pid}", json={"business": {"customer_spend": 800, "margin_pct": 40, "mention_pricing": True}}).json()
    assert r["quote"]["customer_value"] == 320 and "Starter quick wins" in r["pitch"]["body"] and "pays for itself" in r["pitch"]["body"]
    html = client.get(f"/prospects/{pid}/print").text
    assert "Free digital check-up" in html and "0400 000 000" in html and "Starter: quick wins" in html and "Pays for itself" in html
    assert 'class="noprice"' in client.get(f"/prospects/{pid}/print?prices=0").text


def test_price_check_verdicts():
    from app.services import pricing, social
    rep = {"checks": [{"key": "analytics", "ok": False}, {"key": "cta", "ok": False}], "top_issues": [{"problem": "a"}], "score": 40}
    ss = social.social_summary({}, "trades", "sole")
    q = pricing.build_quote(rep, {"industry": "trades", "size": "sole", "revenue": 180000}, ss, pricing.DEFAULT_RATE_CARD)
    pc = {r["name"]: r for r in q["price_check"]["rows"]}
    assert pc["Growth"]["verdict"] == "too_expensive" and pc["Local Lite"]["verdict"] == "good"
    assert q["price_check"]["best"] == "Local Lite"
    rc = {**pricing.DEFAULT_RATE_CARD, "your_hourly_rate": 500}
    q2 = pricing.build_quote(rep, {"industry": "trades", "size": "sole"}, ss, rc)
    assert all(r["verdict"] == "too_cheap" for r in q2["price_check"]["rows"]) and q2["price_check"]["best"] is None


def test_ai_review(client, monkeypatch):
    from app.services import ai
    pid = client.get("/api/prospects").json()[0]["id"]
    monkeypatch.setattr(ai, "api_key", lambda: "")
    assert client.post(f"/api/prospects/{pid}/ai-review").status_code == 400
    sent = {}

    class Resp:
        status_code = 200
        def json(self):
            return {"content": [{"type": "text", "text": '```json\n{"lead_with": "Local Lite", "suggested_monthly": 280, "why": "Fits their budget.",'
                                                          ' "say_this": "Start small.", "change": ["Drop Instagram"], "ask_them": [], "watch_out": []}\n```'}]}

    def fake_post(url, **kw):
        sent.update(kw["json"])
        return Resp()
    monkeypatch.setattr(ai, "api_key", lambda: "k")
    monkeypatch.setattr(ai.httpx, "post", fake_post)
    r = client.post(f"/api/prospects/{pid}/ai-review").json()
    assert r["ai_review"]["lead_with"] == "Local Lite" and r["ai_review"]["change"] == ["Drop Instagram"] and not r["ai_review"]["stale"]
    assert "price_check" in sent["messages"][0]["content"] and sent["model"]
    client.patch(f"/api/prospects/{pid}", json={"business": {"size": "large"}})
    assert client.get(f"/api/prospects/{pid}").json()["ai_review"]["stale"]


def test_industry_from_domain():
    from app.services import prospects
    rep = {"name": "East Bentleigh Pharm", "title": "Home", "h1": [], "domain": "eastbentleighpharmacy.com.au", "industry_guess": "other",
           "score": 48, "checks": [], "top_issues": [], "business": {"industry": "other", "size": "small"}}
    out = prospects.enrich(rep)
    assert out["business"]["industry"] == "pharmacy" and out["compliance"]
    rep2 = {**rep, "industry_guess": "other", "business": {"industry": "other", "industry_set": True}}
    assert prospects.enrich(rep2)["business"]["industry"] == "other"     # a choice you made yourself is kept


def test_ai_prompt_copy(client):
    pid = client.get("/api/prospects").json()[0]["id"]
    t = client.get(f"/api/prospects/{pid}/ai-prompt").json()["text"]
    assert "Lead with" in t and "price_check" in t and "packages" in t


def test_ad_budget_calculator():
    from app.services import adbudget, pricing
    rc = pricing.DEFAULT_RATE_CARD
    # 4 customers, $5 clicks, 10% enquire, 50% buy -> 80 clicks -> $400; each customer $100
    x = adbudget.evaluate({"platform": "google", "customers": 4, "cpc": 5, "conv": 10, "close": 50, "value": 400}, "pharmacy", rc, None, 0)
    assert x["clicks"] == 80 and x["budget"] == 400 and x["cost_per_customer"] == 100 and x["verdict"] == "too_small"
    assert x["min_budget"] == 1000 and x["fast_budget"] > 2000 and x["profit"] == 1200
    # budget mode works backwards
    y = adbudget.evaluate({"platform": "google", "budget": 3000, "cpc": 5, "conv": 10, "close": 50, "value": 400}, "pharmacy", rc, None, 0)
    assert y["customers"] == 30 and y["verdict"] == "strong"
    z = adbudget.evaluate({"platform": "meta", "budget": 1500, "cpc": 3, "conv": 2, "close": 20, "value": 200}, "trades", rc, None, 350)
    assert z["verdict"] == "loses" and z["profit"] < 0
    d = adbudget.defaults("dental", "google", 1.5)
    assert d["cpc"] == 12.0 and d["exact_match"] and d["url"].startswith("https://")
    assert not adbudget.defaults("automotive", "meta", 1.5)["exact_match"]


def test_ad_campaigns_api(client):
    pid = client.get("/api/prospects").json()[0]["id"]
    r = client.get(f"/api/prospects/{pid}").json()
    assert r["ad_presets"] and r["ad_defaults"]["google"]["cpc"] > 0
    r = client.patch(f"/api/prospects/{pid}", json={"ad_campaigns": [{"name": "Flu shots", "platform": "google", "customers": 10, "value": 300, "evil": 1}]}).json()
    c = r["ad_campaigns"][0]
    assert c["name"] == "Flu shots" and "evil" not in c and c["calc"]["budget"] > 0 and c["calc"]["mgmt_fee"] > 0


# ---------- uploads, audience, Google & reviews, monthly report, client logins ----------
META_CAMPAIGNS = """Campaign name,Reporting starts,Reporting ends,Amount spent (AUD),Impressions,Reach,Link clicks,Results,Result indicator
Flu shots – Search,2026-08-01,2026-08-31,"1,250.50",48000,21000,960,41,actions:lead
Webster packs,2026-08-01,2026-08-31,640.00,30500,15000,310,9,actions:lead
"""
META_AGE_GENDER = """Campaign name,Age,Gender,Reporting starts,Reporting ends,Amount spent (AUD),Impressions,Link clicks,Results
All,25-34,female,2026-08-01,2026-08-31,200,9000,180,12
All,25-34,male,2026-08-01,2026-08-31,300,9500,120,2
All,35-44,female,2026-08-01,2026-08-31,250,8000,170,14
All,35-44,male,2026-08-01,2026-08-31,150,6000,60,3
All,65+,female,2026-08-01,2026-08-31,100,3000,40,1
"""
GOOGLE_ADS = "Campaign report\nAugust 1, 2026 - August 31, 2026\nCampaign\tCost\tImpr.\tClicks\tConversions\tConv. value\nSearch – Flu\t$800.00\t12,000\t640\t30.00\t0.00\nTotal: Account\t$800.00\t12,000\t640\t30.00\t0.00\n"
GA4_AGE = "# ----------------------------------------\n# Demographic details: Age\n# Start date: 20260801\n# End date: 20260831\n# ----------------------------------------\nAge,Active users,Sessions,Key events\n25-34,420,600,30\n35-44,380,520,25\n(not set),50,60,0\n"


def _cid(client, name="Harbour Accounting"):
    return db.one("SELECT id FROM clients WHERE name=?", (name,))["id"]


def test_upload_reports(client):
    cid = _cid(client)
    r = client.post(f"/api/clients/{cid}/import", files={"file": ("meta.csv", META_CAMPAIGNS.encode(), "text/csv")}).json()
    assert r["platform"] == "meta_ads" and r["kind"] == "ads" and r["rows"] == 2 and r["period"] == ["2026-08-01", "2026-08-31"]
    got = db.one("SELECT SUM(spend) s, SUM(conversions) c FROM ad_metrics WHERE client_id=? AND account_id='upload'", (cid,))
    assert round(got["s"], 2) == 1890.5 and round(got["c"], 2) == 50
    # Google Ads TSV in UTF-16 with a title line, date range line and a Total row
    r = client.post(f"/api/clients/{cid}/import", files={"file": ("g.csv", GOOGLE_ADS.encode("utf-16"), "text/csv")}).json()
    assert r["platform"] == "google_ads" and r["rows"] == 1 and r["period"] == ["2026-08-01", "2026-08-31"]
    # demographics
    r = client.post(f"/api/clients/{cid}/import", files={"file": ("age.csv", META_AGE_GENDER.encode(), "text/csv")}).json()
    assert r["kind"] == "demographics"
    r = client.post(f"/api/clients/{cid}/import", files={"file": ("ga.csv", GA4_AGE.encode(), "text/csv")}).json()
    assert r["platform"] == "ga4" and r["kind"] == "demographics" and r["period"] == ["2026-08-01", "2026-08-31"]
    # bad file
    bad = client.post(f"/api/clients/{cid}/import", files={"file": ("x.csv", b"hello,world\n1,2\n", "text/csv")})
    assert bad.status_code == 400 and "headings" in bad.json()["detail"]
    assert len(client.get(f"/api/clients/{cid}/imports").json()["history"]) >= 4


def test_audience_insights(client):
    cid = _cid(client)
    db.execute("DELETE FROM demographics WHERE client_id=? AND source!='upload'", (cid,))
    a = client.get(f"/api/clients/{cid}/audience?months=24").json()
    ages = {s["segment"]: s for s in a["ads"]["age"]["segments"]}
    assert ages["35-44"]["conversions"] == 17 and ages["25-34"]["spend"] == 500
    assert a["ads"]["gender"]["segments"] and a["web"]["age"]["segments"]
    texts = " ".join(i["text"] for i in a["insights"])
    assert "cheapest customers" in texts and "Most website visitors" in texts


def test_local_reviews_and_monthly_report(client):
    cid = _cid(client)
    client.patch(f"/api/clients/{cid}", json={"area": "Bentleigh VIC"})
    s = client.put(f"/api/clients/{cid}/local/2026-07", json={"values": {"calls": 40, "direction_requests": 60, "reviews_total": 50, "rating": 4.6}}).json()
    s = client.put(f"/api/clients/{cid}/local/2026-08", json={"values": {"calls": 52, "direction_requests": 70, "website_clicks": 30, "reviews_total": 56, "rating": 4.7},
                                                              "competitors": [{"name": "Big Rival", "rating": 4.8, "reviews": 120}, {"name": "Small Rival", "reviews": 20}]}).json()
    aug = next(x for x in s["series"] if x["month"] == "2026-08")
    assert aug["calls"] == 52 and aug["new_reviews"] == 6
    m = client.get(f"/api/clients/{cid}/monthly?month=2026-08").json()
    text = " ".join(" ".join(x["lines"]) for x in m["sections"])
    assert "52 people called you" in text and "Big Rival leads with 120" in text and "You rank #2 of 3" in text
    assert "Your ads" in [x["title"] for x in m["sections"]] and m["next_steps"]
    assert "In August 2026" in m["headline"]
    page = client.get(f"/clients/{cid}/monthly?month=2026-08")
    assert page.status_code == 200 and "do next month" in page.text and "52 people called you" in page.text
    link = client.post(f"/api/clients/{cid}/monthly-link?month=2026-08").json()["url"]
    token = link.split("/m/")[1]
    with TestClient(app) as anon:
        assert "52 people called you" in anon.get(f"/m/{token}").text
        assert anon.get("/m/garbage").status_code == 404
    assert client.put(f"/api/clients/{cid}/local/2026-8", json={"values": {"calls": 1}}).status_code == 400


def test_client_login_sees_only_own_business(client):
    cid = _cid(client)
    other = _cid(client, "Stride Running Co")
    r = client.post(f"/api/clients/{cid}/logins", json={"email": "owner@harbour.example", "password": "harbour123", "name": "Sam"})
    assert r.status_code == 200 and r.json()[0]["email"] == "owner@harbour.example"
    assert client.post(f"/api/clients/{cid}/logins", json={"email": "owner@harbour.example", "password": "harbour123"}).status_code == 400
    with TestClient(app) as c:
        assert c.post("/login", data={"email": "owner@harbour.example", "password": "harbour123"}, follow_redirects=False).status_code == 303
        home = c.get("/", follow_redirects=False)
        assert home.status_code in (302, 307) and home.headers["location"].startswith(f"/clients/{cid}")
        assert c.get(f"/clients/{cid}").status_code == 200
        for ok in [f"/api/clients/{cid}/monthly", f"/api/clients/{cid}/local", f"/api/clients/{cid}/audience", f"/api/clients/{cid}/performance"]:
            assert c.get(ok).status_code == 200, ok
        for bad in [f"/api/clients/{other}/performance", "/api/overview", "/api/prospects", f"/api/clients/{cid}/people", f"/api/clients/{cid}/connections",
                    "/api/agency", f"/api/clients/{cid}/imports", "/api/rate-card"]:
            assert c.get(bad).status_code == 403, bad
        assert c.patch(f"/api/clients/{cid}", json={"name": "x"}).status_code == 403
        assert c.put(f"/api/clients/{cid}/local/2026-08", json={"values": {"calls": 1}}).status_code == 403
        assert c.get(f"/clients/{other}", follow_redirects=False).status_code in (302, 307)
        page = c.get(f"/clients/{cid}").text
        assert "Prospects &amp; audits" not in page and "Upload data" not in page and "Monthly report" in page
    uid = client.get(f"/api/clients/{cid}/logins").json()[0]["id"]
    assert client.delete(f"/api/clients/{cid}/logins/{uid}").json() == []


def test_demo_sync_fills_demographics(client):
    cid = _cid(client, "Stride Running Co")
    a = client.get(f"/api/clients/{cid}/audience?months=3").json()
    assert a["ads"]["age"]["segments"] and a["web"]["city"]["segments"] and a["insights"]
    loc = client.get(f"/api/clients/{cid}/local").json()
    assert loc["ranking"] and loc["series"]


def test_find_local_competitors(client, monkeypatch):
    from app.services import competitors
    cid = _cid(client, "Planwise Software")
    client.patch(f"/api/clients/{cid}", json={"area": "East Bentleigh VIC", "search_term": "pharmacy"})
    monkeypatch.setattr(competitors, "api_key", lambda: "k")
    monkeypatch.setattr(competitors, "find", lambda term, area, d, n: [
        {"name": "Planwise Software", "rating": 4.5, "reviews": 30, "is_self": True},
        {"name": "Chemist One", "rating": 4.2, "reviews": 210, "is_self": False},
        {"name": "Pharmacy Two", "rating": 4.9, "reviews": 45, "is_self": False}])
    s = client.post(f"/api/clients/{cid}/local/2026-08/find").json()
    assert [r["name"] for r in s["competitors"]["list"]] == ["Chemist One", "Pharmacy Two"]
    assert s["search_term"] == "pharmacy" and "pharmacy+near+East+Bentleigh+VIC" in s["maps_link"]
    aug = next(x for x in s["series"] if x["month"] == "2026-08")
    assert aug["reviews_total"] == 30


def test_seven_day_trial(client):
    cid = _cid(client)
    assert client.get(f"/api/clients/{cid}/trial").json()["started"] is False
    t = client.post(f"/api/clients/{cid}/trial/start", json={"start_date": "2026-09-01"}).json()
    assert t["started"] and t["total"] >= 14 and t["day"] == 7 and t["end_date"] == "2026-09-07"
    first = t["tasks"][0]["id"]
    t = client.put(f"/api/clients/{cid}/trial", json={
        "goal": "More flu shot bookings",
        "baseline": {"reviews_total": 12, "rating": 4.1, "photos": 3}, "after": {"reviews_total": 19, "rating": 4.3, "photos": 17},
        "checks_before": {"hours": True, "website_phone": True}, "checks_after": {k: True for k in ["hours", "categories", "services", "description", "booking", "website_phone", "photos10", "posted"]},
        "tasks": [{"id": first, "done": True, "note": "Added as Manager"}, {"new": True, "title": "Flu shot landing page", "day": 5}]}).json()
    assert t["done"] == 1 and t["completeness_before"] == 25 and t["completeness_after"] == 100
    assert any(x["title"] == "Flu shot landing page" and x["day"] == 5 for x in t["tasks"])
    page = client.get(f"/clients/{cid}/trial-report").text
    assert "7 new Google reviews" in page and "25% to 100% complete" in page and "Added as Manager" in page and "Local Lite" in page
    url = client.post(f"/api/clients/{cid}/trial-link").json()["url"]
    with TestClient(app) as anon:
        assert "7 new Google reviews" in anon.get("/t/" + url.split("/t/")[1]).text
    client.put(f"/api/clients/{cid}/trial", json={"show_price": False})
    assert 'class="noprice"' in client.get(f"/clients/{cid}/trial-report").text
    # a client login can see the trial and the report, not change them
    client.post(f"/api/clients/{cid}/logins", json={"email": "trial@harbour.example", "password": "harbour123"})
    with TestClient(app) as c:
        c.post("/login", data={"email": "trial@harbour.example", "password": "harbour123"})
        assert c.get(f"/api/clients/{cid}/trial").json()["done"] == 1
        assert c.get(f"/clients/{cid}/trial-report").status_code == 200
        assert c.put(f"/api/clients/{cid}/trial", json={"goal": "x"}).status_code == 403


def test_trial_website_before_after(client, monkeypatch):
    from app.seed import EXAMPLE_SITES
    from app.services import prospects
    cid = _cid(client)
    client.post(f"/api/clients/{cid}/trial/start", json={})
    client.put(f"/api/clients/{cid}/trial", json={"website_url": "https://pharmacy.example/"})
    pages = {"before": EXAMPLE_SITES[0][4], "after": EXAMPLE_SITES[2][4]}   # a weak site, then a well set-up one
    state = {"which": "before"}
    monkeypatch.setattr(prospects, "fetch", lambda url: {"requested": url, "final_url": url, "status": 200, "html": pages[state["which"]],
                                                         "bytes": 50000, "seconds": 0.8, "robots": True, "sitemap": True})
    monkeypatch.setattr(prospects, "pagespeed", lambda url, screenshot=False: {"score": 80, "screenshot": "data:image/jpeg;base64,AAAA"})
    t = client.post(f"/api/clients/{cid}/trial/website/before").json()
    assert t["website"]["before"]["score"] < 60 and t["website"]["todo"] and t["website_tips"]
    state["which"] = "after"
    t = client.post(f"/api/clients/{cid}/trial/website/after").json()
    w = t["website"]
    assert w["after"]["score"] > w["before"]["score"] and w["fixed"] and w["score_change"] > 0
    page = client.get(f"/clients/{cid}/trial-report").text
    assert "Your website" in page and "website score up from" in page and "data:image/jpeg;base64,AAAA" in page
    assert client.post(f"/api/clients/{cid}/trial/website/sideways").status_code == 400


def test_business_details_and_photos(client):
    import io, zipfile
    cid = _cid(client)
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 2000
    d = client.put(f"/api/clients/{cid}/details", json={"business_name": "Harbour", "hours": "Mon-Fri 9-5", "website_platform": "Wix",
                                                       "gbp_manager": True, "evil": "x"}).json()
    assert d["details"]["hours"] == "Mon-Fri 9-5" and d["details"]["website_platform"] == "Wix" and d["access_done"] == 1 and "evil" not in d["details"]
    d = client.post(f"/api/clients/{cid}/photos", files={"file": ("shop.jpg", jpg, "image/jpeg")}, data={"category": "shopfront"}).json()
    pid = d["photos"][0]["id"]
    assert d["photos"][0]["category"] == "shopfront"
    r = client.get(f"/api/clients/{cid}/photos/{pid}")
    assert r.status_code == 200 and r.content == jpg and r.headers["content-type"] == "image/jpeg"
    bad = client.post(f"/api/clients/{cid}/photos", files={"file": ("x.jpg", b"<svg>", "image/jpeg")})
    assert bad.status_code == 400
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/clients/{cid}/photos.zip").content))
    assert any(n.startswith("shopfront/") for n in z.namelist()) and "Mon-Fri 9-5" in z.read("business-details.txt").decode()
    # the owner can edit their own details & photos from a client login, but not another client's
    other = _cid(client, "Stride Running Co")
    client.post(f"/api/clients/{cid}/logins", json={"email": "photos@harbour.example", "password": "harbour123"})
    with TestClient(app) as c:
        c.post("/login", data={"email": "photos@harbour.example", "password": "harbour123"})
        assert c.put(f"/api/clients/{cid}/details", json={"services": "Tax returns"}).json()["details"]["services"] == "Tax returns"
        up = c.post(f"/api/clients/{cid}/photos", files={"file": ("team.jpg", jpg, "image/jpeg")}, data={"category": "team"}).json()
        assert up["details"]["updated_by"] if "updated_by" in up["details"] else True
        assert c.get(f"/api/clients/{cid}/photos/{pid}").status_code == 200
        assert c.put(f"/api/clients/{other}/details", json={"services": "x"}).status_code == 403
        assert c.post(f"/api/clients/{other}/photos", files={"file": ("t.jpg", jpg, "image/jpeg")}).status_code == 403
        assert c.get(f"/api/clients/{cid}/photos.zip").status_code == 403
        assert c.delete(f"/api/clients/{cid}/photos/{pid}").status_code == 200
    assert client.get(f"/api/clients/{cid}/details").json()["updated_by"] == "photos@harbour.example"


def test_campaign_builder_google(client):
    import csv as _csv, io
    cid = _cid(client)
    client.put(f"/api/clients/{cid}/details", json={"business_name": "East Bentleigh Pharmacy", "services": "Flu vaccinations\nWebster packs",
                                                   "booking_link": "eastbentleighpharmacy.com.au/book", "address": "1 Centre Rd, Bentleigh East VIC 3165"})
    client.patch(f"/api/clients/{cid}", json={"area": "Bentleigh East VIC", "search_term": "pharmacy"})
    c = client.post(f"/api/clients/{cid}/campaigns", json={"platform": "google", "service": "Flu vaccinations", "monthly_budget": 900}).json()
    d = c["data"]
    assert 3 <= len(d["headlines"]) <= 15 and all(len(h) <= 30 for h in d["headlines"]) and all(len(x) <= 90 for x in d["descriptions"])
    assert "flu vaccinations near me" in d["keywords"] and d["final_url"].startswith("https://") and "jobs" in d["negatives"]
    assert not [x for x in c["checks"] if x["level"] == "error"], c["checks"]
    # Ahpra / policy checks on bad copy
    bad = client.put(f"/api/clients/{cid}/campaigns/{c['id']}", json={"headlines": d["headlines"][:2] + ["Best Pharmacy In Melbourne!", "Painless Flu Shots"],
                                                                       "descriptions": d["descriptions"][:1] + ["Call 03 9555 1234. Our patients say we're great."]}).json()
    msgs = " ".join(x["message"] for x in bad["checks"])
    assert "best" in msgs and "exclamation" in msgs and "painless" in msgs.lower() and "Phone numbers" in msgs and "testimonials" in msgs
    assert client.post(f"/api/clients/{cid}/campaigns/{c['id']}/ask-approval").status_code == 400      # red problems block approval
    client.put(f"/api/clients/{cid}/campaigns/{c['id']}", json={"headlines": d["headlines"], "descriptions": d["descriptions"]})
    assert client.post(f"/api/clients/{cid}/campaigns/{c['id']}/ask-approval").json()["status"] == "awaiting_approval"
    # the owner approves from their own login
    client.post(f"/api/clients/{cid}/logins", json={"email": "ads@harbour.example", "password": "harbour123"})
    with TestClient(app) as o:
        o.post("/login", data={"email": "ads@harbour.example", "password": "harbour123"})
        assert o.get(f"/api/clients/{cid}/campaigns").status_code == 200
        assert o.put(f"/api/clients/{cid}/campaigns/{c['id']}", json={"name": "x"}).status_code == 403
        assert o.get(f"/api/clients/{cid}/campaigns/{c['id']}/google-ads-editor.csv").status_code == 403
        r = o.post(f"/api/clients/{cid}/campaigns/{c['id']}/review", json={"approve": True, "note": "Looks good"}).json()
        assert r["status"] == "approved" and r["owner_note"] == "Looks good"
    # Google Ads Editor file
    res = client.get(f"/api/clients/{cid}/campaigns/{c['id']}/google-ads-editor.csv")
    rows = list(_csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))
    camp = rows[0]
    assert camp["Campaign Type"] == "Search" and camp["Campaign Status"] == "Paused" and float(camp["Budget"]) == round(900 / 30.4, 2)
    assert any(r["Location"].startswith("1 Centre Rd") and r["Radius"] == "5" for r in rows)
    assert any(r["Keyword"] == "flu vaccinations near me" and r["Criterion Type"] == "Phrase" for r in rows)
    assert any(r["Criterion Type"] == "Campaign negative phrase" for r in rows)
    ad = next(r for r in rows if r["Ad type"] == "Responsive search ad")
    assert ad["Headline 1"] == d["headlines"][0] and ad["Final URL"] == d["final_url"]
    assert client.get(f"/api/clients/{cid}").json() and client.get(f"/api/clients/{cid}/campaigns").json()["campaigns"][0]["status"] == "exported"
    # can't send without a connected Google Ads account
    r = client.post(f"/api/clients/{cid}/campaigns/{c['id']}/send")
    assert r.status_code == 400 and "Connect" in r.json()["detail"]


def test_campaign_send_google_and_meta(client, monkeypatch):
    import httpx
    from app.security import encrypt_json
    cid = _cid(client, "Planwise Software")
    client.put(f"/api/clients/{cid}/details", json={"business_name": "Planwise", "services": "Project planning", "website": "https://planwise.example"})
    db.execute("INSERT INTO connections (client_id, platform, account_id, account_name, credentials_enc, is_demo) VALUES (?,?,?,?,?,0)",
               (cid, "google_ads", "123-456-7890", "live", encrypt_json({"access_token": "tok", "expires_at": 9999999999})))
    db.execute("INSERT INTO connections (client_id, platform, account_id, account_name, credentials_enc, is_demo) VALUES (?,?,?,?,?,0)",
               (cid, "meta_ads", "555", "live", encrypt_json({"access_token": "mtok"})))
    calls = []

    class R:
        def __init__(self, body, code=200):
            self.status_code, self._b, self.headers, self.text = code, body, {"content-type": "application/json"}, str(body)
        def json(self):
            return self._b

    def fake_post(url, **kw):
        calls.append((url, kw))
        if "googleAds:mutate" in url:
            ops = kw["json"]["mutateOperations"]
            assert ops[1]["campaignOperation"]["create"]["status"] == "PAUSED"
            return R({"mutateOperationResponses": [{"campaignBudgetResult": {}}, {"campaignResult": {"resourceName": "customers/1234567890/campaigns/99"}}]})
        if "campaigns:mutate" in url:
            return R({"results": [{}]})
        if url.endswith("/adimages"):
            return R({"images": {"x": {"hash": "abc"}}})
        if url.endswith("/campaigns"):
            assert kw["data"]["status"] == "PAUSED"
            return R({"id": "c1"})
        if url.endswith("/adsets"):
            return R({"id": "s1"})
        if url.endswith("/adcreatives"):
            return R({"id": "cr1"})
        if url.endswith("/ads"):
            assert kw["data"]["status"] == "PAUSED"
            return R({"id": "a1"})
        return R({"success": True})
    monkeypatch.setattr(httpx, "post", fake_post)
    lst = client.get(f"/api/clients/{cid}/campaigns").json()
    assert lst["can_send"] == {"google": True, "meta": True}
    g = client.post(f"/api/clients/{cid}/campaigns", json={"platform": "google", "service": "Project planning"}).json()
    r = client.post(f"/api/clients/{cid}/campaigns/{g['id']}/send").json()
    assert r["status"] == "sent" and r["remote"]["campaign"].endswith("/99")
    assert client.post(f"/api/clients/{cid}/campaigns/{g['id']}/switch", json={"on": True}).json()["status"] == "live"
    # Meta needs a photo and a Page ID
    jpg = b"\xff\xd8\xff\xe0" + b"1" * 500
    pid = client.post(f"/api/clients/{cid}/photos", files={"file": ("p.jpg", jpg, "image/jpeg")}).json()["photos"][0]["id"]
    m = client.post(f"/api/clients/{cid}/campaigns", json={"platform": "meta", "service": "Project planning"}).json()
    assert any(x["field"] == "photo_id" and x["level"] == "error" for x in m["checks"])
    client.put(f"/api/clients/{cid}/campaigns/{m['id']}", json={"photo_id": pid})
    assert "Page ID" in client.post(f"/api/clients/{cid}/campaigns/{m['id']}/send").json()["detail"]
    client.put(f"/api/clients/{cid}/campaigns/{m['id']}", json={"page_id": "777"})
    r = client.post(f"/api/clients/{cid}/campaigns/{m['id']}/send").json()
    assert r["status"] == "sent" and r["remote"]["ad"] == "a1"
    adset_call = next(kw for u, kw in calls if u.endswith("/adsets"))
    assert '"radius": 5' in adset_call["data"]["targeting"] or '"countries"' in adset_call["data"]["targeting"]
    assert client.delete(f"/api/clients/{cid}/campaigns/{m['id']}").status_code == 200
    assert any(c["id"] == m["id"] for c in client.get(f"/api/clients/{cid}/campaigns").json()["campaigns"])   # sent campaigns can't be deleted
