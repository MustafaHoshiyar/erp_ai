import httpx
import json
import os
import asyncio
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
    import json
    async with httpx.AsyncClient() as client:
        # Fetch all dashboards and find the newly created one and any working ones
        r_list = await client.get(
            f"{ERP_URL}/api/resource/Insights Dashboard v3",
            headers=headers,
            params={"limit_page_length": 100, "order_by": "creation desc"}
        )
        
        results = {}
        if r_list.status_code == 200:
            for dash in r_list.json().get("data", []):
                r = await client.get(
                    f"{ERP_URL}/api/resource/Insights Dashboard v3/{dash['name']}",
                    headers=headers
                )
                if r.status_code == 200:
                    doc = r.json().get("data", {})
                    title = doc.get("title", "")
                    if any(x in title.lower() for x in ["grid fix", "hello", "top items"]):
                        raw_items = doc.get("items")
                        results[dash['name']] = {
                            "title": title,
                            "items_type": type(raw_items).__name__,
                            "items_raw": raw_items,
                            "linked_charts_count": len(doc.get("linked_charts", [])),
                            "workbook": doc.get("workbook")
                        }
                        print(f"\n=== {title} ({dash['name']}) ===")
                        print(f"  items type: {type(raw_items).__name__}")
                        print(f"  items value: {repr(raw_items)[:200]}")
                        print(f"  linked_charts: {len(doc.get('linked_charts', []))} entries")

        with open("grid_debug.json", "w") as f:
            json.dump(results, f, indent=2)
        print("\nWrote to grid_debug.json")

if __name__ == "__main__":
    asyncio.run(run())

if __name__ == "__main__":
    asyncio.run(run())

if __name__ == "__main__":
    asyncio.run(run())
