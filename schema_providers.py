"""ERP-specific live schema discovery adapters."""

from abc import ABC, abstractmethod
import json
from urllib.parse import quote

import httpx


class SchemaProvider(ABC):
    @abstractmethod
    def fetch_available_tables(self) -> list:
        raise NotImplementedError

    @abstractmethod
    def fetch_table_detail(self, table_name: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def fetch_custom_tables(self) -> list:
        raise NotImplementedError

    @abstractmethod
    def fetch_custom_fields(self) -> list:
        raise NotImplementedError


class FrappeSchemaProvider(SchemaProvider):
    def __init__(self, config: dict):
        self.config = config
        self.base_url = config["erp_url"]
        self.headers = {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}

    def fetch_available_tables(self) -> list:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{self.base_url}/api/resource/DocType",
                headers=self.headers,
                params={
                    "fields": json.dumps(["name", "module", "custom", "istable"]),
                    "limit_page_length": 0,
                },
            )
            response.raise_for_status()
            return response.json().get("data", [])

    def fetch_table_detail(self, table_name: str) -> dict:
        doctype = table_name[3:] if table_name.startswith("tab") else table_name
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{self.base_url}/api/resource/DocType/{quote(doctype, safe='')}",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json().get("data", {})

        fields = []
        child_tables = []
        layout_types = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}
        for field in data.get("fields", []):
            if field.get("fieldtype") in layout_types:
                continue
            fields.append({
                "fieldname": field.get("fieldname"),
                "fieldtype": field.get("fieldtype"),
                "label": field.get("label"),
                "options": field.get("options"),
            })
            if field.get("fieldtype") == "Table":
                child_tables.append({
                    "child_doctype": field.get("options"),
                    "fieldname": field.get("fieldname"),
                })

        return {
            "name": data.get("name"),
            "module": data.get("module"),
            "custom": data.get("custom", 0),
            "istable": data.get("istable", 0),
            "fields": fields,
            "child_tables": child_tables,
        }

    def fetch_custom_tables(self) -> list:
        try:
            rows = self._get_resource(
                "DocType",
                {"filters": json.dumps([["custom", "=", 1]]), "fields": json.dumps(["name"]), "limit_page_length": 0},
            )
            return [self.fetch_table_detail(row["name"]) for row in rows if row.get("name")]
        except Exception as exc:
            print(f"[FrappeSchema] Failed to fetch custom tables: {exc}")
            return []

    def fetch_custom_fields(self) -> list:
        try:
            return self._get_resource(
                "Custom Field",
                {"fields": json.dumps(["name", "dt", "fieldname", "fieldtype", "label", "options"]), "limit_page_length": 0},
            )
        except Exception as exc:
            print(f"[FrappeSchema] Failed to fetch custom fields: {exc}")
            return []

    def _get_resource(self, resource: str, params: dict) -> list:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{self.base_url}/api/resource/{quote(resource, safe='')}",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            return response.json().get("data", [])


class OdooSchemaProvider(SchemaProvider):
    def __init__(self, config: dict):
        self.base_url = config["erp_url"]
        self.secret = config.get("api_secret", "")
        self.database = config.get("odoo_db", "")

    def _call_bridge(self, params: dict) -> list:
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    f"{self.base_url}/erp_ai/fetch_metadata?db={quote(self.database)}",
                    headers={"X-ERP-AI-Secret": self.secret},
                    json={"jsonrpc": "2.0", "method": "call", "params": params},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Exception("Odoo bridge metadata request failed") from exc

        if data.get("error"):
            error = data["error"]
            raise Exception(error.get("message", "Odoo bridge metadata request failed") if isinstance(error, dict) else str(error))
        result = data.get("result") or {}
        if result.get("error"):
            raise Exception(str(result["error"]))
        return result.get("data", [])

    def fetch_available_tables(self) -> list:
        return [
            {
                "name": row.get("model"),
                "label": row.get("name"),
                "original_model": row.get("model"),
            }
            for row in self._call_bridge({"mode": "models"})
            if row.get("model")
        ]

    def fetch_table_detail(self, table_name: str) -> dict:
        model = table_name.replace("_", ".")
        fields = []
        for field in self._call_bridge({"mode": "fields", "model": model}):
            relation = field.get("relation")
            fields.append({
                "fieldname": field.get("name"),
                "fieldtype": field.get("type"),
                "label": field.get("label"),
                "options": relation.replace(".", "_") if relation else None,
            })
        return {"name": table_name, "fields": fields, "child_tables": []}

    def fetch_custom_tables(self) -> list:
        return []

    def fetch_custom_fields(self) -> list:
        return []
