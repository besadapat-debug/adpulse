"""Audience intelligence: first-party intent scoring, consent-gated segments, hashed
syncing to ad platforms, and platform-native targeting suggestions.

Hard rule enforced here, not just in the UI: a contact is only ever exported or uploaded if
consent_marketing=1 AND deleted_at IS NULL. Data scraped from other people's accounts has no
path into this module."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
from datetime import datetime, timedelta, timezone

import httpx

from .. import db
from ..config import settings
from ..security import decrypt_json
from .metrics import classify_intent

# event weights for intent scoring (tune per client in definition["weights"])
WEIGHTS = {
    "page_view": 1, "product_view": 3, "pricing_view": 6, "add_to_cart": 9, "begin_checkout": 12,
    "form_start": 6, "lead": 10, "email_open": 1, "email_click": 4, "ad_click": 3, "video_50": 2, "return_visit": 3, "page_leave": 0,
}
HALF_LIFE_DAYS = 7.0
SCALE = 12.0  # raw score at which intent ≈ 63/100


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def score_contacts(client_id: int, lookback_days: int = 30, weights: dict | None = None) -> dict[int, dict]:
    w = {**WEIGHTS, **(weights or {})}
    since = (_now() - timedelta(days=lookback_days)).isoformat()
    scores: dict[int, dict] = {}
    now = _now()
    for e in db.rows("SELECT contact_id, event, ts FROM events WHERE client_id=? AND contact_id IS NOT NULL AND ts>=?", (client_id, since)):
        age = (now - datetime.fromisoformat(e["ts"][:19])).total_seconds() / 86400
        s = scores.setdefault(e["contact_id"], {"raw": 0.0, "events": 0, "last": e["ts"], "top": {}})
        s["raw"] += w.get(e["event"], 0.5) * 0.5 ** (age / HALF_LIFE_DAYS)
        s["events"] += 1
        s["last"] = max(s["last"], e["ts"])
        s["top"][e["event"]] = s["top"].get(e["event"], 0) + 1
    for s in scores.values():
        s["score"] = round(100 * (1 - math.exp(-s["raw"] / SCALE)))
    return scores


def tier(score: int) -> str:
    return "hot" if score >= 70 else "warm" if score >= 40 else "cool" if score >= 15 else "cold"


def eligible_contacts(client_id: int) -> list[dict]:
    return db.rows("SELECT * FROM contacts WHERE client_id=? AND consent_marketing=1 AND deleted_at IS NULL", (client_id,))


def members(client_id: int, definition: dict) -> list[dict]:
    d = {"min_score": 0, "max_score": 100, "lookback_days": 30, "include_customers": False, "customers_only": False, **definition}
    scores = score_contacts(client_id, d["lookback_days"], d.get("weights"))
    out = []
    for c in eligible_contacts(client_id):
        s = scores.get(c["id"], {"score": 0, "events": 0, "last": None, "top": {}})
        if d["customers_only"]:
            if c["is_customer"]:
                out.append({**c, **s})
            continue
        if c["is_customer"] and not d["include_customers"]:
            continue
        if d["min_score"] <= s["score"] <= d["max_score"]:
            if d.get("required_events") and not any(ev in s["top"] for ev in d["required_events"]):
                continue
            out.append({**c, **s})
    out.sort(key=lambda r: -r["score"])
    return out


def score_distribution(client_id: int) -> dict:
    scores = score_contacts(client_id)
    all_c = db.rows("SELECT id, consent_marketing, deleted_at, is_customer FROM contacts WHERE client_id=?", (client_id,))
    dist = {"hot": 0, "warm": 0, "cool": 0, "cold": 0}
    consented = 0
    for c in all_c:
        if c["deleted_at"]:
            continue
        if c["consent_marketing"]:
            consented += 1
            if not c["is_customer"]:
                dist[tier(scores.get(c["id"], {}).get("score", 0))] += 1
    top_events = db.rows("SELECT event, COUNT(*) n FROM events WHERE client_id=? AND ts>=? GROUP BY event ORDER BY n DESC",
                         (client_id, (_now() - timedelta(days=30)).isoformat()))
    return {"total_contacts": len([c for c in all_c if not c["deleted_at"]]), "consented": consented,
            "customers": sum(1 for c in all_c if c["is_customer"] and c["consent_marketing"] and not c["deleted_at"]),
            "tiers": dist, "top_events": top_events}


# ---------- normalisation + hashing (platform specs: SHA-256 of normalised values) ----------
COUNTRY_CODES = {"AU": "61", "NZ": "64", "US": "1", "CA": "1", "GB": "44", "UK": "44", "IE": "353", "SG": "65", "DE": "49", "FR": "33"}


def norm_email(e: str, google: bool = False) -> str:
    e = (e or "").strip().lower()
    if google and "@" in e:
        local, dom = e.split("@", 1)
        if dom in ("gmail.com", "googlemail.com"):
            local = local.split("+", 1)[0].replace(".", "")
        e = f"{local}@{dom}"
    return e


def norm_phone(p: str, country: str = "AU") -> str:
    digits = re.sub(r"\D", "", p or "")
    if not digits:
        return ""
    if (p or "").strip().startswith("+"):
        return "+" + digits
    cc = COUNTRY_CODES.get((country or "AU").upper(), "61")
    if digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith(cc) and len(digits) > 9:
        return "+" + digits
    return f"+{cc}{digits}"


def sha(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest() if v else ""


def hashed_identifiers(c: dict, region: str = "AU", google: bool = False) -> dict:
    phone = norm_phone(c.get("phone", ""), c.get("country") or region)
    return {
        "email": sha(norm_email(c.get("email", ""), google)),
        # Meta wants digits only (no '+'); Google wants E.164 with '+'
        "phone_e164": sha(phone),
        "phone_digits": sha(phone.lstrip("+")),
        "fn": sha((c.get("first_name") or "").strip().lower()),
        "ln": sha((c.get("last_name") or "").strip().lower()),
        "country": (c.get("country") or region or "").strip().lower(),
        "zip": (c.get("postcode") or "").strip().lower().replace(" ", ""),
    }


def export_csv(client_id: int, audience_id: int, platform: str) -> str:
    """Hashed customer file for manual upload in each platform's UI."""
    a = db.one("SELECT * FROM audiences WHERE id=? AND client_id=?", (audience_id, client_id))
    client = db.one("SELECT * FROM clients WHERE id=?", (client_id,))
    ms = members(client_id, json.loads(a["definition"]))
    buf = io.StringIO()
    w = csv.writer(buf)
    if platform == "google_ads":
        w.writerow(["Email", "Phone", "First Name", "Last Name", "Country", "Zip"])
        for m in ms:
            h = hashed_identifiers(m, client["region"], google=True)
            w.writerow([h["email"], h["phone_e164"], h["fn"], h["ln"], h["country"].upper(), h["zip"]])
    elif platform == "meta_ads":
        w.writerow(["email", "phone", "fn", "ln", "country", "zip"])
        for m in ms:
            h = hashed_identifiers(m, client["region"])
            w.writerow([h["email"], h["phone_digits"], h["fn"], h["ln"], sha(h["country"]), sha(h["zip"])])
    else:  # tiktok / linkedin: hashed email only
        w.writerow(["sha256_email"])
        for m in ms:
            h = hashed_identifiers(m, client["region"])
            if h["email"]:
                w.writerow([h["email"]])
    db.audit("", "audience_export", f"client={client_id} audience={audience_id} platform={platform} rows={len(ms)}")
    return buf.getvalue()


