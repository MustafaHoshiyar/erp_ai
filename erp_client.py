import httpx
from urllib.parse import urlparse

from runtime_config import get_client_runtime_config


def _extract_erp_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        if data.get("exc"):
            return str(data["exc"])
        if data.get("exception"):
            return str(data["exception"])
        if isinstance(data.get("message"), dict):
            message = data["message"]
            if message.get("error"):
                return str(message["error"])
        if data.get("_server_messages"):
            return str(data["_server_messages"])
        if data.get("detail"):
            return str(data["detail"])

    text = response.text.strip()
    return text or response.reason_phrase or f"HTTP {response.status_code}"


def _get_headers(config: dict):
    return {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}


async def run_query(sql, client_id="DEMO_CLIENT_123"):
    config = get_client_runtime_config(client_id)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{config['erp_url']}/api/method/smberp_ai.api.run_ai_query",
            headers=_get_headers(config),
            json={"sql": sql},
            timeout=30.0,
        )

        if response.is_error:
            error_msg = _extract_erp_error_message(response)
            raise Exception(f"ERPNext SQL Error: {error_msg}")

        data = response.json()

        if isinstance(data, dict):
            if "exc" in data or "exception" in data:
                error_msg = data.get("exc") or data.get("exception")
                raise Exception(f"ERPNext SQL Error: {error_msg}")

            if "message" in data and isinstance(data["message"], dict) and "error" in data["message"]:
                raise Exception(f"ERPNext SQL Error: {data['message']['error']}")

        return data


async def get_app_name(client_id="DEMO_CLIENT_123"):
    """Fetches the App Name from ERPNext System Settings."""
    config = get_client_runtime_config(client_id)
    if config.get("app_name_override"):
        return config["app_name_override"]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{config['erp_url']}/api/resource/System Settings",
                headers=_get_headers(config),
                params={"fields": '["app_name"]'},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("data", {}).get("app_name")
    except Exception as e:
        print(f"[ERPClient] Failed to fetch app_name for {client_id}: {e}")

    return urlparse(config["erp_url"]).netloc or "ERP AI"


_CURRENCY_CACHE = {}
_CURRENCY_DECIMAL_MAP = {
    "KWD": 3,
}


async def get_default_currency_info(client_id="DEMO_CLIENT_123"):
    """Fetches the Default Currency code and symbol from ERPNext (with per-client caching)."""
    if client_id in _CURRENCY_CACHE:
        return _CURRENCY_CACHE[client_id]

    config = get_client_runtime_config(client_id)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{config['erp_url']}/api/resource/Company",
                headers=_get_headers(config),
                params={"fields": '["default_currency"]'},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                companies = data.get("data", [])
                if companies and companies[0].get("default_currency"):
                    currency_code = companies[0].get("default_currency")
                    decimal_places = _CURRENCY_DECIMAL_MAP.get(currency_code, 2)

                    sym_res = await client.get(
                        f"{config['erp_url']}/api/resource/Currency/{currency_code}",
                        headers=_get_headers(config),
                        params={"fields": '["symbol"]'},
                        timeout=10.0,
                    )
                    if sym_res.status_code == 200:
                        sym_data = sym_res.json()
                        symbol = sym_data.get("data", {}).get("symbol") or currency_code
                        symbol = symbol.strip().split()[0] if symbol else currency_code
                        _CURRENCY_CACHE[client_id] = {
                            "code": currency_code,
                            "symbol": symbol,
                            "decimal_places": decimal_places,
                        }
                        return _CURRENCY_CACHE[client_id]

                    _CURRENCY_CACHE[client_id] = {
                        "code": currency_code,
                        "symbol": currency_code,
                        "decimal_places": decimal_places,
                    }
                    return _CURRENCY_CACHE[client_id]
    except Exception as e:
        print(f"[ERPClient] Failed to fetch currency info for {client_id}: {e}")

    return {"code": "KWD", "symbol": "KD", "decimal_places": 3}
