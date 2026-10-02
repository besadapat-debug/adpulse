"""AdPulse web app (FastAPI). Run: uvicorn app.main:app --reload"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import date
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, oauth
from .config import settings
from .connectors import PLATFORMS
from .security import encrypt_json, hash_password, random_state, sign, unsign, verify_password
from .services import alerts as alerts_svc
from .services import attribution as attr_svc
from .services import audiences as aud_svc
from .services import budget as budget_svc
from .services import ai as ai_svc, competitors as comp_svc, compliance, metrics, prospects as prospect_svc, visitors
from .services.sync import scheduler, sync_client, sync_connection

logging.basicConfig(level=logging.INFO)
HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app):
    from .security import fernet
    fernet()  # fail fast if SECRET_KEY is missing in a cloud deployment
    db.connect().close()
    alerts_svc.ensure_default_rules()
    if settings.DEMO_MODE and not db.one("SELECT id FROM clients LIMIT 1"):
        from .seed import seed
        seed()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
# changes on every deploy, so browsers fetch the new scripts/styles instead of an old cached copy
templates.env.globals["v"] = (os.getenv("RENDER_GIT_COMMIT") or "")[:8] or str(int(__import__("time").time()))
SESSION_TTL = 60 * 60 * 24 * 14


# ---------------- auth ----------------
def current_user(request: Request) -> dict | None:
    tok = request.cookies.get("session")
    data = unsign(tok) if tok else None
    return db.one("SELECT id, email, name, role, client_id FROM users WHERE id=?", (data["uid"],)) if data else None


# A client login can only read its own business: these pages/endpoints, GET only, and only for users.client_id.
CLIENT_PATHS = re.compile(r"^/(?:$|logout$|clients/(?P<a>\d+)(?:/monthly|/trial-report)?$|api/platforms$|"
                          r"api/clients/(?P<b>\d+)(?:/(?:performance|engagement|organic|seo|email|audience|local|monthly|trial|campaigns(?:/\d+)?))?$)")


CLIENT_WRITE = re.compile(r"^/api/clients/(\d+)/(?:details|photos(?:/\d+)?|campaigns/\d+/review)$")


def require_user(request: Request) -> dict:
    u = current_user(request)
    if not u:
        raise HTTPException(401, "Not signed in")
    if u["role"] == "client":
        path = request.url.path
        w = CLIENT_WRITE.match(path)
        if w and request.method in ("GET", "POST", "PUT", "DELETE") and u["client_id"] and int(w.group(1)) == u["client_id"]:
            return u                      # the owner may fill in their own business details and photos
        m = CLIENT_PATHS.match(path)
        cid = m and (m.group("a") or m.group("b"))
        if not m or request.method != "GET" or (cid and int(cid) != u["client_id"]) or not u["client_id"]:
            raise HTTPException(403, "This login can only see its own business")
    return u


def require_editor(user: dict = Depends(require_user)) -> dict:
    if user["role"] in ("viewer", "client"):
        raise HTTPException(403, "Read-only account")
    return user


def require_owner(user: dict = Depends(require_user)) -> dict:
    if user["role"] != "owner":
        raise HTTPException(403, "Owner only")
    return user


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    if exc.status_code == 401 and not request.url.path.startswith("/api"):
        return RedirectResponse("/login")
    if exc.status_code == 403 and not request.url.path.startswith("/api") and request.method == "GET":
        return RedirectResponse("/")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def ctx(request: Request, user: dict | None, **kw):
    return {"request": request, "user": user, "agency": db.one("SELECT * FROM agency WHERE id=1"), "app_name": settings.APP_NAME,
            "clients": (db.rows("SELECT id, name, brand_color FROM clients WHERE id=?", (user["client_id"],)) if user and user["role"] == "client"
                        else db.rows("SELECT id, name, brand_color FROM clients ORDER BY name") if user else []),
            "is_client": bool(user and user["role"] == "client"), "demo": settings.DEMO_MODE and not (user and user["role"] == "client"), **kw}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    if not db.one("SELECT id FROM users LIMIT 1"):
        return RedirectResponse("/setup")
    return templates.TemplateResponse(request, "login.html", ctx(request, None, error=error))


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    u = db.one("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
    if not u or not verify_password(password, u["password_hash"]):
        return RedirectResponse("/login?error=Invalid+email+or+password", status_code=303)
    r = RedirectResponse("/", status_code=303)
    r.set_cookie("session", sign({"uid": u["id"]}, SESSION_TTL), max_age=SESSION_TTL, httponly=True, samesite="lax",
                 secure=settings.BASE_URL.startswith("https"))
    db.audit(u["email"], "login")
    return r


@app.get("/logout")
def logout():
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie("session")
    return r


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    if db.one("SELECT id FROM users LIMIT 1"):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "setup.html", ctx(request, None))


@app.post("/setup")
def setup(agency: str = Form(...), name: str = Form(""), email: str = Form(...), password: str = Form(...)):
    if db.one("SELECT id FROM users LIMIT 1"):
        raise HTTPException(400, "Already set up")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    db.execute("INSERT INTO users (email, name, password_hash, role) VALUES (?,?,?, 'owner')", (email.strip().lower(), name, hash_password(password)))
    db.execute("UPDATE agency SET name=? WHERE id=1", (agency,))
    return RedirectResponse("/login", status_code=303)


# ---------------- pages ----------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(require_user)):
    if user["role"] == "client":
        return RedirectResponse(f"/clients/{user['client_id']}#monthly")
    return templates.TemplateResponse(request, "overview.html", ctx(request, user, page="overview"))


@app.get("/clients/{cid}", response_class=HTMLResponse)
def client_page(request: Request, cid: int, user=Depends(require_user)):
    c = db.one("SELECT * FROM clients WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "client.html", ctx(request, user, page="client", client=c))


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user=Depends(require_user)):
    return templates.TemplateResponse(request, "settings.html", ctx(request, user, page="settings", oauth_status={p: oauth.is_configured(p) for p in oauth.PROVIDERS}))


@app.get("/prospects", response_class=HTMLResponse)
def prospects_page(request: Request, user=Depends(require_user)):
    return templates.TemplateResponse(request, "prospects.html", ctx(request, user, page="prospects"))


@app.get("/r/{token}", response_class=HTMLResponse)
def report(request: Request, token: str, days: int = 30):
    data = unsign(token)
    if not data or "report" not in data:
        raise HTTPException(404, "Report link invalid or expired")
    c = db.one("SELECT * FROM clients WHERE id=?", (data["report"],))
    days = data.get("days", days)
    payload = {"client": c, "performance": metrics.client_performance(c["id"], days), "organic": metrics.client_organic(c["id"], days),
               "seo": metrics.client_seo(c["id"], min(days, 28)), "email": metrics.client_email(c["id"], days)}
    return templates.TemplateResponse(request, "report.html", {"request": request, "c": c, "days": days, "data_json": json.dumps(payload, default=str),
                                                               "agency": db.one("SELECT * FROM agency WHERE id=1"), **payload})


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/tasks/sync")
def tasks_sync(key: str, background: BackgroundTasks):
    """For a free external scheduler (e.g. cron-job.org) on hosts where the app sleeps between visits."""
    import hmac as _hmac
    import os as _os
    secret = _os.getenv("CRON_SECRET", "")
    if not secret or not _hmac.compare_digest(key, secret):
        raise HTTPException(403, "Invalid key")
    from .services.sync import sync_all
    background.add_task(sync_all)
    return {"ok": True, "started": True}


# ---------------- JSON API ----------------
def _client(cid: int) -> dict:
    c = db.one("SELECT * FROM clients WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "Client not found")
    return c


@app.get("/api/platforms")
def api_platforms(user=Depends(require_user)):
    out = []
    for p in PLATFORMS.values():
        prov = oauth.PLATFORM_PROVIDER.get(p["platform"])
        out.append({**p, "oauth_provider": prov, "oauth_ready": bool(prov and oauth.is_configured(prov))})
    return out


@app.get("/api/overview")
def api_overview(days: int = 30, user=Depends(require_user)):
    rows = metrics.agency_overview(days)
    recent = db.rows("SELECT a.*, c.name client_name FROM alerts a JOIN clients c ON c.id=a.client_id WHERE acknowledged=0 ORDER BY a.id DESC LIMIT 12")
    return {"clients": rows, "alerts": recent}


@app.post("/api/clients")
def create_client(request: Request, name: str = Form(...), industry: str = Form("ecommerce"), region: str = Form("AU"),
                  monthly_budget: float = Form(0), user=Depends(require_editor)):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "client"
    base, i = slug, 2
    while db.one("SELECT id FROM clients WHERE slug=?", (slug,)):
        slug, i = f"{base}-{i}", i + 1
    cid = db.execute("INSERT INTO clients (name, slug, industry, region, monthly_budget) VALUES (?,?,?,?,?)", (name, slug, industry, region, monthly_budget))
    db.audit(user["email"], "client_create", name)
    return {"id": cid}


@app.get("/api/clients/{cid}")
def get_client(cid: int, user=Depends(require_user)):
    return _client(cid)


EDITABLE = {"name", "industry", "currency", "brand_color", "logo_url", "report_title", "report_footer", "monthly_budget", "target_cpa", "target_roas", "region", "area", "search_term"}


@app.patch("/api/clients/{cid}")
async def update_client(cid: int, request: Request, user=Depends(require_editor)):
    _client(cid)
    body = {k: v for k, v in (await request.json()).items() if k in EDITABLE}
    if body:
        db.execute(f"UPDATE clients SET {', '.join(f'{k}=?' for k in body)} WHERE id=?", (*body.values(), cid))
    return _client(cid)


@app.delete("/api/clients/{cid}")
def delete_client(cid: int, user=Depends(require_owner)):
    db.execute("DELETE FROM clients WHERE id=?", (cid,))
    db.audit(user["email"], "client_delete", str(cid))
    return {"ok": True}


@app.get("/api/clients/{cid}/performance")
def api_perf(cid: int, days: int = 30, user=Depends(require_user)):
    _client(cid)
    return metrics.client_performance(cid, days)


@app.get("/api/clients/{cid}/engagement")
def api_engagement(cid: int, days: int = 30, user=Depends(require_user)):
    return metrics.client_engagement(cid, days)


@app.get("/api/clients/{cid}/organic")
def api_organic(cid: int, days: int = 30, user=Depends(require_user)):
    return metrics.client_organic(cid, days)


@app.get("/api/clients/{cid}/seo")
def api_seo(cid: int, days: int = 28, user=Depends(require_user)):
    return metrics.client_seo(cid, days)


@app.get("/api/clients/{cid}/email")
def api_email(cid: int, days: int = 30, user=Depends(require_user)):
    return metrics.client_email(cid, days)


@app.get("/api/clients/{cid}/attribution")
def api_attr(cid: int, days: int = 30, user=Depends(require_user)):
    return attr_svc.attribution(cid, days)


@app.get("/api/clients/{cid}/budget")
def api_budget(cid: int, budget: float | None = None, objective: str = "revenue", max_shift: float = 0.3, user=Depends(require_user)):
    c = _client(cid)
    return budget_svc.recommend(cid, budget if budget is not None else (c["monthly_budget"] or None), objective, max(0.05, min(max_shift, 1.0)))


# alerts
@app.get("/api/clients/{cid}/alerts")
def api_alerts(cid: int, include_ack: bool = False, user=Depends(require_user)):
    q = "SELECT * FROM alerts WHERE client_id=?" + ("" if include_ack else " AND acknowledged=0") + " ORDER BY id DESC LIMIT 200"
    return db.rows(q, (cid,))


@app.post("/api/alerts/{aid}/ack")
def ack_alert(aid: int, user=Depends(require_user)):
    db.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (aid,))
    return {"ok": True}


@app.get("/api/rules")
def api_rules(user=Depends(require_user)):
    return {"rules": db.rows("SELECT r.*, c.name client_name FROM alert_rules r LEFT JOIN clients c ON c.id=r.client_id ORDER BY r.client_id IS NOT NULL, r.kind"),
            "help": alerts_svc.RULE_HELP}


@app.post("/api/rules")
async def upsert_rule(request: Request, user=Depends(require_editor)):
    b = await request.json()
    if b["kind"] not in alerts_svc.RULE_HELP:
        raise HTTPException(400, "Unknown rule kind")
    if b.get("id"):
        db.execute("UPDATE alert_rules SET threshold=?, window_days=?, enabled=?, platform=? WHERE id=?",
                   (float(b["threshold"]), int(b.get("window_days", 3)), int(b.get("enabled", 1)), b.get("platform", ""), b["id"]))
        return {"id": b["id"]}
    return {"id": db.execute("INSERT INTO alert_rules (client_id, kind, platform, threshold, window_days, enabled) VALUES (?,?,?,?,?,?)",
                             (b.get("client_id"), b["kind"], b.get("platform", ""), float(b["threshold"]), int(b.get("window_days", 3)), int(b.get("enabled", 1))))}


@app.post("/api/clients/{cid}/alerts/evaluate")
def evaluate(cid: int, user=Depends(require_user)):
    return alerts_svc.evaluate_client(cid)


# connections
@app.get("/api/clients/{cid}/connections")
def api_connections(cid: int, user=Depends(require_user)):
    rows = db.rows("SELECT id, platform, account_id, account_name, is_demo, status, last_synced_at, last_error FROM connections WHERE client_id=? ORDER BY platform", (cid,))
    for r in rows:
        r["label"] = PLATFORMS.get(r["platform"], {}).get("label", r["platform"])
        r["category"] = PLATFORMS.get(r["platform"], {}).get("category", "")
    return rows


@app.post("/api/clients/{cid}/connections")
async def add_connection(cid: int, request: Request, user=Depends(require_editor)):
    """Add an API-key connection, or a demo connection. OAuth platforms go through /oauth/{provider}/start."""
    _client(cid)
    b = await request.json()
    p = b.get("platform")
    if p not in PLATFORMS:
        raise HTTPException(400, "Unknown platform")
    demo = bool(b.get("demo"))
    if not demo and PLATFORMS[p]["auth"] != "api_key":
        raise HTTPException(400, "This platform connects with OAuth")
    creds = {k: v for k, v in (b.get("credentials") or {}).items() if v}
    try:
        conn_id = db.execute("INSERT INTO connections (client_id, platform, account_id, account_name, credentials_enc, is_demo) VALUES (?,?,?,?,?,?)",
                             (cid, p, b.get("account_id") or f"demo-{p}", b.get("account_name") or PLATFORMS[p]["label"], encrypt_json(creds), int(demo)))
    except Exception:
        raise HTTPException(400, "That account is already connected")
    db.audit(user["email"], "connection_add", f"client={cid} platform={p} demo={demo}")
    return {"id": conn_id, "sync": sync_connection(conn_id, full=True)}


@app.delete("/api/connections/{conn_id}")
def del_connection(conn_id: int, user=Depends(require_editor)):
    db.execute("DELETE FROM connections WHERE id=?", (conn_id,))
    db.audit(user["email"], "connection_delete", str(conn_id))
    return {"ok": True}


@app.post("/api/connections/{conn_id}/sync")
def sync_one(conn_id: int, full: bool = False, user=Depends(require_user)):
    return sync_connection(conn_id, full)


@app.post("/api/clients/{cid}/sync")
def sync_all_for_client(cid: int, user=Depends(require_user)):
    return sync_client(cid)


# oauth
@app.get("/oauth/{provider}/start")
def oauth_start(provider: str, client_id: int, platform: str, account_id: str, user=Depends(require_editor)):
    if provider not in oauth.PROVIDERS or not oauth.is_configured(provider):
        raise HTTPException(400, f"{provider} app credentials are not configured (see .env.example)")
    state = random_state()
    db.execute("INSERT INTO oauth_states (state, client_id, platform) VALUES (?,?,?)", (state, client_id, json.dumps({"platform": platform, "account_id": account_id})))
    return RedirectResponse(oauth.authorize_url(provider, state))


@app.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, state: str, code: str = "", auth_code: str = "", error: str = "", user=Depends(require_editor)):
    st = db.one("SELECT * FROM oauth_states WHERE state=?", (state,))
    if not st:
        raise HTTPException(400, "Unknown OAuth state")
    db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
    if error:
        return RedirectResponse(f"/clients/{st['client_id']}?error={error}#connections")
    tok = oauth.exchange_code(provider, code or auth_code)
    meta = json.loads(st["platform"])
    platform, account_id = meta["platform"], meta["account_id"]
    if provider == "tiktok" and not account_id and tok.get("advertiser_ids"):
        account_id = str(tok["advertiser_ids"][0])
    existing = db.one("SELECT id FROM connections WHERE client_id=? AND platform=? AND account_id=?", (st["client_id"], platform, account_id))
    if existing:
        db.execute("UPDATE connections SET credentials_enc=?, status='active', last_error='' WHERE id=?", (encrypt_json(tok), existing["id"]))
        conn_id = existing["id"]
    else:
        conn_id = db.execute("INSERT INTO connections (client_id, platform, account_id, account_name, credentials_enc) VALUES (?,?,?,?,?)",
                             (st["client_id"], platform, account_id, PLATFORMS[platform]["label"], encrypt_json(tok)))
    db.audit(user["email"], "oauth_connect", f"client={st['client_id']} platform={platform}")
    sync_connection(conn_id, full=True)
    return RedirectResponse(f"/clients/{st['client_id']}#connections", status_code=303)


# people + companies
@app.get("/api/clients/{cid}/people")
def api_people(cid: int, q: str = "", days: int = 90, user=Depends(require_user)):
    _client(cid)
    return visitors.list_people(cid, q, days)


@app.get("/api/clients/{cid}/people/{pid}")
def api_person(cid: int, pid: int, user=Depends(require_user)):
    d = visitors.person_detail(cid, pid)
    if not d:
        raise HTTPException(404, "Person not found, or they haven't opted in")
    return d


@app.get("/api/clients/{cid}/companies")
def api_companies(cid: int, days: int = 30, user=Depends(require_user)):
    _client(cid)
    return visitors.list_companies(cid, days)


@app.get("/api/clients/{cid}/companies/{coid}")
def api_company(cid: int, coid: int, user=Depends(require_user)):
    d = visitors.company_detail(cid, coid)
    if not d:
        raise HTTPException(404, "Company not found")
    return d


# audiences
@app.get("/api/clients/{cid}/audiences")
def api_audiences(cid: int, user=Depends(require_user)):
    out = []
    for a in db.rows("SELECT * FROM audiences WHERE client_id=? ORDER BY id", (cid,)):
        a["definition"] = json.loads(a["definition"])
        a["size"] = len(aud_svc.members(cid, a["definition"]))
        a["syncs"] = db.rows("SELECT platform, status, uploaded, detail, synced_at FROM audience_syncs WHERE id IN "
                             "(SELECT MAX(id) FROM audience_syncs WHERE audience_id=? GROUP BY platform)", (a["id"],))
        out.append(a)
    return {"audiences": out, "distribution": aud_svc.score_distribution(cid), "sync_targets": aud_svc.SUPPORTED_SYNC,
            "connected": [r["platform"] for r in db.rows("SELECT DISTINCT platform FROM connections WHERE client_id=?", (cid,))]}


@app.post("/api/clients/{cid}/audiences")
async def create_audience(cid: int, request: Request, user=Depends(require_editor)):
    b = await request.json()
    d = {k: b[k] for k in ("min_score", "max_score", "lookback_days", "include_customers", "customers_only", "required_events") if k in b}
    aid = db.execute("INSERT INTO audiences (client_id, name, definition) VALUES (?,?,?)", (cid, b["name"], json.dumps(d)))
    return {"id": aid, "size": len(aud_svc.members(cid, d))}


@app.post("/api/clients/{cid}/audiences/preview")
async def preview_audience(cid: int, request: Request, user=Depends(require_user)):
    d = await request.json()
    ms = aud_svc.members(cid, d)
    return {"size": len(ms), "sample": [{"name": f"{m['first_name']} {m['last_name'][:1]}.", "score": m["score"], "events": m["events"],
                                         "last": m["last"], "top": m["top"]} for m in ms[:15]]}


@app.delete("/api/audiences/{aid}")
def delete_audience(aid: int, user=Depends(require_editor)):
    db.execute("DELETE FROM audiences WHERE id=?", (aid,))
    return {"ok": True}


@app.post("/api/audiences/{aid}/sync/{platform}")
def sync_audience(aid: int, platform: str, user=Depends(require_editor)):
    if platform not in aud_svc.SUPPORTED_SYNC:
        raise HTTPException(400, "Unsupported platform")
    return aud_svc.sync_audience(aid, platform)


@app.get("/api/clients/{cid}/audiences/{aid}/export/{platform}.csv")
def export_audience(cid: int, aid: int, platform: str, user=Depends(require_editor)):
    return Response(aud_svc.export_csv(cid, aid, platform), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="audience-{aid}-{platform}-hashed.csv"'})


@app.get("/api/clients/{cid}/targeting")
def api_targeting(cid: int, user=Depends(require_user)):
    return aud_svc.targeting_suggestions(cid)


@app.post("/api/clients/{cid}/contacts/import")
async def import_contacts(cid: int, file: UploadFile = File(...), user=Depends(require_editor)):
    """CSV with columns: email, phone, first_name, last_name, country, postcode, consent (yes/no/true/1), is_customer.
    Rows without an explicit consent value are imported with consent=0 and are never uploaded."""
    _client(cid)
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    n = consented = 0
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items() if k}
        if not row.get("email") and not row.get("phone"):
            continue
        c = row.get("consent", row.get("marketing_consent", "")).lower() in ("1", "yes", "y", "true", "opted_in", "subscribed")
        row["is_customer"] = row.get("is_customer", "").lower() in ("1", "yes", "y", "true")
        compliance.upsert_contact(cid, row, c, f"csv_import:{file.filename}")
        n += 1
        consented += c
    db.audit(user["email"], "contacts_import", f"client={cid} rows={n} consented={consented}")
    return {"imported": n, "consented": consented}


# privacy
@app.get("/api/clients/{cid}/privacy")
def privacy_info(cid: int, user=Depends(require_user)):
    c = _client(cid)
    return {"region": c["region"], "policy": compliance.REGION_POLICY.get(c["region"], compliance.REGION_POLICY["AU"]),
            "retention_days": settings.EVENT_RETENTION_DAYS,
            "audit": db.rows("SELECT * FROM audit_log WHERE detail LIKE ? ORDER BY id DESC LIMIT 30", (f"%client={cid}%",))}


@app.get("/api/clients/{cid}/privacy/access")
def privacy_access(cid: int, email: str, user=Depends(require_editor)):
    return compliance.access_request(cid, email)


@app.post("/api/clients/{cid}/privacy/erase")
async def privacy_erase(cid: int, request: Request, user=Depends(require_editor)):
    return compliance.erase(cid, (await request.json())["email"])


# reports
@app.post("/api/clients/{cid}/report-link")
def report_link(cid: int, days: int = 30, valid_days: int = 90, user=Depends(require_user)):
    _client(cid)
    return {"url": f"{settings.BASE_URL}/r/{sign({'report': cid, 'days': days}, valid_days * 86400)}"}


# uploads, audience, Google Maps & reviews, monthly report, client logins
@app.post("/api/clients/{cid}/import")
async def import_report(cid: int, file: UploadFile = File(...), platform: str = Form("auto"), period_from: str = Form(""),
                        period_to: str = Form(""), user=Depends(require_editor)):
    from .services import imports
    _client(cid)
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(400, "File is too big (15 MB max). Export fewer rows or a shorter date range.")
    try:
        r = imports.import_csv(cid, raw, file.filename or "", platform, period_from, period_to, user["email"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.audit(user["email"], "report_import", f"{cid}:{r['platform']}:{r['kind']}:{r['rows']}")
    return r


@app.get("/api/clients/{cid}/imports")
def import_history(cid: int, user=Depends(require_editor)):
    from .services import imports
    return {"history": imports.history(cid), "platforms": imports.PLATFORMS}


@app.get("/api/clients/{cid}/audience")
def api_audience(cid: int, months: int = 3, user=Depends(require_user)):
    from .services import audience
    _client(cid)
    return audience.client_audience(cid, max(1, min(months, 24)))


@app.get("/api/clients/{cid}/local")
def api_local(cid: int, user=Depends(require_user)):
    from .services import local
    _client(cid)
    return local.summary(cid)


@app.put("/api/clients/{cid}/local/{month}")
async def put_local(cid: int, month: str, request: Request, user=Depends(require_editor)):
    from .services import local
    _client(cid)
    body = await request.json()
    try:
        if isinstance(body.get("values"), dict):
            local.save_month(cid, month, body["values"])
        if isinstance(body.get("competitors"), list):
            local.save_competitors(cid, month, body["competitors"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return local.summary(cid)


@app.post("/api/clients/{cid}/local/{month}/find")
def find_local_competitors(cid: int, month: str, user=Depends(require_editor)):
    from .services import local
    _client(cid)
    try:
        local.find_competitors(cid, month)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return local.summary(cid)


@app.post("/api/clients/{cid}/local/{month}/refresh")
def refresh_local(cid: int, month: str, user=Depends(require_editor)):
    from .services import local
    _client(cid)
    try:
        local.refresh_reviews(cid, month)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return local.summary(cid)


@app.get("/api/clients/{cid}/monthly")
def api_monthly(cid: int, month: str = "", user=Depends(require_user)):
    from .services import monthly
    _client(cid)
    if month and not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(400, "Month must look like 2026-09")
    return monthly.build(cid, month or None)


def _monthly_page(request: Request, cid: int, month: str, shared: bool):
    from .services import monthly
    if month and not re.fullmatch(r"\d{4}-\d{2}", month):
        month = ""
    rep = monthly.build(cid, month or None)
    return templates.TemplateResponse(request, "monthly.html", {"request": request, "r": rep, "shared": shared,
                                                                 "c": _client(cid), "agency": db.one("SELECT * FROM agency WHERE id=1")})


@app.get("/clients/{cid}/monthly", response_class=HTMLResponse)
def monthly_page(request: Request, cid: int, month: str = "", user=Depends(require_user)):
    return _monthly_page(request, cid, month, False)


@app.post("/api/clients/{cid}/monthly-link")
def monthly_link(cid: int, month: str = "", user=Depends(require_editor)):
    _client(cid)
    return {"url": f"{settings.BASE_URL}/m/{sign({'monthly': cid, 'month': month}, 120 * 86400)}"}


@app.get("/m/{token}", response_class=HTMLResponse)
def monthly_shared(request: Request, token: str):
    data = unsign(token)
    if not data or "monthly" not in data:
        raise HTTPException(404, "Report link invalid or expired")
    return _monthly_page(request, data["monthly"], data.get("month") or "", True)


def _is_health(c: dict) -> bool:
    from .services import social as social_svc
    ind = (c.get("industry") or "").lower()
    name = (c.get("name") or "").lower()
    return social_svc.INDUSTRIES.get(ind, {}).get("health", False) or any(w in name for w in ("pharm", "chemist", "dental", "physio", "clinic", "medical", "health"))


@app.get("/api/clients/{cid}/trial")
def get_trial(cid: int, user=Depends(require_user)):
    from .services import trial
    _client(cid)
    return trial.get(cid)


@app.post("/api/clients/{cid}/trial/start")
async def start_trial(cid: int, request: Request, user=Depends(require_editor)):
    from .services import trial
    c = _client(cid)
    body = await request.json() if (await request.body()) else {}
    try:
        return trial.start(cid, _is_health(c), body.get("start_date") or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/clients/{cid}/trial")
async def put_trial(cid: int, request: Request, user=Depends(require_editor)):
    from .services import trial
    _client(cid)
    try:
        return trial.update(cid, await request.json())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/clients/{cid}/trial/website/{which}")
def trial_website(cid: int, which: str, user=Depends(require_editor)):
    from .services import trial
    _client(cid)
    try:
        return trial.website_check(cid, which)
    except (ValueError, httpx.HTTPError) as e:
        raise HTTPException(400, f"Couldn't check the website: {e}")


def _trial_page(request: Request, cid: int, shared: bool):
    from .services import trial
    rep = trial.report(cid)
    if not rep["started"]:
        raise HTTPException(404, "No trial started for this client")
    return templates.TemplateResponse(request, "trial_report.html", {"request": request, "r": rep, "c": rep["client"], "shared": shared,
                                                                      "agency": db.one("SELECT * FROM agency WHERE id=1")})


@app.get("/clients/{cid}/trial-report", response_class=HTMLResponse)
def trial_report_page(request: Request, cid: int, user=Depends(require_user)):
    _client(cid)
    return _trial_page(request, cid, False)


@app.post("/api/clients/{cid}/trial-link")
def trial_link(cid: int, user=Depends(require_editor)):
    _client(cid)
    return {"url": f"{settings.BASE_URL}/t/{sign({'trial': cid}, 60 * 86400)}"}


@app.get("/t/{token}", response_class=HTMLResponse)
def trial_shared(request: Request, token: str):
    data = unsign(token)
    if not data or "trial" not in data:
        raise HTTPException(404, "Report link invalid or expired")
    return _trial_page(request, data["trial"], True)


@app.get("/api/clients/{cid}/details")
def get_details(cid: int, user=Depends(require_user)):
    from .services import details
    _client(cid)
    return details.get(cid)


@app.put("/api/clients/{cid}/details")
async def put_details(cid: int, request: Request, user=Depends(require_user)):
    from .services import details
    if user["role"] == "viewer":
        raise HTTPException(403, "Read-only account")
    _client(cid)
    return details.save(cid, await request.json(), user["email"])


@app.post("/api/clients/{cid}/photos")
async def upload_photo(cid: int, file: UploadFile = File(...), category: str = Form("other"), caption: str = Form(""),
                       user=Depends(require_user)):
    from .services import details
    if user["role"] == "viewer":
        raise HTTPException(403, "Read-only account")
    _client(cid)
    raw = await file.read(details.MAX_PHOTO_BYTES + 1)
    try:
        return details.add_photo(cid, raw, file.filename or "photo.jpg", category, caption, user["email"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/clients/{cid}/photos/{photo_id}")
def get_photo(cid: int, photo_id: int, user=Depends(require_user)):
    from .services import details
    got = details.photo(cid, photo_id)
    if not got:
        raise HTTPException(404)
    data, ctype, name = got
    return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=86400", "Content-Disposition": f'inline; filename="{name}"'})


@app.delete("/api/clients/{cid}/photos/{photo_id}")
def delete_photo(cid: int, photo_id: int, user=Depends(require_user)):
    from .services import details
    if user["role"] == "viewer":
        raise HTTPException(403, "Read-only account")
    return details.delete_photo(cid, photo_id)


@app.get("/api/clients/{cid}/photos.zip")
def photos_zip(cid: int, user=Depends(require_editor)):
    from .services import details
    c = _client(cid)
    return Response(details.photos_zip(cid), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{c["slug"]}-photos-and-details.zip"'})


@app.get("/api/clients/{cid}/campaigns")
def list_campaigns(cid: int, user=Depends(require_user)):
    from .services import campaigns, details
    _client(cid)
    d = details.get(cid)
    return {"campaigns": [{"id": c["id"], "platform": c["platform"], "name": c["name"], "status": c["status"],
                           "status_label": campaigns.STATUSES.get(c["status"], c["status"]), "updated_at": c["updated_at"],
                           "monthly_budget": c["data"].get("monthly_budget")} for c in campaigns.list_(cid)],
            "services": [x.strip(" -•") for x in (d["details"].get("services") or "").splitlines() if x.strip(" -•")],
            "can_send": {p: campaigns.can_send(cid, p) for p in ("google", "meta")},
            "photos": [{"id": p["id"], "category": p["category"]} for p in d["photos"]],
            "objectives": campaigns.META_OBJECTIVES, "ctas": campaigns.META_CTAS, "limits": {"google": campaigns.GOOGLE_LIMITS, "meta": campaigns.META_LIMITS},
            "health": campaigns.is_health(cid)}


@app.post("/api/clients/{cid}/campaigns")
async def create_campaign(cid: int, request: Request, user=Depends(require_editor)):
    from .services import campaigns
    _client(cid)
    b = await request.json()
    try:
        return campaigns.create(cid, b.get("platform", "google"), str(b.get("service") or ""), float(b.get("monthly_budget") or 600),
                                int(b.get("radius_km") or 5), user["email"])
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/clients/{cid}/campaigns/{camp_id}")
def get_campaign(cid: int, camp_id: int, user=Depends(require_user)):
    from .services import campaigns
    try:
        return campaigns.get(cid, camp_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.put("/api/clients/{cid}/campaigns/{camp_id}")
async def put_campaign(cid: int, camp_id: int, request: Request, user=Depends(require_editor)):
    from .services import campaigns
    try:
        return campaigns.update(cid, camp_id, await request.json())
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/clients/{cid}/campaigns/{camp_id}")
def delete_campaign(cid: int, camp_id: int, user=Depends(require_editor)):
    from .services import campaigns
    campaigns.delete(cid, camp_id)
    return {"ok": True}


@app.post("/api/clients/{cid}/campaigns/{camp_id}/ask-approval")
def ask_approval(cid: int, camp_id: int, user=Depends(require_editor)):
    from .services import campaigns
    try:
        c = campaigns.get(cid, camp_id)
        if any(i["level"] == "error" for i in c["checks"]):
            raise ValueError("Fix the red problems before sending it to the owner.")
        return campaigns.set_status(cid, camp_id, "awaiting_approval")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/clients/{cid}/campaigns/{camp_id}/review")
async def review_campaign(cid: int, camp_id: int, request: Request, user=Depends(require_user)):
    """The business owner approves the ad, or asks for changes (works from their client login)."""
    from .services import campaigns
    b = await request.json()
    try:
        c = campaigns.get(cid, camp_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if c["status"] != "awaiting_approval":
        raise HTTPException(400, "This campaign isn't waiting for approval.")
    ok = bool(b.get("approve"))
    db.audit(user["email"], "campaign_approved" if ok else "campaign_changes_requested", f"{cid}:{camp_id}")
    return campaigns.set_status(cid, camp_id, "approved" if ok else "changes_requested", str(b.get("note") or ""), user["email"])


@app.get("/api/clients/{cid}/campaigns/{camp_id}/google-ads-editor.csv")
def campaign_csv(cid: int, camp_id: int, user=Depends(require_editor)):
    from .services import campaigns
    try:
        c = campaigns.get(cid, camp_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if c["platform"] != "google":
        raise HTTPException(400, "The Google Ads Editor file is for Google campaigns.")
    if c["status"] in ("draft", "approved", "changes_requested", "awaiting_approval"):
        db.execute("UPDATE campaigns SET status='exported' WHERE id=? AND status IN ('approved')", (camp_id,))
    slug = re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-") or "campaign"
    return Response(campaigns.editor_csv(c), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{slug}.csv"'})


@app.post("/api/clients/{cid}/campaigns/{camp_id}/send")
def send_campaign(cid: int, camp_id: int, user=Depends(require_editor)):
    from .services import campaigns
    try:
        r = campaigns.send(cid, camp_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network / platform problems
        raise HTTPException(400, f"Couldn't send: {str(e)[:300]}")
    db.audit(user["email"], "campaign_sent", f"{cid}:{camp_id}")
    return r


@app.post("/api/clients/{cid}/campaigns/{camp_id}/switch")
async def switch_campaign(cid: int, camp_id: int, request: Request, user=Depends(require_editor)):
    from .services import campaigns
    on = bool((await request.json()).get("on"))
    try:
        r = campaigns.switch(cid, camp_id, on)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Couldn't change it: {str(e)[:300]}")
    db.audit(user["email"], "campaign_on" if on else "campaign_off", f"{cid}:{camp_id}")
    return r


@app.get("/api/clients/{cid}/logins")
def list_logins(cid: int, user=Depends(require_owner)):
    return db.rows("SELECT id, email, name, created_at FROM users WHERE role='client' AND client_id=?", (cid,))


@app.post("/api/clients/{cid}/logins")
async def add_login(cid: int, request: Request, user=Depends(require_owner)):
    _client(cid)
    b = await request.json()
    email = str(b.get("email", "")).strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a valid email address")
    if len(b.get("password", "")) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    try:
        db.execute("INSERT INTO users (email, name, password_hash, role, client_id) VALUES (?,?,?,'client',?)",
                   (email, str(b.get("name", ""))[:80], hash_password(b["password"]), cid))
    except Exception:
        raise HTTPException(400, "That email already has a login")
    db.audit(user["email"], "client_login_create", f"{cid}:{email}")
    return list_logins(cid, user)


@app.delete("/api/clients/{cid}/logins/{uid}")
def delete_login(cid: int, uid: int, user=Depends(require_owner)):
    db.execute("DELETE FROM users WHERE id=? AND role='client' AND client_id=?", (uid, cid))
    db.audit(user["email"], "client_login_delete", f"{cid}:{uid}")
    return list_logins(cid, user)


# prospects (new-business audits)
@app.get("/api/prospects")
def list_prospects(user=Depends(require_user)):
    return db.rows("SELECT id, url, domain, name, score, status, notes, is_example, created_at FROM prospects ORDER BY id DESC")


@app.post("/api/prospects")
async def create_prospect(request: Request, user=Depends(require_editor)):
    url = (await request.json()).get("url", "")
    try:
        r = prospect_svc.run_audit(url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(400, f"Couldn't load that website ({e.__class__.__name__}). Check the address and try again.")
    db.audit(user["email"], "prospect_audit", r["domain"])
    return r


@app.get("/api/prospects/options")
def prospect_options(user=Depends(require_user)):
    from .services import social as social_svc
    return {"industries": [{"key": k, "label": v["label"], "health": v["health"], "expected": v["expected"]} for k, v in social_svc.INDUSTRIES.items()],
            "sizes": [{"key": k, "label": v["label"]} for k, v in social_svc.SIZES.items()],
            "platforms": [{"key": k, "label": v["label"]} for k, v in social_svc.PLATFORMS.items()],
            "places_enabled": bool(comp_svc.api_key()), "ai_enabled": bool(ai_svc.api_key()),
            "usd_to_aud": __import__("app.services.pricing", fromlist=["rate_card"]).rate_card()["usd_to_aud"]}


def _load_prospect(pid: int) -> tuple[dict, dict]:
    p = db.one("SELECT * FROM prospects WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404)
    return p, json.loads(p["report"])


def _save_prospect(pid: int, report: dict) -> None:
    db.execute("UPDATE prospects SET report=?, score=?, name=? WHERE id=?",
               (json.dumps(report), report["overall"]["score"], report.get("name") or "", pid))


@app.get("/api/prospects/{pid}")
def get_prospect(pid: int, user=Depends(require_user)):
    p, report = _load_prospect(pid)
    if "social_links" not in report and not p["is_example"]:
        # audits made before social scoring existed: re-read the site once to find their social profiles
        try:
            report = prospect_svc.rescan(report)
        except Exception:
            report["social_links"] = {}
    report = prospect_svc.enrich(report, pid)   # keeps older audits up to date with scoring/pricing changes
    if report.get("ai_review"):
        report["ai_review"]["stale"] = report["ai_review"].get("basis") != _price_basis(report)
    _save_prospect(pid, report)
    return {**report, "id": p["id"], "status": p["status"], "notes": p["notes"], "is_example": p["is_example"], "created_at": p["created_at"]}


@app.patch("/api/prospects/{pid}")
async def update_prospect(pid: int, request: Request, user=Depends(require_editor)):
    body = await request.json()
    b = {k: v for k, v in body.items() if k in ("status", "notes")}
    if b:
        db.execute(f"UPDATE prospects SET {', '.join(f'{k}=?' for k in b)} WHERE id=?", (*b.values(), pid))
    if any(k in body for k in ("business", "social", "name", "competitors", "ad_campaigns")):
        _, report = _load_prospect(pid)
        if isinstance(body.get("business"), dict):
            report["business"] = {**(report.get("business") or {}), **body["business"]}
            if "industry" in body["business"]:
                report["business"]["industry_set"] = True
        if isinstance(body.get("social"), dict):
            soc = report.get("social") or {}
            for plat, vals in body["social"].items():
                if isinstance(vals, dict):
                    soc[plat] = {**(soc.get(plat) or {}), **vals}
                    if "url" in vals and not vals["url"]:
                        soc[plat].pop("detected", None)
                        (report.get("social_links") or {}).pop(plat, None)
            report["social"] = soc
        if body.get("name"):
            report["name"] = str(body["name"])[:80]
        if isinstance(body.get("ad_campaigns"), list):
            keep = ("name", "platform", "customers", "budget", "cpc", "conv", "close", "value", "include_fee")
            report["ad_campaigns"] = [{k: c.get(k) for k in keep} for c in body["ad_campaigns"][:12] if isinstance(c, dict)]
        if isinstance(body.get("competitors"), list):
            clean = []
            for c in body["competitors"][:30]:
                if isinstance(c, dict) and str(c.get("name", "")).strip():
                    clean.append({"name": str(c["name"]).strip()[:120], "rating": c.get("rating"), "reviews": c.get("reviews"),
                                  "website": str(c.get("website") or "")[:300], "address": str(c.get("address") or "")[:200],
                                  "maps": str(c.get("maps") or "")[:500], "is_self": bool(c.get("is_self")), "manual": bool(c.get("manual"))})
            report["competitors"] = {**(report.get("competitors") or {}), "list": clean}
        report = prospect_svc.enrich(report, pid)
        _save_prospect(pid, report)
    return get_prospect(pid, user)


@app.get("/prospects/{pid}/print", response_class=HTMLResponse)
def print_prospect(request: Request, pid: int, prices: int = 1, user=Depends(require_user)):
    """One-page leave-behind audit to print (or save as PDF) and hand over at the counter."""
    _, report = _load_prospect(pid)
    report = prospect_svc.enrich(report, pid)
    ss = report.get("social_summary") or {}
    cap = lambda t: t[:1].upper() + t[1:]
    issues = [{"problem": i.get("problem") or i["title"], "impact": cap(prospect_svc._second_person(i["impact"])), "fix": i.get("fix", "")}
              for i in report.get("top_issues", [])[:3]]
    social = [{"problem": f"No {m} profile found", "impact": "Customers check here before choosing, and find your competitors instead."}
              for m in (ss.get("missing") or [])[:2]]
    cs = report.get("competitor_summary")
    if cs and cs.get("my_reviews") is not None and cs["top"]["reviews"] > cs["my_reviews"]:
        social.insert(0, {"problem": f"Fewer Google reviews than nearby competitors ({cs['my_reviews']} vs {cs['top']['reviews']})",
                          "impact": f"{cs['top']['name']} has {cs['top']['reviews']} reviews. Most people choose the business with more reviews."})
        social = social[:3]
    for plat in sorted((p for p in (ss.get("platforms") or {}).values() if p.get("exists") and p.get("score") is not None and p.get("notes")),
                       key=lambda p: p["score"])[:max(0, 3 - len(social))]:
        if plat["score"] < 70:
            social.append({"problem": f"{plat['label']} scores {plat['score']}/100", "impact": plat["notes"][0]})
    tiers = (report.get("quote") or {}).get("tiers") or []
    return templates.TemplateResponse(request, "prospect_print.html", {
        "request": request, "r": report, "o": report.get("overall") or {}, "issues": issues, "social": social,
        "starter": next((t for t in tiers if t.get("starter")), None),
        "growth": next((t for t in tiers if t.get("recommended")), None),
        "quote": report.get("quote") or {}, "show_prices": bool(prices),
        "agency": db.one("SELECT * FROM agency WHERE id=1") or {}, "today": f"{date.today().day} {date.today():%B %Y}"})


@app.post("/api/prospects/{pid}/competitors")
async def find_competitors(pid: int, request: Request, user=Depends(require_editor)):
    """Look up similar businesses nearby on Google (Places API) and compare their ratings and reviews."""
    body = await request.json()
    _, report = _load_prospect(pid)
    business = report.get("business") or {}
    term = str(body.get("search_term") or business.get("search_term") or "").strip()[:60]
    area = str(body.get("area") or business.get("area") or "").strip()[:80]
    report["business"] = {**business, "search_term": term, "area": area}
    try:
        found = comp_svc.find(term, area, report.get("domain", ""), report.get("name", ""))
    except ValueError as e:
        report = prospect_svc.enrich(report, pid)
        _save_prospect(pid, report)
        raise HTTPException(400, str(e))
    manual = [c for c in (report.get("competitors") or {}).get("list", []) if c.get("manual")]
    report["competitors"] = {"list": found + manual, "query": f"{term} in {area}", "found_at": date.today().isoformat()}
    report = prospect_svc.enrich(report, pid)
    _save_prospect(pid, report)
    return get_prospect(pid, user)


def _price_basis(report: dict) -> list:
    return [[t["name"], t["setup_total"], t["monthly_total"]] for t in (report.get("quote") or {}).get("tiers", [])]


@app.get("/api/prospects/{pid}/ai-prompt")
def ai_prompt(pid: int, user=Depends(require_user)):
    _, report = _load_prospect(pid)
    return {"text": ai_svc.prompt_text(prospect_svc.enrich(report, pid))}


@app.post("/api/prospects/{pid}/ai-review")
def ai_review(pid: int, user=Depends(require_editor)):
    """Ask Claude to review this prospect's packages and suggest which to lead with and how to pitch it."""
    _, report = _load_prospect(pid)
    report = prospect_svc.enrich(report, pid)
    try:
        result = ai_svc.review(report)
    except ValueError as e:
        raise HTTPException(400, str(e))
    result["basis"] = _price_basis(report)
    report["ai_review"] = result
    _save_prospect(pid, report)
    db.audit(user["email"], "ai_price_review", report.get("domain", ""))
    return get_prospect(pid, user)


