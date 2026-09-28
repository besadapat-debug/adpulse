"""Analytics, SEO and email connectors: GA4, Search Console, DataForSEO rank tracking,
Mailchimp, Klaviyo."""
from __future__ import annotations

from datetime import date
from urllib.parse import quote

from ..oauth import refresh_if_needed
from .base import Connector, ConnectorError, SyncResult


class GA4(Connector):
    platform, label, category = "ga4", "Google Analytics 4", "analytics"
    account_hint = "GA4 property id (digits)"

    def fetch(self, start: date, end: date) -> SyncResult:
        creds = refresh_if_needed("google", self.creds)
        out = SyncResult(updated_credentials=creds)
        creds = creds or self.creds
        url = f"https://analyticsdata.googleapis.com/v1beta/properties/{self.account_id}:runReport"
        headers = {"Authorization": f"Bearer {creds['access_token']}"}
        metrics = ["sessions", "totalUsers", "engagedSessions", "keyEvents", "totalRevenue"]
        offset = 0
        with self.http() as h:
            while True:
                body = self.check(h.post(url, headers=headers, json={
                    "dateRanges": [{"startDate": str(start), "endDate": str(end)}],
                    "dimensions": [{"name": "date"}, {"name": "sessionDefaultChannelGroup"}],
                    "metrics": [{"name": m} for m in metrics],
                    "limit": 10000, "offset": offset}))
                rows = body.get("rows", [])
                for r in rows:
                    d = r["dimensionValues"][0]["value"]
                    d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                    ch = r["dimensionValues"][1]["value"]
                    for i, m in enumerate(metrics):
                        out.organic_metrics.append(dict(platform="ga4", dimension=ch, metric=m, date=d,
                                                        value=float(r["metricValues"][i]["value"] or 0)))
                offset += len(rows)
                if not rows or offset >= int(body.get("rowCount", 0)):
                    break
        return out


class SearchConsole(Connector):
    platform, label, category = "gsc", "Google Search Console", "seo"
    account_hint = "Property, e.g. sc-domain:example.com or https://www.example.com/"

    def fetch(self, start: date, end: date) -> SyncResult:
        creds = refresh_if_needed("google", self.creds)
        out = SyncResult(updated_credentials=creds)
        creds = creds or self.creds
        url = f"https://www.googleapis.com/webmasters/v3/sites/{quote(self.account_id, safe='')}/searchAnalytics/query"
        headers = {"Authorization": f"Bearer {creds['access_token']}"}
        start_row = 0
        with self.http() as h:
            while True:
                body = self.check(h.post(url, headers=headers, json={
                    "startDate": str(start), "endDate": str(end), "dimensions": ["date", "query", "page"],
                    "rowLimit": 25000, "startRow": start_row}))
                rows = body.get("rows", [])
                for r in rows:
                    d, q, p = r["keys"]
                    out.seo_queries.append(dict(source="gsc", date=d, query=q, page=p, clicks=int(r["clicks"]),
                                                impressions=int(r["impressions"]), position=float(r["position"])))
                if len(rows) < 25000:
                    break
                start_row += 25000
        return out


class DataForSEORank(Connector):
    """Daily rank tracking for a keyword list (much cheaper than Ahrefs/Semrush APIs)."""
    platform, label, category, auth = "dataforseo", "Rank tracking (DataForSEO)", "seo", "api_key"
    account_hint = "Your domain, e.g. example.com.au"

    def fetch(self, start: date, end: date) -> SyncResult:
        out = SyncResult()
        keywords = [k.strip() for k in self.creds.get("keywords", "").split(",") if k.strip()]
        if not keywords:
            return out
        loc = int(self.creds.get("location_code", 2036))  # 2036 = Australia
        tasks = [{"keyword": k, "location_code": loc, "language_code": self.creds.get("language_code", "en"), "depth": 100}
                 for k in keywords]
        with self.http() as h:
            body = self.check(h.post("https://api.dataforseo.com/v3/serp/google/organic/live/regular",
                                     auth=(self.creds["login"], self.creds["password"]), json=tasks))
        today = str(date.today())
        domain = self.account_id.lower().replace("https://", "").replace("http://", "").strip("/")
        for t in body.get("tasks", []):
            kw = t.get("data", {}).get("keyword", "")
            pos = 101.0
            url = ""
            for res in (t.get("result") or []):
                for item in res.get("items") or []:
                    if item.get("type") == "organic" and domain in (item.get("domain") or ""):
                        pos, url = float(item["rank_group"]), item.get("url", "")
                        break
            out.seo_queries.append(dict(source="rank", date=today, query=kw, page=url, clicks=0, impressions=0, position=pos))
        return out