# ---------- platform sync ----------
SUPPORTED_SYNC = {"meta_ads": "Meta Custom Audience", "google_ads": "Google Customer Match", "tiktok_ads": "TikTok Custom Audience",
                  "linkedin_ads": "LinkedIn Matched Audience"}


def sync_audience(audience_id: int, platform: str) -> dict:
    a = db.one("SELECT * FROM audiences WHERE id=?", (audience_id,))
    client = db.one("SELECT * FROM clients WHERE id=?", (a["client_id"],))
    conn = db.one("SELECT * FROM connections WHERE client_id=? AND platform=? ORDER BY is_demo LIMIT 1", (a["client_id"], platform))
    if not conn:
        return {"ok": False, "error": f"Connect {SUPPORTED_SYNC.get(platform, platform)} for this client first."}
    ms = members(a["client_id"], json.loads(a["definition"]))
    prior = db.one("SELECT * FROM audience_syncs WHERE audience_id=? AND platform=? AND status='ok' ORDER BY id DESC LIMIT 1", (audience_id, platform))
    ext = prior["external_id"] if prior else ""
    try:
        if conn["is_demo"]:
            rnd = random.Random(audience_id * 31 + len(platform))
            ext = ext or f"demo-{platform}-{audience_id}"
            detail = f"Demo sync: {len(ms)} hashed records sent; est. match rate {0.45 + rnd.random() * 0.3:.0%}."
        else:
            creds = decrypt_json(conn["credentials_enc"])
            fn = {"meta_ads": _meta, "google_ads": _google, "tiktok_ads": _tiktok, "linkedin_ads": _linkedin}[platform]
            ext, detail = fn(conn, creds, client, a, ms, ext)
        db.execute("INSERT INTO audience_syncs (audience_id, platform, external_id, uploaded, status, detail) VALUES (?,?,?,?, 'ok', ?)",
                   (audience_id, platform, ext, len(ms), detail))
        db.execute("UPDATE audiences SET size=? WHERE id=?", (len(ms), audience_id))
        db.audit("", "audience_sync", f"audience={audience_id} platform={platform} rows={len(ms)}")
        return {"ok": True, "uploaded": len(ms), "external_id": ext, "detail": detail}
    except Exception as e:
        db.execute("INSERT INTO audience_syncs (audience_id, platform, uploaded, status, detail) VALUES (?,?,0,'error',?)",
                   (audience_id, platform, str(e)[:500]))
        return {"ok": False, "error": str(e)[:500]}


