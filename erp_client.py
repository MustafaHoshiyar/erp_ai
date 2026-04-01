import httpx
import os
from runtime_config import get_client_runtime_config

def _get_headers(config: dict):
    return {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}

async def run_query(sql, client_id="DEMO_CLIENT_123"):
    """
    Executes a SELECT query on the client's CUSTOM ERPNext app.
    """
    config = get_client_runtime_config(client_id)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config['erp_url']}/api/method/smberp_ai.api.run_ai_query",
                headers=_get_headers(config),
                json={"sql": sql},
                timeout=30.0,
            )
            response.raise_for_status()
            res_json = response.json()
            return res_json.get("message", {})
    except Exception as e:
        print(f"[ERPClient] Custom Query Error for {client_id}: {e}")
        return {"error": str(e)}