@app.post("/api/prospects/{pid}/rescan")
def rescan_prospect(pid: int, user=Depends(require_editor)):
    _, report = _load_prospect(pid)
    try:
        fresh = prospect_svc.rescan(report)
    except (ValueError, httpx.HTTPError) as e:
        raise HTTPException(400, f"Couldn't load the website again: {e}")
    fresh = prospect_svc.enrich(fresh, pid)
    _save_prospect(pid, fresh)
    return get_prospect(pid, user)


@app.get("/api/rate-card")
def get_rate_card(user=Depends(require_user)):
    from .services import pricing
    return {"rates": pricing.rate_card(), "defaults": pricing.DEFAULT_RATE_CARD}


@app.put("/api/rate-card")
async def put_rate_card(request: Request, user=Depends(require_owner)):
    from .services import pricing
    try:
        return {"rates": pricing.save_rate_card(await request.json()), "defaults": pricing.DEFAULT_RATE_CARD}
    except (TypeError, ValueError):
        raise HTTPException(400, "Rates must be numbers")


@app.delete("/api/prospects/{pid}")
def delete_prospect(pid: int, user=Depends(require_editor)):
    db.execute("DELETE FROM prospects WHERE id=?", (pid,))
    return {"ok": True}


# agency settings + users
@app.get("/api/agency")
def get_agency(user=Depends(require_user)):
    return {"agency": db.one("SELECT * FROM agency WHERE id=1"), "users": db.rows("SELECT id, email, name, role, created_at FROM users")}


