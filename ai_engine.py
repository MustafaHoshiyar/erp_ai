import os
import re
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from memory_manager import get_relevant_schema_context
from schema_fetcher import get_local_schema, format_local_schema_for_prompt

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o")

if AI_PROVIDER == "groq":
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
elif AI_PROVIDER == "openai":
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    raise ValueError(f"Unsupported AI_PROVIDER: {AI_PROVIDER}")

print(f"[AI Engine] Using provider: {AI_PROVIDER}, model: {AI_MODEL}")

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
- If a user asks for "low stock", "items to reorder", or "items out of stock", NEVER use `projected_qty < 0`. ALWAYS use `actual_qty`. To handle this dynamically:
  1. If the user specifies a quantity (e.g., "below 50"), use `actual_qty < 50`.
  2. If the user DOES NOT specify a quantity, you can assume a sensible default threshold for the query (e.g., `actual_qty <= 10`) OR join with the item's `reorder_level` if available.

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
- For any amount, total, or currency fields, return the RAW numeric values. Do NOT use FORMAT() or CONCAT() to add currency symbols in the SQL.
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
Generate accurate, optimized, production-ready ERPNext MariaDB queries (currency: {currency}) using strict Frappe framework schema conventions.

Rules for Conversation:
- If the user says "hello" or asks a general question, just reply nicely as an AI assistant. DO NOT GENERATE SQL.

Safety & Row Limits:
- A middleware validator appends `LIMIT 1000` to all queries by default to protect performance.
- IF and ONLY IF the user explicitly asks for "all records", "everything", "no limit", or mentions a large amount that exceeds 1000, you MUST include the comment `/* NO_LIMIT */` immediately after `SELECT` or `WITH`.
- Example: `SELECT /* NO_LIMIT */ name, customer FROM tabSales Invoice`
- Do NOT add a `LIMIT` clause yourself if the user asks for all records; use the comment instead.

