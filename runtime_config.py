import os

from dotenv import load_dotenv

from database import ClientConfig, SessionLocal

load_dotenv()

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
        all_clients = db.query(ClientConfig).all()
        print(f"[ConfigDebug] Total clients in DB: {len(all_clients)}. IDs: {[c.client_id for c in all_clients]}")

        # Fuzzy lookup using strip to handle hidden database spaces
        target = client_id.strip()
        config = (
            db.query(ClientConfig)
            .filter(ClientConfig.client_id == target)
            .first()
        )
        # If not found directly, try stripping the DB side too
        if not config:
            print(f"[ConfigDebug] Direct lookup failed for '{target}' (len:{len(target)})")
            for c in all_clients:
                db_id = (c.client_id or "").strip()
                print(f"[ConfigDebug] Comparing target '{target}' (len:{len(target)}) vs DB ID '{db_id}' (len:{len(db_id)})")
                if db_id == target:
                    config = c
                    break

            if not config:
                print(f"[ConfigDebug] FAILED to find '{target}' in database after fuzzy search!")
                return {
                    **_fallback_config(client_id),
                    "debug_all_client_ids": [c.client_id for c in all_clients],
                    "debug_target_received": target,
                    "debug_target_len": len(target)
                }

        url = config.erp_url or ""
        if url and not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        result = {
            "client_id": client_id,
            "erp_url": url.rstrip("/"),
            "api_key": "Set" if config.api_key else "Missing",
            "api_secret": "Set" if config.api_secret else "Missing",
            "app_name_override": config.app_name_override,
            "source": "db",
            "debug_db_raw_url": config.erp_url,
            "debug_all_client_ids": [c.client_id for c in all_clients]
        }
        print(f"[ConfigDebug] SUCCESSFULLY found '{target}' in database. Logic: {result}")
        return result
    finally:
        db.close()


def sanitize_client_cache_key(client_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (client_id or "default"))
    return safe or "default"
