"""Paid media connectors: Meta, Google Ads, TikTok, LinkedIn."""
from __future__ import annotations

from datetime import date, timedelta

from ..config import settings
from ..oauth import refresh_if_needed
from .base import Connector, ConnectorError, SyncResult, demographic_months, merge_segments, month_end


def _chunks(start: date, end: date, days: int):
    cur = start
    while cur <= end:
        stop = min(end, cur + timedelta(days=days - 1))
        yield cur, stop
        cur = stop + timedelta(days=1)


class MetaAds(Connector):
    platform, label, category = "meta_ads", "Meta Ads (Facebook & Instagram)", "paid"
    account_hint = "Ad account id, digits only (act_ prefix optional)"

    def fetch(self, start: date, end: date) -> SyncResult:
        acct = self.account_id if self.account_id.startswith("act_") else f"act_{self.account_id}"
        conv_types = set(self.creds.get("conversion_action_types") or ["purchase", "lead"])
        rev_types = set(self.creds.get("revenue_action_types") or ["purchase"])
        url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{acct}/insights"
        params = {
            "access_token": self.creds["access_token"],
            "level": "campaign",
            "time_increment": 1,
            "fields": ("campaign_id,campaign_name,objective,spend,impressions,clicks,actions,action_values,reach,inline_post_engagement,"
                       "video_play_actions,video_thruplay_watched_actions,video_avg_time_watched_actions,video_p100_watched_actions"),
            "time_range": f'{{"since":"{start}","until":"{end}"}}',
            "limit": 500,
        }
        out = SyncResult()
        with self.http() as h:
            body = self.check(h.get(url, params=params))
            while True:
                for r in body.get("data", []):
                    conv = sum(float(a["value"]) for a in r.get("actions", []) if a["action_type"] in conv_types)
                    rev = sum(float(a["value"]) for a in r.get("action_values", []) if a["action_type"] in rev_types)
                    out.ad_metrics.append(dict(
                        account_id=self.account_id, campaign_id=r["campaign_id"], campaign_name=r.get("campaign_name"),
                        campaign_type=r.get("objective", ""), date=r["date_start"], spend=float(r.get("spend", 0)),
                        impressions=int(r.get("impressions", 0)), clicks=int(r.get("clicks", 0)),
                        conversions=conv, revenue=rev))
                    out.engagement_metrics.append(self._engagement(r))
                nxt = body.get("paging", {}).get("next")
                if not nxt:
                    break
                body = self.check(h.get(nxt))
            try:
                out.demographics = self._demographics(h, url, end, conv_types)
            except Exception:
                pass          # breakdowns are extra; never fail the core spend sync over them
        return out

    def _demographics(self, h, url: str, end: date, conv_types: set) -> list[dict]:
        """Age, gender and region breakdowns per calendar month (group totals from Meta, never individuals)."""
        rows = []
        for m_start, m_end in demographic_months(end):
            for breakdown, dims in (("age,gender", ("age", "gender")), ("region", ("region",))):
                body = self.check(h.get(url, params={
                    "access_token": self.creds["access_token"], "level": "account", "breakdowns": breakdown,
                    "fields": "spend,impressions,reach,clicks,actions", "limit": 500,
                    "time_range": f'{{"since":"{m_start}","until":"{m_end}"}}'}))
                for r in body.get("data", []):
                    vals = {"spend": float(r.get("spend", 0) or 0), "impressions": int(r.get("impressions", 0) or 0),
                            "reach": int(r.get("reach", 0) or 0), "clicks": int(r.get("clicks", 0) or 0),
                            "conversions": sum(float(a["value"]) for a in r.get("actions", []) if a["action_type"] in conv_types)}
                    segs = [(d, r.get(d, "Unknown")) for d in dims]
                    if len(dims) == 2:
                        segs.append(("age_gender", f"{r.get('age', 'Unknown')} · {str(r.get('gender', 'unknown')).title()}"))
                    for dim, seg in segs:
                        seg = str(seg).title() if dim == "gender" else str(seg)
                        rows.append({"dimension": dim, "segment": seg, "date_from": str(m_start),
                                     "date_to": str(month_end(m_start)),
                                     "source": "api", **vals})
        return merge_segments(rows)


    def _engagement(self, r: dict) -> dict:
        def act(field, kind=None):
            vals = r.get(field) or []
            return sum(float(a.get("value", 0)) for a in vals if kind is None or a.get("action_type") == kind)
        acts = {a["action_type"]: float(a["value"]) for a in r.get("actions", [])}
        plays = act("video_play_actions")
        avg = act("video_avg_time_watched_actions")          # seconds per play
        return dict(account_id=self.account_id, campaign_id=r["campaign_id"], date=r["date_start"],
                    reach=int(r.get("reach", 0) or 0), video_views=int(plays), video_watch_seconds=avg * plays,
                    video_completions=int(act("video_thruplay_watched_actions") or act("video_p100_watched_actions")),
                    engagements=int(float(r.get("inline_post_engagement", 0) or 0)),
                    shares=int(acts.get("post", 0)), saves=int(acts.get("onsite_conversion.post_save", 0)), comments=int(acts.get("comment", 0)))


