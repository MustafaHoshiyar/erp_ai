import os
import re
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from memory_manager import get_relevant_schema_context
from schema_fetcher import get_local_schema, format_local_schema_for_prompt

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
AI_MODEL    = os.getenv("AI_MODEL", "gpt-4o")

if AI_PROVIDER == "groq":
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
elif AI_PROVIDER == "openai":
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    raise ValueError(f"Unsupported AI_PROVIDER: {AI_PROVIDER}")

print(f"[AI Engine] Using provider: {AI_PROVIDER}, model: {AI_MODEL}")

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

Aggregation & Metrics Rules:
- If the user asks "how many" or "total number of", you MUST use the `COUNT(name)` function (e.g. `SELECT COUNT(name) AS total_users FROM tabUser`). Do NOT just return a list of records.
- Use `SUM()` for requests like "total amount", "total sales", or "revenue".

Performance & Syntax Rules:
- STRICTLY USE MariaDB functions! (e.g., IFNULL, DATE_FORMAT, CURDATE(), DATEDIFF, CONCAT).
- NEVER use backticks around date literals or string values (e.g. use '2025-11-30', NEVER `2025-11-30`). Backticks are ONLY for table and column names.
- Date filtering must use index-friendly logic (avoid wrapping columns in functions).
- Use DATE_FORMAT(CURDATE(), '%Y-%m-01') for current month filtering.
- Use DATE_SUB(CURDATE(), INTERVAL X DAY) for rolling ranges.
- NEVER wrap indexed columns in functions in WHERE clause.
- For TIME-SERIES FORECASTING or PREDICTIONS:
  - Do NOT attempt to calculate the forecast in SQL using recursive CTEs.
  - INSTEAD: 
    1. Write a simple SQL query to extract the historical data grouped by month (e.g. `SELECT DATE_FORMAT(posting_date, '%Y-%m') AS 'Month', SUM(grand_total) AS 'Sales' FROM ... GROUP BY Month`).
    2. You MUST include the exact string "FORECAST: <date_col>, <target_col>, <periods>" anywhere in your markdown response outside the SQL block. 
       Example: FORECAST: Month, Sales, 6
  - The Python backend will catch this flag, execute your historical SQL, and run a statistical forecast model (Holt-Winters) on the results automatically.
- Format the totals and amount columns with 2 decimal places.
- Always group correctly when using aggregates.
- Avoid SELECT *. Return specific columns.

Security Rules:
- Only generate SELECT queries.
- Never generate DELETE, UPDATE, INSERT, DROP, ALTER, TRUNCATE, or any DDL.
- No subqueries that modify data.

Output Rules:
- Return ONLY raw SQL.
- Do NOT include explanations, markdown formatting, or conversational text (but SQL comments like /* NO_LIMIT */ ARE ALLOWED).
- SQL must start directly with SELECT or WITH.

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
    
    # Schema Routing (Pass 1 - Token Optimization)
    from schema_router import get_optimized_schema_context
    local_schema = None
    try:
        local_schema = get_local_schema()
    except Exception as e:
        print(f"[AI Engine] Could not load local schema for router: {e}")
        
    filtered_schema, pass1_tokens = get_optimized_schema_context(user_prompt, GLOBAL_SCHEMA, local_schema)
    dynamic_system_prompt += f"\n\n{filtered_schema}"
    
    # Layer 3: Memory (previously successful queries)
    if memory_context:
        dynamic_system_prompt += f"\n\n{memory_context}"

    messages = [{"role": "system", "content": dynamic_system_prompt}]
    
    if history:
        messages.extend(history)
        
    messages.append({"role": "user", "content": user_prompt})

    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=messages,
        temperature=0
    )

    raw_output = response.choices[0].message.content.strip()
    tokens_used = response.usage.total_tokens if hasattr(response, "usage") and response.usage else 0
    tokens_used += pass1_tokens

    # Check for Python Forecaster Command
    needs_forecast = False
    if "FORECAST:" in raw_output:
        needs_forecast = True
        
    # Try to extract SQL from a markdown block
    match = re.search(r"```sql(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used, "needs_forecast": needs_forecast}

    # Fallback to older matching if it didn't use the markdown block
    match = re.search(r"(SELECT .*?;)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used, "needs_forecast": needs_forecast}

    # Fallback if no semicolon
    match = re.search(r"(SELECT .*?$)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used, "needs_forecast": needs_forecast}

    # Conversational reply, no SQL
    return {"sql": None, "message": raw_output, "tokens_used": tokens_used, "needs_forecast": False}


def generate_chart_config(columns, data_sample, dataset_summary=None):
    system_prompt = """
You are an expert data visualization and dashboard assistant.
Given a list of column names, their inferred data types, a small JSON sample of the data, and an overall dataset summary (total rows and sums of numerical columns), your task is to generate a comprehensive JSON dashboard configuration.

Your output MUST be a single raw JSON object with the following structure:
{
  "kpis": [
    {
      "label": "Total Orders",
      "value": "66",
      "trend_percentage": "24.53",
      "trend_direction": "up"
    }
  ],
  "chart": {
     // Valid Chart.js configuration object here
  }
}

KPI INSTRUCTIONS:
- Generate up to 4 Key Performance Indicators (KPIs) that summarize the data.
- **CRITICAL**: Use the `dataset_summary` provided in the user prompt to populate the KPI values (e.g. Total Rows, Sums of key numerical columns). Do NOT base the KPIs solely on the small `Data Sample`.
- `value` should be formatted nicely (e.g., "99.4k", "140.7", "$12.5M").
- `trend_percentage` is optional (an estimated trend based on the data context, e.g., "24.5"). Omit if not applicable.
- `trend_direction` must be "up", "down", or "neutral".

CHART INSTRUCTIONS:
Choose the best chart type (e.g., 'bar', 'line', 'pie', 'doughnut') that represents the data.
Usually, there is one categorical column (for labels) and one or more numerical columns (for datasets).

CRITICAL SCALING INSTRUCTION:
If there are multiple numerical datasets and their values have vastly different scales (for example, "Total Orders" ranges from 1-100, while "Total Sales" ranges from 1,000-10,000+), you MUST configure multiple Y-axes (e.g., `y` and `y1`) in the `options.scales` configuration and assign each dataset to the appropriate `yAxisID`.

CRITICAL DATE ISSUES:
Do NOT use `type: 'time'` for x-axis or y-axis scales. The frontend does not have a date adapter loaded. Treat dates as simple categorical strings (i.e. use the default `type: 'category'` or omit `type` for the x-axis).

Return ONLY the raw JSON object, starting with `{` and ending with `}`.
Do NOT include explanations, markdown formatting, or comments.
"""
    
    user_prompt = f"Columns: {columns}\nData Sample: {data_sample}"
    if dataset_summary:
        user_prompt += f"\nDataset Summary (Real Totals for KPIs): {dataset_summary}"

    response = client.chat.completions.create(
        model=AI_MODEL,
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
