"""Google Maps & reviews tracker: what the business's Google listing brings in each month, and its reviews vs competitors.

Monthly figures come from the Google Business Profile "Performance" page (calls, direction requests, website clicks,
profile views, searches, bookings), typed in once a month, or from a connection. Google only gives these to approved
Business Profile API projects, so typing them in is the reliable route for now. Review counts and ratings for the
business and its competitors can be refreshed from Google Places with an API key, or typed in.
"""
from __future__ import annotations

import re
from datetime import date

from .. import db
from . import competitors as comp_svc

ACTIVITY = [  # metric, label
    ("calls", "Calls"), ("direction_requests", "Direction requests"), ("website_clicks", "Website clicks"),
    ("bookings", "Bookings"), ("profile_views", "Profile views"), ("searches", "Searches you appeared in"),
]
SNAPSHOT = [("reviews_total", "Total Google reviews"), ("rating", "Star rating")]
PLATFORM = "google_business"


def _month(m: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", m or ""):
        raise ValueError("Month must look like 2026-09")
    return m


def prev_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:])
    mo -= 1
    if mo == 0:
        y, mo = y - 1, 12
    return f"{y}-{mo:02d}"


def last_full_month() -> str:
    return prev_month(date.today().strftime("%Y-%m"))


def save_month(client_id: int, month: str, values: dict) -> None:
    month = _month(month)
    keys = [k for k, _ in ACTIVITY + SNAPSHOT]
    with db.tx() as c:
        for k in keys:
            if k not in values:
                continue
            v = values[k]
            if v in (None, ""):
                c.execute("DELETE FROM organic_metrics WHERE client_id=? AND platform=? AND dimension='monthly' AND metric=? AND date=?",
                          (client_id, PLATFORM, k, f"{month}-01"))
                continue
            c.execute("INSERT INTO organic_metrics (client_id, platform, dimension, metric, date, value) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(client_id, platform, dimension, metric, date) DO UPDATE SET value=excluded.value",
                      (client_id, PLATFORM, "monthly", k, f"{month}-01", float(str(v).replace(",", ""))))


def monthly_series(client_id: int, months: int = 12) -> list[dict]:
    """One row per month. Typed-in monthly figures win over daily figures from a connection for the same month."""
    rows = db.rows("SELECT substr(date,1,7) m, dimension, metric, SUM(value) v, MAX(value) mx FROM organic_metrics "
                   "WHERE client_id=? AND platform=? GROUP BY substr(date,1,7), dimension, metric", (client_id, PLATFORM))
    typed, daily = {}, {}
    for r in rows:
        val = r["mx"] if r["metric"] in ("reviews_total", "rating") else r["v"]
        (typed if r["dimension"] == "monthly" else daily)[(r["m"], r["metric"])] = val
    out = []
    for m in sorted({k[0] for k in {**typed, **daily}})[-months:]:
        s = {"month": m, "typed": any(k[0] == m for k in typed)}
        for (mm, metric), v in {**daily, **typed}.items():          # typed overrides daily
            if mm == m and v is not None:
                s[metric] = round(v, 1) if metric == "rating" else round(v)
        out.append(s)
    for i, s in enumerate(out):
        p = out[i - 1] if i else None
        s["new_reviews"] = (s["reviews_total"] - p["reviews_total"]) if p and s.get("reviews_total") is not None and p.get("reviews_total") is not None else None
    return out


def save_competitors(client_id: int, month: str, items: list[dict]) -> None:
    month = _month(month)
    with db.tx() as c:
        c.execute("DELETE FROM local_competitors WHERE client_id=? AND month=?", (client_id, month))
        for it in items[:15]:
            name = str(it.get("name") or "").strip()[:120]
            if not name:
                continue
            rating = _f(it.get("rating"))
            reviews = _f(it.get("reviews"))
            c.execute("INSERT INTO local_competitors (client_id, month, name, rating, reviews) VALUES (?,?,?,?,?)",
                      (client_id, month, name, rating, None if reviews is None else int(reviews)))


