"""Platform catalogue + connector registry."""
from __future__ import annotations

from .base import Connector, ConnectorError, SyncResult
from .demo import DemoConnector
from .other import GA4, DataForSEORank, Klaviyo, Mailchimp, SearchConsole
from .paid import GoogleAds, LinkedInAds, MetaAds, TikTokAds

LIVE = {c.platform: c for c in (MetaAds, GoogleAds, TikTokAds, LinkedInAds, GA4, SearchConsole, DataForSEORank, Mailchimp, Klaviyo)}

# (platform, label, category, auth, live?) — live=False means demo data only for now (roadmap connector)
CATALOG = [
    ("meta_ads", "Meta Ads (Facebook & Instagram)", "paid", "oauth"),
    ("google_ads", "Google Ads", "paid", "oauth"),
    ("tiktok_ads", "TikTok Ads", "paid", "oauth"),
    ("linkedin_ads", "LinkedIn Ads", "paid", "oauth"),
    ("x_ads", "X (Twitter) Ads", "paid", "oauth"),
    ("pinterest_ads", "Pinterest Ads", "paid", "oauth"),
    ("snapchat_ads", "Snapchat Ads", "paid", "oauth"),
    ("reddit_ads", "Reddit Ads", "paid", "oauth"),
    ("amazon_ads", "Amazon Ads", "paid", "oauth"),
    ("ga4", "Google Analytics 4", "analytics", "oauth"),
    ("gsc", "Google Search Console", "seo", "oauth"),
    ("bing_webmaster", "Bing Webmaster Tools", "seo", "api_key"),
    ("dataforseo", "Rank tracking (DataForSEO)", "seo", "api_key"),
    ("google_business", "Google Business Profile", "organic", "oauth"),
    ("facebook_page", "Facebook Page", "organic", "oauth"),
    ("instagram", "Instagram", "organic", "oauth"),
    ("tiktok_organic", "TikTok (organic)", "organic", "oauth"),
    ("linkedin_page", "LinkedIn Page", "organic", "oauth"),
    ("x_organic", "X (organic)", "organic", "oauth"),
    ("pinterest_organic", "Pinterest (organic)", "organic", "oauth"),
    ("youtube", "YouTube", "organic", "oauth"),
    ("mailchimp", "Mailchimp", "email", "api_key"),
    ("klaviyo", "Klaviyo", "email", "api_key"),
    ("hubspot", "HubSpot Marketing Email", "email", "oauth"),
]
PLATFORMS = {p: {"platform": p, "label": l, "category": c, "auth": a, "live": p in LIVE} for p, l, c, a in CATALOG}


def label(platform: str) -> str:
    return PLATFORMS.get(platform, {}).get("label", platform)


def build(connection: dict, credentials: dict, client: dict) -> Connector:
    p = connection["platform"]
    if connection.get("is_demo") or p not in LIVE:
        return DemoConnector(connection["account_id"], credentials, p, client)
    return LIVE[p](connection["account_id"], credentials)


__all__ = ["Connector", "ConnectorError", "SyncResult", "PLATFORMS", "LIVE", "build", "label"]
