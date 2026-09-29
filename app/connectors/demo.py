"""Demo connector: realistic, deterministic synthetic data for any platform so the whole
site works before any developer app is approved. Connections flagged is_demo use it."""
from __future__ import annotations

import hashlib
import math
import random
from datetime import date, timedelta

from .base import Connector, SyncResult

PAID_PROFILE = {
    # platform: (campaign names, base daily spend, cpc, cvr, aov multiplier)
    "meta_ads": (["Prospecting – Broad", "Retargeting – 30d Visitors", "Advantage+ Shopping", "Lead Gen – Instant Form"], 180, 1.10, 0.028, 1.0),
    "google_ads": (["Search – Brand", "Search – Non-brand", "Performance Max", "YouTube – Awareness", "Shopping – Top Sellers"], 220, 2.40, 0.045, 1.15),
    "tiktok_ads": (["Spark Ads – UGC", "Smart+ Conversions"], 90, 0.55, 0.012, 0.8),
    "linkedin_ads": (["ABM – Decision Makers", "Lead Gen Forms – Webinar"], 110, 7.50, 0.020, 3.0),
    "x_ads": (["Promoted Posts – Launch"], 30, 0.90, 0.008, 0.9),
    "pinterest_ads": (["Shopping – Catalog", "Consideration – Pins"], 40, 0.70, 0.015, 1.0),
    "snapchat_ads": (["Story Ads – 18-24"], 35, 0.60, 0.009, 0.8),
    "reddit_ads": (["Community Targeting – Niche Subs"], 25, 0.80, 0.014, 1.0),
    "amazon_ads": (["Sponsored Products – Auto", "Sponsored Brands"], 70, 0.95, 0.045, 0.7),
}
ORGANIC_SOCIAL = ["facebook_page", "instagram", "tiktok_organic", "linkedin_page", "x_organic", "pinterest_organic", "youtube"]
SEO_QUERIES = {
    "ecommerce": ["buy running shoes online", "best trail running shoes", "running shoes melbourne", "wide fit running shoes",
                  "{brand}", "{brand} discount code", "how to choose running shoes", "marathon training plan", "gel running shoes sale"],
    "services": ["accountant near me", "tax return help", "small business accountant", "{brand}", "{brand} reviews",
                 "bookkeeping services", "how to lodge tax return", "gst registration", "business structure advice"],
    "b2b": ["project management software", "{brand} pricing", "{brand}", "best crm for agencies", "resource planning tool",
            "{brand} vs asana", "team capacity planning", "saas time tracking", "agency workflow software"],
}


def month_start_prev(d: date) -> date:
    """First day of the month before d's month."""
    first = d.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:12], 16))