class GoogleAds(Connector):
    platform, label, category = "google_ads", "Google Ads (Search, PMax, YouTube, Shopping, Display)", "paid"
    account_hint = "Customer id, digits only (e.g. 1234567890)"

    def fetch(self, start: date, end: date) -> SyncResult:
        creds = refresh_if_needed("google", self.creds)
        out = SyncResult(updated_credentials=creds)
        creds = creds or self.creds
        cid = self.account_id.replace("-", "")
        url = f"https://googleads.googleapis.com/{settings.GOOGLE_ADS_API_VERSION}/customers/{cid}/googleAds:searchStream"
        # Since Sept 2026 Google Ads API access is granted to the Google Cloud project; a developer token is ignored if sent.
        headers = {"Authorization": f"Bearer {creds['access_token']}"}
        if settings.GOOGLE_ADS_DEVELOPER_TOKEN:
            headers["developer-token"] = settings.GOOGLE_ADS_DEVELOPER_TOKEN
        if settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID:
            headers["login-customer-id"] = settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID.replace("-", "")
        query = (
            "SELECT campaign.id, campaign.name, campaign.advertising_channel_type, segments.date, "
            "metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, metrics.conversions_value "
            f"FROM campaign WHERE segments.date BETWEEN '{start}' AND '{end}'"
        )
        with self.http() as h:
            resp = h.post(url, headers=headers, json={"query": query})
            if resp.status_code >= 400:
                raise ConnectorError(f"{resp.status_code}: {resp.text[:400]}")
            for batch in resp.json():
                for r in batch.get("results", []):
                    c, m, s = r["campaign"], r.get("metrics", {}), r["segments"]
                    out.ad_metrics.append(dict(
                        account_id=self.account_id, campaign_id=str(c["id"]), campaign_name=c.get("name"),
                        campaign_type=c.get("advertisingChannelType", ""), date=s["date"],
                        spend=int(m.get("costMicros", 0)) / 1e6, impressions=int(m.get("impressions", 0)),
                        clicks=int(m.get("clicks", 0)), conversions=float(m.get("conversions", 0)),
                        revenue=float(m.get("conversionsValue", 0))))
            try:
                eq = ("SELECT campaign.id, segments.date, metrics.engagements, metrics.video_trueview_views, metrics.video_quartile_p100_rate "
                      f"FROM campaign WHERE segments.date BETWEEN '{start}' AND '{end}'")
                er = h.post(url, headers=headers, json={"query": eq})
                if er.status_code < 400:
                    for batch in er.json():
                        for r in batch.get("results", []):
                            m = r.get("metrics", {})
                            views = int(m.get("videoTrueviewViews", 0) or 0)
                            out.engagement_metrics.append(dict(
                                account_id=self.account_id, campaign_id=str(r["campaign"]["id"]), date=r["segments"]["date"],
                                video_views=views, video_completions=int(views * float(m.get("videoQuartileP100Rate", 0) or 0)),
                                engagements=int(m.get("engagements", 0) or 0)))
            except Exception:
                pass  # engagement is optional; never fail the core spend sync over it
            try:
                out.demographics = self._demographics(h, url, headers, end)
            except Exception:
                pass
        return out

    AGE = {"AGE_RANGE_18_24": "18-24", "AGE_RANGE_25_34": "25-34", "AGE_RANGE_35_44": "35-44", "AGE_RANGE_45_54": "45-54",
           "AGE_RANGE_55_64": "55-64", "AGE_RANGE_65_UP": "65+"}

    def _demographics(self, h, url, headers, end: date) -> list[dict]:
        rows = []
        m0 = demographic_months(end)[0][0]
        for view, field, fmtseg, dim in (("age_range_view", "ad_group_criterion.age_range.type", lambda v: self.AGE.get(v, "Unknown"), "age"),
                                         ("gender_view", "ad_group_criterion.gender.type", lambda v: {"FEMALE": "Female", "MALE": "Male"}.get(v, "Unknown"), "gender")):
            q = (f"SELECT {field}, segments.month, metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions "
                 f"FROM {view} WHERE segments.date BETWEEN '{m0}' AND '{end}'")
            resp = h.post(url, headers=headers, json={"query": q})
            if resp.status_code >= 400:
                continue
            for batch in resp.json():
                for r in batch.get("results", []):
                    crit = r.get("adGroupCriterion", {})
                    raw = (crit.get("ageRange") or crit.get("gender") or {}).get("type", "")
                    m = r.get("metrics", {})
                    ms = date.fromisoformat(r["segments"]["month"])
                    rows.append({"dimension": dim, "segment": fmtseg(raw), "date_from": str(ms), "date_to": str(month_end(ms)), "source": "api",
                                 "spend": int(m.get("costMicros", 0)) / 1e6, "impressions": int(m.get("impressions", 0)),
                                 "clicks": int(m.get("clicks", 0)), "conversions": float(m.get("conversions", 0))})
        return merge_segments(rows)


