"""Business details & photos: the owner fills these in from their own login, so the agency has everything
needed to complete the Google Business Profile and website (hours, services, description, team, photos, access).

Photos are resized in the browser before upload (max ~1600px JPEG) and stored in the database, so they survive
restarts on hosts with temporary disks (e.g. Render's free plan).
"""
from __future__ import annotations

import base64
import io
import json
import re
import zipfile

from .. import db

FIELDS = [
    # key, label, type, help
    ("business_name", "Business name (exactly as on the sign)", "text", ""),
    ("phone", "Phone", "text", ""),
    ("email", "Email for enquiries", "text", ""),
    ("address", "Address", "text", ""),
    ("website", "Website", "text", ""),
    ("booking_link", "Online booking link (if any)", "text", "e.g. your booking page or HotDoc/MedAdvisor link"),
    ("hours", "Opening hours", "textarea", "One line per day, e.g. Mon–Fri 8:30am–7pm, Sat 9am–5pm, Sun closed"),
    ("holiday_hours", "Public holiday hours coming up", "textarea", ""),
    ("services", "Services you offer", "textarea", "One per line, e.g. Flu & COVID vaccinations, Webster packs, script refills, blood pressure checks"),
    ("description", "About the business (2–4 sentences)", "textarea", "What you do, who you help, what makes you different. Facts only: no promises about health results."),
    ("team", "Pharmacists / team to mention", "textarea", "Name and role, e.g. Sarah Nguyen, Pharmacist in charge. Only people happy to be named."),
    ("parking", "Parking, access and getting here", "textarea", ""),
    ("website_platform", "Your website is built with", "select", ""),
    ("website_manager", "Who looks after the website (name, company, email)", "text", "Leave blank if you do it yourself"),
    ("notes", "Anything else we should know", "textarea", ""),
    # --- for tailoring the ads (shown under their own heading) ---
    ("promote", "Which services do you most want more customers for?", "textarea",
     "Most important first, one per line, e.g. Flu vaccinations, Webster packs, skin checks"),
    ("customers", "Who are your best customers?", "textarea", "e.g. seniors and carers nearby, young families, people who work locally"),
    ("why_us", "Why do people choose you over other businesses nearby?", "textarea",
     "One per line, e.g. Open till 9pm, Free local delivery, Greek & Vietnamese spoken, Scripts ready while you wait"),
    ("offers", "Any offers, events or seasonal services coming up?", "textarea",
     "e.g. Free blood pressure checks on Tuesdays, flu shots from April. Only things you're happy to advertise."),
    ("service_area", "Suburbs you want customers from", "text", "e.g. East Bentleigh, Bentleigh, Moorabbin, Ormond"),
    ("languages", "Languages your team speaks", "text", ""),
    ("ad_budget", "Rough monthly amount you're comfortable spending on ads", "text",
     "Paid straight to Google/Meta on your own card. A range is fine, e.g. $300–$500"),
    ("avoid", "Anything we should NOT advertise or say?", "textarea", ""),
]
AD_FIELDS_START = "promote"
PLATFORMS = ["Don't know", "WordPress", "Wix", "Squarespace", "Shopify", "GoDaddy", "Banner group / head office site", "Other"]
ACCESS = [
    ("gbp_manager", "I've added the agency as Manager on our Google Business Profile",
     "business.google.com → Business Profile settings → People and access → Add → agency email → Manager"),
    ("website_access", "I've given the agency a login to our website (or introduced them to whoever manages it)", ""),
    ("photos_ok", "Staff in the photos are happy for them to be used online", ""),
]
PHOTO_TYPES = [("shopfront", "Shopfront (outside)"), ("inside", "Inside the store"), ("counter", "Counter / dispensary"),
               ("team", "Team (with their OK)"), ("services", "Services (e.g. consult room)"), ("products", "Products / displays"), ("other", "Other")]
MAX_PHOTO_BYTES = 3 * 1024 * 1024
MAX_PHOTOS = 40
_MAGIC = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"RIFF": "image/webp"}


