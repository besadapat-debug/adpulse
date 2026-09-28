"""Optional AI pricing review, using Claude through the Anthropic API.

Set ANTHROPIC_API_KEY (from console.anthropic.com) to turn it on. Each review sends the audit summary,
your packages, the price check and market prices, and asks for a recommendation in plain English.
It never changes your prices by itself: it suggests, you decide. A review typically costs a few cents.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

import httpx

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM = """You are a pricing adviser for a small Australian digital marketing agency that sells to local businesses
(tradies, pharmacies, allied health, cafés, retail). You review one proposal and tell the agency owner, in plain simple
English, which package to lead with and how to pitch it so the business owner says yes and the agency still makes money.

Rules:
- Use ONLY the numbers in the data. Never invent statistics, benchmarks, results or percentages. If something is unknown, say what to ask.
- Prices are AUD excluding GST. Ad spend is paid to Google/Meta, not the agency.
- If the business can't comfortably afford a package (see price_check and pct_revenue), recommend a smaller one or a cut-down version.
- If a package earns the agency less than its hourly target, say so and suggest what work to remove or what to charge.
- Month-to-month, no lock-in, and small one-off first jobs are preferred for small businesses.
- For health businesses (compliance notes present), remind them of AHPRA: no patient testimonials in advertising.
- Never promise a number of new customers or a ranking.
Reply with JSON only, no markdown, in exactly this shape:
{"lead_with": "<package name>", "suggested_monthly": <number or null>, "suggested_setup": <number or null>,
 "why": "<2-3 sentences>", "say_this": "<what to say to the owner, 2-3 sentences, speaking to them as 'you'>",
 "change": ["<specific price or scope change>", ...], "ask_them": ["<question to ask the owner>", ...],
 "watch_out": ["<risk>", ...]}"""


def api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "")


def _payload(report: dict) -> dict:
    q = report.get("quote") or {}
    ss = report.get("social_summary") or {}
    return {
        "business": {"name": report.get("name") or report.get("domain"), **{k: v for k, v in (report.get("business") or {}).items()
                                                                              if k not in ("mention_pricing",)}},
        "industry_label": q.get("industry"), "size_label": q.get("size"),
        "scores": report.get("overall"),
        "top_website_problems": [i.get("problem") or i.get("title") for i in report.get("top_issues", [])[:5]],
        "social_missing": ss.get("missing"), "social_scores": {p["label"]: p.get("score") for p in (ss.get("platforms") or {}).values()},
        "competitors": report.get("competitor_summary"),
        "customer_value_per_year": q.get("customer_value"),
        "packages": [{"name": t["name"], "setup_total": t["setup_total"], "monthly_total": t["monthly_total"], "suggested_ad_spend": t["ad_spend"],
                      "setup_items": [f"{i['item']} ${i['amount']}" for i in t["setup"]],
                      "monthly_items": [f"{i['item']} ${i['amount']}" for i in t["monthly"]],
                      "payback": t.get("payback"), "one_off_only": bool(t.get("starter"))} for t in q.get("tiers", [])],
        "price_check": q.get("price_check"),
        "market_prices": [{"option": r["label"], "price": r["price"], "note": r["note"]} for r in (report.get("market") or {}).get("rows", [])],
        "compliance_notes": report.get("compliance"),
    }


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def review(report: dict) -> dict:
    key = api_key()
    if not key:
        raise ValueError("AI review isn't switched on. Add ANTHROPIC_API_KEY in Render → Environment (see DEPLOY.md, Step 7).")
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=90,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": MODEL, "max_tokens": 1500, "system": SYSTEM,
                             "messages": [{"role": "user", "content": "Review this proposal:\n" + json.dumps(_payload(report), default=str)}]})
    except httpx.HTTPError as e:
        raise ValueError(f"Couldn't reach the AI service: {e}")
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = r.text[:200]
        if r.status_code == 401:
            msg = "The ANTHROPIC_API_KEY isn't valid. Create a new key at console.anthropic.com and paste it into Render again."
        elif "credit" in msg.lower() or r.status_code == 402:
            msg = "Your Anthropic account is out of credit. Add credit at console.anthropic.com → Billing."
        raise ValueError(msg or f"AI service error {r.status_code}")
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    try:
        out = _parse(text)
    except Exception:
        out = {"why": text.strip()[:1500]}
    for k in ("change", "ask_them", "watch_out"):
        out[k] = [str(x) for x in (out.get(k) or [])][:6]
    out["date"] = date.today().isoformat()
    out["model"] = MODEL
    return out
