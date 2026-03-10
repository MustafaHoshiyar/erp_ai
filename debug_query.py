"""Check Insights Data Source configuration to debug '127.0.0.1 does not exist' error."""
import asyncio, httpx, os, json
from dotenv import load_dotenv
load_dotenv()
ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")
headers = {
    "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
    "Content-Type": "application/json"
}

async def run():
    async with httpx.AsyncClient(timeout=30) as client:
        # Check data sources
        r = await client.get(f"{ERP_URL}/api/resource/Insights Data Source v3", headers=headers, params={"limit_page_length": 50})
        print("=== Data Sources ===")
        if r.status_code == 200:
            for ds in r.json().get("data", []):
                r2 = await client.get(f"{ERP_URL}/api/resource/Insights Data Source v3/{ds['name']}", headers=headers)
                if r2.status_code == 200:
                    doc = r2.json()["data"]
                    print(f"  {ds['name']}: title={doc.get('title')}, database_type={doc.get('database_type')}, host={doc.get('host')}, is_site_db={doc.get('is_site_db')}")
        
        # Also check Insights Settings
        r3 = await client.get(f"{ERP_URL}/api/resource/Insights Settings", headers=headers)
        print("\n=== Insights Settings ===")
        if r3.status_code == 200:
            print(json.dumps(r3.json().get("data", {}), indent=2, default=str))
        
        # Check the dashboard home page
        r4 = await client.get(f"{ERP_URL}/api/method/insights.api.home.get_dashboard_list", headers=headers)
        print("\n=== Dashboard List API ===")
        print(f"  Status: {r4.status_code}")
        if r4.status_code == 200:
            data = r4.json().get("message", [])
            print(f"  Count: {len(data)}")
            for d in data[:5]:
                print(f"  - {d}")

if __name__ == "__main__":
    asyncio.run(run())