class Mailchimp(Connector):
    platform, label, category, auth = "mailchimp", "Mailchimp", "email", "api_key"
    account_hint = "Account name (any label)"

    def fetch(self, start: date, end: date) -> SyncResult:
        out = SyncResult()
        key = self.creds["api_key"]
        dc = key.rsplit("-", 1)[-1]
        with self.http() as h:
            off = 0
            while True:
                body = self.check(h.get(f"https://{dc}.api.mailchimp.com/3.0/reports", auth=("anystring", key), params={
                    "since_send_time": f"{start}T00:00:00+00:00", "before_send_time": f"{end}T23:59:59+00:00",
                    "count": 200, "offset": off}))
                reps = body.get("reports", [])
                for r in reps:
                    ec = r.get("ecommerce", {}) or {}
                    out.email_metrics.append(dict(
                        platform="mailchimp", campaign_id=r["id"], campaign_name=r.get("campaign_title") or r.get("subject_line"),
                        date=r["send_time"][:10], sends=int(r.get("emails_sent", 0)),
                        opens=int((r.get("opens") or {}).get("unique_opens", 0)),
                        clicks=int((r.get("clicks") or {}).get("unique_subscriber_clicks", 0)),
                        conversions=float(ec.get("total_orders", 0)), revenue=float(ec.get("total_revenue", 0))))
                off += len(reps)
                if not reps or off >= body.get("total_items", 0):
                    break
        return out


class Klaviyo(Connector):
    platform, label, category, auth = "klaviyo", "Klaviyo", "email", "api_key"
    account_hint = "Account name (any label)"
    REVISION = "2024-10-15"

    def fetch(self, start: date, end: date) -> SyncResult:
        out = SyncResult()
        headers = {"Authorization": f"Klaviyo-API-Key {self.creds['api_key']}", "revision": self.REVISION,
                   "accept": "application/vnd.api+json", "content-type": "application/vnd.api+json"}
        metric_id = self.creds.get("conversion_metric_id")
        with self.http() as h:
            if not metric_id:
                ms = self.check(h.get("https://a.klaviyo.com/api/metrics/", headers=headers))
                metric_id = next((m["id"] for m in ms.get("data", []) if m["attributes"]["name"] == "Placed Order"), None)
                if not metric_id:
                    raise ConnectorError("No 'Placed Order' metric found; set conversion_metric_id in credentials")
            body = self.check(h.post("https://a.klaviyo.com/api/campaign-values-reports/", headers=headers, json={"data": {
                "type": "campaign-values-report", "attributes": {
                    "statistics": ["recipients", "opens_unique", "clicks_unique", "conversions", "conversion_value"],
                    "timeframe": {"start": f"{start}T00:00:00Z", "end": f"{end}T23:59:59Z"},
                    "conversion_metric_id": metric_id}}}))
            for r in body["data"]["attributes"].get("results", []):
                cid = r["groupings"]["campaign_id"]
                st = r["statistics"]
                name, sent = cid, str(start)
                try:
                    c = h.get(f"https://a.klaviyo.com/api/campaigns/{cid}/", headers=headers).json()["data"]["attributes"]
                    name = c.get("name", cid)
                    sent = (c.get("send_time") or c.get("scheduled_at") or str(start))[:10]
                except Exception:
                    pass
                out.email_metrics.append(dict(platform="klaviyo", campaign_id=cid, campaign_name=name, date=sent,
                                              sends=int(st.get("recipients", 0)), opens=int(st.get("opens_unique", 0)),
                                              clicks=int(st.get("clicks_unique", 0)), conversions=float(st.get("conversions", 0)),
                                              revenue=float(st.get("conversion_value", 0))))
        return out

