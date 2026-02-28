import os
import re
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from memory_manager import get_relevant_schema_context
from schema_fetcher import get_local_schema, format_local_schema_for_prompt

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
#client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Load global schema once at startup
_GLOBAL_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schemas", "global_schema.txt")
try:
    with open(_GLOBAL_SCHEMA_PATH, "r", encoding="utf-8") as f:
        GLOBAL_SCHEMA = f.read()
    print(f"[AI Engine] Loaded global schema ({len(GLOBAL_SCHEMA)} chars)")
except FileNotFoundError:
    GLOBAL_SCHEMA = ""
    print("[AI Engine] WARNING: global_schema.txt not found. AI will operate without global schema.")

SYSTEM_PROMPT = """
You are a senior ERPNext database engineer and MariaDB expert.

You specialize in writing complex, optimized, production-safe SQL queries
for ERPNext and the Frappe Framework (MariaDB backend).
You MUST use MariaDB specific SQL syntax. Do not use generic SQL or PostgreSQL/SQL Server functions.

Database Schema Rules for ERPNext and Frappe:
- ERPNext/Frappe DocTypes are stored as tables prefixed with `tab`. E.g., `Sales Invoice` becomes `tabSales Invoice`.
- Table names and column names often contain spaces or reserved words and MUST be wrapped in backticks (e.g., `tabSales Invoice`, `tabItem`).
- Every table has standard Frappe columns:
  - `name` (VARCHAR) is the Primary Key for all tables.
  - `creation` (DATETIME), `modified` (DATETIME), `modified_by` (VARCHAR), `owner` (VARCHAR).
- Child tables link to their parent via the `parent` column. They also have `parentfield`, `parenttype`, and `idx` columns.
- Most transactional data is in `tabSales Invoice`, `tabPurchase Invoice`, `tabJournal Entry`, `tabPayment Entry`, `tabStock Ledger Entry`, `tabGL Entry`.

ERPNext Financial Intelligence:
- Gross profit is NOT stored in Sales Invoice Item.
- Cost comes from `tabStock Ledger Entry`.
- Join cost using:
    sle.voucher_no = si.name
    AND sle.item_code = sii.item_code
- Use ABS(sle.stock_value_difference) as cost impact.
- Only stock items generate Stock Ledger Entries.

ERPNext Inventory Logic:
- Stock Ledger Entry tracks inventory movement.
- Use actual_qty for quantity movement.
- Negative actual_qty indicates outgoing stock.
- Warehouse-based reports must join `tabWarehouse`.

Performance & Syntax Rules:
- STRICTLY USE MariaDB functions! (e.g., IFNULL, DATE_FORMAT, CURDATE(), DATEDIFF, CONCAT).
- Date filtering must use index-friendly logic (avoid wrapping columns in functions).
- Use DATE_FORMAT(CURDATE(), '%Y-%m-01') for current month filtering.
- Use DATE_SUB(CURDATE(), INTERVAL X DAY) for rolling ranges.
- NEVER wrap indexed columns in functions in WHERE clause.
- Use >= date comparisons instead of MONTH() filters.
- Always include LIMIT.
- Format the totals and amount columns with 2 decimal places.
- Always group correctly when using aggregates.
- Avoid SELECT *. Return specific columns.

Security Rules:
- Only generate SELECT queries.
- Never generate DELETE, UPDATE, INSERT, DROP, ALTER, TRUNCATE, or any DDL.
- No subqueries that modify data.

Output Rules:
- Return ONLY raw SQL.
- Do NOT include explanations, markdown formatting, comments, or conversational text.
- SQL must start directly with SELECT.

Your goal:
Generate accurate, optimized, production-ready ERPNext MariaDB queries using strict Frappe framework schema conventions.

Rules for Conversation:
- If the user says "hello" or asks a general question, just reply nicely as an AI assistant. DO NOT GENERATE SQL.
"""

def generate_sql(user_prompt, history=None, client_id="DEMO_CLIENT_123"):
    # Fetch relevant historical schema context (Memory Layer)
    memory_context = get_relevant_schema_context(client_id, user_prompt)
    
    # Build the dynamic system prompt with all 3 layers
    dynamic_system_prompt = SYSTEM_PROMPT
    
    # Layer 1: Global Schema
    if GLOBAL_SCHEMA:
        dynamic_system_prompt += f"\n\n{GLOBAL_SCHEMA}"
    
    # Layer 2: Local Schema (client customizations)
    try:
        local_schema = get_local_schema()
        local_schema_text = format_local_schema_for_prompt(local_schema)
        if local_schema_text:
            dynamic_system_prompt += f"\n\n{local_schema_text}"
    except Exception as e:
        print(f"[AI Engine] Could not load local schema: {e}")
    
    # Layer 3: Memory (previously successful queries)
    if memory_context:
        dynamic_system_prompt += f"\n\n{memory_context}"

    messages = [{"role": "system", "content": dynamic_system_prompt}]
    
    if history:
        messages.extend(history)
        
    messages.append({"role": "user", "content": user_prompt})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0
    )

    raw_output = response.choices[0].message.content.strip()
    tokens_used = response.usage.total_tokens if hasattr(response, "usage") and response.usage else 0

    # Try to extract SQL from a markdown block
    match = re.search(r"```sql(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used}

    # Fallback to older matching if it didn't use the markdown block
    match = re.search(r"(SELECT .*?;)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used}

    # Fallback if no semicolon
    match = re.search(r"(SELECT .*?$)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used}

    # Conversational reply, no SQL
    return {"sql": None, "message": raw_output, "tokens_used": tokens_used}


def generate_chart_config(columns, data_sample):
    system_prompt = """
You are an expert data visualization assistant.
Given a list of column names, their inferred data types, and a small JSON sample of the data, your task is to generate a valid, optimized JSON configuration object for Chart.js.
Choose the best chart type (e.g., 'bar', 'line', 'pie', 'doughnut') that represents the data.
Usually, there is one categorical column (for labels) and one or more numerical columns (for datasets).

CRITICAL SCALING INSTRUCTION:
If there are multiple numerical datasets and their values have vastly different scales (for example, "Total Orders" ranges from 1-100, while "Total Sales" ranges from 1,000-10,000+), you MUST configure multiple Y-axes (e.g., `y` and `y1`) in the `options.scales` configuration and assign each dataset to the appropriate `yAxisID`.

Return ONLY the raw JSON object for the Chart.js configuration, starting with `{` and ending with `}`.
Do NOT include explanations, markdown formatting, or comments.
"""
    user_prompt = f"Columns: {columns}\nData Sample: {data_sample}"

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0
    )

    raw_output = response.choices[0].message.content.strip()

    # Try to extract JSON from a markdown block
    match = re.search(r"```json(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Fallback to direct output if no markdown
    return raw_output.strip()
