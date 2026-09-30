"""7-day trial: a day-by-day plan, a before/after snapshot and an end-of-trial report that makes the case to continue.

A week is too short to promise sales, so the trial is built around things that visibly change in 7 days:
a complete Google profile, fresh photos and posts, a review system that brings in new reviews, and website quick wins.
Calls and direction requests are included when the owner has given access to their Google Business Profile.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from .. import db

PROFILE_CHECKS = [
    ("hours", "Opening hours correct (incl. public holidays)"),
    ("categories", "Main + extra categories set"),
    ("services", "Services listed"),
    ("description", "Business description written"),
    ("booking", "Booking / appointment link"),
    ("website_phone", "Website and phone correct"),
    ("photos10", "10+ recent photos"),
    ("posted", "Posted on Google in the last 7 days"),
]

SNAPSHOT_FIELDS = [
    ("reviews_total", "Google reviews"), ("rating", "Star rating"), ("photos", "Photos on Google profile"),
    ("posts_30d", "Google posts (last 30 days)"), ("calls", "Calls from Google (last 7 days)"),
    ("direction_requests", "Direction requests (last 7 days)"), ("website_clicks", "Website clicks (last 7 days)"),
]

HEALTH_NOTE = " Keep it factual: no claims about treatment results, no patient testimonials."


def default_tasks(health: bool) -> list[dict]:
    h = HEALTH_NOTE if health else ""
    plan = [
        (1, "Get Manager access to their Google Business Profile", "Owner: business.google.com → Business Profile settings → People and access → Add → your email → Manager."),
        (1, "Record the 'before' numbers", "Fill in the Before column below: reviews, rating, photos, posts and the profile checklist."),
        (1, "Agree one goal for the week", "e.g. more flu vaccination bookings, more new customers, more reviews. Write it in the Goal box."),
        (2, "Fix the basics on Google", "Check name, address, phone and hours (add upcoming public-holiday hours)."),
        (2, "Set the right categories and services", "Main category plus extra categories; list the services people search for (e.g. vaccinations, blister packs, script refills)."),
        (2, "Write the business description and add the booking link", "Plain words about what they offer and who they help." + h),
        (3, "Upload 10+ real photos", "Shopfront (so people recognise it), inside, counter, products. Photos of staff only with their OK; no customers."),
        (3, "Publish Google post #1", "One timely offer or service, e.g. 'Flu vaccinations now available: book online or walk in'." + h),
        (4, "Start the review system", "Counter card with a QR code to the Google review link, and the link in receipts/texts if they have them. "
                                        "Ask every customer the same way: no gifts or discounts for reviews, and don't only ask happy customers (Google rules)."),
        (4, "Reply to every existing review", "Short, polite, thank them. Never confirm someone is a patient or mention health details."),
        (5, "Fix the top 3 website problems", "From the audit: e.g. tap-to-call button, clear booking button, Google Analytics installed."),
        (5, "Make website hours and phone match Google", "Mismatches confuse customers and Google."),
        (6, "Publish Google post #2", "A different service or a friendly 'meet the team' post." + h),
        (6, "Answer common questions", "Add 2–3 FAQs (parking, bookings, services) on the website or in posts."),
        (7, "Record the 'after' numbers", "Fill in the After column: same figures as day 1."),
        (7, "Send the end-of-trial report and book a 15-minute chat", "Open 'End-of-trial report', check it, then send the link or print it."),
    ]
    internal = {"Record the 'before' numbers", "Record the 'after' numbers", "Send the end-of-trial report and book a 15-minute chat"}
    return [{"id": f"t{i}", "day": d, "title": t, "help": hlp, "done": False, "note": "", "internal": t in internal}
            for i, (d, t, hlp) in enumerate(plan, 1)]


def _row(client_id: int) -> dict | None:
    r = db.one("SELECT * FROM trials WHERE client_id=?", (client_id,))
    if not r:
        return None
    out = dict(r)
    for k in ("baseline", "after", "tasks", "checks_before", "checks_after", "website_before", "website_after"):
        try:
            out[k] = json.loads(out.get(k) or ("[]" if k == "tasks" else "{}"))
        except Exception:
            out[k] = [] if k == "tasks" else {}
    return out


def start(client_id: int, health: bool, start_date: str | None = None) -> dict:
    s = start_date or date.today().isoformat()
    db.execute("DELETE FROM trials WHERE client_id=?", (client_id,))
    db.execute("INSERT INTO trials (client_id, start_date, goal, baseline, after, tasks, checks_before, checks_after, show_price) VALUES (?,?,?,?,?,?,?,?,1)",
               (client_id, s, "", "{}", "{}", json.dumps(default_tasks(health)), "{}", "{}"))
    return get(client_id)


def update(client_id: int, body: dict) -> dict:
    cur = _row(client_id)
    if not cur:
        raise ValueError("Start the trial first.")
    fields = {}
    if "goal" in body:
        fields["goal"] = str(body["goal"])[:300]
    if "start_date" in body:
        date.fromisoformat(str(body["start_date"]))
        fields["start_date"] = str(body["start_date"])
    if "website_url" in body:
        fields["website_url"] = str(body["website_url"]).strip()[:300]
    if "show_price" in body:
        fields["show_price"] = 1 if body["show_price"] else 0
    for k in ("baseline", "after"):
        if isinstance(body.get(k), dict):
            clean = {}
            for f, _ in SNAPSHOT_FIELDS:
                v = body[k].get(f)
                if v not in (None, ""):
                    clean[f] = float(str(v).replace(",", ""))
            fields[k] = json.dumps(clean)
    for k in ("checks_before", "checks_after"):
        if isinstance(body.get(k), dict):
            fields[k] = json.dumps({c: bool(body[k].get(c)) for c, _ in PROFILE_CHECKS})
    if isinstance(body.get("tasks"), list):
        by_id = {t["id"]: t for t in cur["tasks"]}
        for t in body["tasks"]:
            if isinstance(t, dict) and t.get("id") in by_id:
                by_id[t["id"]]["done"] = bool(t.get("done"))
                by_id[t["id"]]["note"] = str(t.get("note") or "")[:300]
            elif isinstance(t, dict) and t.get("new") and str(t.get("title", "")).strip():
                nid = f"c{len(by_id) + 1}"
                by_id[nid] = {"id": nid, "day": int(t.get("day") or 7), "title": str(t["title"])[:120], "help": "", "done": False, "note": ""}
        fields["tasks"] = json.dumps(sorted(by_id.values(), key=lambda x: (x["day"], x["id"][0] != "t", int(x["id"][1:]))))
    if fields:
        db.execute(f"UPDATE trials SET {', '.join(f'{k}=?' for k in fields)} WHERE client_id=?", (*fields.values(), client_id))
    return get(client_id)


def _completeness(checks: dict) -> int | None:
    if not checks:
        return None
    return round(100 * sum(1 for c, _ in PROFILE_CHECKS if checks.get(c)) / len(PROFILE_CHECKS))


def get(client_id: int) -> dict:
    t = _row(client_id)
    if not t:
        return {"started": False, "fields": SNAPSHOT_FIELDS, "profile_checks": PROFILE_CHECKS}
    start_d = date.fromisoformat(t["start_date"])
    day = min(7, max(1, (date.today() - start_d).days + 1))
    done = sum(1 for x in t["tasks"] if x["done"])
    return {**t, "started": True, "fields": SNAPSHOT_FIELDS, "profile_checks": PROFILE_CHECKS, "day": day,
            "end_date": (start_d + timedelta(days=6)).isoformat(), "done": done, "total": len(t["tasks"]),
            "completeness_before": _completeness(t["checks_before"]), "completeness_after": _completeness(t["checks_after"]),
            "website": website_compare(t), "website_tips": WEBSITE_TIPS}


def report(client_id: int) -> dict:
    """What the end-of-trial page says: what we did, before vs after, and what continuing looks like."""
    from . import pricing
    t = get(client_id)
    c = db.one("SELECT * FROM clients WHERE id=?", (client_id,))
    if not t["started"]:
        return {"started": False, "client": c}
    b, a = t["baseline"], t["after"]
    rows = []
    for f, label in SNAPSHOT_FIELDS:
        if f in b or f in a:
            bv, av = b.get(f), a.get(f)
            ch = (av - bv) if bv is not None and av is not None else None
            rows.append({"label": label, "before": bv, "after": av, "change": ch, "rating": f == "rating"})
    if t["completeness_before"] is not None or t["completeness_after"] is not None:
        rows.insert(0, {"label": "Google profile complete", "before": t["completeness_before"], "after": t["completeness_after"], "pct": True,
                        "change": (t["completeness_after"] - t["completeness_before"])
                        if t["completeness_before"] is not None and t["completeness_after"] is not None else None})
    wins = []
    for r in rows:
        if r["change"] and r["change"] > 0:
            if r.get("pct"):
                wins.append(f"Google profile went from {r['before']:.0f}% to {r['after']:.0f}% complete")
            elif r["label"] == "Google reviews":
                wins.append(f"{r['change']:.0f} new Google review{'s' if r['change'] != 1 else ''}")
            elif r["label"] == "Photos on Google profile":
                wins.append(f"{r['change']:.0f} new photos on Google")
            elif r["label"].startswith("Google posts"):
                wins.append(f"{r['change']:.0f} new Google post{'s' if r['change'] != 1 else ''}")
            elif not r.get("rating"):
                wins.append(f"{r['change']:.0f} more {r['label'].split(' (')[0].lower()}")
    w = t.get("website")
    if w and w["score_change"] and w["score_change"] > 0:
        wins.insert(0, f"website score up from {w['before']['score']} to {w['after']['score']}/100")
    done = [x for x in t["tasks"] if x["done"] and not x.get("internal")]      # the owner sees the work, not our admin
    rc = pricing.rate_card()
    lite = round(rc["lite_monthly"] / 10) * 10
    return {"started": True, "client": c, "trial": t, "rows": rows, "wins": wins, "done": done,
            "not_done": [x for x in t["tasks"] if not x["done"]], "lite_price": lite, "show_price": bool(t.get("show_price", 1))}


WEBSITE_TIPS = [
    ("Clear top section", "Business name, phone (tap-to-call on mobile), today's hours and one main button such as 'Book a vaccination', all visible without scrolling."),
    ("Real photos", "Replace stock images with real photos of the shopfront, counter and team (with their OK). No photos of customers."),
    ("One page per service", "Vaccinations, blister/Webster packs, script refills, health checks: what it is, who it's for, how to book."),
    ("Easy to book or call", "A booking button or form on every page, and the phone number in the header."),
    ("Matches Google", "Same name, address, phone and hours as the Google listing, and a Google map on the contact page."),
    ("Fast and mobile-first", "Compress large images, remove pop-ups and old plugins. Most visitors are on a phone."),
    ("Trust without testimonials", "Pharmacist names, qualifications and memberships; accurate, factual service info. No patient testimonials or outcome claims (Ahpra)."),
    ("Tidy and current", "Remove old promotions and broken links, use 2 fonts and the brand colours consistently, update the footer year."),
]


def website_check(client_id: int, which: str) -> dict:
    """Scan the client's website (same checks as the prospect audit) and keep it as the 'before' or 'after' snapshot."""
    from . import prospects
    if which not in ("before", "after"):
        raise ValueError("which must be before or after")
    t = _row(client_id)
    if not t:
        raise ValueError("Start the trial first.")
    url = (t.get("website_url") or "").strip()
    if not url:
        raise ValueError("Type their website address first.")
    page = prospects.fetch(url)
    speed = prospects.pagespeed(page["final_url"], screenshot=True)
    rep = prospects.analyse(page, speed)
    checks = [{"key": c["key"], "ok": bool(c["ok"]), "title": c["title"], "fix": c.get("fix", ""), "impact": c.get("impact", ""),
               "problem": prospects.problem_label(c), "weight": c.get("weight", 1)} for c in rep["checks"]]
    snap = {"date": date.today().isoformat(), "url": page["final_url"], "score": rep["score"], "checks": checks,
            "speed": (speed or {}).get("score"), "screenshot": (speed or {}).get("screenshot", "")}
    db.execute(f"UPDATE trials SET website_{which}=? WHERE client_id=?", (json.dumps(snap), client_id))
    return get(client_id)


def website_compare(t: dict) -> dict | None:
    b, a = t.get("website_before") or {}, t.get("website_after") or {}
    if not b and not a:
        return None
    bk = {c["key"]: c for c in b.get("checks", [])}
    ak = {c["key"]: c for c in a.get("checks", [])}
    fixed = [ak[k] for k in ak if ak[k]["ok"] and k in bk and not bk[k]["ok"]]
    latest = a or b
    todo = sorted([c for c in latest.get("checks", []) if not c["ok"]], key=lambda c: -c.get("weight", 1))
    return {"before": b, "after": a, "fixed": fixed, "todo": todo,
            "score_change": (a["score"] - b["score"]) if a and b else None}
