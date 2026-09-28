"""OAuth 2.0 flows for the platforms that use it. Each provider needs an approved
developer app; credentials come from environment variables (see .env.example)."""
from __future__ import annotations

import time
from urllib.parse import urlencode

import httpx

from .config import settings

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "client_id": lambda: settings.GOOGLE_CLIENT_ID,
        "client_secret": lambda: settings.GOOGLE_CLIENT_SECRET,
        "scope": " ".join([
            "https://www.googleapis.com/auth/adwords",
            "https://www.googleapis.com/auth/analytics.readonly",
            "https://www.googleapis.com/auth/webmasters.readonly",
            "https://www.googleapis.com/auth/business.manage",
        ]),
        "extra": {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
    },
    "meta": {
        "authorize": f"https://www.facebook.com/{settings.META_API_VERSION}/dialog/oauth",
        "token": f"https://graph.facebook.com/{settings.META_API_VERSION}/oauth/access_token",
        "client_id": lambda: settings.META_APP_ID,
        "client_secret": lambda: settings.META_APP_SECRET,
        "scope": "ads_read,ads_management,business_management,read_insights,instagram_basic,instagram_manage_insights,pages_read_engagement",
        "extra": {},
    },
    "tiktok": {
        # TikTok Marketing API uses its own authorize page + auth_code exchange
        "authorize": "https://business-api.tiktok.com/portal/auth",
        "token": "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
        "client_id": lambda: settings.TIKTOK_APP_ID,
        "client_secret": lambda: settings.TIKTOK_APP_SECRET,
        "scope": "",
        "extra": {},
    },
    "linkedin": {
        "authorize": "https://www.linkedin.com/oauth/v2/authorization",
        "token": "https://www.linkedin.com/oauth/v2/accessToken",
        "client_id": lambda: settings.LINKEDIN_CLIENT_ID,
        "client_secret": lambda: settings.LINKEDIN_CLIENT_SECRET,
        "scope": "r_ads r_ads_reporting rw_dmp_segments r_organization_social",
        "extra": {},
    },
}

# which OAuth provider each platform connector authenticates through
PLATFORM_PROVIDER = {
    "google_ads": "google", "ga4": "google", "gsc": "google", "google_business": "google",
    "meta_ads": "meta", "facebook_page": "meta", "instagram": "meta",
    "tiktok_ads": "tiktok",
    "linkedin_ads": "linkedin",
}


def redirect_uri(provider: str) -> str:
    return f"{settings.BASE_URL}/oauth/{provider}/callback"


def is_configured(provider: str) -> bool:
    p = PROVIDERS[provider]
    return bool(p["client_id"]() and p["client_secret"]())


def authorize_url(provider: str, state: str) -> str:
    p = PROVIDERS[provider]
    if provider == "tiktok":
        return p["authorize"] + "?" + urlencode({"app_id": p["client_id"](), "state": state, "redirect_uri": redirect_uri(provider)})
    q = {"client_id": p["client_id"](), "redirect_uri": redirect_uri(provider), "response_type": "code", "state": state}
    if p["scope"]:
        q["scope"] = p["scope"]
    q.update(p["extra"])
    return p["authorize"] + "?" + urlencode(q)


def exchange_code(provider: str, code: str) -> dict:
    p = PROVIDERS[provider]
    with httpx.Client(timeout=30) as h:
        if provider == "tiktok":
            r = h.post(p["token"], json={"app_id": p["client_id"](), "secret": p["client_secret"](), "auth_code": code})
            body = r.json()
            if body.get("code") != 0:
                raise RuntimeError(body.get("message", "TikTok token exchange failed"))
            d = body["data"]
            return {"access_token": d["access_token"], "advertiser_ids": d.get("advertiser_ids", [])}
        r = h.post(p["token"], data={
            "client_id": p["client_id"](), "client_secret": p["client_secret"](), "code": code,
            "redirect_uri": redirect_uri(provider), "grant_type": "authorization_code",
        })
        if r.status_code >= 400:
            raise RuntimeError(f"Token exchange failed: {r.text[:300]}")
        tok = r.json()
        if provider == "meta":
            # swap the short-lived token for a ~60-day long-lived token
            r2 = h.get(p["token"], params={"grant_type": "fb_exchange_token", "client_id": p["client_id"](),
                                           "client_secret": p["client_secret"](), "fb_exchange_token": tok["access_token"]})
            if r2.status_code < 400:
                tok = r2.json()
        if "expires_in" in tok:
            tok["expires_at"] = int(time.time()) + int(tok["expires_in"]) - 60
        return tok


def refresh_if_needed(provider: str, creds: dict) -> dict | None:
    """Return updated credentials if a refresh happened, else None."""
    if provider not in ("google", "linkedin") or not creds.get("refresh_token"):
        return None
    if creds.get("expires_at", 0) > time.time() + 120:
        return None
    p = PROVIDERS[provider]
    with httpx.Client(timeout=30) as h:
        r = h.post(p["token"], data={"client_id": p["client_id"](), "client_secret": p["client_secret"](),
                                     "refresh_token": creds["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code >= 400:
        raise RuntimeError(f"Token refresh failed ({provider}): {r.text[:300]}")
    new = r.json()
    out = dict(creds, access_token=new["access_token"])
    if "refresh_token" in new:
        out["refresh_token"] = new["refresh_token"]
    out["expires_at"] = int(time.time()) + int(new.get("expires_in", 3600)) - 60
    return out
