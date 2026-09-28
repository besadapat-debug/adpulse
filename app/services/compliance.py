"""Privacy & compliance: consent capture, access/erasure requests, retention, region policy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import db
from ..config import settings

REGION_POLICY = {
    "AU": {"law": "Privacy Act 1988 (APPs) + Spam Act 2003", "basis": "Consent for direct marketing; disclose ad-platform sharing in your privacy policy",
           "notes": "Honour opt-outs promptly; hashed uploads are still personal information."},
    "EU": {"law": "GDPR + ePrivacy", "basis": "Explicit opt-in consent (incl. ad_user_data / ad_personalization for Google)",
           "notes": "Consent Mode v2 required for Google Ads measurement; DPA with each platform; 30-day DSAR response."},
    "UK": {"law": "UK GDPR + PECR", "basis": "Opt-in consent for marketing cookies/uploads", "notes": "As EU."},
    "US-CA": {"law": "CCPA/CPRA", "basis": "Notice + right to opt out of 'sharing' for cross-context behavioural ads",
              "notes": "Honour Global Privacy Control; 'Do Not Sell or Share' link required."},
    "US": {"law": "State privacy laws (VA, CO, CT, TX, etc.)", "basis": "Notice + opt-out of targeted advertising", "notes": "Check each state."},
    "NZ": {"law": "Privacy Act 2020 + UEMA 2007", "basis": "Consent for marketing messages", "notes": ""},
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def upsert_contact(client_id: int, data: dict, consent: bool | None, source: str) -> int:
    email = (data.get("email") or "").strip().lower()
    existing = db.one("SELECT * FROM contacts WHERE client_id=? AND email=?", (client_id, email)) if email else None
    fields = {k: (data.get(k) or "").strip() for k in ("phone", "first_name", "last_name", "country", "postcode", "external_id")}
    if existing:
        sets = {k: v for k, v in fields.items() if v}
        if consent is not None:
            sets.update(consent_marketing=int(consent), consent_source=source, consent_at=_now())
        if data.get("is_customer"):
            sets["is_customer"] = 1
        if sets:
            db.execute(f"UPDATE contacts SET {', '.join(f'{k}=?' for k in sets)}, deleted_at=NULL WHERE id=?", (*sets.values(), existing["id"]))
        return existing["id"]
    return db.execute(
        "INSERT INTO contacts (client_id, email, phone, first_name, last_name, country, postcode, external_id, consent_marketing, consent_source, consent_at, is_customer) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (client_id, email, fields["phone"], fields["first_name"], fields["last_name"], fields["country"], fields["postcode"], fields["external_id"],
         int(bool(consent)), source if consent is not None else "", _now() if consent is not None else None, int(bool(data.get("is_customer")))))


def access_request(client_id: int, email: str) -> dict:
    c = db.one("SELECT * FROM contacts WHERE client_id=? AND email=?", (client_id, email.strip().lower()))
    if not c:
        return {"found": False}
    evs = db.rows("SELECT event, url, source, medium, campaign, value, ts FROM events WHERE contact_id=? ORDER BY ts", (c["id"],))
    syncs = db.rows("SELECT DISTINCT s.platform FROM audience_syncs s JOIN audiences a ON a.id=s.audience_id WHERE a.client_id=? AND s.status='ok'", (client_id,))
    db.audit("", "dsar_access", f"client={client_id} contact={c['id']}")
    return {"found": True, "contact": c, "events": evs, "shared_with_platforms": [s["platform"] for s in syncs]}


def erase(client_id: int, email: str) -> dict:
    """Right to erasure. Marks deleted immediately (excluded from every export and removed from
    platform audiences on the next sync), then PII is wiped by purge_erased() after 30 days."""
    c = db.one("SELECT id FROM contacts WHERE client_id=? AND email=?", (client_id, email.strip().lower()))
    if not c:
        return {"found": False}
    db.execute("UPDATE contacts SET deleted_at=?, consent_marketing=0 WHERE id=?", (_now(), c["id"]))
    db.execute("DELETE FROM events WHERE contact_id=?", (c["id"],))
    db.audit("", "dsar_erase", f"client={client_id} contact={c['id']}")
    return {"found": True, "erased": True}


def purge_expired_events() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.EVENT_RETENTION_DAYS)).isoformat()
    with db.tx() as c:
        n = c.execute("DELETE FROM events WHERE ts < ?", (cutoff,)).rowcount
        wipe = (datetime.now(timezone.utc) - timedelta(days=30)).replace(tzinfo=None).isoformat()
        c.execute("UPDATE contacts SET email='', phone='', first_name='', last_name='', postcode='', external_id='' "
                  "WHERE deleted_at IS NOT NULL AND deleted_at < ? AND email<>''", (wipe,))
    return n