class TikTokAds(Connector):
    platform, label, category = "tiktok_ads", "TikTok Ads", "paid"
    account_hint = "Advertiser id"

    def fetch(self, start: date, end: date) -> SyncResult:
        import json
        out = SyncResult()
        url = "https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/"
        headers = {"Access-Token": self.creds["access_token"]}
        with self.http() as h:
            # daily breakdowns are limited to ~30-day ranges per request
            for s, e in _chunks(start, end, 30):
                page = 1
                while True:
                    params = {
                        "advertiser_id": self.account_id, "report_type": "BASIC", "data_level": "AUCTION_CAMPAIGN",
                        "dimensions": json.dumps(["campaign_id", "stat_time_day"]),
                        "metrics": json.dumps(["campaign_name", "spend", "impressions", "clicks", "conversion", "complete_payment_roas", "reach",
                                               "video_play_actions", "average_video_play", "video_views_p100", "engagements", "likes",
                                               "comments", "shares"]),
                        "start_date": str(s), "end_date": str(e), "page": page, "page_size": 1000,
                    }
                    body = self.check(h.get(url, headers=headers, params=params))
                    if body.get("code") != 0:
                        raise ConnectorError(body.get("message", "TikTok API error"))
                    data = body["data"]
                    for r in data.get("list", []):
                        d, m = r["dimensions"], r["metrics"]
                        spend = float(m.get("spend", 0) or 0)
                        out.ad_metrics.append(dict(
                            account_id=self.account_id, campaign_id=str(d["campaign_id"]), campaign_name=m.get("campaign_name"),
                            date=d["stat_time_day"][:10], spend=spend, impressions=int(float(m.get("impressions", 0) or 0)),
                            clicks=int(float(m.get("clicks", 0) or 0)), conversions=float(m.get("conversion", 0) or 0),
                            revenue=spend * float(m.get("complete_payment_roas", 0) or 0)))
                        num = lambda k: float(m.get(k, 0) or 0)  # noqa: E731
                        out.engagement_metrics.append(dict(
                            account_id=self.account_id, campaign_id=str(d["campaign_id"]), date=d["stat_time_day"][:10],
                            reach=int(num("reach")), video_views=int(num("video_play_actions")),
                            video_watch_seconds=num("average_video_play") * num("video_play_actions"),
                            video_completions=int(num("video_views_p100")), engagements=int(num("engagements")),
                            shares=int(num("shares")), comments=int(num("comments"))))
                    info = data.get("page_info", {})
                    if page >= info.get("total_page", 1):
                        break
                    page += 1
        return out


