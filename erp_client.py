import os
import httpx
from dotenv import load_dotenv

load_dotenv()

ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

async def run_query(sql):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{ERP_URL}/api/method/erp_ai.api.run_ai_query",
            headers={
                "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"
            },
            json={"sql": sql},
            timeout=30.0
        )
        
        # Raise exception for HTTP errors (4xx, 5xx)
        response.raise_for_status()
        
        data = response.json()
        
        # Frappe/ERPNext often returns errors inside a 200 response with message or error keys
        if isinstance(data, dict):
            if "exc" in data or "exception" in data:
                error_msg = data.get("exc") or data.get("exception")
                raise Exception(f"ERPNext SQL Error: {error_msg}")
            
            # If the response has a "message" key that is actually an error object
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
    
    # Fallback to domain/site name if possible
    from urllib.parse import urlparse
    return urlparse(ERP_URL).netloc or "ERP AI"