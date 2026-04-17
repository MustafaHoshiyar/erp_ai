"""
Schema Fetcher - fetches live ERPNext schema metadata and caches it locally.
The cache includes:
- available live DocTypes in the connected ERP
- custom DocTypes and custom fields
- on-demand detailed metadata for routed DocTypes
"""

import json
import os
import time
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from runtime_config import get_client_runtime_config, sanitize_client_cache_key
from schema_providers import FrappeSchemaProvider, OdooSchemaProvider

load_dotenv()

CACHE_DIR = os.path.join(os.path.dirname(__file__), "schemas")
CACHE_TTL_SECONDS = 86400  # 24 Hours

def get_schema_provider(client_id: str):
    config = get_client_runtime_config(client_id)
    erp_type = config.get("erp_type", "erpnext")
    if erp_type == "odoo":
        return OdooSchemaProvider(config)
    return FrappeSchemaProvider(config)
_LAYOUT_FIELD_TYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}


def _get_cache_path(client_id: str):
    return os.path.join(CACHE_DIR, f"local_schema_cache_{sanitize_client_cache_key(client_id)}.json")


def _get_headers(config: dict):
    # This is currently only used for internal historical references if any, 
    # but actual fetching is now delegated to the Provider.
    return {"Authorization": f"token {config['api_key']}:{config['api_secret']}"}

def _get_erp_type(client_id: str):
    return get_client_runtime_config(client_id).get("erp_type", "erpnext")


