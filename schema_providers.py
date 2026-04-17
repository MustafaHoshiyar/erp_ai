import abc
import httpx
import json
from urllib.parse import quote

class SchemaProvider(abc.ABC):
    @abc.abstractmethod
    def fetch_available_tables(self) -> list:
        pass

    @abc.abstractmethod
    def fetch_table_detail(self, table_name: str) -> dict:
        pass

    @abc.abstractmethod
    def fetch_custom_tables(self) -> list:
        pass

    @abc.abstractmethod
    def fetch_custom_fields(self) -> list:
        pass

class FrappeSchemaProvider(SchemaProvider):
    def __init__(self, config: dict):
        self.config = config
        self.headers = {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}
        self.base_url = config['erp_url']

    def fetch_available_tables(self) -> list:
        try:
            with httpx.Client(timeout=30) as client:
                res = client.get(
                    f"{self.base_url}/api/resource/DocType",
                    headers=self.headers,
                    params={"fields": json.dumps(["name", "module", "custom", "istable"]), "limit_page_length": 0},
                )
                res.raise_for_status()
                return res.json().get("data", [])
        except Exception as e:
            print(f"[FrappeSchema] Error: {e}")
            return []

    def fetch_table_detail(self, table_name: str) -> dict:
        # ERPNext uses 'tab' prefix in DB but resource name is and without prefix
        doctype_name = table_name[3:] if table_name.startswith("tab") else table_name
        encoded_name = quote(doctype_name, safe="")
        with httpx.Client(timeout=30) as client:
            res = client.get(f"{self.base_url}/api/resource/DocType/{encoded_name}", headers=self.headers)
            res.raise_for_status()
            data = res.json().get("data", {})
            return self._normalize(data)

    def _normalize(self, dt_data):
        # Existing normalization logic from schema_fetcher.py
        fields = []
        child_tables = []
        _LAYOUT_FIELD_TYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}
        for field in dt_data.get("fields", []):
            if field.get("fieldtype") in _LAYOUT_FIELD_TYPES: continue
            fields.append({
                "fieldname": field.get("fieldname"),
                "fieldtype": field.get("fieldtype"),
                "label": field.get("label"),
                "options": field.get("options"),
            })
            if field.get("fieldtype") == "Table":
                child_tables.append({"child_doctype": field.get("options"), "fieldname": field.get("fieldname")})
        return {
            "name": dt_data.get("name"),
            "module": dt_data.get("module"),
            "custom": dt_data.get("custom", 0),
            "istable": dt_data.get("istable", 0),
            "fields": fields,
            "child_tables": child_tables,
        }

    def fetch_custom_tables(self) -> list:
        try:
            with httpx.Client(timeout=30) as client:
                res = client.get(
                    f"{self.base_url}/api/resource/DocType",
                    headers=self.headers,
                    params={"filters": json.dumps([["custom", "=", 1]]), "fields": json.dumps(["name"]), "limit_page_length": 0},
                )
                res.raise_for_status()
                names = [d["name"] for d in res.json().get("data", [])]
                return [self.fetch_table_detail(name) for name in names]
        except: return []

    def fetch_custom_fields(self) -> list:
        try:
            with httpx.Client(timeout=30) as client:
                res = client.get(
                    f"{self.base_url}/api/resource/Custom Field",
                    headers=self.headers,
                    params={"fields": json.dumps(["name", "dt", "fieldname", "fieldtype", "label", "options"]), "limit_page_length": 0},
                )
                res.raise_for_status()
                return res.json().get("data", [])
        except: return []

class OdooSchemaProvider(SchemaProvider):
    def __init__(self, config: dict):
        self.config = config
        self.url = config['erp_url']
        self.secret = config['api_secret']

    def _call_bridge(self, params: dict):
        # We use a synchronous Client because SchemaFetcher is currently synchronous
        with httpx.Client(timeout=30) as client:
            try:
                response = client.post(
                    f"{self.url}/erp_ai/fetch_metadata",
                    headers={"X-ERP-AI-Secret": self.secret},
                    json={"params": params}
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as he:
                raise Exception(f"Failed to communicate with Odoo Bridge at {self.url}/erp_ai/fetch_metadata: HTTP Error. Is the bridge module installed? Details: {he}")
            except Exception as e:
                raise Exception(f"Failed to parse response from Odoo Bridge. It might be returning HTML instead of JSON. Details: {e}")
            if "error" in data:
                raise Exception(f"Odoo Bridge Error: {data['error'].get('message', 'Unknown Error')}")
            result = data.get("result", {})
            if "error" in result:
                raise Exception(f"Odoo Bridge Application Error: {result['error']}")
            return result.get("data", [])

    def fetch_available_tables(self) -> list:
        data = self._call_bridge({"mode": "models"})
        # Map Odoo 'model' to same format as 'name' in available_doctypes (underscores for tables)
        return [{"name": d["model"].replace(".", "_"), "label": d["name"], "original_model": d["model"]} for d in data]

    def fetch_table_detail(self, table_name: str) -> dict:
        # Table name in Odoo uses underscores, but metadata bridge needs the original model name with dots
        # Typical Odoo convention: product.product -> product_product
        # We try to restore the dots for the bridge call if possible, or just pass as is if the bridge handles both.
        # But based on ir_model metadata, it's safer to pass dots.
        model_name = table_name.replace("_", ".") # Heuristic, but accurate for standard Odoo
        
        data = self._call_bridge({"mode": "fields", "model": model_name})
        
        fields = []
        for d in data:
            fields.append({
                "fieldname": d["name"],
                "fieldtype": d["type"], # many2one, one2many, etc.
                "label": d["label"],
                "options": d["relation"].replace(".", "_") if d["relation"] else None
            })
        
        return {
            "name": table_name,
            "fields": fields,
            "child_tables": [] # Relations are handled via Link/Table field types in graph
        }

    def fetch_custom_tables(self) -> list:
        # Custom models in Odoo usually start with x_
        # But for now, we'll return empty or specialized logic
        return []

    def fetch_custom_fields(self) -> list:
        # Custom fields in Odoo also start with x_
        return []
