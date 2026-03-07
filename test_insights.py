import asyncio
import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()
ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

async def test_creation_flow():
    headers = {
        "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    async with httpx.AsyncClient() as client:
        # 1. Create Question (Query v3)
        query_data = {
            "title": "API Flow Test",
            "workbook": "3",  # default workbook we've been using
            "use_live_connection": 1,
            "operations": json.dumps([
                {
                    "type": "sql",
                    "raw_sql": "SELECT name FROM tabUser LIMIT 5",
                    "name": "Query",
                    "data_source": "Site DB"
                }
            ])
        }
        res1 = await client.post(f"{ERP_URL}/api/resource/Insights Query v3", headers=headers, json=query_data)
        query_name = res1.json().get("data", {}).get("name")
        print("Created Query:", query_name)
        
        # 2. Create Chart
        chart_data = {
            "title": "API Flow Chart",
            "workbook": "3",
            "query": query_name,
            "chart_type": "Bar",
            "config": json.dumps({
                "x_axis": {
                    "dimension": {
                        "column_name": "name", 
                        "data_type": "String", 
                        "dimension_name": "name", 
                        "label": "name"
                    }
                },
                "y_axis": {
                    "series": [
                        { "measure": { "aggregation": "count", "column_name": "name", "data_type": "Integer" } }
                    ],
                    "stack": True
                }
            })
        }
        res2 = await client.post(f"{ERP_URL}/api/resource/Insights Chart v3", headers=headers, json=chart_data)
        if res2.status_code != 200:
            print("Chart creation failed:", res2.text)
            return
            
        chart_name = res2.json().get("data", {}).get("name")
        print("Created Chart:", chart_name)
        
        # 3. Create Dashboard
        dashboard_data = {
            "title": "API Flow Dashboard",
            "workbook": "3",
            "items": json.dumps([
                {
                    "type": "chart",
                    "chart": chart_name,
                    "w": 6,
                    "h": 4,
                    "x": 0,
                    "y": 0,
                    "i": "1"
                }
            ])
        }
        res3 = await client.post(f"{ERP_URL}/api/resource/Insights Dashboard v3", headers=headers, json=dashboard_data)
        if res3.status_code != 200:
            print("Dashboard creation failed:", res3.text)
            return
            
        dash_name = res3.json().get("data", {}).get("name")
        print("Created Dashboard:", dash_name)
        print("Done!")

if __name__ == "__main__":
    asyncio.run(test_creation_flow())
