import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()
ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

async def get_fields(doctype):
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{ERP_URL}/api/method/frappe.desk.form.load.getdoctype",
            headers={"Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"},
            params={"doctype": doctype}
        )
        for f in res.json().get("docs", [])[0].get("fields", []):
            print(f"{f.get('fieldname')}: {f.get('fieldtype')}")

if __name__ == "__main__":
    asyncio.run(get_fields("Insights Chart v3"))
