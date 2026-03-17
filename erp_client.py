import os
import httpx
from dotenv import load_dotenv

load_dotenv()

ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")


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

async def run_query(sql):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{ERP_URL}/api/method/smberp_ai.api.run_ai_query",
            headers={
                "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"
            },
            json={"sql": sql},
            timeout=30.0
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

async def get_app_name():
    """Fetches the App Name from ERPNext System Settings."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ERP_URL}/api/resource/System Settings",
                headers={
                    "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"
                },
                params={"fields": '["app_name"]'},
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("data", {}).get("app_name")
    except Exception as e:
        print(f"[ERPClient] Failed to fetch app_name: {e}")
    
    from urllib.parse import urlparse
    return urlparse(ERP_URL).netloc or "ERP AI"

_CURRENCY_CACHE = None
_CURRENCY_DECIMAL_MAP = {
    "KWD": 3,
}

async def get_default_currency_info():
    """Fetches the Default Currency code and symbol from ERPNext (with caching)."""
    global _CURRENCY_CACHE
    if _CURRENCY_CACHE:
        return _CURRENCY_CACHE
        
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ERP_URL}/api/resource/Company",
                headers={
                    "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"
                },
                params={"fields": '["default_currency"]'},
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                companies = data.get("data", [])
                if companies and companies[0].get("default_currency"):
                    currency_code = companies[0].get("default_currency")
                    decimal_places = _CURRENCY_DECIMAL_MAP.get(currency_code, 2)
                    
                    sym_res = await client.get(
                        f"{ERP_URL}/api/resource/Currency/{currency_code}",
                        headers={
                            "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"
                        },
                        params={"fields": '["symbol"]'},
                        timeout=10.0
                    )
                    if sym_res.status_code == 200:
                        sym_data = sym_res.json()
                        symbol = sym_data.get("data", {}).get("symbol") or currency_code
                        if symbol:
                            symbol = symbol.strip().split()[0]
                        else:
                            symbol = currency_code
                            
                        _CURRENCY_CACHE = {
                            "code": currency_code,
                            "symbol": symbol,
                            "decimal_places": decimal_places
                        }
                        return _CURRENCY_CACHE
                    
                    _CURRENCY_CACHE = {
                        "code": currency_code,
                        "symbol": currency_code,
                        "decimal_places": decimal_places
                    }
                    return _CURRENCY_CACHE
    except Exception as e:
        print(f"[ERPClient] Failed to fetch currency info: {e}")
    
    return {"code": "USD", "symbol": "$", "decimal_places": 2}
