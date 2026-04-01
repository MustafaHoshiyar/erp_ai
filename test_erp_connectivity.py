import httpx
import asyncio
import json
from database import SessionLocal, ClientConfig

async def test_supernatural():
    db = SessionLocal()
    config_obj = db.query(ClientConfig).filter(ClientConfig.client_id == 'supernatural').first()
    db.close()
    
    if not config_obj:
        print("Supernatural config not found in DB")
        return

    url = config_obj.erp_url.rstrip('/')
    headers = {
        "Authorization": f"token {config_obj.api_key}:{config_obj.api_secret}"
    }
    
    print(f"Testing URL: {url}/api/method/frappe.desk.query_report.run")
    
    sql = "SELECT name FROM `tabSales Invoice` LIMIT 1"
    filters = json.dumps({"sql": sql})
    
    async with httpx.AsyncClient() as client:
        # Test 1: POST with Data (Form-Encoded)
        print("\n--- Test 1: POST with FORM-DATA ---")
        try:
            res1 = await client.post(
                f"{url}/api/method/frappe.desk.query_report.run",
                headers=headers,
                data={"report_name": "AI Report Writer", "filters": filters}
            )
            print(f"Status: {res1.status_code}")
            if res1.status_code != 200:
                print(f"Body: {res1.text[:200]}")
        except Exception as e:
            print(f"Error 1: {e}")

        # Test 2: POST with JSON
        print("\n--- Test 2: POST with JSON ---")
        try:
            res2 = await client.post(
                f"{url}/api/method/frappe.desk.query_report.run",
                headers=headers,
                json={"report_name": "AI Report Writer", "filters": {"sql": sql}}
            )
            print(f"Status: {res2.status_code}")
            if res2.status_code != 200:
                print(f"Body: {res2.text[:200]}")
        except Exception as e:
            print(f"Error 2: {e}")

if __name__ == "__main__":
    asyncio.run(test_supernatural())
