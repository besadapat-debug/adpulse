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
    s, l = small["tiers"], large["tiers"]
    assert s[0]["monthly_total"] < s[1]["monthly_total"] < s[2]["monthly_total"]
    assert l[1]["monthly_total"] > s[1]["monthly_total"] and l[1]["ad_spend"] > s[1]["ad_spend"]
    assert s[1]["recommended"] and any("Tracking" in i["item"] for i in s[1]["setup"])


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
    before = client.get(f"/api/prospects/{pid}").json()["quote"]["tiers"][1]["monthly_total"]
    rc = client.get("/api/rate-card").json()["rates"]
    client.put("/api/rate-card", json={**rc, "social_monthly": rc["social_monthly"] * 2, "seo_monthly": rc["seo_monthly"] * 2})
    after = client.get(f"/api/prospects/{pid}").json()["quote"]["tiers"][1]["monthly_total"]
    assert after > before
    client.put("/api/rate-card", json=client.get("/api/rate-card").json()["defaults"])
