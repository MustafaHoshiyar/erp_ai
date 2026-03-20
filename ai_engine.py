import os
import re
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from memory_manager import get_relevant_schema_context
from schema_fetcher import extract_available_table_names, get_local_schema

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

_FORECAST_TERMS = (
    "forecast",
    "predict",
    "projection",
    "projected",
    "estimate future",
    "next month",
    "next quarter",
    "next year",
)

_CHAT_PATTERNS = (
    r"^\s*(hi|hello|hey|good morning|good afternoon|good evening)\b.*$",
    r"^\s*(thanks|thank you|ok|okay|cool|great)\b.*$",
    r"^\s*(who are you|what('?s| is) your name|how are you|what can you do)\??\s*$",
)

_UNSUPPORTED_TERMS = (
    "write an email",
    "draft an email",
    "write a poem",
    "tell me a joke",
    "translate this",
    "generate image",
    "create image",
)

_REPORT_HINT_TERMS = (
    "report",
    "dashboard",
    "chart",
    "sales",
    "invoice",
    "purchase",
    "customer",
    "supplier",
    "employee",
    "user",
    "stock",
    "warehouse",
    "profit",
    "revenue",
    "expense",
    "maintenance",
    "payment",
    "order",
    "quotation",
    "lead",
    "opportunity",
    "count",
    "total",
    "sum",
    "show",
    "list",
)

_FOLLOW_UP_EDIT_TERMS = (
    "remove",
    "add",
    "change",
    "replace",
    "move",
    "sort",
    "filter",
    "keep",
    "hide",
)

_ORDINAL_COLUMN_PATTERN = re.compile(
    r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last|\d+(?:st|nd|rd|th))\s+(column|field)\b"
)

_VAGUE_FOLLOW_UP_PATTERN = re.compile(
    r"\b(change|replace|modify|update)\s+(it|this|that|the column|column|the field|field)\b"
)

_REORDER_TERMS = (
    "reorder level",
    "below their reorder level",
    "need replenishment",
)

_STOCK_EXHAUSTION_TERMS = (
    "run out of stock",
    "exhaust",
    "exhausted within",
    "stock will not last",
    "within the next 30 days",
    "past 3 months",
    "average daily sales",
    "replenishment soon",
)

_REVENUE_RANKING_TERMS = (
    "highest revenue",
    "sales revenue",
    "performing products",
    "top products",
    "top 10 performing products",
)

_SALESPERSON_TERMS = (
    "salesperson",
    "salespersons",
    "sales person",
    "sales persons",
)

_PAYMENT_COLLECTION_TERMS = (
    "payment received",
    "payments received",
    "payment amount collected",
    "customer payments",
    "received payments",
)