def _batches(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _meta(conn, creds, client, a, ms, ext):
    base = f"https://graph.facebook.com/{settings.META_API_VERSION}"
    acct = conn["account_id"] if conn["account_id"].startswith("act_") else f"act_{conn['account_id']}"
    tok = creds["access_token"]
    with httpx.Client(timeout=60) as h:
        if not ext:
            r = h.post(f"{base}/{acct}/customaudiences", data={"name": f"{client['name']} · {a['name']}", "subtype": "CUSTOM",
                                                               "description": "Synced from AdPulse (consented first-party)",
                                                               "customer_file_source": "USER_PROVIDED_ONLY", "access_token": tok})
            if r.status_code >= 400:
                raise RuntimeError(r.text[:400])
            ext = r.json()["id"]
        schema = ["EMAIL", "PHONE", "FN", "LN", "COUNTRY", "ZIP"]
        data = []
        for m in ms:
            hi = hashed_identifiers(m, client["region"])
            data.append([hi["email"], hi["phone_digits"], hi["fn"], hi["ln"], sha(hi["country"]), sha(hi["zip"])])
        received = 0
        for b in _batches(data, 10000):
            r = h.post(f"{base}/{ext}/users", data={"payload": json.dumps({"schema": schema, "data": b}), "access_token": tok})
            if r.status_code >= 400:
                raise RuntimeError(r.text[:400])
            received += r.json().get("num_received", len(b))
        _remove_withdrawn_meta(h, base, ext, tok, client)
    return ext, f"Meta received {received} records."


def _remove_withdrawn_meta(h, base, ext, tok, client):
    """Contacts who withdrew consent or were deleted are removed from the platform audience."""
    gone = db.rows("SELECT * FROM contacts WHERE client_id=? AND (consent_marketing=0 OR deleted_at IS NOT NULL) AND email<>''", (client["id"],))
    if gone:
        data = [[hashed_identifiers(c, client["region"])["email"]] for c in gone]
        for b in _batches(data, 10000):
            h.request("DELETE", f"{base}/{ext}/users", data={"payload": json.dumps({"schema": ["EMAIL"], "data": b}), "access_token": tok})


def _google(conn, creds, client, a, ms, ext):
    from ..oauth import refresh_if_needed
    new = refresh_if_needed("google", creds)
    if new:
        from ..security import encrypt_json
        db.execute("UPDATE connections SET credentials_enc=? WHERE id=?", (encrypt_json(new), conn["id"]))
        creds = new
    cid = conn["account_id"].replace("-", "")
    base = f"https://googleads.googleapis.com/{settings.GOOGLE_ADS_API_VERSION}"
    hd = {"Authorization": f"Bearer {creds['access_token']}"}
    if settings.GOOGLE_ADS_DEVELOPER_TOKEN:  # legacy; access is now granted to the Cloud project
        hd["developer-token"] = settings.GOOGLE_ADS_DEVELOPER_TOKEN
    if settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID:
        hd["login-customer-id"] = settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID.replace("-", "")

    def post(url, body):
        r = h.post(url, headers=hd, json=body)
        if r.status_code >= 400:
            raise RuntimeError(r.text[:400])
        return r.json()

    with httpx.Client(timeout=120) as h:
        if not ext:
            res = post(f"{base}/customers/{cid}/userLists:mutate", {"operations": [{"create": {
                "name": f"{client['name']} · {a['name']} (AdPulse)", "membershipLifeSpan": 540,
                "crmBasedUserList": {"uploadKeyType": "CONTACT_INFO", "dataSourceType": "FIRST_PARTY"}}}]})
            ext = res["results"][0]["resourceName"]
        job = post(f"{base}/customers/{cid}/offlineUserDataJobs:create", {"job": {
            "type": "CUSTOMER_MATCH_USER_LIST",
            "customerMatchUserListMetadata": {"userList": ext, "consent": {"adUserData": "GRANTED", "adPersonalization": "GRANTED"}}}})["resourceName"]
        ops = []
        for m in ms:
            hi = hashed_identifiers(m, client["region"], google=True)
            ids = []
            if hi["email"]:
                ids.append({"hashedEmail": hi["email"]})
            if hi["phone_e164"]:
                ids.append({"hashedPhoneNumber": hi["phone_e164"]})
            if hi["fn"] and hi["ln"] and hi["country"] and hi["zip"]:
                ids.append({"addressInfo": {"hashedFirstName": hi["fn"], "hashedLastName": hi["ln"],
                                            "countryCode": hi["country"].upper(), "postalCode": hi["zip"]}})
            if ids:
                ops.append({"create": {"userIdentifiers": ids}})
        gone = db.rows("SELECT * FROM contacts WHERE client_id=? AND (consent_marketing=0 OR deleted_at IS NOT NULL) AND email<>''", (client["id"],))
        for c in gone:
            ops.append({"remove": {"userIdentifiers": [{"hashedEmail": hashed_identifiers(c, client["region"], True)["email"]}]}})
        for b in _batches(ops, 10000):
            post(f"{base}/{job}:addOperations", {"operations": b, "enablePartialFailure": True})
        post(f"{base}/{job}:run", {})
    return ext, f"Customer Match job {job.rsplit('/', 1)[-1]} submitted with {len(ops)} operations (processing takes up to 24h)."


def _tiktok(conn, creds, client, a, ms, ext):
    base = "https://business-api.tiktok.com/open_api/v1.3"
    hd = {"Access-Token": creds["access_token"]}
    content = "\n".join(h for h in (hashed_identifiers(m, client["region"])["email"] for m in ms) if h).encode()
    with httpx.Client(timeout=120) as h:
        r = h.post(f"{base}/dmp/custom_audience/file/upload/", headers=hd,
                   data={"advertiser_id": conn["account_id"], "calculate_type": "EMAIL_SHA256", "file_signature": hashlib.md5(content).hexdigest()},
                   files={"file": ("audience.txt", content, "text/plain")})
        body = r.json()
        if body.get("code") != 0:
            raise RuntimeError(body.get("message"))
        path = body["data"]["file_path"]
        if ext:
            r = h.post(f"{base}/dmp/custom_audience/update/", headers=hd, json={
                "advertiser_id": conn["account_id"], "custom_audience_id": ext, "action": "APPEND", "file_paths": [path], "calculate_type": "EMAIL_SHA256"})
        else:
            r = h.post(f"{base}/dmp/custom_audience/create/", headers=hd, json={
                "advertiser_id": conn["account_id"], "custom_audience_name": f"{client['name']} · {a['name']}"[:128],
                "file_paths": [path], "calculate_type": "EMAIL_SHA256"})
        body = r.json()
        if body.get("code") != 0:
            raise RuntimeError(body.get("message"))
        ext = ext or str(body["data"]["custom_audience_id"])
    return ext, "TikTok audience file uploaded (matching takes a few hours)."


def _linkedin(conn, creds, client, a, ms, ext):
    hd = {"Authorization": f"Bearer {creds['access_token']}", "LinkedIn-Version": settings.LINKEDIN_API_VERSION,
          "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"}
    with httpx.Client(timeout=120) as h:
        if not ext:
            r = h.post("https://api.linkedin.com/rest/dmpSegments", headers=hd, json={
                "name": f"{client['name']} · {a['name']}", "sourcePlatform": "LIST_UPLOAD", "type": "USER",
                "account": f"urn:li:sponsoredAccount:{conn['account_id']}", "destinations": [{"destination": "LINKEDIN"}]})
            if r.status_code >= 400:
                raise RuntimeError(r.text[:400])
            ext = r.headers.get("x-restli-id", "")
        els = [{"action": "ADD", "userIds": [{"idType": "SHA256_EMAIL", "idValue": hi}]}
               for hi in (hashed_identifiers(m, client["region"])["email"] for m in ms) if hi]
        for b in _batches(els, 5000):
            r = h.post(f"https://api.linkedin.com/rest/dmpSegments/{ext}/users", headers={**hd, "X-RestLi-Method": "BATCH_CREATE"}, json={"elements": b})
            if r.status_code >= 400:
                raise RuntimeError(r.text[:400])
    return ext, f"LinkedIn segment updated with {len(els)} hashed emails (min. 300 matched members to serve)."


# ---------- platform-native targeting suggestions (no personal data involved) ----------
def targeting_suggestions(client_id: int) -> dict:
    since = (_now() - timedelta(days=28)).date().isoformat()
    qs = db.rows("SELECT query, SUM(clicks) clicks, SUM(impressions) impressions, SUM(position*impressions)/NULLIF(SUM(impressions),0) pos "
                 "FROM seo_queries WHERE client_id=? AND source='gsc' AND date>=? GROUP BY query ORDER BY impressions DESC LIMIT 200", (client_id, since))
    by_intent: dict[str, list] = {}
    for q in qs:
        it = classify_intent(q["query"])
        by_intent.setdefault(it, []).append(q)
    high = by_intent.get("transactional", []) + by_intent.get("commercial", [])
    # queries with demand but weak organic position are the best candidates for paid search coverage
    gaps = sorted([q for q in high if (q["pos"] or 0) > 5], key=lambda q: -q["impressions"])[:15]
    web_rules = [
        {"name": "High intent – pricing/cart visitors (14d)", "meta_rule": {"inclusions": {"operator": "or", "rules": [
            {"event_sources": [{"type": "pixel", "id": "<PIXEL_ID>"}], "retention_seconds": 1209600,
             "filter": {"operator": "or", "filters": [{"field": "event", "operator": "eq", "value": "AddToCart"},
                                                       {"field": "url", "operator": "i_contains", "value": "pricing"}]}}]},
            "exclusions": {"operator": "or", "rules": [{"event_sources": [{"type": "pixel", "id": "<PIXEL_ID>"}], "retention_seconds": 2592000,
                                                        "filter": {"operator": "or", "filters": [{"field": "event", "operator": "eq", "value": "Purchase"}]}}]}},
         "ga4_audience": "Condition: event in (add_to_cart, begin_checkout) OR page_location contains 'pricing' · 14 days · exclude purchasers",
         "why": "Anonymous visitors can't be exported as people, but the platforms can build this audience from their own pixel/tag data."},
        {"name": "Engaged researchers (3+ pages, 30d)", "meta_rule": None,
         "ga4_audience": "Condition: session_count ≥ 2 AND engaged pages ≥ 3 · 30 days → share to Google Ads",
         "why": "Warm, not yet converting — good for mid-funnel creative."},
    ]
    return {"keyword_gaps": gaps, "intent_mix": {k: len(v) for k, v in by_intent.items()},
            "search_themes": [q["query"] for q in high[:25]], "website_audience_rules": web_rules}
