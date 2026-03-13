"""
Schema Fetcher - Fetches client-specific custom schema from their ERPNext instance.
Caches results locally for performance. Supports TTL-based refresh.
"""

import os
import json
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

CACHE_DIR = os.path.join(os.path.dirname(__file__), "schemas")
LOCAL_SCHEMA_CACHE = os.path.join(CACHE_DIR, "local_schema_cache.json")
CACHE_TTL_SECONDS = 86400  # 24 Hours


def _get_headers():
    return {
        "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"
    }


def _fetch_custom_doctypes():
    """Fetch all custom DocTypes from the client's ERPNext."""
    try:
        with httpx.Client(timeout=30) as client:
            # Get list of custom doctypes
            res = client.get(
                f"{ERP_URL}/api/resource/DocType",
                headers=_get_headers(),
                params={
                    "filters": json.dumps([["custom", "=", 1]]),
                    "fields": json.dumps(["name", "module"]),
                    "limit_page_length": 0
                }
            )
            res.raise_for_status()
            doctypes = res.json().get("data", [])

            # For each custom doctype, fetch its fields
            detailed_doctypes = []
            for dt in doctypes:
                dt_res = client.get(
                    f"{ERP_URL}/api/resource/DocType/{dt['name']}",
                    headers=_get_headers()
                )
                dt_res.raise_for_status()
                dt_data = dt_res.json().get("data", {})

                fields = []
                child_tables = []
                for f in dt_data.get("fields", []):
                    if f.get("fieldtype") in ("Section Break", "Column Break", "Tab Break"):
                        continue
                    field_info = {
                        "fieldname": f.get("fieldname"),
                        "fieldtype": f.get("fieldtype"),
                        "label": f.get("label"),
                        "options": f.get("options")
                    }
                    fields.append(field_info)

                    if f.get("fieldtype") == "Table":
                        child_tables.append({
                            "child_doctype": f.get("options"),
                            "fieldname": f.get("fieldname")
                        })

                detailed_doctypes.append({
                    "name": dt["name"],
                    "module": dt.get("module"),
                    "fields": fields,
                    "child_tables": child_tables
                })

            return detailed_doctypes
    except Exception as e:
        print(f"[SchemaFetcher] Error fetching custom doctypes: {e}")
        return []


def _fetch_custom_fields():
    """Fetch all Custom Fields added to standard DocTypes."""
    try:
        with httpx.Client(timeout=30) as client:
            res = client.get(
                f"{ERP_URL}/api/resource/Custom Field",
                headers=_get_headers(),
                params={
                    "fields": json.dumps(["name", "dt", "fieldname", "fieldtype", "label", "options"]),
                    "limit_page_length": 0
                }
            )
            res.raise_for_status()
            return res.json().get("data", [])
    except Exception as e:
        print(f"[SchemaFetcher] Error fetching custom fields: {e}")
        return []


def fetch_and_cache_local_schema():
    """
    Fetches the client's custom schema from ERPNext and caches it locally.
    Returns the schema dict.
    """
    print("[SchemaFetcher] Fetching local schema from ERPNext...")

    custom_doctypes = _fetch_custom_doctypes()
    custom_fields = _fetch_custom_fields()

    schema = {
        "fetched_at": time.time(),
        "fetched_at_readable": time.strftime("%Y-%m-%d %H:%M:%S"),
        "custom_doctypes": custom_doctypes,
        "custom_fields": custom_fields
    }

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(LOCAL_SCHEMA_CACHE, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    print(f"[SchemaFetcher] Cached {len(custom_doctypes)} custom doctypes and {len(custom_fields)} custom fields.")
    return schema


def get_local_schema():
    """
    Returns the local schema from cache. If cache is missing or stale, fetches fresh.
    """
    if os.path.exists(LOCAL_SCHEMA_CACHE):
        with open(LOCAL_SCHEMA_CACHE, "r", encoding="utf-8") as f:
            schema = json.load(f)

        fetched_at = schema.get("fetched_at", 0)
        if (time.time() - fetched_at) < CACHE_TTL_SECONDS:
            return schema

        print("[SchemaFetcher] Cache expired, refreshing...")

    return fetch_and_cache_local_schema()


def format_local_schema_for_prompt(schema: dict) -> str:
    """
    Converts the cached local schema into a concise text block for injection into the AI's system prompt.
    """
    lines = [
        "### CLIENT CUSTOM SCHEMA ###",
        "The following custom tables and fields are specific to THIS client's ERPNext instance.",
        "Use these when the user asks about custom or non-standard data.",
        ""
    ]

    if schema.get("custom_doctypes"):
        lines.append("## CUSTOM DOCTYPES:")
        for dt in schema["custom_doctypes"]:
            table_name = f"`tab{dt['name']}`"
            field_strs = []
            for f in dt.get("fields", []):
                ftype = f.get("fieldtype", "")
                fname = f.get("fieldname", "")
                if ftype in ("Table", "Link"):
                    field_strs.append(f"{fname} ({ftype}->{f.get('options', '')})")
                elif ftype not in ("HTML", "Button", "Heading"):
                    field_strs.append(f"{fname} ({ftype})")
            lines.append(f"{table_name}: {', '.join(field_strs)}")

            for ct in dt.get("child_tables", []):
                lines.append(f"  Child: `tab{ct['child_doctype']}` (via field: {ct['fieldname']})")
        lines.append("")

    if schema.get("custom_fields"):
        lines.append("## CUSTOM FIELDS ON STANDARD TABLES:")
        by_dt = {}
        for cf in schema["custom_fields"]:
            dt_name = cf.get("dt", "Unknown")
            if dt_name not in by_dt:
                by_dt[dt_name] = []
            by_dt[dt_name].append(cf)

        for dt_name, fields in by_dt.items():
            field_strs = []
            for f in fields:
                ftype = f.get("fieldtype", "")
                fname = f.get("fieldname", "")
                if ftype in ("Table", "Link"):
                    field_strs.append(f"{fname} ({ftype}->{f.get('options', '')})")
                elif ftype not in ("Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"):
                    field_strs.append(f"{fname} ({ftype})")
            if field_strs:
                lines.append(f"`tab{dt_name}` added: {', '.join(field_strs)}")

    return "\n".join(lines)
