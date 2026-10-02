"""Campaign builder: write a Google Search or Meta (Facebook/Instagram) campaign in AdPulse, check it, then launch it.

Launch options:
  * Google Ads Editor file (.csv): works today without API approval. Import it in Google Ads Editor, review, then Post.
  * Meta copy kit: every field in Ads Manager order with copy buttons (Meta's bulk sheet format changes too often to generate safely).
  * Direct send (once the platform connection is live and approved): creates the campaign in the client's own account,
    PAUSED, so nothing spends until you've checked it and switched it on.

Ad text is drafted from the owner's Business details (services, suburb, phone, booking link) and checked against the
platforms' length rules, common Google/Meta policy problems, and Ahpra rules for health businesses.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date

from .. import db

GOOGLE_LIMITS = {"headline": 30, "description": 90, "path": 15, "headlines": (3, 15), "descriptions": (2, 4)}
META_LIMITS = {"primary_text": 125, "headline": 40, "description": 30}
META_OBJECTIVES = {"OUTCOME_TRAFFIC": "More website visits / bookings", "OUTCOME_AWARENESS": "Get seen by locals",
                   "OUTCOME_ENGAGEMENT": "Messages & engagement"}
META_CTAS = {"BOOK_NOW": "Book now", "LEARN_MORE": "Learn more", "CALL_NOW": "Call now", "GET_DIRECTIONS": "Get directions",
             "CONTACT_US": "Contact us", "SIGN_UP": "Sign up"}
STATUSES = {"draft": "Draft", "awaiting_approval": "Waiting for owner's OK", "approved": "Approved by owner",
            "changes_requested": "Owner asked for changes", "exported": "Exported to Google Ads Editor", "sent": "Sent (paused)",
            "live": "Running", "paused": "Paused"}

# Ahpra (health) and general ad-policy red flags: (pattern, message, severity)
HEALTH_FLAGS = [
    (r"\b(best|number one|no\.? ?1|leading|top[- ]rated)\b", "Claims like 'best' or 'leading' can be misleading under Ahpra's advertising rules. Use a factual statement instead.", "error"),
    (r"\b(guarantee[ds]?|100%|cure[sd]?|miracle|instant(ly)?|permanent(ly)?)\b", "Don't promise results or cures in health advertising (Ahpra).", "error"),
    (r"\b(safe|painless|pain[- ]free|risk[- ]free|no side effects)\b", "'Safe' / 'painless' claims create unreasonable expectations (Ahpra).", "error"),
    (r"(patients? say|reviews? say|\bloved by\b|★|5[- ]star|testimonial)", "No testimonials or review quotes in health ads (Ahpra).", "error"),
    (r"\b(better than|cheaper than|unlike other)\b", "Avoid comparing yourself to other practitioners (Ahpra).", "warn"),
    (r"\b(free|discount|% off|gift|bonus|prize)\b", "Offers and gifts are allowed only with clear terms and conditions, and shouldn't encourage unnecessary use of health services (Ahpra).", "warn"),
]
PERSONAL_ATTR = (r"\b(are you|do you (have|suffer)|your (diabetes|depression|anxiety|illness|condition|medication)|struggling with)\b",
                 "Meta doesn't allow ad text that implies you know someone's health condition (e.g. 'Do you have diabetes?'). Speak about the service instead.")
GENERAL_FLAGS = [
    (r"!!|\?\?|!\?", "Google/Meta reject repeated punctuation.", "error"),
    (r"\b[A-Z]{5,}\b", "Avoid words in ALL CAPS (Google rejects gimmicky capitals).", "warn"),
    (r"(\+?61|\(0\d\)|\b0[2-478])\s?\d{4}\s?\d{4}|\b04\d{2}\s?\d{3}\s?\d{3}\b|\b1[38]00\s?\d{3}\s?\d{3}\b", "Phone numbers aren't allowed in Google ad text; use a call asset (the phone field) instead.", "error"),
]
NEGATIVE_DEFAULTS = ["jobs", "careers", "salary", "course", "courses", "degree", "wholesale", "how to become"]


# ---------------------------------------------------------------- drafting
def _fit(text: str, limit: int) -> str | None:
    t = re.sub(r"\s+", " ", text).strip()
    return t if 0 < len(t) <= limit else None


def _uniq(items):
    seen, out = set(), []
    for i in items:
        if i and i.lower() not in seen:
            seen.add(i.lower())
            out.append(i)
    return out


def business_context(client_id: int) -> dict:
    from . import details
    c = db.one("SELECT name, area, search_term FROM clients WHERE id=?", (client_id,)) or {}
    d = details.get(client_id)["details"]
    services = [s.strip(" -•\t") for s in (d.get("services") or "").splitlines() if s.strip(" -•\t")]
    area = (c.get("area") or "").replace(" VIC", "").replace(" NSW", "").replace(" QLD", "").strip() or ""
    return {"business": d.get("business_name") or c.get("name") or "", "area": area, "area_full": c.get("area") or "",
            "term": c.get("search_term") or "", "services": services, "phone": d.get("phone") or "",
            "website": d.get("website") or "", "booking": d.get("booking_link") or "", "address": d.get("address") or "",
            "hours": d.get("hours") or ""}


def is_health(client_id: int) -> bool:
    from . import social
    c = db.one("SELECT name, industry, search_term FROM clients WHERE id=?", (client_id,)) or {}
    text = " ".join(str(c.get(k) or "") for k in ("name", "industry", "search_term")).lower()
    return social.INDUSTRIES.get(c.get("industry") or "", {}).get("health", False) or bool(
        re.search(r"pharm|chemist|dental|dentist|physio|clinic|medical|health|chiro|psycholog|podiat|optom", text))


def draft(client_id: int, platform: str, service: str, monthly_budget: float = 600, radius_km: int = 5) -> dict:
    """First version of the campaign from the business details. Everything is editable afterwards."""
    ctx = business_context(client_id)
    s = service.strip() or (ctx["services"][0] if ctx["services"] else ctx["term"].title() or "Our services")
    a, b = ctx["area"], ctx["business"]
    url = ctx["booking"] or ctx["website"] or ""
    if url and not url.startswith("http"):
        url = "https://" + url
    base = {"platform": platform, "service": s, "name": f"{s} – {a}".strip(" –") if a else s, "monthly_budget": monthly_budget,
            "radius_km": radius_km, "location": ctx["address"] or ctx["area_full"], "final_url": url, "phone": ctx["phone"],
            "start_date": date.today().isoformat()}
    if platform == "google":
        term = ctx["term"] or ""
        heads = _uniq([_fit(h, 30) for h in [
            f"{s} in {a}" if a else s, f"{s} Near You", b, f"Book {s} Online" if ctx["booking"] else f"Enquire About {s}",
            "Book Online Today" if ctx["booking"] else "Call Us Today", f"Local {term.title()} in {a}" if term and a else "",
            f"Visit Us in {a}" if a else "", "Friendly Local Team", "Walk-ins Welcome", f"{s} – {b}", "Easy Online Booking" if ctx["booking"] else "",
            f"Your Local {term.title()}" if term else "", "See Our Opening Hours", s]])
        descs = _uniq([_fit(d, 90) for d in [
            f"{s} at {b}{' in ' + a if a else ''}. {'Book online' if ctx['booking'] else 'Call'} or visit us today.",
            f"Friendly local team{' in ' + a if a else ''}. " + (", ".join(ctx["services"][:3]) + "." if ctx["services"] else "Here to help."),
            f"Find us{' in ' + a if a else ''}. Check our opening hours and {'book online in a few clicks' if ctx['booking'] else 'give us a call'}.",
            f"{s} with a local team you can talk to. {'Book online' if ctx['booking'] else 'Call us'} today."]])
        kw_base = [s.lower()] + ([term.lower()] if term else [])
        keywords = _uniq([k for base_kw in kw_base for k in (f"{base_kw} {a.lower()}" if a else "", f"{base_kw} near me", base_kw)])
        path = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:15]
        return {**base, "headlines": heads[:15], "descriptions": descs[:4], "keywords": keywords[:15], "match": "PHRASE",
                "negatives": NEGATIVE_DEFAULTS, "path1": path, "path2": re.sub(r"[^A-Za-z0-9]+", "-", a).strip("-")[:15] if a else "",
                "bidding": "MAXIMIZE_CLICKS"}
    cta = "BOOK_NOW" if ctx["booking"] else ("CALL_NOW" if ctx["phone"] else "LEARN_MORE")
    return {**base, "objective": "OUTCOME_TRAFFIC", "age_min": 18, "age_max": 65,
            "primary_text": (_fit(f"{s} now available at {b}{' in ' + a if a else ''}. {'Book online in a few clicks' if ctx['booking'] else 'Pop in or give us a call'}.", 125)
                             or _fit(f"{s} at {b}. Book online or visit us.", 125) or s),
            "headline": _fit(f"{s} in {a}", 40) or _fit(s, 40) or "",
            "description": _fit("Book online or walk in" if ctx["booking"] else "Visit us or call today", 30) or "",
            "cta": cta, "photo_id": None, "page_id": ""}


# ---------------------------------------------------------------- checks
def _scan(text: str, health: bool, meta: bool) -> list[tuple[str, str]]:
    out = []
    for rx, msg, sev in GENERAL_FLAGS + (HEALTH_FLAGS if health else []):
        if re.search(rx, text or "", re.I if "A-Z" not in rx else 0):
            out.append((sev, msg))
    if meta and health and re.search(PERSONAL_ATTR[0], text or "", re.I):
        out.append(("error", PERSONAL_ATTR[1]))
    return out


def check(c: dict, health: bool) -> list[dict]:
    """Problems that would get the ad rejected, or break Ahpra rules for health businesses. [{level, field, message}]"""
    issues = []

    def add(level, field, msg):
        issues.append({"level": level, "field": field, "message": msg})
    if not c.get("final_url"):
        add("error", "final_url", "Add the page people land on (booking page or website).")
    elif not re.match(r"^https?://[^\s/$.?#].[^\s]*$", c["final_url"]):
        add("error", "final_url", "The landing page must be a full web address starting with https://")
    if (c.get("monthly_budget") or 0) <= 0:
        add("error", "monthly_budget", "Set a monthly budget.")
    elif c["monthly_budget"] < 300:
        add("warn", "monthly_budget", "Under $300/month gives very few clicks. Expect slow results.")
    if c["platform"] == "google":
        hs, ds = [h for h in c.get("headlines", []) if h.strip()], [d for d in c.get("descriptions", []) if d.strip()]
        if len(hs) < 3:
            add("error", "headlines", "Google needs at least 3 headlines (ideally 8–15).")
        elif len(hs) < 8:
            add("warn", "headlines", "Add a few more headlines (8–15) so Google can find the best mix.")
        if len(ds) < 2:
            add("error", "descriptions", "Google needs at least 2 descriptions.")
        for i, h in enumerate(hs):
            if len(h) > 30:
                add("error", f"headlines.{i}", f"Headline {i + 1} is {len(h)} characters (max 30).")
        if len({h.lower() for h in hs}) < len(hs):
            add("error", "headlines", "Two headlines are the same. Each must be different.")
        for i, d in enumerate(ds):
            if len(d) > 90:
                add("error", f"descriptions.{i}", f"Description {i + 1} is {len(d)} characters (max 90).")
        for i, h in enumerate(hs):
            if "!" in h:
                add("error", f"headlines.{i}", f"Headline {i + 1}: exclamation marks aren't allowed in Google headlines.")
        for p in ("path1", "path2"):
            if len(c.get(p) or "") > 15:
                add("error", p, "Display path parts are max 15 characters.")
        if not [k for k in c.get("keywords", []) if k.strip()]:
            add("error", "keywords", "Add at least one keyword.")
        texts = [("headlines", h) for h in hs] + [("descriptions", d) for d in ds]
    else:
        if c.get("objective") not in META_OBJECTIVES:
            add("error", "objective", "Choose what the campaign is for.")
        for f, lim in META_LIMITS.items():
            v = c.get(f) or ""
            if f != "description" and not v.strip():
                add("error", f, f"Add the {f.replace('_', ' ')}.")
            if len(v) > lim:
                add("warn", f, f"{f.replace('_', ' ').capitalize()} is {len(v)} characters; over {lim} gets cut off on phones.")
        if not c.get("photo_id"):
            add("error", "photo_id", "Pick a photo (from Business details & photos).")
        if not (18 <= int(c.get("age_min") or 18) <= int(c.get("age_max") or 65) <= 65):
            add("error", "age_min", "Ages must be between 18 and 65+.")
        texts = [(f, c.get(f) or "") for f in ("primary_text", "headline", "description")]
    for field, t in texts:
        for sev, msg in _scan(t, health, c["platform"] == "meta"):
            if c["platform"] == "meta" and "Phone numbers" in msg:
                continue          # phone numbers are fine in Meta text
            add(sev, field, f"“{t[:40]}{'…' if len(t) > 40 else ''}”: {msg}")
    if health:
        add("info", "", "Health business: keep ads factual, with no testimonials, no promised results and no 'best' claims (Ahpra). "
                        "The owner should approve the wording before it goes live.")
    return issues


# ---------------------------------------------------------------- storage
def _row(r: dict) -> dict:
    out = dict(r)
    out["data"] = json.loads(out.get("data") or "{}")
    out["remote"] = json.loads(out.get("remote") or "{}")
    return out


def list_(client_id: int) -> list[dict]:
    return [_row(r) for r in db.rows("SELECT * FROM campaigns WHERE client_id=? ORDER BY id DESC", (client_id,))]


def get(client_id: int, cid: int) -> dict:
    r = db.one("SELECT * FROM campaigns WHERE id=? AND client_id=?", (cid, client_id))
    if not r:
        raise ValueError("Campaign not found")
    c = _row(r)
    c["checks"] = check({**c["data"], "platform": c["platform"]}, is_health(client_id))
    c["status_label"] = STATUSES.get(c["status"], c["status"])
    return c


def create(client_id: int, platform: str, service: str, monthly_budget: float, radius_km: int, user: str) -> dict:
    if platform not in ("google", "meta"):
        raise ValueError("Platform must be google or meta")
    data = draft(client_id, platform, service, monthly_budget, radius_km)
    cid = db.execute("INSERT INTO campaigns (client_id, platform, name, status, data, created_by) VALUES (?,?,?,?,?,?)",
                     (client_id, platform, data["name"][:120], "draft", json.dumps(data), user))
    return get(client_id, cid)


EDITABLE = {"name", "service", "monthly_budget", "radius_km", "location", "final_url", "phone", "start_date", "headlines", "descriptions",
            "keywords", "match", "negatives", "path1", "path2", "objective", "age_min", "age_max", "primary_text", "headline",
            "description", "cta", "photo_id", "page_id", "bidding"}


def update(client_id: int, cid: int, body: dict) -> dict:
    c = get(client_id, cid)
    data = c["data"]
    for k, v in body.items():
        if k not in EDITABLE:
            continue
        if k in ("headlines", "descriptions", "keywords", "negatives"):
            v = [re.sub(r"\s+", " ", str(x)).strip() for x in (v or []) if str(x).strip()][:20]
        elif k in ("monthly_budget",):
            v = max(0.0, float(v or 0))
        elif k in ("radius_km", "age_min", "age_max", "photo_id"):
            v = int(v) if v not in (None, "") else None
        else:
            v = str(v or "").strip()[:600]
        data[k] = v
    status = c["status"] if c["status"] in ("draft", "changes_requested") else "draft"   # an edit after approval needs approving again
    db.execute("UPDATE campaigns SET data=?, name=?, status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND client_id=?",
               (json.dumps(data), (data.get("name") or c["name"])[:120], status if c["status"] not in ("sent", "live", "paused") else c["status"], cid, client_id))
    return get(client_id, cid)


def set_status(client_id: int, cid: int, status: str, note: str = "", user: str = "") -> dict:
    get(client_id, cid)
    db.execute("UPDATE campaigns SET status=?, owner_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND client_id=?",
               (status, (note or "")[:500], cid, client_id))
    return get(client_id, cid)


def delete(client_id: int, cid: int) -> None:
    db.execute("DELETE FROM campaigns WHERE id=? AND client_id=? AND status NOT IN ('sent','live','paused')", (cid, client_id))


# ---------------------------------------------------------------- Google Ads Editor export
def editor_csv(c: dict) -> bytes:
    """One row per item (campaign, location, ad group, keywords, negatives, ad), the layout Google Ads Editor imports.
    In Editor: Account → Import → From file…, review the changes, then Post. Everything arrives Paused."""
    d = c["data"]
    camp, group = d.get("name") or c["name"], (d.get("service") or "Ad group 1")[:80]
    daily = round((d.get("monthly_budget") or 0) / 30.4, 2)
    cols = ["Campaign", "Campaign Type", "Networks", "Budget", "Budget type", "Bid Strategy Type", "Campaign Status", "Start Date",
            "Languages", "Location", "Radius", "Unit", "Ad Group", "Ad Group Status", "Keyword", "Criterion Type", "Ad type"] + \
           [f"Headline {i}" for i in range(1, 16)] + [f"Description {i}" for i in range(1, 5)] + ["Path 1", "Path 2", "Final URL", "Status"]
    rows = []

    def row(**kw):
        rows.append({k: kw.get(k.replace(" ", "_"), "") for k in cols})
    row(Campaign=camp, Campaign_Type="Search", Networks="Google search", Budget=f"{daily:.2f}", Budget_type="Daily",
        Bid_Strategy_Type="Maximize clicks" if d.get("bidding") != "MAXIMIZE_CONVERSIONS" else "Maximize conversions",
        Campaign_Status="Paused", Start_Date=d.get("start_date", ""), Languages="en")
    if d.get("location"):
        row(Campaign=camp, Location=d["location"], Radius=str(d.get("radius_km") or 5), Unit="km")
    row(Campaign=camp, Ad_Group=group, Ad_Group_Status="Enabled")
    match = {"EXACT": "Exact", "PHRASE": "Phrase", "BROAD": "Broad"}.get(d.get("match", "PHRASE"), "Phrase")
    for k in d.get("keywords", []):
        row(Campaign=camp, Ad_Group=group, Keyword=k, Criterion_Type=match, Status="Enabled")
    for k in d.get("negatives", []):
        row(Campaign=camp, Keyword=k, Criterion_Type="Campaign negative phrase")
    ad = {"Campaign": camp, "Ad_Group": group, "Ad_type": "Responsive search ad", "Path_1": d.get("path1", ""), "Path_2": d.get("path2", ""),
          "Final_URL": d.get("final_url", ""), "Status": "Enabled"}
    for i, h in enumerate(d.get("headlines", [])[:15], 1):
        ad[f"Headline_{i}"] = h
    for i, x in enumerate(d.get("descriptions", [])[:4], 1):
        ad[f"Description_{i}"] = x
    row(**ad)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------- direct send (needs a live, approved connection)
def _connection(client_id: int, platform: str) -> dict | None:
    key = {"google": "google_ads", "meta": "meta_ads"}[platform]
    return db.one("SELECT * FROM connections WHERE client_id=? AND platform=? AND is_demo=0 AND status!='error' ORDER BY id DESC LIMIT 1",
                  (client_id, key))


def can_send(client_id: int, platform: str) -> bool:
    return _connection(client_id, platform) is not None


def send(client_id: int, cid: int) -> dict:
    """Create the campaign in the client's own ad account, PAUSED. Raises ValueError with a plain-English reason."""
    from ..security import decrypt_json, encrypt_json
    c = get(client_id, cid)
    if any(i["level"] == "error" for i in c["checks"]):
        raise ValueError("Fix the red problems first.")
    if c["status"] in ("sent", "live", "paused"):
        raise ValueError("This campaign has already been sent.")
    conn = _connection(client_id, c["platform"])
    if not conn:
        raise ValueError("Connect their " + ("Google Ads" if c["platform"] == "google" else "Meta ad") + " account first (Connections tab). "
                         "Until then, use the Google Ads Editor file or the Meta copy kit.")
    creds = decrypt_json(conn["credentials_enc"])
    if c["platform"] == "google":
        remote, new_creds = _send_google(conn["account_id"], creds, c)
        if new_creds:
            db.execute("UPDATE connections SET credentials_enc=? WHERE id=?", (encrypt_json(new_creds), conn["id"]))
    else:
        remote = _send_meta(client_id, conn["account_id"], creds, c)
    db.execute("UPDATE campaigns SET status='sent', remote=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(remote), cid))
    return get(client_id, cid)


def _send_google(account_id: str, creds: dict, c: dict) -> tuple[dict, dict | None]:
    import httpx
    from ..config import settings
    from ..oauth import refresh_if_needed
    new = refresh_if_needed("google", creds)
    tok = (new or creds)["access_token"]
    cust = account_id.replace("-", "")
    d = c["data"]
    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    if settings.GOOGLE_ADS_DEVELOPER_TOKEN:
        headers["developer-token"] = settings.GOOGLE_ADS_DEVELOPER_TOKEN
    if settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID:
        headers["login-customer-id"] = settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID.replace("-", "")
    rn = lambda kind, n: f"customers/{cust}/{kind}/{n}"   # noqa: E731  (temporary ids let one request create everything)
    budget, camp, group = rn("campaignBudgets", -1), rn("campaigns", -2), rn("adGroups", -3)
    ops = [
        {"campaignBudgetOperation": {"create": {"resourceName": budget, "name": f"{d['name']} budget {date.today()}",
                                                "amountMicros": int(round((d["monthly_budget"] / 30.4) * 1_000_000, -4)),
                                                "deliveryMethod": "STANDARD", "explicitlyShared": False}}},
        {"campaignOperation": {"create": {"resourceName": camp, "name": d["name"], "status": "PAUSED", "advertisingChannelType": "SEARCH",
                                          "campaignBudget": budget, "targetSpend": {},
                                          "networkSettings": {"targetGoogleSearch": True, "targetSearchNetwork": False,
                                                              "targetContentNetwork": False, "targetPartnerSearchNetwork": False},
                                          "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"}}},
        {"adGroupOperation": {"create": {"resourceName": group, "campaign": camp, "name": d.get("service") or "Ad group 1",
                                         "status": "ENABLED", "type": "SEARCH_STANDARD"}}},
    ]
    if d.get("location"):
        ops.append({"campaignCriterionOperation": {"create": {"campaign": camp, "proximity": {
            "address": {"streetAddress": d["location"], "countryCode": "AU"}, "radius": float(d.get("radius_km") or 5), "radiusUnits": "KILOMETERS"}}}})
    for k in d.get("keywords", []):
        ops.append({"adGroupCriterionOperation": {"create": {"adGroup": group, "status": "ENABLED",
                                                             "keyword": {"text": k, "matchType": d.get("match", "PHRASE")}}}})
    for k in d.get("negatives", []):
        ops.append({"campaignCriterionOperation": {"create": {"campaign": camp, "negative": True, "keyword": {"text": k, "matchType": "PHRASE"}}}})
    ops.append({"adGroupAdOperation": {"create": {"adGroup": group, "status": "ENABLED", "ad": {
        "finalUrls": [d["final_url"]], "responsiveSearchAd": {
            "headlines": [{"text": h} for h in d["headlines"][:15]], "descriptions": [{"text": x} for x in d["descriptions"][:4]],
            **({"path1": d["path1"]} if d.get("path1") else {}), **({"path2": d["path2"]} if d.get("path2") and d.get("path1") else {})}}}}})
    url = f"https://googleads.googleapis.com/{settings.GOOGLE_ADS_API_VERSION}/customers/{cust}/googleAds:mutate"
    r = httpx.post(url, headers=headers, json={"mutateOperations": ops}, timeout=60)
    if r.status_code >= 400:
        raise ValueError(_google_error(r))
    res = r.json().get("mutateOperationResponses", [])
    camp_rn = next((x.get("campaignResult", {}).get("resourceName") for x in res if "campaignResult" in x), "")
    return {"platform": "google", "campaign": camp_rn, "customer": cust,
            "url": f"https://ads.google.com/aw/campaigns?ocid=&__e={cust}"}, new


def _google_error(r) -> str:
    try:
        errs = r.json()["error"]["details"][0]["errors"]
        return "Google Ads said: " + "; ".join(e.get("message", "") for e in errs[:3])
    except Exception:
        txt = r.text[:300]
        if r.status_code in (401, 403):
            return ("Google Ads refused access. Check the Google Ads API access for your Google Cloud project is approved, "
                    "and that the connected login can manage this account. " + txt)
        return f"Google Ads error {r.status_code}: {txt}"


def _send_meta(client_id: int, account_id: str, creds: dict, c: dict) -> dict:
    import base64
    import httpx
    from ..config import settings
    from . import details
    d = c["data"]
    if not d.get("page_id"):
        raise ValueError("Add their Facebook Page ID (Meta asks which Page the ad runs from).")
    acct = account_id if account_id.startswith("act_") else f"act_{account_id}"
    g = f"https://graph.facebook.com/{settings.META_API_VERSION}"
    tok = creds["access_token"]

    def post(path, data):
        r = httpx.post(f"{g}/{path}", data={**data, "access_token": tok}, timeout=60)
        body = r.json() if r.headers.get("content-type", "").startswith(("application/json", "text/javascript")) else {}
        if r.status_code >= 400 or "error" in body:
            msg = (body.get("error") or {}).get("error_user_msg") or (body.get("error") or {}).get("message") or r.text[:300]
            raise ValueError(f"Meta said: {msg}")
        return body
    photo = details.photo(client_id, int(d["photo_id"]))
    if not photo:
        raise ValueError("The chosen photo was deleted. Pick another.")
    img = post(f"{acct}/adimages", {"bytes": base64.b64encode(photo[0]).decode()})
    image_hash = next(iter(img.get("images", {}).values()), {}).get("hash")
    camp = post(f"{acct}/campaigns", {"name": d["name"], "objective": d["objective"], "status": "PAUSED",
                                      "special_ad_categories": "[]", "is_adset_budget_sharing_enabled": "false"})
    goal = {"OUTCOME_TRAFFIC": "LINK_CLICKS", "OUTCOME_AWARENESS": "REACH", "OUTCOME_ENGAGEMENT": "POST_ENGAGEMENT"}[d["objective"]]
    targeting = {"age_min": int(d.get("age_min") or 18), "age_max": int(d.get("age_max") or 65),
                 "geo_locations": {"custom_locations": [{"address_string": d["location"], "radius": int(d.get("radius_km") or 5),
                                                         "distance_unit": "kilometer"}]} if d.get("location") else {"countries": ["AU"]}}
    adset = post(f"{acct}/adsets", {"name": f"{d['name']} – {d.get('radius_km') or 5}km", "campaign_id": camp["id"],
                                    "daily_budget": str(int(round(d["monthly_budget"] / 30.4 * 100))), "billing_event": "IMPRESSIONS",
                                    "optimization_goal": goal, "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "status": "PAUSED",
                                    "targeting": json.dumps(targeting)})
    link = {"link": d["final_url"], "message": d["primary_text"], "name": d["headline"], "image_hash": image_hash,
            "call_to_action": {"type": d.get("cta", "LEARN_MORE"), "value": {"link": d["final_url"]}}}
    if d.get("description"):
        link["description"] = d["description"]
    creative = post(f"{acct}/adcreatives", {"name": f"{d['name']} creative",
                                            "object_story_spec": json.dumps({"page_id": d["page_id"], "link_data": link})})
    ad = post(f"{acct}/ads", {"name": f"{d['name']} ad", "adset_id": adset["id"], "creative": json.dumps({"creative_id": creative["id"]}),
                              "status": "PAUSED"})
    return {"platform": "meta", "campaign": camp["id"], "adset": adset["id"], "ad": ad["id"], "account": acct,
            "url": f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={acct.replace('act_', '')}"}


def switch(client_id: int, cid: int, on: bool) -> dict:
    """Turn a sent campaign on or off in the ad platform."""
    import httpx
    from ..config import settings
    from ..security import decrypt_json
    c = get(client_id, cid)
    if c["status"] not in ("sent", "live", "paused"):
        raise ValueError("Send the campaign first.")
    conn = _connection(client_id, c["platform"])
    if not conn:
        raise ValueError("The ad account connection is missing.")
    creds = decrypt_json(conn["credentials_enc"])
    rem = c["remote"]
    if c["platform"] == "google":
        from ..oauth import refresh_if_needed
        tok = (refresh_if_needed("google", creds) or creds)["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}
        if settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID:
            headers["login-customer-id"] = settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID.replace("-", "")
        r = httpx.post(f"https://googleads.googleapis.com/{settings.GOOGLE_ADS_API_VERSION}/customers/{rem['customer']}/campaigns:mutate",
                       headers=headers, json={"operations": [{"update": {"resourceName": rem["campaign"], "status": "ENABLED" if on else "PAUSED"},
                                                              "updateMask": "status"}]}, timeout=30)
        if r.status_code >= 400:
            raise ValueError(_google_error(r))
    else:
        for obj in (rem["campaign"], rem["adset"], rem["ad"]):
            r = httpx.post(f"https://graph.facebook.com/{settings.META_API_VERSION}/{obj}",
                           data={"status": "ACTIVE" if on else "PAUSED", "access_token": creds["access_token"]}, timeout=30)
            if r.status_code >= 400:
                raise ValueError("Meta said: " + r.text[:300])
    db.execute("UPDATE campaigns SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", ("live" if on else "paused", cid))
    return get(client_id, cid)
