"""Upload reports: turn a CSV exported from Meta Ads Manager, Google Ads or Google Analytics into dashboard data.

Works with no API approvals. The file's columns are recognised by name (e.g. "Amount spent (AUD)", "Cost",
"Impr.", "Link clicks", "Results", "Age", "Gender", "Region", "Town/City", "Active users"), so the usual exports
work as they come. Three kinds of file:
  * ad results by campaign (and optionally by day)      → Paid performance
  * a breakdown by age / gender / region / city        → Audience (demographics)
  * website visitors by day (GA4)                      → Web & social
"""
from __future__ import annotations

import calendar
import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime

from .. import db
from .sync import UPSERTS

FIELDS = {
    # field: aliases in order of preference (lower-case; "(…)" suffixes such as currency are ignored)
    "date": ["day", "date", "reporting starts", "week", "month", "year month"],
    "date_end": ["reporting ends"],
    "campaign": ["campaign name", "campaign"],
    "spend": ["amount spent", "cost", "spend"],
    "impressions": ["impressions", "impr.", "impr"],
    "reach": ["reach"],
    "clicks": ["link clicks", "clicks", "clicks (all)"],
    "conversions": ["results", "conversions", "leads", "purchases", "key events", "all conversions"],
    "revenue": ["purchases conversion value", "website purchases conversion value", "conv. value", "conversion value", "total revenue", "revenue"],
    "age": ["age", "age range", "age bracket"],
    "gender": ["gender"],
    "region": ["region", "state", "location", "user location", "country/region"],
    "city": ["town/city", "city", "suburb"],
    "users": ["active users", "total users", "users"],
    "sessions": ["sessions"],
}
DEMO_DIMS = ("age", "gender", "region", "city")
AD_PLATFORMS = {"meta_ads": "Meta Ads (Facebook & Instagram)", "google_ads": "Google Ads", "tiktok_ads": "TikTok Ads", "linkedin_ads": "LinkedIn Ads"}
PLATFORMS = {**AD_PLATFORMS, "ga4": "Google Analytics"}
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%b %d, %Y", "%a, %b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y", "%Y/%m/%d", "%m/%d/%Y"]


class ImportError_(ValueError):
    pass


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or raw[1:2] == b"\x00":
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportError_("Couldn't read the file. Please export it as CSV.")


def _norm(h: str) -> str:
    h = (h or "").strip().strip('"').lower().replace("﻿", "")
    return re.sub(r"\s*\([^)]*\)\s*$", "", h).strip()      # "amount spent (aud)" -> "amount spent"


