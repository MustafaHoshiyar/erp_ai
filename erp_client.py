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
    Fetches the Default Currency code and symbol. 
    Logic: 
    1. Try Live fetch from ERPNext Company resource.
    2. If fails, use ClientConfig 'default_currency' from DB Cache.
    3. If fails, fallback to USD.
    """
    if client_id in _CURRENCY_CACHE:
        return _CURRENCY_CACHE[client_id]

    config = get_client_runtime_config(client_id)
    
    # 1. ATTEMPT LIVE FETCH (Primary source)
    try:
        async with httpx.AsyncClient() as client:
            # Get default company currency
            comp_res = await client.get(
                f"{config['erp_url']}/api/resource/Company",
                headers=_get_headers(config),
                params={"fields": '["default_currency"]'},
                timeout=5.0,
            )
            if comp_res.status_code == 200:
                companies = comp_res.json().get("data", [])
                if companies and companies[0].get("default_currency"):
                    currency_code = companies[0].get("default_currency")
                    
                    # Fetch symbol for this currency
                    sym_res = await client.get(
                        f"{config['erp_url']}/api/resource/Currency/{currency_code}",
                        headers=_get_headers(config),
                        params={"fields": '["symbol"]'},
                        timeout=5.0,
                    )
                    
                    symbol = currency_code
                    if sym_res.status_code == 200:
                        symbol = sym_res.json().get("data", {}).get("symbol") or currency_code
                    
                    # Clean up symbol (e.g., 'KWD 1.000' -> 'KWD')
                    symbol = symbol.strip().split()[0] if symbol else currency_code
                    
                    res = {
                        "code": currency_code,
                        "symbol": symbol,
                        "decimal_places": _CURRENCY_DECIMAL_MAP.get(currency_code, 2),
                    }
                    _CURRENCY_CACHE[client_id] = res
                    return res
    except Exception as live_err:
        print(f"[ERPClient] Live currency fetch failed for {client_id}, checking DB fallback: {live_err}")

    # 2. DB FALLBACK (Workspace-Specific Last Good State)
    if config.get("default_currency_code"):
         res = {
                "code": config["default_currency_code"],
                "symbol": config.get("default_currency_symbol", config["default_currency_code"]),
                "decimal_places": _CURRENCY_DECIMAL_MAP.get(config["default_currency_code"], 2)
         }
         _CURRENCY_CACHE[client_id] = res
         return res

    # 3. EMERGENCY FALLBACK
    return {"code": "USD", "symbol": "$", "decimal_places": 2}


async def run_query(sql: str, client_id="DEMO_CLIENT_123"):
    """
    Executes a SELECT query on the client's ERPNext instance.
    """
    import json
    config = get_client_runtime_config(client_id)
    try:
        # Wrap SQL in the filters dict for the 'AI Report Writer' report
        filters = json.dumps({"sql": sql})
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config['erp_url']}/api/method/frappe.desk.query_report.run",
                headers=_get_headers(config),
                data={
                    "report_name": "AI Report Writer", 
                    "filters": filters
                },
                timeout=30.0,
            )
            response.raise_for_status()
            res_json = response.json()
            return res_json.get("message", {})
    except Exception as e:
        print(f"[ERPClient] Query Error for {client_id}: {e}")
        return {"error": str(e)}
