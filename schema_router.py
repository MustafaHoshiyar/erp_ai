import os
import re
import json
from openai import OpenAI
from dotenv import load_dotenv
from schema_fetcher import get_local_schema

load_dotenv()
ROUTER_MODEL = "gpt-4o-mini" # Fast, cheap model for Pass 1
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_api_key) if openai_api_key else None

def build_schema_index(global_schema: str, local_schema: dict) -> str:
    """
    Builds a very lightweight list of available tables and a tiny subset of columns
    just so the router knows what exists.
    """
    lines = ["Available Database Tables:"]
    
    # Process global schema lines
    for line in global_schema.split("\n"):
        line = line.strip()
        if line.startswith("`tab"):
            lines.append(line)
            
    # Process local schema
    if local_schema.get("custom_doctypes"):
        lines.append("\nCustom Client Tables:")
        for dt in local_schema["custom_doctypes"]:
            table_name = f"`tab{dt['name']}`"
            field_strs = []
            for f in dt.get("fields", [])[:5]: # just the first few fields for index
                ftype = f.get("fieldtype", "")
                fname = f.get("fieldname", "")
                if ftype not in ("HTML", "Button", "Heading"):
                    field_strs.append(f"{fname}")
            lines.append(f"{table_name}: {', '.join(field_strs)} ...")
            
    return "\n".join(lines)

def identify_required_tables(user_prompt: str, schema_index: str) -> tuple[list[str], int]:
    """
    Pass 1: Asks a fast LLM to identify the exact tables needed to answer the prompt.
    """
    if not client:
        return []
        
    system_prompt = f"""
You are a database routing assistant for ERPNext.
Given a user request and a list of available tables, your job is to identify EXACTLY which tables are required to write the SQL query.
Return your answer ONLY as a JSON array of table strings (e.g., ["tabSales Invoice", "tabSales Invoice Item"]).
Do not include backticks in your JSON output.
Do not include any other text or markdown block formatting.

{schema_index}
"""
    try:
        response = client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0
        )
        
        raw_output = response.choices[0].message.content.strip()
        
        # Remove markdown if it wrapped it in ```json ... ```
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_output, re.IGNORECASE | re.DOTALL)
        if match:
             raw_output = match.group(1).strip()
             
        tables = json.loads(raw_output)
        tokens_used = response.usage.total_tokens if hasattr(response, "usage") and response.usage else 0
        if isinstance(tables, list):
            return [t.strip('`') for t in tables], tokens_used
        return [], tokens_used
    except Exception as e:
        print(f"[SchemaRouter] Error identifying tables: {e}")
        return [], 0

def filter_schema(global_schema: str, local_schema_text: str, required_tables: list[str]) -> str:
    """
    Extracts only the definitions for the required tables from the full schemas.
    """
    if not required_tables:
        # If router failed or returned empty, fallback to full schema
        return global_schema + "\n\n" + local_schema_text
        
    filtered_schema = ["### FILTERED DATABASE SCHEMA ###"]
    
    # Also include the relationships/rules block at the bottom of global_schema
    rules_block = []
    in_rules = False
    
    for line in global_schema.split("\n"):
        if "## KEY RELATIONSHIPS" in line:
            in_rules = True
            
        if in_rules:
            rules_block.append(line)
            continue
            
        if line.startswith("`tab"):
            table_name = line.split(":", 1)[0].replace("`", "").strip()
            if table_name in required_tables:
                filtered_schema.append(line)
                
    # Filter local schema text
    if local_schema_text:
        filtered_schema.append("\n### CUSTOM CLIENT SCHEMA ###")
        for line in local_schema_text.split("\n"):
            if line.startswith("`tab"):
                table_name = line.split(":", 1)[0].replace("`", "").strip()
                if table_name in required_tables:
                    filtered_schema.append(line)
            elif "added:" in line: # Custom fields on standard tables
                # "`tabSales Invoice` added: custom_field (Data)"
                match_dt = re.search(r"`(tab.*?)`", line)
                if match_dt and match_dt.group(1) in required_tables:
                    filtered_schema.append(line)
                    
    filtered_schema.extend(["\n"])
    filtered_schema.extend(rules_block)
    
    return "\n".join(filtered_schema)

def get_optimized_schema_context(user_prompt: str, global_schema: str, local_schema: dict) -> tuple[str, int]:
    """
    Returns the filtered schema string and the tokens used by the routing pass.
    """
    from schema_fetcher import format_local_schema_for_prompt
    
    local_schema_text = format_local_schema_for_prompt(local_schema) if local_schema else ""
    
    # 1. Build Index
    schema_index = build_schema_index(global_schema, local_schema)
    
    # 2. Identify Tables (Pass 1)
    required_tables, pass1_tokens = identify_required_tables(user_prompt, schema_index)
    
    # 3. Filter Schema
    filtered_schema = filter_schema(global_schema, local_schema_text, required_tables)
    
    return filtered_schema, pass1_tokens