def _f(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def competitors(client_id: int, month: str | None = None) -> dict:
    months = [r["month"] for r in db.rows("SELECT DISTINCT month FROM local_competitors WHERE client_id=? ORDER BY month", (client_id,))]
    if not months:
        return {"month": None, "months": [], "list": [], "previous": {}}
    m = month if month in months else months[-1]
    lst = db.rows("SELECT name, rating, reviews FROM local_competitors WHERE client_id=? AND month=? ORDER BY reviews DESC", (client_id, m))
    prev = {}
    i = months.index(m)
    if i:
        prev = {r["name"]: r for r in db.rows("SELECT name, rating, reviews FROM local_competitors WHERE client_id=? AND month=?", (client_id, months[i - 1]))}
    for r in lst:
        p = prev.get(r["name"])
        r["new_reviews"] = (r["reviews"] - p["reviews"]) if p and r["reviews"] is not None and p["reviews"] is not None else None
    return {"month": m, "months": months, "list": lst}


def summary(client_id: int) -> dict:
    series = monthly_series(client_id)
    this_month = date.today().strftime("%Y-%m")
    for r in series:
        r["partial"] = r["month"] >= this_month
    full = [r for r in series if not r["partial"]]          # headline figures use whole months only
    latest = full[-1] if full else (series[-1] if series else {})
    prev = full[-2] if len(full) > 1 else {}
    comp = competitors(client_id, latest.get("month"))
    me = {"name": "You", "reviews": latest.get("reviews_total"), "rating": latest.get("rating"), "new_reviews": latest.get("new_reviews"), "is_self": True}
    ranking = sorted([me, *comp["list"]], key=lambda r: -(r["reviews"] or 0)) if comp["list"] else []
    rank = next((i + 1 for i, r in enumerate(ranking) if r.get("is_self")), None)
    top = next((r for r in ranking if not r.get("is_self")), None)
    changes = {}
    for k, _ in ACTIVITY:
        a, b = latest.get(k), prev.get(k)
        changes[k] = ((a - b) / b) if a is not None and b else None
    c = db.one("SELECT name, area, search_term FROM clients WHERE id=?", (client_id,)) or {}
    return {"series": series, "latest": latest, "previous": prev, "changes": changes, "activity": ACTIVITY,
            "competitors": comp, "ranking": ranking, "rank": rank, "of": len(ranking), "top_competitor": top,
            "places_enabled": bool(comp_svc.api_key()), "area": c.get("area") or "", "search_term": c.get("search_term") or "",
            "maps_link": comp_svc.maps_link(c.get("search_term") or "", c.get("area") or "") if c.get("area") else "", "suggest_month": last_full_month()}


def refresh_reviews(client_id: int, month: str) -> dict:
    """Look up current rating & review count on Google for the business and each competitor (needs a Places key)."""
    month = _month(month)
    c = db.one("SELECT name, area FROM clients WHERE id=?", (client_id,))
    area = (c or {}).get("area") or ""
    if not area:
        raise ValueError("Add the business's suburb first (the 'Suburb' box on this tab).")
    names = [r["name"] for r in competitors(client_id)["list"]]
    found = {}
    for n in [c["name"], *names]:
        try:
            res = comp_svc.find(n, area)
        except ValueError as e:
            if not found:
                raise
            res, _ = [], e
        if res:
            found[n] = res[0]
    me = found.get(c["name"])
    if me:
        save_month(client_id, month, {"reviews_total": me.get("reviews"), "rating": me.get("rating")})
    save_competitors(client_id, month, [{"name": n, "rating": (found.get(n) or {}).get("rating"), "reviews": (found.get(n) or {}).get("reviews")} for n in names])
    return {"updated": len(found)}


def find_competitors(client_id: int, month: str) -> dict:
    """Search Google Places for similar businesses in the client's suburb and track the top few (needs a Places key)."""
    month = _month(month)
    c = db.one("SELECT name, area, search_term FROM clients WHERE id=?", (client_id,))
    term, area = (c or {}).get("search_term") or "", (c or {}).get("area") or ""
    if not term or not area:
        raise ValueError("Fill in 'What they do' (e.g. pharmacy) and 'Suburb' first.")
    found = comp_svc.find(term, area, "", c["name"])
    me = next((f for f in found if f["is_self"]), None)
    if me:
        save_month(client_id, month, {"reviews_total": me.get("reviews"), "rating": me.get("rating")})
    others = [f for f in found if not f["is_self"]][:6]
    if not others:
        raise ValueError(f"Google found no '{term}' businesses near {area}. Try a broader search word or add the suburb's state (e.g. VIC).")
    save_competitors(client_id, month, [{"name": f["name"], "rating": f.get("rating"), "reviews": f.get("reviews")} for f in others])
    return {"found": len(others)}
