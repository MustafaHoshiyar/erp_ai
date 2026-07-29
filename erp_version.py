import httpx
from runtime_config import get_client_runtime_config

_VERSION_CACHE = {}


def _get_headers(config: dict):
    return {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}


def get_cached_erp_version(client_id: str):
    return _VERSION_CACHE.get(client_id)


async def _detect_via_version_endpoint(config: dict) -> str | None:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{config['erp_url']}/api/method/smberp_ai.api.get_frappe_version",
                headers=_get_headers(config),
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                version_str = data.get("message", "")
                if version_str.startswith("15."):
                    return "15"
                if version_str.startswith("14."):
                    return "14"
        except Exception:
            pass
    return None


async def _detect_via_schema_probe(config: dict) -> str | None:
    probe_sql = (
        "SELECT COUNT(*) as cnt FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tabSerial and Batch Bundle'"
    )
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{config['erp_url']}/api/method/smberp_ai.api.run_ai_query",
                headers=_get_headers(config),
                json={"sql": probe_sql},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                message = data.get("message", [])
                if isinstance(message, list) and len(message) > 0:
                    cnt = message[0].get("cnt", 0)
                    return "15" if cnt > 0 else "14"
        except Exception:
            pass
    return None


async def get_erp_version(client_id: str = "DEMO_CLIENT_123") -> str | None:
    if client_id in _VERSION_CACHE:
        return _VERSION_CACHE[client_id]

    config = get_client_runtime_config(client_id)
    version = await _detect_via_version_endpoint(config)
    if version:
        _VERSION_CACHE[client_id] = version
        return version

    version = await _detect_via_schema_probe(config)
    if version:
        _VERSION_CACHE[client_id] = version
        return version

    _VERSION_CACHE[client_id] = None
    return None