Client-Specific Hard Rule:
- For maintenance prompts about records that are "scheduled", "upcoming", "next week", "this week", or date-windowed future maintenance, prefer `tabMaintenance` over `tabMaintenance Schedule`.
- In this client, the correct fields are `tabMaintenance`.`customer_id` and `tabMaintenance`.`scheduled_date`.
- Do NOT use `tabMaintenance Schedule`.`start_date` for those prompts unless the user explicitly asks for Maintenance Schedule.
"""

def generate_sql(user_prompt, history=None, client_id="DEMO_CLIENT_123", currency="USD", currency_symbol="$"):
    memory_context = get_relevant_schema_context(client_id, user_prompt)
    
    dynamic_system_prompt = SYSTEM_PROMPT.format(currency=currency)
    
    from schema_router import get_optimized_schema_context
    local_schema = None
    try:
        local_schema = get_local_schema()
    except Exception as e:
        print(f"[AI Engine] Could not load local schema for router: {e}")
        
    filtered_schema, pass1_tokens = get_optimized_schema_context(user_prompt, GLOBAL_SCHEMA, local_schema)
    dynamic_system_prompt += f"\n\n{filtered_schema}"
    
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

    needs_forecast = False
    if "FORECAST:" in raw_output:
        needs_forecast = True
        
    match = re.search(r"```sql(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used, "needs_forecast": needs_forecast}

    match = re.search(r"(SELECT .*?;)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used, "needs_forecast": needs_forecast}

    match = re.search(r"(SELECT .*?$)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {"sql": match.group(1).strip(), "message": raw_output, "tokens_used": tokens_used, "needs_forecast": needs_forecast}

    return {"sql": None, "message": raw_output, "tokens_used": tokens_used, "needs_forecast": False}


def generate_chart_config(columns, data_sample, dataset_summary=None, currency="USD", currency_symbol="$"):
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
- **CRITICAL INTELLIGENCE**: Do NOT create KPIs that sum or aggregate identifiers, phone numbers, mobile numbers, index columns, or status flags (e.g. 'mobile', 'phone', 'id', 'name', 'idx'). Only aggregate meaningful business metrics (e.g. amounts, quantities, totals, revenues, counts).
- **CRITICAL**: Use the `dataset_summary` provided in the user prompt to populate the KPI values (e.g. Total Rows, Sums of key numerical columns). However, ignore meaningless sums provided in `dataset_summary` (like the sum of mobile numbers). Do NOT base the KPIs solely on the small `Data Sample`.
- If the only numeric columns are identifiers/phone numbers, just return a single KPI for "Total Count" or "Total Rows".
- `value` should be formatted nicely including the currency symbol '{currency_symbol}' (e.g., "{currency_symbol} 99.4k", "140.7 {currency_symbol}", "12.5M {currency_symbol}").
- `trend_percentage` is optional (an estimated trend based on the data context, e.g., "24.5"). Omit if not applicable.
- `trend_direction` must be "up", "down", or "neutral".

CHART INSTRUCTIONS:
Choose the best chart type (e.g., 'bar', 'line', 'pie', 'doughnut') that represents the data.
Usually, there is one categorical column (for labels) and one or more numerical columns (for datasets).

CRITICAL CHART INTELLIGENCE:
- Do NOT use identifiers, phone numbers, mobile numbers, index columns, or status flags as the numerical values in your dataset (e.g., do NOT plot phone numbers on the Y-axis). These are NOT numeric metrics.
- If the table contains records (like Leads or Users) and the only numeric-looking columns are phone numbers or IDs, you MUST NOT plot the phone number values. Instead, try to count occurrences of a categorical column (like 'status' or 'country') to create a meaningful distribution chart.

CRITICAL SCALING INSTRUCTION:
If there are multiple numerical datasets and their values have vastly different scales (for example, "Total Orders" ranges from 1-100, while "Total Sales" ranges from 1,000-10,000+), you MUST configure multiple Y-axes (e.g., `y` and `y1`) in the `options.scales` configuration and assign each dataset to the appropriate `yAxisID`.

CRITICAL DATE ISSUES:
Do NOT use `type: 'time'` for x-axis or y-axis scales. The frontend does not have a date adapter loaded. Treat dates as simple categorical strings (i.e. use the default `type: 'category'` or omit `type` for the x-axis).

Return ONLY the raw JSON object, starting with `{` and ending with `}`.
Do NOT include explanations, markdown formatting, or comments.
"""
    
    formatted_system_prompt = system_prompt.format(currency_symbol=currency_symbol)
    user_prompt = f"Columns: {columns}\nData Sample: {data_sample}"
    if dataset_summary:
        user_prompt += f"\nDataset Summary (Real Totals for KPIs): {dataset_summary}"

    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": formatted_system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0
    )

    raw_output = response.choices[0].message.content.strip()

    match = re.search(r"```json(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    
    return raw_output.strip()

def determine_insights_chart_config(sql: str, data_sample: list):
    """
    Uses AI to determine the best X and Y axes for a Frappe Insights Chart
    based on the SQL query and a sample of the resulting data.
    """
    system_prompt = """
You are an expert data analyst configuring a chart for Frappe Insights v3.
The user has executed a SQL query and we have a small sample of the resulting data rows.
Your job is to determine the absolute best way to visualize this data in a Frappe Insights Chart.

Frappe Insights Charts require:
1. One strict categorical column for the X-axis (e.g., status, owner, country, date, item_group).
2. One or more numerical measures for the Y-axis.

CRITICAL RULES:
- If the tabular data contains ONLY categorical columns or identifiers (like 'name', 'lead_owner', 'customer_name', 'phone_number'), you MUST NOT plot these directly. Instead, compute an aggregation (like "count") over one of the categorical columns to show a distribution (e.g. Count of leads by territory).
- If the table contains real numeric metrics (like 'total_revenue', 'grand_total', 'amount', 'qty', 'stock_value', 'sales'), you should plot these metrics and use aggregations like "sum" or "avg".
- Do NOT use phone numbers, document IDs, or timestamps as numerical Y-axis measures.
- Use the best logical `chart_type` based on the data ("Bar", "Line", "Pie", "Donut", "Number"). E.g. time-series data => "Line". Category distribution => "Bar" or "Donut".

Return ONLY a raw JSON object with this exact structure:
{
    "chart_type": "Bar",
    "x_col": "lead_owner",
    "y_series": [
        {"column": "lead_owner", "aggregation": "count"}
    ]
}

Another Example for Sales Data:
{
    "chart_type": "Line",
    "x_col": "transaction_date",
    "y_series": [
        {"column": "grand_total", "aggregation": "sum"}
    ]
}

Return strictly the JSON object. No markdown, no explanations.
"""
    
    user_prompt = f"SQL Query:\n{sql}\n\nData Sample (first few rows):\n{data_sample}"

    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0
        )

        raw_output = response.choices[0].message.content.strip()
        
        match = re.search(r"```json(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
        if match:
            raw_output = match.group(1).strip()
            
        import json
        return json.loads(raw_output)
    except Exception as e:
        print(f"[DEBUG] AI Insights Chart Config failed: {e}")
        return None
