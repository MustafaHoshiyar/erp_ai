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
            json={"sql": sql}
        )
        return response.json()