@app.patch("/api/agency")
async def patch_agency(request: Request, user=Depends(require_owner)):
    b = {k: v for k, v in (await request.json()).items() if k in ("name", "brand_color", "logo_url", "contact_name", "phone", "email", "website")}
    if b:
        db.execute(f"UPDATE agency SET {', '.join(f'{k}=?' for k in b)} WHERE id=1", tuple(b.values()))
    return db.one("SELECT * FROM agency WHERE id=1")


@app.post("/api/users")
async def add_user(request: Request, user=Depends(require_owner)):
    b = await request.json()
    if len(b.get("password", "")) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    try:
        uid = db.execute("INSERT INTO users (email, name, password_hash, role) VALUES (?,?,?,?)",
                         (b["email"].strip().lower(), b.get("name", ""), hash_password(b["password"]), b.get("role", "member")))
    except Exception:
        raise HTTPException(400, "User already exists")
    return {"id": uid}


# ---------------- first-party tracking (public) ----------------
TRACK_JS = (HERE / "static" / "track.js").read_text() if (HERE / "static" / "track.js").exists() else ""


@app.get("/t.js")
def track_js():
    return Response(TRACK_JS.replace("__ENDPOINT__", f"{settings.BASE_URL}/collect"), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.options("/collect")
def collect_preflight():
    return Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST", "Access-Control-Allow-Headers": "Content-Type"})


ALLOWED_EVENTS = set(aud_svc.WEIGHTS) | {"purchase", "lead", "identify", "page_leave"}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


@app.post("/collect")
async def collect(request: Request, background: BackgroundTasks):
    """Receives events from the site snippet. The snippet only sends after the visitor consents."""
    try:
        b = json.loads(await request.body())
    except Exception:
        raise HTTPException(400)
    c = db.one("SELECT id FROM clients WHERE slug=?", (str(b.get("c", "")),))
    hdr = {"Access-Control-Allow-Origin": "*"}
    if not c:
        return JSONResponse({"ok": False}, status_code=404, headers=hdr)
    anon = str(b.get("a", ""))[:64]
    ev = str(b.get("e", ""))[:40]
    if ev not in ALLOWED_EVENTS:
        ev = "page_view" if ev == "" else ev[:40]
    contact_id = None
    if ev == "identify":
        p = b.get("p") or {}
        contact_id = compliance.upsert_contact(c["id"], p, bool(p.get("consent")) if "consent" in p else None, "site_form")
        db.execute("UPDATE events SET contact_id=? WHERE client_id=? AND anon_id=? AND contact_id IS NULL", (contact_id, c["id"], anon))
        return JSONResponse({"ok": True}, headers=hdr)
    prev = db.one("SELECT contact_id FROM events WHERE client_id=? AND anon_id=? AND contact_id IS NOT NULL LIMIT 1", (c["id"], anon))
    contact_id = prev["contact_id"] if prev else None
    from datetime import datetime, timezone
    try:
        dur = max(0.0, min(float(b.get("d") or 0), 3600.0))
    except (TypeError, ValueError):
        dur = 0.0
    known = db.one("SELECT company_id FROM events WHERE client_id=? AND anon_id=? AND company_id IS NOT NULL LIMIT 1", (c["id"], anon))
    eid = db.execute("INSERT INTO events (client_id, contact_id, anon_id, event, url, value, source, medium, campaign, ts, duration_sec, company_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (c["id"], contact_id, anon, ev, str(b.get("u", ""))[:500], float(b.get("v") or 0), str(b.get("s", ""))[:60], str(b.get("m", ""))[:60],
                      str(b.get("cp", ""))[:120], datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"), dur,
                      known["company_id"] if known else None))
    if not known and ev != "page_leave":
        background.add_task(visitors.attach_company, eid, c["id"], _client_ip(request))  # IP used for lookup only, never stored
    return JSONResponse({"ok": True}, headers=hdr)


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /\n"

