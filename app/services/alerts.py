"""Alert rules engine + notifications (Slack webhook / SMTP email)."""
from __future__ import annotations

import logging
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage

import httpx

from .. import db
from ..config import settings
from ..connectors import label

log = logging.getLogger("adpulse.alerts")

DEFAULT_RULES = [
    # kind, threshold, window_days, description
    ("cpa_spike", 0.40, 3, "Campaign CPA up ≥40% vs its 28-day baseline"),
    ("roas_drop", 0.30, 3, "Campaign ROAS down ≥30% vs its 28-day baseline"),
    ("spend_spike", 0.50, 1, "Daily spend ≥50% above baseline"),
    ("zero_conversions", 150, 3, "≥$150 spent with no conversions"),
    ("ranking_drop", 3, 7, "Keyword average position worse by ≥3 places week-on-week"),
    ("traffic_drop", 0.20, 7, "Organic search sessions down ≥20% vs baseline"),
    ("sync_failure", 1, 1, "A data connection failed to sync"),
]
RULE_HELP = {k: d for k, _, _, d in DEFAULT_RULES}


def ensure_default_rules():
    if not db.one("SELECT id FROM alert_rules WHERE client_id IS NULL LIMIT 1"):
        for k, t, w, _ in DEFAULT_RULES:
            db.execute("INSERT INTO alert_rules (client_id, kind, threshold, window_days) VALUES (NULL,?,?,?)", (k, t, w))


def rules_for(client_id: int) -> list[dict]:
    """Client-specific rules override global rules of the same kind."""
    rules = {r["kind"]: r for r in db.rows("SELECT * FROM alert_rules WHERE client_id IS NULL AND enabled=1")}
    for r in db.rows("SELECT * FROM alert_rules WHERE client_id=?", (client_id,)):
        if r["enabled"]:
            rules[r["kind"]] = r
        else:
            rules.pop(r["kind"], None)
    return list(rules.values())


def _window(days: int, baseline: int = 28):
    end = date.today()
    ws = end - timedelta(days=days - 1)
    be = ws - timedelta(days=1)
    bs = be - timedelta(days=baseline - 1)
    return str(ws), str(end), str(bs), str(be)


def _campaign_stats(client_id, s, e):
    return {(r["platform"], r["campaign_id"]): r for r in db.rows(
        "SELECT platform, campaign_id, MAX(campaign_name) campaign_name, SUM(spend) spend, SUM(conversions) conv, SUM(revenue) rev, COUNT(DISTINCT date) days "
        "FROM ad_metrics WHERE client_id=? AND date BETWEEN ? AND ? GROUP BY platform, campaign_id", (client_id, s, e))}


