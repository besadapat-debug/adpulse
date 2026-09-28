"""Runtime settings, read from environment variables (or a .env file)."""
from __future__ import annotations

import os
import re
from pathlib import Path


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = re.split(r"\s+#", v, maxsplit=1)[0]   # allow "KEY=value   # comment"
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


class Settings:
    APP_NAME = os.getenv("APP_NAME", "AdPulse")
    # Public address of this site. On Render it's picked up automatically (RENDER_EXTERNAL_URL).
    BASE_URL = (os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:8000").rstrip("/")
    # Postgres connection string (e.g. Supabase). When set, it's used instead of the SQLite file.
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(Path(__file__).resolve().parent.parent / "data" / "adpulse.db"))
    # 32 url-safe base64 bytes (Fernet key). Generate with:
    # python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    DEMO_MODE = _bool("DEMO_MODE", True)

    SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))
    # Platforms restate conversions for days/weeks after the event; re-pull this window every sync.
    TRAILING_WINDOW_DAYS = int(os.getenv("TRAILING_WINDOW_DAYS", "28"))
    BACKFILL_DAYS = int(os.getenv("BACKFILL_DAYS", "120"))
    EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "395"))

    # Notifications (optional)
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
    ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

    # --- Platform app credentials (each needs its own developer approval) ---
    META_APP_ID = os.getenv("META_APP_ID", "")
    META_APP_SECRET = os.getenv("META_APP_SECRET", "")
    META_API_VERSION = os.getenv("META_API_VERSION", "v21.0")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    GOOGLE_ADS_LOGIN_CUSTOMER_ID = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "")  # MCC id, digits only
    GOOGLE_ADS_API_VERSION = os.getenv("GOOGLE_ADS_API_VERSION", "v21")

    TIKTOK_APP_ID = os.getenv("TIKTOK_APP_ID", "")
    TIKTOK_APP_SECRET = os.getenv("TIKTOK_APP_SECRET", "")

    LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
    LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
    LINKEDIN_API_VERSION = os.getenv("LINKEDIN_API_VERSION", "202509")

    # API-key based (entered per client in the Connections screen, stored encrypted)
    # Klaviyo, Mailchimp, DataForSEO use keys rather than OAuth.


settings = Settings()