class DemoConnector(Connector):
    implemented = True

    def __init__(self, account_id: str, credentials: dict, platform: str, client: dict):
        super().__init__(account_id, credentials)
        self.platform = platform
        self.client = client

    def fetch(self, start: date, end: date) -> SyncResult:
        p = self.platform
        if p in PAID_PROFILE:
            return self._paid(start, end)
        if p == "ga4":
            return self._ga4(start, end)
        if p in ("gsc", "dataforseo", "bing_webmaster"):
            return self._seo(start, end)
        if p in ("mailchimp", "klaviyo", "hubspot"):
            return self._email(start, end)
        if p in ORGANIC_SOCIAL or p == "google_business":
            return self._social(start, end)
        return SyncResult()

    # scale per client, so different clients look different
    def _scale(self) -> float:
        return 0.5 + _rng(self.client["id"], "scale").random() * 1.5

    def _budget_scale(self, base: float, n_campaigns: int) -> float:
        """Size daily spend so all of the client's paid platforms add up to its monthly budget."""
        budget = self.client.get("monthly_budget") or 0
        if not budget:
            return self._scale()
        from .. import db
        plats = [r["platform"] for r in db.rows("SELECT platform FROM connections WHERE client_id=?", (self.client["id"],)) if r["platform"] in PAID_PROFILE]
        weight = sum(PAID_PROFILE[p][1] * len(PAID_PROFILE[p][0]) for p in plats) or base * n_campaigns
        return budget / 30.4 / weight

    def _days(self, start, end):
        d = start
        while d <= end:
            yield d
            d += timedelta(days=1)

    def _paid(self, start, end) -> SyncResult:
        names, base, cpc, cvr, aovm = PAID_PROFILE[self.platform]
        # services/b2b "revenue" = assigned lead/pipeline value
        aov = {"ecommerce": 95, "services": 150, "b2b": 260}.get(self.client.get("industry") or "ecommerce", 120) * (aovm if self.client.get("industry") == "ecommerce" else 1)
        scale = self._budget_scale(base, len(names))
        out = SyncResult()
        today = date.today()
        for i, name in enumerate(names):
            cr = _rng(self.client["id"], self.platform, name)
            eff = 0.6 + cr.random() * 0.9           # campaign efficiency
            share = 0.5 + cr.random()
            # one campaign per client gets a recent CPA blow-out, so alerts have something to catch
            troubled = (i == 1 and _rng(self.client["id"], self.platform).random() < 0.45)
            for d in self._days(start, end):
                r = _rng(self.client["id"], self.platform, name, d)
                season = 1 + 0.18 * math.sin((d.timetuple().tm_yday / 365) * 2 * math.pi) + (0.12 if d.weekday() in (0, 1) else 0) - (0.1 if d.weekday() == 5 else 0)
                trend = 1 + (d - (today - timedelta(days=120))).days / 900
                spend = base * scale * share * season * trend * (0.85 + r.random() * 0.3)
                clicks = spend / (cpc * (0.85 + r.random() * 0.3))
                # diminishing returns on spend: cvr falls as spend rises
                c_rate = cvr * eff * (1.25 - 0.25 * min(2, spend / (base * scale)))
                if troubled and (today - d).days <= 4:
                    c_rate *= 0.35
                conv = max(0.0, clicks * c_rate * (0.7 + r.random() * 0.6))
                if name.endswith("– Brand"):
                    conv *= 1.8
                rev = conv * aov * (0.8 + r.random() * 0.4)
                impressions = clicks / (0.008 + r.random() * 0.02)
                out.ad_metrics.append(dict(account_id=self.account_id, campaign_id=f"{self.platform[:3]}-{i+1}",
                                           campaign_name=name, campaign_type="", date=str(d), spend=round(spend, 2),
                                           impressions=int(impressions), clicks=int(clicks), conversions=round(conv, 2),
                                           revenue=round(rev, 2)))
                out.engagement_metrics.append(self._engagement(f"{self.platform[:3]}-{i+1}", name, d, impressions, clicks, r))
        if self.platform in ("meta_ads", "google_ads") and not getattr(self, "_nodemo", False):
            dstart = min(start.replace(day=1), month_start_prev(end))
            rows = out.ad_metrics if dstart >= start else self._rows_between(dstart, end)
            out.demographics = self._demographics(rows, ("impressions", "clicks", "spend", "conversions"), self.platform, dstart)
        return out

    def _rows_between(self, start, end):
        self._nodemo = True
        try:
            return self._paid(start, end).ad_metrics
        finally:
            self._nodemo = False

    AGES = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
    REGIONS = ["Victoria", "New South Wales", "Queensland", "South Australia", "Western Australia"]
    CITIES = ["Bentleigh East", "Moorabbin", "Clayton", "Oakleigh", "Brighton", "Caulfield", "Glen Waverley", "Cheltenham"]

    def _demographics(self, rows: list[dict], metric_keys: tuple, platform: str, since: date | None = None) -> list[dict]:
        """Split monthly totals across age, gender and location with a per-client pattern (some groups cheaper than others)."""
        months: dict[str, dict] = {}
        for r in rows:
            m = months.setdefault(r["date"][:7], {k: 0.0 for k in metric_keys})
            for k in metric_keys:
                m[k] += r.get(k, 0) or 0
        pr = _rng(self.client["id"], platform, "demo-shape")
        age_w = [0.6 + pr.random() * 1.6 for _ in self.AGES]
        age_eff = [0.5 + pr.random() * 1.2 for _ in self.AGES]
        g_w, g_eff = {"Female": 0.8 + pr.random(), "Male": 0.6 + pr.random()}, {"Female": 0.7 + pr.random() * 0.8, "Male": 0.6 + pr.random() * 0.8}
        reg_w = [6.0, 1.2, 0.8, 0.4, 0.3]
        city_w = [0.5 + pr.random() * 2 for _ in self.CITIES]
        out = []
        for mon, tot in months.items():
            y, mo = int(mon[:4]), int(mon[5:])
            start = date(y, mo, 1)
            if since and start < since:
                continue                      # only whole months, so a partial month never overwrites a full one
            end = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1))

            def emit(dim, segs):
                wsum = sum(w for _, w, _ in segs)
                esum = sum(w * e for _, w, e in segs) or 1
                for seg, w, e in segs:
                    row = {"platform": platform, "dimension": dim, "segment": seg, "date_from": str(start), "date_to": str(end), "source": "demo"}
                    for k in metric_keys:
                        share = (w * e / esum) if k in ("conversions", "users_conv") else (w / wsum)
                        row[k] = round(tot[k] * share, 2) if k in ("spend", "conversions", "users", "sessions") else int(tot[k] * share)
                    out.append(row)
            emit("age", [(a, age_w[i], age_eff[i]) for i, a in enumerate(self.AGES)])
            emit("gender", [(g, g_w[g], g_eff[g]) for g in g_w])
            emit("age_gender", [(f"{a} · {g}", age_w[i] * g_w[g], age_eff[i] * g_eff[g]) for i, a in enumerate(self.AGES) for g in g_w])
            emit("region", [(rg, reg_w[i], 1.0) for i, rg in enumerate(self.REGIONS)])
            if platform == "ga4":
                emit("city", [(c, city_w[i], 1.0) for i, c in enumerate(self.CITIES)])
        return out

    VIDEO_HINTS = ("YouTube", "Spark", "UGC", "Story", "Smart+", "Awareness", "Promoted", "Advantage+", "Prospecting", "Lead Gen", "Consideration")

    def _engagement(self, cid, name, d, impressions, clicks, r) -> dict:
        search_like = self.platform in ("amazon_ads",) or name.startswith(("Search", "Shopping", "Sponsored"))
        freq = 1.3 + r.random() * 1.4
        reach = 0 if search_like else int(impressions / freq)
        video = not search_like and (self.platform in ("tiktok_ads", "snapchat_ads") or any(h in name for h in self.VIDEO_HINTS))
        views = int(impressions * (0.18 + r.random() * 0.22)) if video else 0
        avg_watch = {"tiktok_ads": 5.5, "snapchat_ads": 3.2, "google_ads": 17.0, "linkedin_ads": 9.0}.get(self.platform, 6.5) * (0.7 + r.random() * 0.6)
        completions = int(views * (0.08 + r.random() * 0.14))
        eng = 0 if search_like else int(clicks * (1.6 + r.random() * 2.4))
        return dict(account_id=self.account_id, campaign_id=cid, date=str(d), reach=reach, video_views=views,
                    video_watch_seconds=round(views * avg_watch, 1), video_completions=completions, engagements=eng,
                    shares=int(eng * 0.06), saves=int(eng * 0.09), comments=int(eng * 0.04))

    def _ga4(self, start, end) -> SyncResult:
        scale = self._scale()
        chans = {"Organic Search": 900, "Paid Search": 520, "Paid Social": 610, "Direct": 400, "Email": 150,
                 "Organic Social": 180, "Referral": 90}
        out = SyncResult()
        for d in self._days(start, end):
            for ch, base in chans.items():
                r = _rng(self.client["id"], "ga4", ch, d)
                s = base * scale * (0.85 + r.random() * 0.3) * (0.9 if d.weekday() >= 5 else 1.05)
                if ch == "Organic Search" and (date.today() - d).days <= 6 and _rng(self.client["id"], "seo-drop").random() < 0.5:
                    s *= 0.72
                ke = s * (0.018 + r.random() * 0.02)
                vals = {"sessions": s, "totalUsers": s * 0.82, "engagedSessions": s * 0.58, "keyEvents": ke,
                        "totalRevenue": ke * 110 * (0.8 + r.random() * 0.4)}
                for m, v in vals.items():
                    out.organic_metrics.append(dict(platform="ga4", dimension=ch, metric=m, date=str(d), value=round(v, 2)))
        if not getattr(self, "_nodemo", False):
            dstart = min(start.replace(day=1), month_start_prev(end))
            src = out.organic_metrics if dstart >= start else self._ga4_rows(dstart, end)
            daily: dict[str, dict] = {}
            for r in src:
                row = daily.setdefault(r["date"], {"date": r["date"], "users": 0.0, "sessions": 0.0, "conversions": 0.0})
                key = {"totalUsers": "users", "sessions": "sessions", "keyEvents": "conversions"}.get(r["metric"])
                if key:
                    row[key] += r["value"]
            out.demographics = self._demographics(list(daily.values()), ("users", "sessions", "conversions"), "ga4", dstart)
        return out

    def _ga4_rows(self, start, end):
        self._nodemo = True
        try:
            return self._ga4(start, end).organic_metrics
        finally:
            self._nodemo = False

    def _seo(self, start, end) -> SyncResult:
        brand = self.client["name"].split()[0].lower()
        qs = [q.replace("{brand}", brand) for q in SEO_QUERIES.get(self.client.get("industry") or "ecommerce", SEO_QUERIES["ecommerce"])]
        out = SyncResult()
        src = "rank" if self.platform == "dataforseo" else ("bing" if self.platform == "bing_webmaster" else "gsc")
        vol = 0.25 if src == "bing" else 1.0
        for qi, q in enumerate(qs):
            qr = _rng(self.client["id"], q)
            base_pos = 1.2 if brand in q else 3 + qr.random() * 18
            imp_base = (400 if brand in q else 150 + qr.random() * 2500) * vol
            dropped = qi == 2 and _rng(self.client["id"], "seo-drop").random() < 0.5
            for d in self._days(start, end):
                r = _rng(self.client["id"], q, d, src)
                pos = base_pos + (r.random() - 0.5) * 1.5 - (date.today() - d).days * 0.01
                if dropped and (date.today() - d).days <= 6:
                    pos += 7
                pos = max(1.0, pos)
                ctr = max(0.005, 0.32 * math.exp(-0.28 * (pos - 1)))
                imp = int(imp_base * (0.8 + r.random() * 0.4))
                out.seo_queries.append(dict(source=src, date=str(d), query=q, page=f"/{q.replace(' ', '-')[:30]}",
                                            clicks=0 if src == "rank" else int(imp * ctr), impressions=0 if src == "rank" else imp,
                                            position=round(pos, 1)))
        return out

    def _email(self, start, end) -> SyncResult:
        out = SyncResult()
        scale = self._scale()
        flows = ["Weekly Newsletter", "Promo – Mid-Season Sale", "Winback – 90d Lapsed", "New Arrivals"]
        for d in self._days(start, end):
            if d.weekday() not in (1, 4):
                continue
            r = _rng(self.client["id"], self.platform, d)
            name = flows[r.randrange(len(flows))]
            sends = int(12000 * scale * (0.9 + r.random() * 0.2))
            opens = int(sends * (0.32 + r.random() * 0.12))
            clicks = int(opens * (0.07 + r.random() * 0.06))
            conv = clicks * (0.03 + r.random() * 0.04)
            out.email_metrics.append(dict(platform=self.platform, campaign_id=f"em-{d}", campaign_name=f"{name} ({d:%d %b})",
                                          date=str(d), sends=sends, opens=opens, clicks=clicks, conversions=round(conv, 1),
                                          revenue=round(conv * 105, 2)))
        return out

    def _social(self, start, end) -> SyncResult:
        out = SyncResult()
        scale = self._scale()
        pr = _rng(self.client["id"], self.platform)
        followers = int((2000 + pr.random() * 40000) * scale)
        for d in self._days(start, end):
            r = _rng(self.client["id"], self.platform, d)
            age = (date.today() - d).days
            f = followers - age * (3 + pr.random() * 25)
            reach = f * (0.05 + r.random() * 0.25)
            eng = reach * (0.015 + r.random() * 0.05)
            vals = {"followers": f, "reach": reach, "engagements": eng, "posts": 1 if r.random() < 0.4 else 0}
            if self.platform == "google_business":       # a local business: a few calls and direction requests a day
                g = scale * (0.8 if d.weekday() >= 5 else 1.0) * (0.7 + r.random() * 0.6)
                vals = {"profile_views": 45 * g, "calls": 1.6 * g, "direction_requests": 2.4 * g, "website_clicks": 1.2 * g}
            for m, v in vals.items():
                out.organic_metrics.append(dict(platform=self.platform, dimension="", metric=m, date=str(d), value=round(v, 2)))
        return out
