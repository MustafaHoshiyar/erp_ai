import httpx
from urllib.parse import urlparse
from runtime_config import get_client_runtime_config

def _get_headers(config: dict):
    return {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}

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
    """
    Emergency fallback for currency info from Database only.
    """
    from database import SessionLocal, ClientConfig
    db = SessionLocal()
    config = db.query(ClientConfig).filter(ClientConfig.client_id == client_id).first()
    db.close()
    
    if config and config.default_currency_code:
        return {
            "symbol": config.default_currency_symbol or config.default_currency_code,
            "code": config.default_currency_code
        }
    
    return {"symbol": "KWD", "code": "KWD"}


async def run_query(sql: str, client_id="DEMO_CLIENT_123"):
    """
    Executes a SELECT query on the client's ERPNext instance.
    """
    config = get_client_runtime_config(client_id)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config['erp_url']}/api/method/frappe.desk.query_report.run",
                headers=_get_headers(config),
                data={"report_name": "AI Report Writer", "filters": '{"sql": "' + sql.replace('"', '\\"') + '"}'},
                timeout=30.0,
            )
            response.raise_for_status()
            res_json = response.json()
            return res_json.get("message", {})
    except Exception as e:
        print(f"[ERPClient] Query Error for {client_id}: {e}")
        return {"error": str(e)}
