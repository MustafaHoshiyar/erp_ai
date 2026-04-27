import os

from dotenv import load_dotenv

from database import ClientConfig, SessionLocal

load_dotenv(override=True)

DEFAULT_ERP_URL = os.getenv("ERP_URL", "").rstrip("/")
DEFAULT_ERP_API_KEY = os.getenv("ERP_API_KEY", "")
DEFAULT_ERP_API_SECRET = os.getenv("ERP_API_SECRET", "")
DEFAULT_APP_NAME = os.getenv("ERP_APP_NAME", "")


def _fallback_config(client_id: str):
    return {
        "client_id": client_id,
        "erp_url": DEFAULT_ERP_URL,
        "api_key": DEFAULT_ERP_API_KEY,
        "api_secret": DEFAULT_ERP_API_SECRET,
        "app_name_override": DEFAULT_APP_NAME or None,
        "source": "env_fallback",
    }


def get_client_runtime_config(client_id: str = "DEMO_CLIENT_123"):
    db = SessionLocal()
    try:
        config = (
            db.query(ClientConfig)
            .filter(ClientConfig.client_id == client_id, ClientConfig.is_active == True)
            .first()
        )
        if not config:
            return _fallback_config(client_id)

        return {
            "client_id": client_id,
            "erp_url": (config.erp_url or "").rstrip("/"),
            "api_key": config.api_key,
            "api_secret": config.api_secret,
            "app_name_override": config.app_name_override,
            "source": "db",
        }
    finally:
        db.close()


def sanitize_client_cache_key(client_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (client_id or "default"))
    return safe or "default"
