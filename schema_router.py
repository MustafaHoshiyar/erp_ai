import json
import os
import re

from openai import OpenAI
from dotenv import load_dotenv
from schema_planner import build_relation_plan_text
from schema_fetcher import (
    ensure_doctype_details,
    extract_available_table_names,
    format_live_doctype_details_for_prompt,
    format_local_schema_for_prompt,
)

load_dotenv()
ROUTER_MODEL = "gpt-4o-mini"
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_api_key) if openai_api_key else None

_SCHEMA_INDEX_CACHE = {
    "global_length": 0,
    "local_length": 0,
    "index_string": "",
}


def build_schema_index(global_schema: str, local_schema: dict) -> str:
    """
    Builds a lightweight list of available tables so the router knows what truly exists.
    """
    global _SCHEMA_INDEX_CACHE

    local_schema_len = len(str(local_schema)) if local_schema else 0
    global_schema_len = len(global_schema)

    if (
        global_schema_len == _SCHEMA_INDEX_CACHE["global_length"]
        and local_schema_len == _SCHEMA_INDEX_CACHE["local_length"]
        and _SCHEMA_INDEX_CACHE["index_string"]
    ):
        return _SCHEMA_INDEX_CACHE["index_string"]

    erp_type = local_schema.get("erp_type", "erpnext") if local_schema else "erpnext"
    lines = [
        f"Available Live {erp_type.upper()} Tables:",
        "Only choose tables that exist in the live inventory below.",
    ]

    live_tables = sorted(extract_available_table_names(local_schema))
    if live_tables:
        chunk_size = 20
        for start in range(0, len(live_tables), chunk_size):
            lines.append(", ".join(live_tables[start:start + chunk_size]))

    lines.append("\nGeneric Global Schema Excerpts:")
    for line in global_schema.split("\n"):
        line = line.strip()
        if erp_type == "erpnext" and line.startswith("`tab"):
            lines.append(line)
        elif erp_type == "odoo" and line.startswith("`") and not line.startswith("`tab"):
            lines.append(line)

    index_str = "\n".join(lines)
    _SCHEMA_INDEX_CACHE["global_length"] = global_schema_len
    _SCHEMA_INDEX_CACHE["local_length"] = local_schema_len
    _SCHEMA_INDEX_CACHE["index_string"] = index_str
    return index_str


def identify_required_tables(user_prompt: str, schema_index: str, erp_type="erpnext") -> tuple[list[str], int]:
    """
    Pass 1: asks a fast LLM to identify the exact live tables needed to answer the prompt.
    """
    prompt_lower = user_prompt.lower()
    if (
        "maintenance" in prompt_lower
        and any(term in prompt_lower for term in ["scheduled", "schedule", "next week", "upcoming", "this week"])
    ):
        table = "tabMaintenance" if erp_type == "erpnext" else "maintenance_order"
        return [table], 0

    if not client:
        return [], 0

    system_prompt = f"""
You are a database routing assistant for an ERP AI platform ({erp_type}).
Given a user request and a list of available live tables, identify EXACTLY which tables are required to write the SQL query.
Return your answer ONLY as a JSON array of table strings (for example ["tabSales Invoice", "tabSales Invoice Item"]).
Do not include backticks in your JSON output.
Do not include any other text or markdown block formatting.
Never invent a table that is not present in the live inventory.

{schema_index}
"""
    try:
        response = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )

        raw_output = response.choices[0].message.content.strip()
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_output, re.IGNORECASE | re.DOTALL)
        if match:
            raw_output = match.group(1).strip()

        tables = json.loads(raw_output)
        tokens_used = response.usage.total_tokens if hasattr(response, "usage") and response.usage else 0
        if isinstance(tables, list):
            return [t.strip("`") for t in tables], tokens_used
        return [], tokens_used
    except Exception as e:
        print(f"[SchemaRouter] Error identifying tables for {erp_type}: {e}")
        return [], 0


def filter_schema(
    global_schema: str,
    local_schema_text: str,
    live_doctype_text: str,
    relation_plan_text: str,
    required_tables: list[str],
) -> str:
    """
    Extracts only the definitions for the required tables from the known schema sources.
    """
    if not required_tables:
        blocks = [global_schema, local_schema_text, live_doctype_text]
        return "\n\n".join(block for block in blocks if block)

    filtered_schema = ["### FILTERED DATABASE SCHEMA ###"]
    if live_doctype_text:
        filtered_schema.append(live_doctype_text)
    if relation_plan_text:
        filtered_schema.append("")
        filtered_schema.append(relation_plan_text)

    rules_block = []
    in_rules = False

    for line in global_schema.split("\n"):
        if "## KEY RELATIONSHIPS" in line:
            in_rules = True

        if in_rules:
            rules_block.append(line)
            continue

        if line.startswith("`"):
            table_name = line.split(":", 1)[0].replace("`", "").strip()
            if table_name in required_tables:
                filtered_schema.append(line)

    if local_schema_text:
        filtered_schema.append("\n### CUSTOM CLIENT SCHEMA ###")
        for line in local_schema_text.split("\n"):
            if line.startswith("`"):
                table_name = line.split(":", 1)[0].replace("`", "").strip()
                if table_name in required_tables:
                    filtered_schema.append(line)
            elif "added:" in line:
                match_dt = re.search(r"`(.*?)`", line)
                if match_dt and match_dt.group(1) in required_tables:
                    filtered_schema.append(line)

    filtered_schema.extend(["\n"])
    filtered_schema.extend(rules_block)
    return "\n".join(filtered_schema)


def get_optimized_schema_context(user_prompt: str, global_schema: str, local_schema: dict, client_id: str = "DEMO_CLIENT_123") -> tuple[str, int, list[str]]:
    """
    Returns the filtered schema string and the tokens used by the routing pass.
    """
    erp_type = local_schema.get("erp_type", "erpnext") if local_schema else "erpnext"
    schema_index = build_schema_index(global_schema, local_schema)
    required_tables, pass1_tokens = identify_required_tables(user_prompt, schema_index, erp_type=erp_type)

    updated_schema = ensure_doctype_details(required_tables, local_schema, client_id=client_id) if local_schema else local_schema
    local_schema_text = format_local_schema_for_prompt(updated_schema) if updated_schema else ""
    live_doctype_text = (
        format_live_doctype_details_for_prompt(updated_schema, required_tables) if updated_schema else ""
    )
    relation_plan_text = (
        build_relation_plan_text(user_prompt, required_tables, updated_schema) if updated_schema else ""
    )
    filtered_schema = filter_schema(
        global_schema,
        local_schema_text,
        live_doctype_text,
        relation_plan_text,
        required_tables,
    )
    return filtered_schema, pass1_tokens, required_tables
