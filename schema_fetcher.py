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

load_dotenv()

ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

CACHE_DIR = os.path.join(os.path.dirname(__file__), "schemas")
LOCAL_SCHEMA_CACHE = os.path.join(CACHE_DIR, "local_schema_cache.json")
CACHE_TTL_SECONDS = 86400  # 24 Hours
_LAYOUT_FIELD_TYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}


def _get_headers():
    return {"Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"}


def _load_cached_schema():
    if not os.path.exists(LOCAL_SCHEMA_CACHE):
        return None

    with open(LOCAL_SCHEMA_CACHE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_schema_cache(schema):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(LOCAL_SCHEMA_CACHE, "w", encoding="utf-8") as f:
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


def _fetch_available_doctypes():
    try:
        with httpx.Client(timeout=30) as client:
            res = client.get(
                f"{ERP_URL}/api/resource/DocType",
                headers=_get_headers(),
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


def _fetch_doctype_detail(client, doctype_name):
    encoded_name = quote(doctype_name, safe="")
    response = client.get(
        f"{ERP_URL}/api/resource/DocType/{encoded_name}",
        headers=_get_headers(),
    )
    response.raise_for_status()
    return _normalize_doctype_detail(response.json().get("data", {}))


def _fetch_custom_doctypes():
    """Fetch all custom DocTypes from the client's ERPNext with full metadata."""
    try:
        with httpx.Client(timeout=30) as client:
            res = client.get(
                f"{ERP_URL}/api/resource/DocType",
                headers=_get_headers(),
                params={
                    "filters": json.dumps([["custom", "=", 1]]),
                    "fields": json.dumps(["name", "module", "custom", "istable"]),
                    "limit_page_length": 0,
                },
            )
            res.raise_for_status()
            doctypes = res.json().get("data", [])
            return [_fetch_doctype_detail(client, dt["name"]) for dt in doctypes]
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
                    "limit_page_length": 0,
                },
            )
            res.raise_for_status()
            return res.json().get("data", [])
    except Exception as e:
        print(f"[SchemaFetcher] Error fetching custom fields: {e}")
        return []


def _table_to_doctype(table_name):
    if not table_name:
        return ""
    return table_name[3:] if table_name.startswith("tab") else table_name


def _doctype_to_table(doctype_name):
    if not doctype_name:
        return ""
    return doctype_name if doctype_name.startswith("tab") else f"tab{doctype_name}"


def fetch_and_cache_local_schema():
    """Fetches live schema metadata from ERPNext and caches it locally."""
    print("[SchemaFetcher] Fetching local schema from ERPNext...")

    available_doctypes = _fetch_available_doctypes()
    custom_doctypes = _fetch_custom_doctypes()
    custom_fields = _fetch_custom_fields()
    doctype_details = {dt["name"]: dt for dt in custom_doctypes if dt.get("name")}

    schema = {
        "fetched_at": time.time(),
        "fetched_at_readable": time.strftime("%Y-%m-%d %H:%M:%S"),
        "available_doctypes": available_doctypes,
        "custom_doctypes": custom_doctypes,
        "custom_fields": custom_fields,
        "doctype_details": doctype_details,
    }

    _write_schema_cache(schema)
    print(
        "[SchemaFetcher] Cached "
        f"{len(available_doctypes)} available doctypes, "
        f"{len(custom_doctypes)} custom doctypes, "
        f"and {len(custom_fields)} custom fields."
    )
    return schema


def get_local_schema():
    """Returns the cached schema. Refreshes if stale or missing new required sections."""
    schema = _load_cached_schema()
    if schema:
        fetched_at = schema.get("fetched_at", 0)
        has_required_sections = all(
            key in schema for key in ("available_doctypes", "custom_doctypes", "custom_fields", "doctype_details")
        )
        if has_required_sections and (time.time() - fetched_at) < CACHE_TTL_SECONDS:
            return schema

        print("[SchemaFetcher] Cache is stale or missing live schema sections, refreshing...")

    return fetch_and_cache_local_schema()


def ensure_doctype_details(required_tables, schema=None):
    """
    Ensures we have detailed field metadata for the routed live DocTypes.
    Returns the updated schema dict.
    """
    schema = schema or get_local_schema()
    doctype_details = schema.setdefault("doctype_details", {})
    available_doctypes = {row.get("name") for row in schema.get("available_doctypes", []) if row.get("name")}

    required_doctypes = []
    for table_name in required_tables or []:
        doctype_name = _table_to_doctype(table_name)
        if doctype_name and doctype_name in available_doctypes and doctype_name not in doctype_details:
            required_doctypes.append(doctype_name)

    if not required_doctypes:
        return schema

    try:
        with httpx.Client(timeout=30) as client:
            for doctype_name in required_doctypes:
                doctype_details[doctype_name] = _fetch_doctype_detail(client, doctype_name)
    except Exception as e:
        print(f"[SchemaFetcher] Error fetching routed doctype details: {e}")
        return schema

    schema["doctype_details"] = doctype_details
    _write_schema_cache(schema)
    return schema


def extract_available_table_names(schema):
    tables = set()
    if not schema:
        return tables

    for row in schema.get("available_doctypes", []):
        if row.get("name"):
            tables.add(_doctype_to_table(row["name"]))

    for row in schema.get("custom_doctypes", []):
        if row.get("name"):
            tables.add(_doctype_to_table(row["name"]))

    for dt_name in schema.get("doctype_details", {}):
        if dt_name:
            tables.add(_doctype_to_table(dt_name))

    for field in schema.get("custom_fields", []):
        if field.get("dt"):
            tables.add(_doctype_to_table(field["dt"]))

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
    required_doctypes = {_table_to_doctype(table_name) for table_name in (required_tables or [])}

    lines = [
        "### LIVE ERP DOCTYPE DETAILS ###",
        "Only use the following DocTypes and fields when generating SQL for this tenant.",
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

        lines.append(f"`tab{doctype_name}`: {', '.join(field_strs)}")
        for child in detail.get("child_tables", []):
            lines.append(f"  Child: `tab{child['child_doctype']}` (via field: {child['fieldname']})")
        added_any = True

    if not added_any:
        return ""

    return "\n".join(lines)


def format_local_schema_for_prompt(schema):
    """
    Converts cached custom schema into a concise text block for injection into the AI's system prompt.
    """
    lines = [
        "### CLIENT CUSTOM SCHEMA ###",
        "The following custom tables and fields are specific to THIS client's ERPNext instance.",
        "Use these when the user asks about custom or non-standard data.",
        "",
    ]

    if schema.get("custom_doctypes"):
        lines.append("## CUSTOM DOCTYPES:")
        for dt in schema["custom_doctypes"]:
            table_name = f"`tab{dt['name']}`"
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
                lines.append(f"  Child: `tab{child['child_doctype']}` (via field: {child['fieldname']})")
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
                lines.append(f"`tab{dt_name}` added: {', '.join(field_strs)}")

    return "\n".join(lines)