def get(client_id: int) -> dict:
    row = db.one("SELECT details, updated_by, updated_at FROM client_details WHERE client_id=?", (client_id,))
    try:
        data = json.loads(row["details"]) if row else {}
    except Exception:
        data = {}
    photos = db.rows("SELECT id, filename, category, caption, size, uploaded_by, created_at FROM client_photos WHERE client_id=? ORDER BY id DESC",
                     (client_id,))
    filled = sum(1 for k, *_ in FIELDS if str(data.get(k, "")).strip())
    return {"details": data, "fields": FIELDS, "platforms": PLATFORMS, "access": ACCESS, "photo_types": PHOTO_TYPES,
            "photos": photos, "filled": filled, "ad_start": AD_FIELDS_START, "total": len(FIELDS),
            "access_done": sum(1 for k, *_ in ACCESS if data.get(k)), "updated_by": (row or {}).get("updated_by"),
            "updated_at": (row or {}).get("updated_at")}


def save(client_id: int, body: dict, user: str) -> dict:
    cur = get(client_id)["details"]
    for k, _, typ, _ in FIELDS:
        if k in body:
            v = str(body[k] or "").strip()[:3000 if typ == "textarea" else 300]
            if typ == "select" and v not in PLATFORMS:
                v = ""
            cur[k] = v
    for k, *_ in ACCESS:
        if k in body:
            cur[k] = bool(body[k])
    db.execute("INSERT INTO client_details (client_id, details, updated_by, updated_at) VALUES (?,?,?,CURRENT_TIMESTAMP) "
               "ON CONFLICT(client_id) DO UPDATE SET details=excluded.details, updated_by=excluded.updated_by, updated_at=CURRENT_TIMESTAMP",
               (client_id, json.dumps(cur), user))
    return get(client_id)


def add_photo(client_id: int, raw: bytes, filename: str, category: str, caption: str, user: str) -> dict:
    if len(raw) > MAX_PHOTO_BYTES:
        raise ValueError("That photo is too big (3 MB max after resizing). Try again, or pick a smaller photo.")
    ctype = next((t for m, t in _MAGIC.items() if raw.startswith(m)), None)
    if not ctype or (ctype == "image/webp" and raw[8:12] != b"WEBP"):
        raise ValueError("Only JPG, PNG or WebP photos can be uploaded.")
    n = db.one("SELECT COUNT(*) n FROM client_photos WHERE client_id=?", (client_id,))["n"]
    if n >= MAX_PHOTOS:
        raise ValueError(f"Up to {MAX_PHOTOS} photos. Delete a few old ones first.")
    cat = category if category in dict(PHOTO_TYPES) else "other"
    name = re.sub(r"[^\w.\- ]", "", filename or "photo")[:80] or "photo"
    db.execute("INSERT INTO client_photos (client_id, filename, content_type, data, category, caption, size, uploaded_by) VALUES (?,?,?,?,?,?,?,?)",
               (client_id, name, ctype, base64.b64encode(raw).decode(), cat, (caption or "")[:200], len(raw), user))
    return get(client_id)


def photo(client_id: int, photo_id: int) -> tuple[bytes, str, str] | None:
    r = db.one("SELECT filename, content_type, data FROM client_photos WHERE id=? AND client_id=?", (photo_id, client_id))
    return (base64.b64decode(r["data"]), r["content_type"], r["filename"]) if r else None


def delete_photo(client_id: int, photo_id: int) -> dict:
    db.execute("DELETE FROM client_photos WHERE id=? AND client_id=?", (photo_id, client_id))
    return get(client_id)


def photos_zip(client_id: int) -> bytes:
    buf = io.BytesIO()
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in db.rows("SELECT id, filename, content_type, data, category FROM client_photos WHERE client_id=? ORDER BY id", (client_id,)):
            stem = re.sub(r"\.[a-z0-9]+$", "", r["filename"], flags=re.I)
            z.writestr(f"{r['category']}/{r['id']}-{stem}.{ext.get(r['content_type'], 'jpg')}", base64.b64decode(r["data"]))
        d = get(client_id)
        lines = []
        for k, label, *_ in FIELDS:
            v = str(d["details"].get(k, "")).strip()
            if v:
                lines.append(f"{label}:\n{v}\n")
        z.writestr("business-details.txt", "\n".join(lines) or "No details filled in yet.")
    return buf.getvalue()