def _num(v) -> float:
    s = str(v or "").strip().replace(",", "").replace("$", "").replace("A", "").replace("%", "").replace(" ", "")
    if s in ("", "--", "-", "—", " --"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(\.\d+)?", s)
        return float(m.group(0)) if m else 0.0


def parse_date(v) -> date | None:
    s = str(v or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{6}", s):                       # GA4 yearMonth 202609
        return date(int(s[:4]), int(s[4:]), 1)
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return date.fromisoformat(m.group(1)) if m else None


def _range_from_text(lines: list[str]) -> tuple[date, date] | None:
    """Google Ads puts e.g. 'September 1, 2026 - September 28, 2026' above the header; GA4 puts '# Start date: 20260901'."""
    text = " ".join(lines)
    ga = re.search(r"start date:\s*(\d{8}).*?end date:\s*(\d{8})", text, re.I)
    if ga:
        return parse_date(ga.group(1)), parse_date(ga.group(2))
    for line in lines:
        parts = re.split(r"\s+[-–]\s+", line.strip().strip('"'))
        if len(parts) == 2:
            a, b = parse_date(parts[0].strip().strip('"')), parse_date(parts[1].strip().strip('"'))
            if a and b:
                return a, b
    return None


def _month_bounds(d: date) -> tuple[date, date]:
    return d.replace(day=1), d.replace(day=calendar.monthrange(d.year, d.month)[1])


def read_table(raw: bytes) -> tuple[list[str], list[list[str]], list[str]]:
    text = _decode(raw)
    lines = [ln for ln in text.splitlines()]
    sample = "\n".join(ln for ln in lines[:30] if not ln.startswith("#"))
    delim = max([",", "\t", ";"], key=lambda d: sample.count(d))
    rows = list(csv.reader(io.StringIO("\n".join(ln for ln in lines if not ln.startswith("#"))), delimiter=delim))
    known = {a for al in FIELDS.values() for a in al}
    for i, r in enumerate(rows[:30]):
        hits = sum(1 for c in r if _norm(c) in known)
        if hits >= 2:
            pre = [" ".join(x) for x in rows[:i]] + [ln.lstrip("# ") for ln in lines if ln.startswith("#")]
            return [c.strip() for c in r], rows[i + 1:], pre
    raise ImportError_("Couldn't find the column headings. Make sure it's a CSV export with columns like "
                       "Campaign name, Amount spent / Cost, Impressions, Clicks, or Age / Gender.")


def map_columns(header: list[str]) -> dict[str, int]:
    normed = [_norm(h) for h in header]
    out = {}
    for f, aliases in FIELDS.items():
        for a in aliases:
            if a in normed:
                out[f] = normed.index(a)
                break
    return out


def detect_platform(header: list[str], cols: dict) -> str | None:
    n = [_norm(h) for h in header]
    if "amount spent" in n or "reporting starts" in n or "results" in n:
        return "meta_ads"
    if "cost" in n and ("impr." in n or "impr" in n or "conv. value" in n or "impressions" in n):
        return "google_ads"
    if "users" in cols or "sessions" in cols:
        return "ga4"
    return None


def import_csv(client_id: int, raw: bytes, filename: str = "", platform: str = "auto",
               period_from: str = "", period_to: str = "", user: str = "") -> dict:
    header, body, pre = read_table(raw)
    cols = map_columns(header)
    plat = platform if platform in PLATFORMS else detect_platform(header, cols)
    if not plat:
        raise ImportError_("Couldn't tell which platform this came from. Choose it in the 'From' box and upload again.")
    given = (parse_date(period_from), parse_date(period_to))
    found = _range_from_text(pre)
    # dates in the file win; the dates typed on the form only fill in when the file has none
    p_from, p_to = found or (given if given[0] and given[1] else (None, None))

    def cell(r, f):
        i = cols.get(f)
        return r[i].strip() if i is not None and i < len(r) else ""

    rows, skipped = [], 0
    for r in body:
        if not any(c.strip() for c in r):
            continue
        first = (r[0] if r else "").strip().lower()
        if first.startswith("total") or first in ("grand total", "totals"):
            skipped += 1
            continue
        d1 = parse_date(cell(r, "date")) if "date" in cols else None
        d2 = parse_date(cell(r, "date_end")) if "date_end" in cols else None
        rows.append((r, d1, d2 or d1))
    if not rows:
        raise ImportError_("The file has headings but no data rows.")
    ds = [d for _, a, b in rows for d in (a, b) if d]
    if ds:
        p_from, p_to = min(ds), max(ds)
    if not p_from:
        raise ImportError_("This file has no dates. Pick the date range the report covers and upload again.")
    rows = [(r, a or p_from, b or p_to) for r, a, b in rows]

    demo_dims = [f for f in DEMO_DIMS if f in cols]
    kind = "demographics" if demo_dims else ("ads" if plat in AD_PLATFORMS else "traffic")
    n = 0
    with db.tx() as c:
        if kind == "demographics":
            agg: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
            for r, a, b in rows:
                start, end = _month_bounds(a) if a == b else (a, b)
                vals = {k: _num(cell(r, k)) for k in ("impressions", "reach", "clicks", "spend", "conversions", "users", "sessions") if k in cols}
                seg = {f: cell(r, f) or "Unknown" for f in demo_dims}
                keys = [(f, seg[f]) for f in demo_dims]
                if "age" in seg and "gender" in seg:
                    keys.append(("age_gender", f"{seg['age']} · {seg['gender']}"))
                for dim, s in keys:
                    for k, v in vals.items():
                        agg[(dim, _clean_segment(dim, s), str(start), str(end))][k] += v
            sql, defaults = UPSERTS["demographics"]
            batch = [{**defaults, "client_id": client_id, "platform": plat, "dimension": dim, "segment": s, "date_from": a, "date_to": b,
                      "source": "upload", **{k: (int(v) if k in ("impressions", "reach", "clicks") else round(v, 2)) for k, v in vals.items()}}
                     for (dim, s, a, b), vals in agg.items()]
            c.executemany(sql, batch)
            n = len(batch)
        elif kind == "ads":
            if "spend" not in cols and "clicks" not in cols:
                raise ImportError_("No spend or clicks column found. Include Amount spent / Cost and Clicks in the export.")
            agg = defaultdict(lambda: defaultdict(float))
            for r, a, b in rows:
                camp = cell(r, "campaign") or "All campaigns"
                days = max(1, min((b - a).days + 1, 400))          # a row covering a period is spread evenly over its days
                for k in ("spend", "impressions", "clicks", "conversions", "revenue"):
                    for i, v in enumerate(_split(_num(cell(r, k)), days, 0 if k in ("impressions", "clicks") else 2)):
                        agg[(camp, str(date.fromordinal(a.toordinal() + i)))][k] += v
            sql, defaults = UPSERTS["ad_metrics"]
            batch = [{**defaults, "client_id": client_id, "platform": plat, "account_id": "upload", "campaign_id": "up:" + camp[:80],
                      "campaign_name": camp, "campaign_type": "", "date": day, "spend": round(v["spend"], 2), "impressions": int(v["impressions"]),
                      "clicks": int(v["clicks"]), "conversions": round(v["conversions"], 2), "revenue": round(v["revenue"], 2)}
                     for (camp, day), v in agg.items()]
            c.executemany(sql, batch)
            n = len(batch)
        else:
            if "date" not in cols:
                raise ImportError_("For website visitors, export by Date (daily) so the chart can show each day.")
            sql, defaults = UPSERTS["organic_metrics"]
            batch = []
            for r, d, _ in rows:
                for f, metric in (("sessions", "sessions"), ("users", "totalUsers"), ("conversions", "keyEvents"), ("revenue", "totalRevenue")):
                    if f in cols:
                        batch.append({**defaults, "client_id": client_id, "platform": "ga4", "dimension": "All (uploaded)", "metric": metric,
                                      "date": str(d), "value": _num(cell(r, f))})
            c.executemany(sql, batch)
            n = len(batch)
        c.execute("INSERT INTO imports (client_id, filename, kind, platform, rows, period_from, period_to, created_by) VALUES (?,?,?,?,?,?,?,?)",
                  (client_id, filename[:200], kind, plat, n, str(p_from), str(p_to), user))
    labels = {"demographics": "Audience (age, gender, location)", "ads": "Paid performance", "traffic": "Web & social"}
    return {"ok": True, "kind": kind, "platform": plat, "platform_label": PLATFORMS[plat], "rows": len(rows), "stored": n, "skipped": skipped,
            "period": [str(p_from), str(p_to)], "shows_in": labels[kind],
            "columns": {f: header[i] for f, i in cols.items()}}


def _split(total: float, parts: int, dp: int) -> list[float]:
    """Split a total into equal daily parts that add back up exactly (the rounding remainder goes on the last day)."""
    each = round(total / parts, dp) if dp else int(total // parts)
    vals = [each] * parts
    vals[-1] = round(total - each * (parts - 1), dp) if dp else int(total - each * (parts - 1))
    return vals


def _clean_segment(dim: str, s: str) -> str:
    s = s.strip()
    if dim == "gender":
        low = s.lower()
        return {"female": "Female", "women": "Female", "f": "Female", "male": "Male", "men": "Male", "m": "Male"}.get(low, s.title() if low != "unknown" else "Unknown")
    if dim == "age":
        return s.replace(" to ", "-").replace("–", "-")
    return s


def history(client_id: int) -> list[dict]:
    return db.rows("SELECT id, filename, kind, platform, rows, period_from, period_to, created_by, created_at FROM imports "
                   "WHERE client_id=? ORDER BY id DESC LIMIT 20", (client_id,))