def _load_cached_schema(client_id: str):
    cache_path = _get_cache_path(client_id)
    if not os.path.exists(cache_path):
        return None

    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_schema_cache(schema, client_id: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_get_cache_path(client_id), "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)


def _normalize_doctype_detail(dt_data):
    fields = []
    child_tables = []
    for field in dt_data.get("fields", []):
        if field.get("fieldtype") in _LAYOUT_FIELD_TYPES:
            continue

        field_info = {
            "fieldname": field.get("fieldname"),
            "fieldtype": field.get("fieldtype"),
            "label": field.get("label"),
            "options": field.get("options"),
        }
        fields.append(field_info)

        if field.get("fieldtype") == "Table":
            child_tables.append(
                {
                    "child_doctype": field.get("options"),
                    "fieldname": field.get("fieldname"),
                }
            )

    return {
        "name": dt_data.get("name"),
        "module": dt_data.get("module"),
        "custom": dt_data.get("custom", 0),
        "istable": dt_data.get("istable", 0),
        "fields": fields,
        "child_tables": child_tables,
    }


def _fetch_available_doctypes(config):
    try:
        with httpx.Client(timeout=30) as client:
            res = client.get(
                f"{config['erp_url']}/api/resource/DocType",
                headers=_get_headers(config),
                params={
                    "fields": json.dumps(["name", "module", "custom", "istable"]),
                    "limit_page_length": 0,
                },
            )
            res.raise_for_status()
            return res.json().get("data", [])
    except Exception as e:
        print(f"[SchemaFetcher] Error fetching available doctypes: {e}")
        return []


def _fetch_doctype_detail(client, doctype_name, config):
    encoded_name = quote(doctype_name, safe="")
    response = client.get(
        f"{config['erp_url']}/api/resource/DocType/{encoded_name}",
        headers=_get_headers(config),
    )
    response.raise_for_status()
    return _normalize_doctype_detail(response.json().get("data", {}))


def _fetch_custom_doctypes(config):
    """Fetch all custom DocTypes from the client's ERPNext with full metadata."""
    try:
        with httpx.Client(timeout=30) as client:
            res = client.get(
                f"{config['erp_url']}/api/resource/DocType",
                headers=_get_headers(config),
                params={
                    "filters": json.dumps([["custom", "=", 1]]),
                    "fields": json.dumps(["name", "module", "custom", "istable"]),
                    "limit_page_length": 0,
                },
            )
            res.raise_for_status()
            doctypes = res.json().get("data", [])
            return [_fetch_doctype_detail(client, dt["name"], config) for dt in doctypes]
    except Exception as e:
        print(f"[SchemaFetcher] Error fetching custom doctypes: {e}")
        return []


def _fetch_custom_fields(config):
    """Fetch all Custom Fields added to standard DocTypes."""
    try:
        with httpx.Client(timeout=30) as client:
            res = client.get(
                f"{config['erp_url']}/api/resource/Custom Field",
                headers=_get_headers(config),
                params={
                    "fields": json.dumps(["name", "dt", "fieldname", "fieldtype", "label", "options"]),
                    "limit_page_length": 0,
                },
            )
            res.raise_for_status()
            return res.json().get("data", [])
    except Exception as e:
        print(f"[SchemaFetcher] Error fetching custom fields: {e}")
        return []


def _table_to_resource(table_name, erp_type="erpnext"):
    if not table_name: return ""
    if erp_type == "erpnext":
        return table_name[3:] if table_name.startswith("tab") else table_name
    return table_name # Odoo uses direct names or underscores

def _resource_to_table(resource_name, erp_type="erpnext"):
    if not resource_name: return ""
    if erp_type == "erpnext":
        return resource_name if resource_name.startswith("tab") else f"tab{resource_name}"
    return resource_name # Odoo has no prefix


def fetch_and_cache_local_schema(client_id="DEMO_CLIENT_123"):
    """Fetches live schema metadata from the ERP and caches it locally."""
    config = get_client_runtime_config(client_id)
    erp_type = config.get("erp_type", "erpnext")
    provider = get_schema_provider(client_id)
    
    print(f"[SchemaFetcher] Fetching local schema from {erp_type} for {client_id}...")

    available_doctypes = provider.fetch_available_tables()
    custom_doctypes = provider.fetch_custom_tables()
    custom_fields = provider.fetch_custom_fields()
    doctype_details = {dt["name"]: dt for dt in custom_doctypes if dt.get("name")}

    schema = {
        "fetched_at": time.time(),
        "fetched_at_readable": time.strftime("%Y-%m-%d %H:%M:%S"),
        "erp_type": erp_type,
        "available_doctypes": available_doctypes,
        "custom_doctypes": custom_doctypes,
        "custom_fields": custom_fields,
        "doctype_details": doctype_details,
    }

    _write_schema_cache(schema, client_id)
    print(
        "[SchemaFetcher] Cached "
        f"{len(available_doctypes)} available tables, "
        f"{len(custom_doctypes)} custom tables, "
        f"and {len(custom_fields)} custom fields."
    )
    return schema


def get_local_schema(client_id="DEMO_CLIENT_123"):
    """Returns the cached schema. Refreshes if stale or missing new required sections."""
    schema = _load_cached_schema(client_id)
    if schema:
        fetched_at = schema.get("fetched_at", 0)
        has_required_sections = all(
            key in schema for key in ("available_doctypes", "custom_doctypes", "custom_fields", "doctype_details")
        )
        if has_required_sections and (time.time() - fetched_at) < CACHE_TTL_SECONDS:
            return schema

        print("[SchemaFetcher] Cache is stale or missing live schema sections, refreshing...")

    return fetch_and_cache_local_schema(client_id)


def ensure_doctype_details(required_tables, schema=None, client_id="DEMO_CLIENT_123"):
    """
    Ensures we have detailed field metadata for the routed live DocTypes/Tables.
    Returns the updated schema dict.
    """
    schema = schema or get_local_schema(client_id)
    erp_type = schema.get("erp_type", "erpnext")
    doctype_details = schema.setdefault("doctype_details", {})
    available_doctypes = {row.get("name") for row in schema.get("available_doctypes", []) if row.get("name")}

    required_doctypes = []
    for table_name in required_tables or []:
        doctype_name = _table_to_resource(table_name, erp_type)
        if doctype_name and doctype_name in available_doctypes and doctype_name not in doctype_details:
            required_doctypes.append(doctype_name)

    if not required_doctypes:
        return schema

    try:
        provider = get_schema_provider(client_id)
        for doctype_name in required_doctypes:
            doctype_details[doctype_name] = provider.fetch_table_detail(doctype_name)
    except Exception as e:
        print(f"[SchemaFetcher] Error fetching routed doctype details: {e}")
        return schema

    schema["doctype_details"] = doctype_details
    _write_schema_cache(schema, client_id)
    return schema


def extract_available_table_names(schema):
    tables = set()
    if not schema:
        return tables
    erp_type = schema.get("erp_type", "erpnext")

    for row in schema.get("available_doctypes", []):
        if row.get("name"):
            tables.add(_resource_to_table(row["name"], erp_type))

    for row in schema.get("custom_doctypes", []):
        if row.get("name"):
            tables.add(_resource_to_table(row["name"], erp_type))

    for dt_name in schema.get("doctype_details", {}):
        if dt_name:
            tables.add(_resource_to_table(dt_name, erp_type))

    for field in schema.get("custom_fields", []):
        if field.get("dt"):
            tables.add(_resource_to_table(field["dt"], erp_type))

    return tables


def get_doctype_detail_map(schema):
    detail_map = {}
    if not schema:
        return detail_map

    for dt_name, detail in (schema.get("doctype_details") or {}).items():
        if dt_name and detail:
            detail_map[dt_name] = detail

    for detail in schema.get("custom_doctypes", []):
        dt_name = detail.get("name")
        if dt_name and dt_name not in detail_map:
            detail_map[dt_name] = detail

    return detail_map


def format_live_doctype_details_for_prompt(schema, required_tables=None):
    """Formats live doctype metadata for prompt injection."""
    if not schema:
        return ""

    detail_map = schema.get("doctype_details", {})
    erp_type = schema.get("erp_type", "erpnext")
    required_doctypes = {_table_to_resource(table_name, erp_type) for table_name in (required_tables or [])}

    prefix = "tab" if erp_type == "erpnext" else ""
    lines = [
        f"### LIVE {erp_type.upper()} SCHEMA DETAILS ###",
        "Only use the following tables and fields when generating SQL for this tenant.",
        "",
    ]

    added_any = False
    for doctype_name, detail in sorted(detail_map.items()):
        if required_doctypes and doctype_name not in required_doctypes:
            continue

        field_strs = []
        for field in detail.get("fields", []):
            fieldtype = field.get("fieldtype", "")
            fieldname = field.get("fieldname", "")
            if fieldtype in ("Table", "Link"):
                field_strs.append(f"{fieldname} ({fieldtype}->{field.get('options', '')})")
            else:
                field_strs.append(f"{fieldname} ({fieldtype})")

        lines.append(f"`{prefix}{doctype_name}`: {', '.join(field_strs)}")
        for child in detail.get("child_tables", []):
            lines.append(f"  Child: `{prefix}{child['child_doctype']}` (via field: {child['fieldname']})")
        added_any = True

    if not added_any:
        return ""

    return "\n".join(lines)


def format_local_schema_for_prompt(schema):
    """
    Converts cached custom schema into a concise text block for injection into the AI's system prompt.
    """
    erp_type = schema.get("erp_type", "erpnext")
    prefix = "tab" if erp_type == "erpnext" else ""
    lines = [
        "### CLIENT CUSTOM SCHEMA ###",
        f"The following custom tables and fields are specific to THIS client's {erp_type.upper()} instance.",
        "Use these when the user asks about custom or non-standard data.",
        "",
    ]

    if schema.get("custom_doctypes"):
        lines.append("## CUSTOM TABLES:")
        for dt in schema["custom_doctypes"]:
            table_name = f"`{prefix}{dt['name']}`"
            field_strs = []
            for field in dt.get("fields", []):
                fieldtype = field.get("fieldtype", "")
                fieldname = field.get("fieldname", "")
                if fieldtype in ("Table", "Link"):
                    field_strs.append(f"{fieldname} ({fieldtype}->{field.get('options', '')})")
                elif fieldtype not in _LAYOUT_FIELD_TYPES:
                    field_strs.append(f"{fieldname} ({fieldtype})")
            lines.append(f"{table_name}: {', '.join(field_strs)}")

            for child in dt.get("child_tables", []):
                lines.append(f"  Child: `{prefix}{child['child_doctype']}` (via field: {child['fieldname']})")
        lines.append("")

    if schema.get("custom_fields"):
        lines.append("## CUSTOM FIELDS ON STANDARD TABLES:")
        by_dt = {}
        for cf in schema["custom_fields"]:
            dt_name = cf.get("dt", "Unknown")
            by_dt.setdefault(dt_name, []).append(cf)

        for dt_name, fields in by_dt.items():
            field_strs = []
            for field in fields:
                fieldtype = field.get("fieldtype", "")
                fieldname = field.get("fieldname", "")
                if fieldtype in ("Table", "Link"):
                    field_strs.append(f"{fieldname} ({fieldtype}->{field.get('options', '')})")
                elif fieldtype not in _LAYOUT_FIELD_TYPES:
                    field_strs.append(f"{fieldname} ({fieldtype})")
            if field_strs:
                lines.append(f"`{prefix}{dt_name}` added: {', '.join(field_strs)}")

    return "\n".join(lines)