def evaluate_client(client_id: int) -> list[dict]:
    client = db.one("SELECT * FROM clients WHERE id=?", (client_id,))
    cur_sym = "$"
    fired: list[dict] = []
    today = str(date.today())

    def fire(rule, key, severity, title, detail):
        dk = f"{rule['kind']}|{client_id}|{key}|{today}"
        try:
            aid = db.execute("INSERT INTO alerts (client_id, rule_id, dedupe_key, severity, title, detail) VALUES (?,?,?,?,?,?)",
                             (client_id, rule["id"], dk, severity, title, detail))
            fired.append({"id": aid, "severity": severity, "title": title, "detail": detail})
        except Exception:
            pass  # already raised today

    for rule in rules_for(client_id):
        k, th, w = rule["kind"], rule["threshold"], rule["window_days"]
        if k in ("cpa_spike", "roas_drop", "zero_conversions", "spend_spike"):
            ws, we, bs, be = _window(w)
            cur, base = _campaign_stats(client_id, ws, we), _campaign_stats(client_id, bs, be)
            for key, c in cur.items():
                if rule["platform"] and key[0] != rule["platform"]:
                    continue
                b = base.get(key)
                name = f"{label(key[0])} · {c['campaign_name']}"
                if k == "zero_conversions":
                    if c["spend"] >= th and c["conv"] < 0.5:
                        fire(rule, key, "critical", f"No conversions: {name}", f"{cur_sym}{c['spend']:,.0f} spent over {w} days with zero conversions.")
                    continue
                if not b or not b["days"] or b["spend"] < 50:
                    continue
                if k == "cpa_spike" and c["conv"] > 0 and b["conv"] > 0:
                    cpa, bcpa = c["spend"] / c["conv"], b["spend"] / b["conv"]
                    if cpa > bcpa * (1 + th):
                        fire(rule, key, "critical" if cpa > bcpa * (1 + 2 * th) else "warning", f"CPA spike: {name}",
                             f"CPA {cur_sym}{cpa:,.2f} over last {w}d vs {cur_sym}{bcpa:,.2f} baseline (+{cpa / bcpa - 1:.0%}).")
                if k == "roas_drop" and b["rev"] > 0 and c["spend"] > 0:
                    roas, broas = c["rev"] / c["spend"], b["rev"] / b["spend"]
                    if roas < broas * (1 - th):
                        fire(rule, key, "warning", f"ROAS drop: {name}", f"ROAS {roas:.2f}x over last {w}d vs {broas:.2f}x baseline ({roas / broas - 1:.0%}).")
                if k == "spend_spike":
                    daily, bdaily = c["spend"] / max(1, c["days"]), b["spend"] / b["days"]
                    if daily > bdaily * (1 + th) and daily - bdaily > 50:
                        fire(rule, key, "warning", f"Spend spike: {name}", f"{cur_sym}{daily:,.0f}/day vs {cur_sym}{bdaily:,.0f}/day baseline.")
        elif k == "ranking_drop":
            q = ("SELECT query, SUM(position*impressions)/NULLIF(SUM(impressions),0) pos, SUM(impressions) imp FROM seo_queries "
                 "WHERE client_id=? AND source='gsc' AND date BETWEEN ? AND ? GROUP BY query")
            ws, we = str(date.today() - timedelta(days=6)), today
            ps, pe = str(date.today() - timedelta(days=13)), str(date.today() - timedelta(days=7))
            prev = {r["query"]: r for r in db.rows(q, (client_id, ps, pe))}
            for r in db.rows(q, (client_id, ws, we)):
                p = prev.get(r["query"])
                if p and r["pos"] and p["pos"] and r["imp"] >= 100 and r["pos"] - p["pos"] >= th:
                    fire(rule, r["query"], "warning", f"Ranking drop: “{r['query']}”",
                         f"Avg position {p['pos']:.1f} → {r['pos']:.1f} week-on-week ({r['imp']:,} impressions).")
        elif k == "traffic_drop":
            ws, we, bs, be = _window(w)
            q = "SELECT SUM(value)/COUNT(DISTINCT date) v FROM organic_metrics WHERE client_id=? AND platform='ga4' AND metric='sessions' AND dimension='Organic Search' AND date BETWEEN ? AND ?"
            c, b = db.one(q, (client_id, ws, we))["v"], db.one(q, (client_id, bs, be))["v"]
            if c and b and c < b * (1 - th):
                fire(rule, "organic", "warning", "Organic search traffic drop", f"{c:,.0f} sessions/day over last {w}d vs {b:,.0f}/day baseline ({c / b - 1:.0%}).")
        elif k == "sync_failure":
            for cn in db.rows("SELECT * FROM connections WHERE client_id=? AND status='error'", (client_id,)):
                fire(rule, cn["id"], "critical", f"Sync failed: {label(cn['platform'])}", cn["last_error"][:300])

    if fired:
        notify(client, fired)
    return fired


def notify(client: dict, alerts: list[dict]) -> None:
    text = f"*{client['name']}* — {len(alerts)} new alert(s)\n" + "\n".join(f"• [{a['severity']}] {a['title']}: {a['detail']}" for a in alerts)
    link = f"{settings.BASE_URL}/clients/{client['id']}#alerts"
    if settings.SLACK_WEBHOOK_URL:
        try:
            httpx.post(settings.SLACK_WEBHOOK_URL, json={"text": f"{text}\n<{link}|Open in {settings.APP_NAME}>"}, timeout=10)
        except Exception:
            log.exception("slack notify failed")
    if settings.SMTP_HOST and settings.ALERT_EMAIL_TO:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[{settings.APP_NAME}] {client['name']}: {len(alerts)} alert(s)"
            msg["From"] = settings.ALERT_EMAIL_FROM or settings.SMTP_USER
            msg["To"] = settings.ALERT_EMAIL_TO
            msg.set_content(text.replace("*", "") + f"\n\n{link}")
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as s:
                s.starttls()
                if settings.SMTP_USER:
                    s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                s.send_message(msg)
        except Exception:
            log.exception("email notify failed")
