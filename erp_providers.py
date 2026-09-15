"""ERP-specific connection adapters.

The application talks to ERPNext and Odoo through different APIs. Keeping that
difference here prevents the report pipeline from accidentally applying Frappe
assumptions to an Odoo client.
"""

from abc import ABC, abstractmethod
from urllib.parse import quote, urlparse

import httpx


class ERPProvider(ABC):
    @abstractmethod
    async def run_query(self, sql: str):
        raise NotImplementedError

    @abstractmethod
    async def get_app_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def get_currency_info(self) -> dict:
        raise NotImplementedError


class FrappeProvider(ERPProvider):
    def __init__(self, config: dict):
        self.config = config
        self.base_url = config["erp_url"]
        self.headers = {
            "Authorization": f"token {config['api_key']}:{config['api_secret']}"
        }

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            data = None

        if isinstance(data, dict):
            if data.get("exc"):
                return str(data["exc"])
            if data.get("exception"):
                return str(data["exception"])
            if isinstance(data.get("message"), dict) and data["message"].get("error"):
                return str(data["message"]["error"])
            if data.get("_server_messages"):
                return str(data["_server_messages"])

        return response.text.strip() or response.reason_phrase or f"HTTP {response.status_code}"

    async def run_query(self, sql: str):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/method/smberp_ai.api.run_ai_query",
                headers=self.headers,
                json={"sql": sql},
                timeout=30.0,
            )

        if response.is_error:
            raise Exception(f"ERPNext SQL Error: {self._error_message(response)}")

        data = response.json()
        if isinstance(data, dict):
            if data.get("exc") or data.get("exception"):
                raise Exception(f"ERPNext SQL Error: {data.get('exc') or data.get('exception')}")
            if isinstance(data.get("message"), dict) and data["message"].get("error"):
                raise Exception(f"ERPNext SQL Error: {data['message']['error']}")
        return data

    async def get_app_name(self) -> str:
        if self.config.get("app_name_override"):
            return self.config["app_name_override"]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/resource/System Settings",
                    headers=self.headers,
                    params={"fields": '["app_name"]'},
                    timeout=10.0,
                )
            if response.status_code == 200:
                return response.json().get("data", {}).get("app_name")
        except Exception as exc:
            print(f"[FrappeProvider] Failed to fetch app name: {exc}")

        return urlparse(self.base_url).netloc or "ERP AI"

    async def get_currency_info(self) -> dict:
        decimal_places = {"KWD": 3}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/resource/Company",
                    headers=self.headers,
                    params={"fields": '["default_currency"]'},
                    timeout=10.0,
                )
                companies = response.json().get("data", []) if response.status_code == 200 else []
                code = companies[0].get("default_currency") if companies else None
                if code:
                    symbol_response = await client.get(
                        f"{self.base_url}/api/resource/Currency/{code}",
                        headers=self.headers,
                        params={"fields": '["symbol"]'},
                        timeout=10.0,
                    )
                    symbol = code
                    if symbol_response.status_code == 200:
                        symbol = symbol_response.json().get("data", {}).get("symbol") or code
                        symbol = symbol.strip().split()[0]
                    return {
                        "code": code,
                        "symbol": symbol,
                        "decimal_places": decimal_places.get(code, 2),
                    }
        except Exception as exc:
            print(f"[FrappeProvider] Failed to fetch currency: {exc}")

        return {"code": "USD", "symbol": "$", "decimal_places": 2}


class OdooProvider(ERPProvider):
    def __init__(self, config: dict):
        self.config = config
        self.base_url = config["erp_url"]
        self.bridge_secret = config.get("api_secret", "")
        self.database = config.get("odoo_db", "")

    @staticmethod
    def _bridge_error(data: dict) -> str | None:
        if data.get("error"):
            error = data["error"]
            return error.get("message", "Odoo bridge request failed") if isinstance(error, dict) else str(error)
        result = data.get("result") or {}
        if isinstance(result, dict) and result.get("error"):
            return str(result["error"])
        return None

    async def _bridge_call(self, path: str, params: dict) -> list:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}{path}?db={quote(self.database)}",
                    headers={"X-ERP-AI-Secret": self.bridge_secret},
                    json={"jsonrpc": "2.0", "method": "call", "params": params},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise Exception(f"Odoo bridge connection failed: {exc}") from exc
        except ValueError as exc:
            raise Exception("Odoo bridge returned an invalid response") from exc

        error = self._bridge_error(data)
        if error:
            raise Exception(f"Odoo SQL Error: {error}")
        return (data.get("result") or {}).get("data", [])

    async def run_query(self, sql: str):
        return await self._bridge_call("/erp_ai/run_query", {"sql": sql})

    async def get_app_name(self) -> str:
        return self.config.get("app_name_override") or "Odoo AI"

    async def get_currency_info(self) -> dict:
        try:
            rows = await self.run_query(
                "SELECT cur.name AS code, cur.symbol AS symbol "
                "FROM res_company AS comp "
                "JOIN res_currency AS cur ON comp.currency_id = cur.id "
                "ORDER BY comp.id LIMIT 1"
            )
            if rows:
                row = rows[0]
                return {
                    "code": row.get("code") or "USD",
                    "symbol": row.get("symbol") or "$",
                    "decimal_places": 2,
                }
        except Exception as exc:
            print(f"[OdooProvider] Failed to fetch currency: {exc}")
        return {"code": "USD", "symbol": "$", "decimal_places": 2}


def get_provider(config: dict) -> ERPProvider:
    if config.get("erp_type", "erpnext").lower() == "odoo":
        return OdooProvider(config)
    return FrappeProvider(config)
