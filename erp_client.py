import httpx
import os
from runtime_config import get_client_runtime_config

def _get_headers(config: dict):
    return {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}

def get_default_currency_info(client_id="DEMO_CLIENT_123"):
    """
    Emergency fallback for currency info from Database only.
    Using getattr to prevent 500 errors if columns are missing.
    """
    from database import SessionLocal, ClientConfig
    db = SessionLocal()
    try:
        config = db.query(ClientConfig).filter(ClientConfig.client_id == client_id).first()
        if config:
            code = getattr(config, "default_currency_code", "KWD") or "KWD"
            symbol = getattr(config, "default_currency_symbol", code) or code
            return {"symbol": symbol, "code": code}
    except Exception as e:
        print(f"[ERPClient] DB Currency Fetch Error: {e}")
    finally:
        db.close()
    
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