class LinkedInAds(Connector):
    platform, label, category = "linkedin_ads", "LinkedIn Ads", "paid"
    account_hint = "Sponsored ad account id (digits)"

    def fetch(self, start: date, end: date) -> SyncResult:
        creds = refresh_if_needed("linkedin", self.creds)
        out = SyncResult(updated_credentials=creds)
        creds = creds or self.creds
        headers = {"Authorization": f"Bearer {creds['access_token']}", "LinkedIn-Version": settings.LINKEDIN_API_VERSION,
                   "X-Restli-Protocol-Version": "2.0.0"}
        rng = (f"(start:(year:{start.year},month:{start.month},day:{start.day}),"
               f"end:(year:{end.year},month:{end.month},day:{end.day}))")
        fields = "dateRange,pivotValues,costInLocalCurrency,impressions,clicks,externalWebsiteConversions,conversionValueInLocalCurrency"
        # Rest.li syntax must not be percent-encoded, so the query string is assembled by hand.
        url = ("https://api.linkedin.com/rest/adAnalytics?q=analytics&pivot=CAMPAIGN&timeGranularity=DAILY"
               f"&dateRange={rng}&accounts=List(urn%3Ali%3AsponsoredAccount%3A{self.account_id})&fields={fields}")
        with self.http() as h:
            body = self.check(h.get(url, headers=headers))
            names = self._campaign_names(h, headers)
            for r in body.get("elements", []):
                d = r["dateRange"]["start"]
                urn = r["pivotValues"][0]
                cid = urn.rsplit(":", 1)[-1]
                out.ad_metrics.append(dict(
                    account_id=self.account_id, campaign_id=cid, campaign_name=names.get(cid, urn),
                    date=f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}",
                    spend=float(r.get("costInLocalCurrency", 0) or 0), impressions=int(r.get("impressions", 0)),
                    clicks=int(r.get("clicks", 0)), conversions=float(r.get("externalWebsiteConversions", 0)),
                    revenue=float(r.get("conversionValueInLocalCurrency", 0) or 0)))
            try:
                ef = "dateRange,pivotValues,approximateMemberReach,videoViews,videoCompletions,totalEngagements,shares,comments"
                er = h.get(url.split("&fields=")[0] + f"&fields={ef}", headers=headers)
                if er.status_code < 400:
                    for r in er.json().get("elements", []):
                        d = r["dateRange"]["start"]
                        out.engagement_metrics.append(dict(
                            account_id=self.account_id, campaign_id=r["pivotValues"][0].rsplit(":", 1)[-1],
                            date=f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}", reach=int(r.get("approximateMemberReach", 0) or 0),
                            video_views=int(r.get("videoViews", 0) or 0), video_completions=int(r.get("videoCompletions", 0) or 0),
                            engagements=int(r.get("totalEngagements", 0) or 0), shares=int(r.get("shares", 0) or 0),
                            comments=int(r.get("comments", 0) or 0)))
            except Exception:
                pass
        return out

    def _campaign_names(self, h, headers) -> dict:
        try:
            r = h.get(f"https://api.linkedin.com/rest/adAccounts/{self.account_id}/adCampaigns?q=search&pageSize=1000", headers=headers)
            return {str(e["id"]): e.get("name", "") for e in r.json().get("elements", [])}
        except Exception:
            return {}