_SQL_TABLE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+`([^`]+)`|\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_SQL_TABLE_ALIAS_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+`([^`]+)`(?:\s+(?:AS\s+)?(?!ON\b|WHERE\b|JOIN\b|GROUP\b|ORDER\b|LIMIT\b)([A-Za-z_][A-Za-z0-9_]*))?",
    re.IGNORECASE,
)

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
- Reorder levels in ERPNext are warehouse-specific. If the live schema includes a reorder doctype, join it with `tabBin` using both item code and warehouse instead of assuming a `reorder_level` column exists on `tabItem`.
- For stock runout or replenishment-soon reports based on consumption rate, exclude already exhausted items unless the user explicitly asks for them. Prefer a filter like `tabBin.actual_qty > 0`.

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
- For TIME-SERIES FORECASTING, PREDICTIONS, or PROJECTIONS:
  - Do NOT attempt to calculate the forecast in SQL using recursive CTEs.
  - INSTEAD:
    1. Write a simple SQL query to extract the historical data grouped by a time period (e.g. Month, Week, Day).
    2. Group by the time period and SUM/AVG the target metric (e.g. `SELECT DATE_FORMAT(posting_date, '%Y-%m') AS 'Month', SUM(grand_total) AS 'Total' FROM ... GROUP BY Month`).
    3. You MUST include the exact string "FORECAST: <date_col>, <target_col>, <periods>" anywhere in your markdown answer/comment. Use 6 as the default periods if the user doesn't specify.
       Example: FORECAST: Month, Total, 6
  - The Python backend will catch this flag, execute your historical SQL, and run a statistical forecast model (Holt-Winters) on the results automatically.
- For any amount, total, or currency fields, return the RAW numeric values. Do NOT use FORMAT() or CONCAT() to add currency symbols in the SQL.
- NEVER use `FORMAT()` in SQL for ranking, ordering, or report output. Formatting belongs in the application layer, not the SQL query.
- Always group correctly when using aggregates.
- Avoid SELECT *. Return specific columns.
- When comparing monthly totals from two transaction tables, aggregate each source independently by month in subqueries or CTEs before joining. Never join raw invoice tables directly on a formatted month value because that inflates totals.

Security Rules:
- Only generate SELECT queries.
- Never generate DELETE, UPDATE, INSERT, DROP, ALTER, TRUNCATE, or any DDL.
- No subqueries that modify data.

Output Rules:
- Return ONLY raw SQL.
- Do NOT include explanations, markdown formatting, or conversational text (but SQL comments like /* NO_LIMIT */ ARE ALLOWED).
- SQL must start directly with SELECT or WITH.
- If the prompt context includes a discovered live relation plan, treat those join paths as authoritative for this tenant and do not invent an alternative relation unless the prompt explicitly requires it.

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

ERPNext Semantics To Respect:
- `sales_partner` is NOT the same as a salesperson. Only use `sales_partner` when the user explicitly asks for sales partners.
- If the user asks who created or recorded a document, prefer the document `owner`.
- If the user asks for salesperson performance or salesperson revenue, prefer an actual salesperson field such as `tabSales Team`.`sales_person` or a client-specific sales-person field already present in schema/context. Do not silently substitute `sales_partner`.
- For Payment Entry reports, submitted records should normally be filtered with `docstatus = 1`. Do not invent workflow statuses like `Completed` unless the schema or prompt explicitly requires them.
"""


def _contains_any(prompt_lower, terms) -> bool:
    return any(term in prompt_lower for term in terms)


def build_prompt_specific_guidance(user_prompt):
    prompt_lower = (user_prompt or "").strip().lower()
    guidance_lines = []

    if _contains_any(prompt_lower, _REORDER_TERMS):
        guidance_lines.extend(
            [
                "- This is a reorder-level report. Never assume `tabItem.reorder_level` exists.",
                "- Reorder levels are warehouse-specific, so if a reorder doctype exists in the live schema, join it with `tabBin` using both item code and warehouse.",
                "- If no reorder doctype or reorder rows exist in the live schema, do not invent one. Ask for clarification or return an empty-result-safe query only if the schema clearly supports it.",
            ]
        )

    if _contains_any(prompt_lower, _STOCK_EXHAUSTION_TERMS):
        guidance_lines.extend(
            [
                "- This is a stock runout or replenishment prediction prompt.",
                "- Exclude already exhausted or zero-stock rows unless the user explicitly asks for out-of-stock items.",
                "- Add a positive stock guard such as `tabBin.actual_qty > 0` before calculating days to exhaust.",
            ]
        )

    if _contains_any(prompt_lower, _REVENUE_RANKING_TERMS):
        guidance_lines.extend(
            [
                "- This prompt ranks revenue or monetary performance.",
                "- Return raw numeric aggregates like `SUM(amount)` and order by that numeric expression.",
                "- Do not use `FORMAT()` or alias-ordering on a formatted string for ranked revenue outputs.",
            ]
        )

    if _contains_any(prompt_lower, _SALESPERSON_TERMS):
        guidance_lines.extend(
            [
                "- Treat salesperson, sales partner, and document owner as different concepts.",
                "- If the prompt says created or recorded, prefer the document `owner` instead of `sales_partner`.",
                "- If the prompt asks for salesperson performance or revenue, prefer a real salesperson field such as `tabSales Team`.`sales_person` or a client-specific sales-person field from schema/context.",
                "- Never substitute `sales_partner` unless the prompt explicitly asks for sales partners.",
            ]
        )

    if _contains_any(prompt_lower, _PAYMENT_COLLECTION_TERMS):
        guidance_lines.extend(
            [
                "- This is a Payment Entry collection report.",
                "- Use `tabPayment Entry.docstatus = 1` for submitted entries instead of generic status text like `Completed`.",
                "- If the prompt is about users who recorded payments, group by `tabPayment Entry.owner`.",
                "- Avoid optional joins that can zero out the result set unless the prompt explicitly requires them.",
            ]
        )

    if (
        "sales vs purchases" in prompt_lower
        or "sales versus purchases" in prompt_lower
        or ("month-wise" in prompt_lower and "sales" in prompt_lower and "purchases" in prompt_lower)
    ):
        guidance_lines.extend(
            [
                "- This is a month-wise comparison between two transaction sources.",
                "- Aggregate sales and purchases independently by month in CTEs or subqueries before joining the monthly totals.",
                "- Do not join raw sales and purchase rows directly on formatted month values.",
            ]
        )

    if not guidance_lines:
        return ""

    return "Prompt-Specific Guidance:\n" + "\n".join(guidance_lines)


def _extract_referenced_tables(sql_text):
    if not sql_text:
        return []

    tables = []
    for match in _SQL_TABLE_PATTERN.finditer(sql_text):
        table_name = (match.group(1) or match.group(2) or "").strip()
        if table_name.lower().startswith("tab") and table_name not in tables:
            tables.append(table_name)
    return tables


def _find_unknown_tables(sql_text, local_schema):
    if not sql_text or not local_schema:
        return []

    available_tables = extract_available_table_names(local_schema)
    if not available_tables:
        return []

    return [table for table in _extract_referenced_tables(sql_text) if table not in available_tables]


def _parse_sql_response(raw_output, tokens_used, needs_forecast):
    detected_intent = "forecast" if needs_forecast else "report"

    match = re.search(r"```sql(.*?)```", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {
            "sql": match.group(1).strip(),
            "message": raw_output,
            "tokens_used": tokens_used,
            "needs_forecast": needs_forecast,
            "detected_intent": detected_intent,
        }

    match = re.search(r"(SELECT .*?;)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {
            "sql": match.group(1).strip(),
            "message": raw_output,
            "tokens_used": tokens_used,
            "needs_forecast": needs_forecast,
            "detected_intent": detected_intent,
        }

    match = re.search(r"(SELECT .*?$)", raw_output, re.IGNORECASE | re.DOTALL)
    if match:
        return {
            "sql": match.group(1).strip(),
            "message": raw_output,
            "tokens_used": tokens_used,
            "needs_forecast": needs_forecast,
            "detected_intent": detected_intent,
        }

    return {
        "sql": None,
        "message": raw_output,
        "tokens_used": tokens_used,
        "needs_forecast": False,
        "detected_intent": "report",
    }


def _extract_table_aliases(sql_text):
    aliases = {}
    for table_name, alias in _SQL_TABLE_ALIAS_PATTERN.findall(sql_text or ""):
        aliases[table_name] = alias or table_name
    return aliases


def _find_relation_constraint_violations(sql_text, relation_constraints):
    if not sql_text or not relation_constraints:
        return []

    aliases = _extract_table_aliases(sql_text)
    violations = []

    for constraint in relation_constraints:
        if constraint.get("kind") != "child_table":
            continue

        child_table = constraint["child_table"]
        parent_table = constraint["parent_table"]
        parent_doctype = constraint["parent_doctype"]
        child_ref = aliases.get(child_table, child_table)
        parent_ref = aliases.get(parent_table, parent_table)

        parent_join_pattern = re.compile(
            rf"(?i)(`{re.escape(child_table)}`|{re.escape(child_ref)})\s*\.\s*`?parent`?\s*=\s*"
            rf"(`{re.escape(parent_table)}`|{re.escape(parent_ref)})\s*\.\s*`?name`?"
        )
        parenttype_pattern = re.compile(
            rf"(?i)(`{re.escape(child_table)}`|{re.escape(child_ref)})\s*\.\s*`?parenttype`?\s*=\s*'{re.escape(parent_doctype)}'"
        )

        if not parent_join_pattern.search(sql_text) or not parenttype_pattern.search(sql_text):
            violations.append(constraint["message"])

    return violations


def _table_ref_for_sql(table_name, aliases):
    alias = aliases.get(table_name)
    if alias and alias != table_name:
        return alias
    return f"`{table_name}`"


def _repair_child_table_joins(sql_text, relation_constraints):
    if not sql_text or not relation_constraints:
        return sql_text

    repaired_sql = sql_text
    aliases = _extract_table_aliases(repaired_sql)

    for constraint in relation_constraints:
        if constraint.get("kind") != "child_table":
            continue

        child_table = constraint["child_table"]
        parent_table = constraint["parent_table"]
        parent_doctype = constraint["parent_doctype"]
        child_alias = aliases.get(child_table)
        child_table_pattern = re.escape(child_table)
        alias_pattern = ""
        if child_alias and child_alias != child_table:
            alias_pattern = rf"(?:\s+(?:AS\s+)?{re.escape(child_alias)})?"

        join_pattern = re.compile(
            rf"(?is)(JOIN\s+`{child_table_pattern}`{alias_pattern}\s+ON\s+)(.*?)(?=\bJOIN\b|\bWHERE\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)"
        )
        match = join_pattern.search(repaired_sql)
        if not match:
            continue

        join_prefix = match.group(1)
        on_clause = match.group(2).strip()
        child_ref = _table_ref_for_sql(child_table, aliases)
        parent_ref = _table_ref_for_sql(parent_table, aliases)

        existing_conditions = [
            condition.strip()
            for condition in re.split(r"(?i)\s+AND\s+", on_clause)
            if condition.strip()
        ]

        filtered_conditions = []
        for condition in existing_conditions:
            normalized = condition.lower()
            if f"{child_table.lower()}`.`parent" in normalized or f"{child_table.lower()}`.`parenttype" in normalized:
                continue
            if child_alias and child_alias != child_table:
                if f"{child_alias.lower()}.`parent" in normalized or f"{child_alias.lower()}.`parenttype" in normalized:
                    continue
            filtered_conditions.append(condition)

        mandatory_conditions = [
            f"{child_ref}.`parent` = {parent_ref}.`name`",
            f"{child_ref}.`parenttype` = '{parent_doctype}'",
        ]
        rebuilt_on_clause = " AND ".join(mandatory_conditions + filtered_conditions)
        suffix = repaired_sql[match.end():]
        if suffix and not suffix[0].isspace():
            suffix = " " + suffix
        repaired_sql = repaired_sql[:match.start()] + join_prefix + rebuilt_on_clause + suffix

    return repaired_sql


def _history_contains_sql(history) -> bool:
    if not history:
        return False
    for item in reversed(history):
        content = str(item.get("content", ""))
        if "```sql" in content.lower() or content.strip().upper().startswith(("SELECT ", "WITH ")):
            return True
    return False


def _needs_follow_up_clarification(prompt_lower, history) -> bool:
    has_sql_history = _history_contains_sql(history)
    has_follow_up_edit = any(term in prompt_lower for term in _FOLLOW_UP_EDIT_TERMS)

    if not has_follow_up_edit:
        return False

    if not has_sql_history:
        return not any(term in prompt_lower for term in _REPORT_HINT_TERMS)

    if _ORDINAL_COLUMN_PATTERN.search(prompt_lower):
        has_explicit_replacement = any(
            cue in prompt_lower for cue in (" to ", " with ", " instead of ", " named ", " called ", " by ")
        )
        if not has_explicit_replacement:
            return True

    if _VAGUE_FOLLOW_UP_PATTERN.search(prompt_lower):
        return True

    short_follow_up = len(prompt_lower.split()) <= 5
    if short_follow_up and any(token in prompt_lower for token in ("column", "field", "it", "this", "that")):
        if " by " in prompt_lower:
            return False
        return True

    return False


def classify_prompt_intent(user_prompt, history=None):
    prompt = (user_prompt or "").strip()
    prompt_lower = prompt.lower()

    if not prompt:
        return {"intent": "clarification_needed"}

    if any(term in prompt_lower for term in _FORECAST_TERMS):
        return {"intent": "forecast"}

    if any(re.match(pattern, prompt_lower) for pattern in _CHAT_PATTERNS):
        return {"intent": "chat"}

    if any(term in prompt_lower for term in _UNSUPPORTED_TERMS) and not any(term in prompt_lower for term in _REPORT_HINT_TERMS):
        return {"intent": "unsupported"}

    if _needs_follow_up_clarification(prompt_lower, history):
        return {"intent": "clarification_needed"}

    return {"intent": "report"}


def build_non_report_response(user_prompt, intent):
    prompt_lower = (user_prompt or "").strip().lower()

    if intent == "chat":
        if "your name" in prompt_lower or "who are you" in prompt_lower:
            return "I am your ERP AI reporting assistant. I can help build ERPNext reports, dashboards, and forecasting queries."
        if "how are you" in prompt_lower:
            return "I am ready to help. Ask me for an ERPNext report, dashboard, KPI, or forecast."
        if "thank" in prompt_lower:
            return "You're welcome. Ask me for any ERPNext report or dashboard when you're ready."
        return "Hello. I can help you build ERPNext reports, dashboards, KPIs, and forecasting queries."

    if intent == "clarification_needed":
        if _ORDINAL_COLUMN_PATTERN.search(prompt_lower):
            return "I need one detail before I change that report. Which column do you want there instead, and are you counting the visible Sr column when you say the third column?"
        return "I can help with ERPNext reporting, but I need a bit more context. Tell me which report or dataset you want to change, or describe the result you want."

    return "I am focused on ERPNext reporting and analytics. Ask me for a report, KPI, dashboard, trend, comparison, or forecast from your ERP data."

def generate_sql(user_prompt, history=None, client_id="DEMO_CLIENT_123", currency="USD", currency_symbol="$"):
    memory_context = get_relevant_schema_context(client_id, user_prompt)
    
    dynamic_system_prompt = SYSTEM_PROMPT.format(currency=currency)
    prompt_specific_guidance = build_prompt_specific_guidance(user_prompt)
    
    from schema_router import get_optimized_schema_context
    from schema_planner import build_relation_constraints
    local_schema = None
    try:
        local_schema = get_local_schema(client_id)
    except Exception as e:
        print(f"[AI Engine] Could not load local schema for router: {e}")
        
    filtered_schema, pass1_tokens, required_tables = get_optimized_schema_context(
        user_prompt,
        GLOBAL_SCHEMA,
        local_schema,
        client_id=client_id,
    )
    if local_schema is not None:
        local_schema = get_local_schema(client_id)
    relation_constraints = build_relation_constraints(required_tables, local_schema) if local_schema else []
    dynamic_system_prompt += f"\n\n{filtered_schema}"
    
    if memory_context:
        dynamic_system_prompt += f"\n\n{memory_context}"

    if prompt_specific_guidance:
        dynamic_system_prompt += f"\n\n{prompt_specific_guidance}"

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

    result = _parse_sql_response(raw_output, tokens_used, needs_forecast)
    unknown_tables = _find_unknown_tables(result.get("sql"), local_schema)
    if unknown_tables:
        unknown_list = ", ".join(sorted(unknown_tables))
        clarification_message = (
            "I found a schema mismatch before running the report. "
            f"These tables are not present in your live ERP schema: {unknown_list}. "
            "Please refresh the schema or tell me which doctype stores that data in your ERP so I can generate the correct query."
        )
        return {
            "sql": None,
            "message": clarification_message,
            "tokens_used": tokens_used,
            "needs_forecast": False,
            "detected_intent": "clarification_needed",
            "model_used": AI_MODEL,
            "routing_tables": required_tables,
        }

    relation_violations = _find_relation_constraint_violations(result.get("sql"), relation_constraints)
    if relation_violations:
        deterministically_repaired_sql = _repair_child_table_joins(result.get("sql"), relation_constraints)
        deterministic_violations = _find_relation_constraint_violations(
            deterministically_repaired_sql,
            relation_constraints,
        )
        deterministic_unknown_tables = _find_unknown_tables(deterministically_repaired_sql, local_schema)
        if deterministically_repaired_sql != result.get("sql") and not deterministic_violations and not deterministic_unknown_tables:
            return {
                "sql": deterministically_repaired_sql,
                "message": deterministically_repaired_sql,
                "tokens_used": tokens_used,
                "needs_forecast": needs_forecast,
                "detected_intent": result.get("detected_intent", "report"),
                "model_used": AI_MODEL,
                "routing_tables": required_tables,
            }

        repair_instruction = (
            "Your previous SQL violated the live relation plan for this tenant.\n"
            "Fix the SQL and return raw SQL only.\n"
            "Mandatory fixes:\n- " + "\n- ".join(relation_violations)
        )
        repair_messages = list(messages)
        repair_messages.append({"role": "assistant", "content": raw_output})
        repair_messages.append({"role": "user", "content": repair_instruction})

        repair_response = client.chat.completions.create(
            model=AI_MODEL,
            messages=repair_messages,
            temperature=0
        )
        repair_output = repair_response.choices[0].message.content.strip()
        repair_tokens = repair_response.usage.total_tokens if hasattr(repair_response, "usage") and repair_response.usage else 0
        tokens_used += repair_tokens
        repair_needs_forecast = "FORECAST:" in repair_output
        repaired_result = _parse_sql_response(repair_output, tokens_used, repair_needs_forecast)

        repaired_unknown_tables = _find_unknown_tables(repaired_result.get("sql"), local_schema)
        repaired_relation_violations = _find_relation_constraint_violations(
            repaired_result.get("sql"),
            relation_constraints,
        )

        if not repaired_unknown_tables and not repaired_relation_violations:
            return repaired_result

        clarification_message = (
            "I found a schema relation mismatch before running the report. "
            + " ".join(relation_violations)
            + " Please tell me if you want this report based on child reorder rows, or point me to the exact doctype/field to use."
        )
        return {
            "sql": None,
            "message": clarification_message,
            "tokens_used": tokens_used,
            "needs_forecast": False,
            "detected_intent": "clarification_needed",
            "model_used": AI_MODEL,
            "routing_tables": required_tables,
        }

    result["model_used"] = AI_MODEL
    result["routing_tables"] = required_tables
    return result


def normalize_sql_with_live_schema(sql_text, required_tables=None, client_id="DEMO_CLIENT_123"):
    if not sql_text:
        return sql_text

    try:
        from schema_planner import build_relation_constraints
        from schema_fetcher import ensure_doctype_details

        local_schema = get_local_schema(client_id)
        referenced_tables = required_tables or _extract_referenced_tables(sql_text)
        local_schema = ensure_doctype_details(referenced_tables, local_schema, client_id=client_id)
        relation_constraints = build_relation_constraints(referenced_tables, local_schema)

        if _find_unknown_tables(sql_text, local_schema):
            return sql_text

        repaired_sql = _repair_child_table_joins(sql_text, relation_constraints)
        if _find_relation_constraint_violations(repaired_sql, relation_constraints):
            return sql_text

        return repaired_sql
    except Exception as e:
        print(f"[AI Engine] SQL normalization skipped: {e}")
        return sql_text


def generate_chart_config(columns, data_sample, dataset_summary=None, currency="USD", currency_symbol="$"):
    system_prompt = """
You are an expert data visualization and dashboard assistant.
Given a list of column names, their inferred data types, a small JSON sample of the data, and an overall dataset summary (total rows and sums of numerical columns), your task is to generate a comprehensive JSON dashboard configuration.

Your output MUST be a single raw JSON object with the following structure:
{{
  "kpis": [
    {{
      "label": "Total Orders",
      "value": "66",
      "trend_percentage": "24.53",
      "trend_direction": "up"
    }}
  ],
  "chart": {{
     // Valid Chart.js configuration object here
  }}
}}

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

FORECAST VISUALIZATION (SPECIAL CASE):
If the data contains a column named 'Type' with values 'Actual' and 'Forecast', you MUST:
1. Use 'line' as the chart type.
2. Ensure the 'Actual' data and 'Forecast' data are plotted correctly.
3. For the 'Forecast' series, you should ideally use a different color or style (like a dashed line) if the Chart.js version supports it via `borderDash: [5, 5]`.
4. If the data is provided in a single list with 'Type' column, you may need to map it to two separate datasets or one continuous dataset with segment styling.

Return ONLY the raw JSON object, starting with `{{` and ending with `}}`.
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
