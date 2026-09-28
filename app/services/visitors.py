"""People (opted-in, identified visitors) and Companies (B2B visitors identified by IP → company).

What the law and platforms allow:
- Ad platforms never reveal which individual saw or clicked an ad.
- Once a visitor lands on your client's site and consents, the tracking snippet records what they
  do there. If they later identify themselves (a form with a marketing opt-in), their earlier
  visits on that browser are linked to them. That is the People view.
- For B2B, an IP-to-company provider can name the *business network* a visit came from. Company
  data isn't personal information, but home/mobile connections (ISPs) and sole traders can be, so
  only business/education/government networks are kept and raw IPs are never stored.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone

import httpx

from .. import db
from ..config import settings
from .attribution import channel_of
from .audiences import WEIGHTS, score_contacts, tier

log = logging.getLogger("adpulse.visitors")
VIEW_EVENTS = ("page_view", "product_view", "pricing_view")
SESSION_GAP_MIN = 30


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _consented(client_id: int, contact_id: int) -> dict | None:
    return db.one("SELECT * FROM contacts WHERE id=? AND client_id=? AND consent_marketing=1 AND deleted_at IS NULL", (contact_id, client_id))


# ---------------- People ----------------
def list_people(client_id: int, q: str = "", days: int = 90, limit: int = 300) -> dict:
    since = (_now() - timedelta(days=days)).isoformat()
    scores = score_contacts(client_id, 30)
    like = f"%{q.strip().lower()}%"
    rows = db.rows(
        "SELECT c.id, c.first_name, c.last_name, c.email, c.postcode, c.country, c.is_customer, c.consent_source, c.consent_at, "
        "COUNT(CASE WHEN e.event IN ('page_view','product_view','pricing_view') THEN 1 END) pageviews, "
        "SUM(e.duration_sec) time_sec, MIN(e.ts) first_seen, MAX(e.ts) last_seen, "
        "SUM(CASE WHEN e.event IN ('purchase','lead') THEN e.value ELSE 0 END) value, "
        "SUM(CASE WHEN e.event IN ('purchase','lead') THEN 1 ELSE 0 END) conversions "
        "FROM contacts c JOIN events e ON e.contact_id=c.id "
        "WHERE c.client_id=? AND c.consent_marketing=1 AND c.deleted_at IS NULL AND e.ts>=? "
        "AND (?='%%' OR lower(c.email) LIKE ? OR lower(c.first_name||' '||c.last_name) LIKE ? OR c.postcode LIKE ?) "
        "GROUP BY c.id ORDER BY last_seen DESC LIMIT ?", (client_id, since, like, like, like, like, limit))
    first = _first_touches(client_id, [r["id"] for r in rows])
    for r in rows:
        s = scores.get(r["id"], {})
        r["score"] = s.get("score", 0)
        r["tier"] = tier(r["score"])
        r["name"] = f"{r['first_name']} {r['last_name']}".strip() or r["email"]
        r["first_touch"] = first.get(r["id"])
    return {"people": rows, "days": days,
            "note": "Only visitors who opted in and identified themselves appear here. Their browsing before they identified is linked to them from the same browser."}


def _first_touches(client_id: int, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    out = {}
    marks = ",".join("?" * len(ids))
    for r in db.rows(f"SELECT contact_id, source, medium, campaign, ts FROM events WHERE client_id=? AND contact_id IN ({marks}) "
                     "AND (source<>'' OR medium<>'') ORDER BY ts", (client_id, *ids)):
        if r["contact_id"] in out:
            continue  # rows are oldest first, so the first one per contact is its first touch
        out[r["contact_id"]] = {"channel": channel_of(r["source"], r["medium"]), "campaign": r["campaign"], "ts": r["ts"]}
    return out


def person_detail(client_id: int, contact_id: int) -> dict | None:
    c = _consented(client_id, contact_id)
    if not c:
        return None
    evs = db.rows("SELECT event, url, value, source, medium, campaign, ts, duration_sec FROM events WHERE contact_id=? ORDER BY ts", (contact_id,))
    timeline, sessions, last_ts = [], [], None
    for e in evs:
        t = datetime.fromisoformat(e["ts"][:19])
        if e["event"] == "page_leave":  # real snippet sends time-on-page as a separate event; fold it into the view
            for prev in reversed(timeline):
                if prev["url"] == e["url"] and prev["event"] in VIEW_EVENTS:
                    prev["duration_sec"] = (prev["duration_sec"] or 0) + (e["duration_sec"] or 0)
                    break
            continue
        if last_ts is None or (t - last_ts).total_seconds() > SESSION_GAP_MIN * 60:
            sessions.append({"start": e["ts"], "channel": channel_of(e["source"], e["medium"]) if (e["source"] or e["medium"]) else "Direct",
                             "campaign": e["campaign"], "events": 0, "time_sec": 0})
        last_ts = t
        row = {**e, "session": len(sessions) - 1}
        if e["source"] or e["medium"]:
            row["channel"] = channel_of(e["source"], e["medium"])
        timeline.append(row)
    for r in timeline:
        s = sessions[r["session"]]
        s["events"] += 1
        s["time_sec"] += r["duration_sec"] or 0
    sc = score_contacts(client_id, 30).get(contact_id, {"score": 0})
    touches = [r for r in timeline if r.get("channel")]
    db.audit("", "person_view", f"client={client_id} contact={contact_id}")
    return {
        "contact": {k: c[k] for k in ("id", "first_name", "last_name", "email", "phone", "postcode", "country", "is_customer", "consent_source", "consent_at")},
        "score": sc["score"], "tier": tier(sc["score"]),
        "first_touch": touches[0] if touches else None, "last_touch": touches[-1] if touches else None,
        "sessions": sessions, "timeline": list(reversed(timeline)),
        "totals": {"pageviews": sum(1 for r in timeline if r["event"] in VIEW_EVENTS), "time_sec": sum(r["duration_sec"] or 0 for r in timeline),
                   "sessions": len(sessions), "value": sum(r["value"] or 0 for r in timeline if r["event"] in ("purchase", "lead"))},
    }


# ---------------- Companies (B2B) ----------------
KEEP_TYPES = {"business", "education", "government"}


def _ip_hash(ip: str) -> str:
    return hashlib.sha256((settings.SECRET_KEY + "|" + ip).encode()).hexdigest()


def lookup_company(ip: str) -> dict | None:
    """IP → company via IPinfo (set IPINFO_TOKEN). Returns None for ISPs, hosting, private ranges."""
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_reserved:
            return None
    except ValueError:
        return None
    token = os.getenv("IPINFO_TOKEN", "")
    if not token:
        return None
    h = _ip_hash(ip)
    cached = db.one("SELECT company_json, looked_up_at FROM ip_company_cache WHERE ip_hash=?", (h,))
    if cached and cached["looked_up_at"] > (_now() - timedelta(days=30)).isoformat(sep=" "):
        return json.loads(cached["company_json"]) if cached["company_json"] else None
    comp = None
    try:
        r = httpx.get(f"https://ipinfo.io/{ip}", params={"token": token}, timeout=5)
        body = r.json() if r.status_code == 200 else {}
        c = body.get("company") or {}
        if c.get("type") in KEEP_TYPES and c.get("domain"):
            comp = {"name": c.get("name", ""), "domain": c["domain"].lower(), "city": body.get("city", ""), "industry": "", "employees": ""}
    except Exception:
        log.warning("company lookup failed", exc_info=True)
        return None
    db.execute("INSERT OR REPLACE INTO ip_company_cache (ip_hash, company_json, looked_up_at) VALUES (?,?,CURRENT_TIMESTAMP)",
               (h, json.dumps(comp) if comp else ""))
    return comp


def upsert_company(client_id: int, comp: dict) -> int:
    now = _now().isoformat(timespec="seconds")
    existing = db.one("SELECT id FROM companies WHERE client_id=? AND domain=?", (client_id, comp["domain"]))
    if existing:
        db.execute("UPDATE companies SET last_seen=? WHERE id=?", (now, existing["id"]))
        return existing["id"]
    return db.execute("INSERT INTO companies (client_id, domain, name, industry, employees, city, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?)",
                      (client_id, comp["domain"], comp.get("name", ""), comp.get("industry", ""), comp.get("employees", ""), comp.get("city", ""), now, now))


def attach_company(event_id: int, client_id: int, ip: str) -> None:
    """Background task after /collect: tag the event (and that browser's other events) with the company."""
    comp = lookup_company(ip)
    if not comp:
        return
    cid = upsert_company(client_id, comp)
    ev = db.one("SELECT anon_id FROM events WHERE id=?", (event_id,))
    db.execute("UPDATE events SET company_id=? WHERE client_id=? AND anon_id=? AND company_id IS NULL", (cid, client_id, ev["anon_id"] if ev else ""))


def list_companies(client_id: int, days: int = 30) -> dict:
    since = (_now() - timedelta(days=days)).isoformat()
    now = _now()
    rows = db.rows(
        "SELECT co.id, co.name, co.domain, co.industry, co.employees, co.city, "
        "COUNT(DISTINCT e.anon_id) visitors, COUNT(CASE WHEN e.event IN ('page_view','product_view','pricing_view') THEN 1 END) pageviews, "
        "SUM(e.duration_sec) time_sec, SUM(CASE WHEN e.event='pricing_view' THEN 1 ELSE 0 END) pricing_views, "
        "SUM(CASE WHEN e.event IN ('lead','form_start') THEN 1 ELSE 0 END) form_actions, MAX(e.ts) last_seen, MIN(e.ts) first_seen "
        "FROM companies co JOIN events e ON e.company_id=co.id WHERE co.client_id=? AND e.ts>=? GROUP BY co.id", (client_id, since))
    evs = db.rows("SELECT company_id, event, ts FROM events WHERE client_id=? AND company_id IS NOT NULL AND ts>=?", (client_id, since))
    raw: dict[int, float] = {}
    for e in evs:
        age = (now - datetime.fromisoformat(e["ts"][:19])).total_seconds() / 86400
        raw[e["company_id"]] = raw.get(e["company_id"], 0) + WEIGHTS.get(e["event"], 0.5) * 0.5 ** (age / 7)
    for r in rows:
        r["score"] = round(100 * (1 - math.exp(-raw.get(r["id"], 0) / 45)))
        r["tier"] = tier(r["score"])
    rows.sort(key=lambda r: -r["score"])
    return {"companies": rows, "days": days, "provider_configured": bool(os.getenv("IPINFO_TOKEN"))}


def company_detail(client_id: int, company_id: int) -> dict | None:
    co = db.one("SELECT * FROM companies WHERE id=? AND client_id=?", (company_id, client_id))
    if not co:
        return None
    evs = db.rows("SELECT anon_id, event, url, source, medium, campaign, ts, duration_sec FROM events WHERE company_id=? ORDER BY ts DESC LIMIT 300", (company_id,))
    visitors = sorted({e["anon_id"] for e in evs})
    alias = {a: f"Visitor {i + 1}" for i, a in enumerate(visitors)}   # never expose the raw browser id
    pages: dict[str, dict] = {}
    for e in evs:
        e["visitor"] = alias[e.pop("anon_id")]
        if e["source"] or e["medium"]:
            e["channel"] = channel_of(e["source"], e["medium"])
        if e["event"] in VIEW_EVENTS:
            p = pages.setdefault(e["url"], {"url": e["url"], "views": 0, "time_sec": 0})
            p["views"] += 1
            p["time_sec"] += e["duration_sec"] or 0
    return {"company": co, "timeline": evs, "top_pages": sorted(pages.values(), key=lambda p: -p["time_sec"])[:10], "visitors": len(visitors)}
