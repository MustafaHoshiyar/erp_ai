import abc
import httpx
import xmlrpc.client
from urllib.parse import urlparse

class ERPProvider(abc.ABC):
    @abc.abstractmethod
    async def run_query(self, sql: str) -> dict:
        pass

    @abc.abstractmethod
    async def get_app_name(self) -> str:
        pass

    @abc.abstractmethod
    async def get_currency_info(self) -> dict:
        pass

class FrappeProvider(ERPProvider):
    def __init__(self, config: dict):
        self.config = config
        self.headers = {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}

    def _extract_error(self, response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            data = None
        if isinstance(data, dict):
            if data.get("exc"): return str(data["exc"])
            if data.get("exception"): return str(data["exception"])
        return response.text or response.reason_phrase

    async def run_query(self, sql: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config['erp_url']}/api/method/smberp_ai.api.run_ai_query",
                headers=self.headers,
                json={"sql": sql},
                timeout=30.0,
            )
            if response.is_error:
                raise Exception(f"ERPNext SQL Error: {self._extract_error(response)}")
            return response.json()

    async def get_app_name(self) -> str:
        if self.config.get("app_name_override"):
            return self.config["app_name_override"]
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.config['erp_url']}/api/resource/System Settings",
                    headers=self.headers,
                    params={"fields": '["app_name"]'},
                    timeout=10.0,
                )
                if response.status_code == 200:
                    return response.json().get("data", {}).get("app_name")
        except: pass
        return urlparse(self.config["erp_url"]).netloc or "ERP AI"

    async def get_currency_info(self) -> dict:
        # Simplified version of existing logic
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    f"{self.config['erp_url']}/api/resource/Company",
                    headers=self.headers,
                    params={"fields": '["default_currency"]'},
                    timeout=10.0,
                )
                if res.status_code == 200:
                    data = res.json().get("data", [])
                    if data:
                        code = data[0].get("default_currency", "USD")
                        return {"code": code, "symbol": code, "decimal_places": 2}
        except: pass
        return {"code": "USD", "symbol": "$", "decimal_places": 2}

class OdooProvider(ERPProvider):
    def __init__(self, config: dict):
        self.config = config
        # Odoo XML-RPC endpoints
        self.url = config['erp_url']
        self.db = config['odoo_db']
        self.username = config['api_key'] # Using api_key as username
        self.password = config['api_secret'] # Using api_secret as password/api_key

    async def run_query(self, sql: str) -> dict:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.url}/erp_ai/run_query",
                    headers={"X-ERP-AI-Secret": self.password},
                    json={
                        "params": {
                            "sql": sql
                        }
                    },
                    timeout=30.0
                )
                data = response.json()
                # Odoo json-rpc wrapper handles 'result' key
                if "error" in data:
                    raise Exception(f"Odoo Bridge Error: {data['error'].get('message', 'Unknown Error')}")
                
                result = data.get("result", {})
                if "error" in result:
                    raise Exception(f"Odoo SQL Error: {result['error']}")
                
                return result.get("data", []) # Should return the list of rows
            except Exception as e:
                raise Exception(f"Failed to reach Odoo bridge: {e}")

    async def get_app_name(self) -> str:
        if self.config.get("app_name_override"):
            return self.config["app_name_override"]
        return "Odoo AI"

    async def get_currency_info(self) -> dict:
        try:
            # We can use the bridge to run a simple SQL to get currency
            sql = """
                SELECT comp.name as code, cur.symbol 
                FROM res_company comp 
                JOIN res_currency cur ON comp.currency_id = cur.id 
                LIMIT 1
            """
            data = await self.run_query(sql)
            if data and isinstance(data, list) and len(data) > 0:
                row = data[0]
                return {
                    "code": row.get("code", "USD"),
                    "symbol": row.get("symbol", "$"),
                    "decimal_places": 2
                }
        except Exception as e:
            print(f"[OdooProvider] Error fetching currency: {e}")
        return {"code": "USD", "symbol": "$", "decimal_places": 2}
