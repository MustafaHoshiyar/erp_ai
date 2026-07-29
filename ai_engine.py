import os
import re
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from memory_manager import get_relevant_schema_context
from schema_fetcher import extract_available_table_names, get_local_schema
from database import SessionLocal, ClientSystemPrompt, ClientFeatureFlag

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o")
# _SALES_INVOICE_FOLLOWUP_GUARDRAIL_CLIENTS replaced by ClientFeatureFlag table in DB
# _SALES_INVOICE_FOLLOWUP_GUARDRAIL_CLIENTS = {
#     client.strip()
#     for client in os.getenv("SALES_INVOICE_FOLLOWUP_GUARDRAIL_CLIENTS", "").split(",")
#     if client.strip()
# }

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

_CONTACT_DETAIL_TERMS = (
    "contact detail",
    "contact details",
    "contact of",
    "phone number",
    "email address",
    "contact number",
    "address of",
)

_SUMMARY_ROW_TERMS = (
    "grand total row",
    "grand total",
    "total row",
    "summary row",
    "totals row",
    "footer row",
)

_SQL_TABLE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+`([^`]+)`|\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_SQL_TABLE_ALIAS_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+`([^`]+)`(?:\s+(?:AS\s+)?(?!ON\b|WHERE\b|JOIN\b|GROUP\b|ORDER\b|LIMIT\b)([A-Za-z_][A-Za-z0-9_]*))?",
    re.IGNORECASE,
)
_RELATION_CLARIFICATION_PATTERN = re.compile(
    r"`(?P<child>tab[^`]+)` is a child table of `(?P<parent>tab[^`]+)`",
    re.IGNORECASE,
)
_CHILD_TABLE_CONFIRM_TERMS = (
    "use child table",
    "use the child table",
    "use child tables",
    "use the child tables",
    "use child row",
    "use the child row",
    "use child rows",
    "use the child rows",
    "child table rows",
    "child rows",
)
_SHORT_AFFIRMATION_TERMS = (
    "yes",
    "y",
    "yeah",
    "yep",
    "sure",
    "ok",
    "okay",
    "proceed",
    "go ahead",
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
- When the user provides a human-readable party, customer, supplier, item, counter, or contact name, prefer case-insensitive matching on label-like fields (for example `LOWER(column) = LOWER('value')`) unless the prompt clearly refers to an exact code or ID field.
- For TIME-SERIES FORECASTING, PREDICTIONS, or PROJECTIONS:
  - Do NOT attempt to calculate the forecast in SQL using recursive CTEs.
  - INSTEAD:
    1. Write a simple SQL query to extract the historical data grouped by a time period (e.g. Month, Week, Day).
    2. Group by the time period and SUM/AVG the target metric (e.g. `SELECT DATE_FORMAT(posting_date, '%Y-%m') AS 'Month', SUM(grand_total) AS 'Total' FROM ... GROUP BY Month`).
    3. You MUST include the exact string "FORECAST: <date_col>, <target_col>, <periods>" in your response OUTSIDE of the SQL code block. Use 6 as the default periods if the user doesn't specify.
    4. The <date_col> and <target_col> MUST exactly match the aliases you used in your SQL query (e.g. if you wrote `SUM(amount) AS Total`, use `FORECAST: Month, Total, 6`).
       Example: 
       ```sql
       SELECT DATE_FORMAT(posting_date, '%Y-%m') AS 'Month', SUM(grand_total) AS 'Total' FROM ... GROUP BY Month
       ```
       FORECAST: Month, Total, 6
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

# Client-Specific Rules moved to ClientSystemPrompt table in DB
# Client-Specific Hard Rule Example (now handled dynamically):
# - For maintenance prompts about records that are "scheduled", "upcoming", "next week", "this week"... prefer `tabMaintenance` over `tabMaintenance Schedule`.

ERPNext Semantics To Respect:
- `sales_partner` is NOT the same as a salesperson. Only use `sales_partner` when the user explicitly asks for sales partners.
- If the user asks who created or recorded a document, prefer the document `owner`.
- If the user asks for salesperson performance or salesperson revenue, prefer an actual salesperson field such as `tabSales Team`.`sales_person` or a client-specific sales-person field already present in schema/context. Do not silently substitute `sales_partner`.
- For Payment Entry reports, submitted records should normally be filtered with `docstatus = 1`. Do not invent workflow statuses like `Completed` unless the schema or prompt explicitly requires them.
"""


_V14_SCHEMA_NOTES = """
[ERPNext v14 Schema Notes]
- Stock batches are tracked via `batch_no` column directly on `tabStock Ledger Entry`.
- Serial numbers are stored in the `serial_no` column directly on `tabStock Ledger Entry`.
- Dunning documents link to a single Sales Invoice via a direct link field.
- Event cancellation is tracked in the `event_type` field (value: 'Cancelled').
- Cashflow Mapper doctype is available for cashflow-related queries.
"""

_V15_SCHEMA_NOTES = """
[ERPNext v15 Schema Notes]
- Stock batches for NEW transactions are stored in `tabSerial and Batch Entry`
  (child of `tabSerial and Batch Bundle`). Legacy entries still have `batch_no`
  directly on `tabStock Ledger Entry`. For safest results, check `tabSerial and Batch Bundle` first.
- Serial numbers for new transactions follow the same `tabSerial and Batch Bundle` pattern.
- Dunning contains a child table of overdue payments, each linking to a separate Sales Invoice.
- Event cancellation is tracked in the `status` field (value: 'Cancelled').
- Cashflow Mapper has been deprecated and removed.
- Account types include: Current Asset, Current Liability, Direct Income, Indirect Income.
"""


def _get_version_schema_notes(erp_version: str) -> str:
    if erp_version == "15":
        return _V15_SCHEMA_NOTES
    elif erp_version == "14":
        return _V14_SCHEMA_NOTES
    return ""


def _contains_any(prompt_lower, terms) -> bool:
    return any(term in prompt_lower for term in terms)


def _client_has_feature_flag(client_id: str, feature_key: str) -> bool:
    if not client_id:
        return False
    db = SessionLocal()
    try:
        flag = db.query(ClientFeatureFlag).filter(
            ClientFeatureFlag.client_id == client_id,
            ClientFeatureFlag.feature_key == feature_key,
            ClientFeatureFlag.is_enabled == True
        ).first()
        return flag is not None
    except Exception as e:
        print(f"[AI Engine] Error checking feature flag {feature_key}: {e}")
        return False
    finally:
        db.close()

def _get_dynamic_system_prompt_segments(client_id: str, app_name: str = None) -> str:
    if not client_id:
        return ""
    db = SessionLocal()
    try:
        from sqlalchemy import or_, func
        query = db.query(ClientSystemPrompt).filter(
            or_(
                ClientSystemPrompt.client_id == client_id,
                ClientSystemPrompt.client_id == "GLOBAL"
            ),
            ClientSystemPrompt.is_active == True
        )
        if app_name:
            # Load both global (null app) and app-specific segments
            query = query.filter(
                or_(
                    func.lower(ClientSystemPrompt.app_name) == func.lower(app_name),
                    ClientSystemPrompt.app_name == None
                )
            )
        else:
            query = query.filter(ClientSystemPrompt.app_name == None)
            
        segments = query.all()
        if not segments:
            return ""
        
        lines = ["\n### DYNAMIC CLIENT-SPECIFIC INSTRUCTIONS ###"]
        for s in segments:
            lines.append(f"Rule ({s.segment_key}): {s.prompt_text}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[AI Engine] Error loading dynamic prompt segments: {e}")
        return ""
    finally:
        db.close()


def build_prompt_specific_guidance(user_prompt, history=None, client_id="DEMO_CLIENT_123", app_name=None):
    prompt_lower = (user_prompt or "").strip().lower()
    guidance_lines = []
    last_sql = _extract_last_sql_from_history(history)
    client_guardrail_enabled = _client_has_feature_flag(client_id, "sales_invoice_followup_guardrail")

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

    if _contains_any(prompt_lower, _CONTACT_DETAIL_TERMS):
        guidance_lines.extend(
            [
                "- This is a contact or address lookup prompt.",
                "- Prefer `tabContact` plus the appropriate optional child tables such as `tabContact Email` and `tabContact Phone` for email/phone details.",
                "- If the user asks for an address, prefer `tabAddress` and the correct link table instead of forcing contact email/phone joins.",
                "- When using `tabContact Email` or `tabContact Phone`, keep them as optional child-table joins through `parent` and `parenttype`.",
                "- Match the requested party name case-insensitively on a human-readable field unless the prompt explicitly gives a code or ID.",
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

    if client_guardrail_enabled and last_sql and any(term in prompt_lower for term in _FOLLOW_UP_EDIT_TERMS):
        guidance_lines.extend(
            [
                "- This is a follow-up edit to an existing SQL report.",
                "- Preserve the existing FROM, JOIN, WHERE, and row granularity unless the user explicitly asks to change the dataset.",
                "- Do not add new one-to-many joins just to compute totals, add labels, or format the output.",
            ]
        )

    if client_guardrail_enabled and _contains_any(prompt_lower, _SUMMARY_ROW_TERMS):
        guidance_lines.extend(
            [
                "- This prompt asks for a summary/footer/grand-total row appended to a detailed result set.",
                "- Reuse the same filtered base dataset for both the detail rows and the summary row, preferably with a CTE or derived table.",
                "- If the detail rows are document-level, aggregate document fields from the document table directly.",
                "- Avoid one-to-many joins that can duplicate parent documents and inflate row counts or sums.",
            ]
        )
        if "sales invoice" in prompt_lower or (last_sql and "tabSales Invoice" in last_sql):
            guidance_lines.append(
                "- For Sales Invoice header reports, do not join `tabSales Invoice Item` unless the user explicitly needs line-item fields, filters, or item-level aggregation."
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
    raw_output = (raw_output or "").strip()

    def build_result(sql_text=None):
        return {
            "sql": sql_text,
            "message": raw_output,
            "tokens_used": tokens_used.get("total", 0),
            "input_tokens": tokens_used.get("prompt", 0),
            "output_tokens": tokens_used.get("completion", 0),
            "needs_forecast": needs_forecast if sql_text else False
        }

    def _apply_safety_repairs(sql: str) -> str:
        """Fixes common stubborn typos that the LLM makes regardless of prompt instructions."""
        if not sql:
            return sql
        
        # 1. Fix the famous 'DATE_FORMAT' trailing backtick error (e.g. '%Y-%m-01`)
        sql = sql.replace("'%Y-%m-01`", "'%Y-%m-01'")
        sql = sql.replace("'%Y-%m-d`", "'%Y-%m-%d'")
        sql = sql.replace("'%Y-%m`", "'%Y-%m'")
        
        # 3. Strip any accidental FORECAST flag that leaked into the SQL
        if "FORECAST:" in sql:
            sql = re.sub(r"FORECAST:\s*.+?,\s*.+?,\s*\d+", "", sql, flags=re.IGNORECASE).strip()
        
        return sql

    def extract_sql_candidate(text):
        if not text:
            return None

        fenced_match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
        if fenced_match:
            candidate = fenced_match.group(1).strip()
            if candidate.upper().startswith(("SELECT ", "WITH ")):
                return candidate

        # Stricter fallback: only catch if SELECT/WITH appears at the START of a line, avoiding conversational "with"
        direct_match = re.search(r"(?m)^\s*(SELECT|WITH)\b", text, re.IGNORECASE)
        if not direct_match:
            return None

        candidate = text[direct_match.start():].strip()
        candidate = re.sub(r"```+$", "", candidate).strip()

        stop_markers = [
            r"(?i)\n(?:Explanation|Notes?|Reasoning|Summary)\s*:",
            r"(?i)\n(?:This query|Here(?:'s| is) the query)\b",
        ]
        for marker in stop_markers:
            split_parts = re.split(marker, candidate, maxsplit=1)
            candidate = split_parts[0].strip()

        # Final sanity check: if the extracted candidate is very clearly mostly English, reject it.
        # A valid query must have FROM or SELECT and not just be a paragraph starting with "With..."
        if candidate and not re.search(r"\bFROM\b", candidate, re.IGNORECASE):
            return None

        return candidate or None

    sql_candidate = extract_sql_candidate(raw_output)
    if sql_candidate:
        return build_result(_apply_safety_repairs(sql_candidate))

    return build_result(None)


def _extract_table_aliases(sql_text):
    aliases = {}
    for table_name, alias in _SQL_TABLE_ALIAS_PATTERN.findall(sql_text or ""):
        aliases[table_name] = alias or table_name
    return aliases


def _table_ref_pattern(table_name, alias_name):
    patterns = []
    if table_name:
        patterns.append(rf"`{re.escape(table_name)}`")
    if alias_name and alias_name != table_name:
        patterns.append(re.escape(alias_name))
    if not patterns:
        return r"(?!x)x"
    return "(?:" + "|".join(patterns) + ")"


def _condition_mentions_field_ref(condition_text, table_name, alias_name, field_name):
    ref_pattern = _table_ref_pattern(table_name, alias_name)
    return re.search(
        rf"(?i){ref_pattern}\s*\.\s*`?{re.escape(field_name)}`?",
        condition_text or "",
    ) is not None


def _extract_last_user_prompt(history):
    if not history:
        return None

    for item in reversed(history):
        if str(item.get("role", "")).lower() != "user":
            continue
        content = str(item.get("content", "")).strip()
        if content:
            return content

    return None


def _extract_recent_relation_clarification(history):
    if not history:
        return None

    for item in reversed(history):
        if str(item.get("role", "")).lower() != "assistant":
            continue

        content = str(item.get("content", "")).strip()
        if "schema relation mismatch before running the report" not in content.lower():
            continue

        matches = [
            {"child_table": match.group("child"), "parent_table": match.group("parent")}
            for match in _RELATION_CLARIFICATION_PATTERN.finditer(content)
        ]
        return {
            "message": content,
            "relations": matches,
        }

    return None


def _is_child_table_confirmation(user_prompt, history):
    prompt_lower = (user_prompt or "").strip().lower()
    if not prompt_lower:
        return False

    if not _extract_recent_relation_clarification(history):
        return False

    if any(term in prompt_lower for term in _CHILD_TABLE_CONFIRM_TERMS):
        return True

    compact_prompt = re.sub(r"[^\w\s]", " ", prompt_lower)
    compact_prompt = re.sub(r"\s+", " ", compact_prompt).strip()
    if compact_prompt in _SHORT_AFFIRMATION_TERMS:
        return True

    return False


def _build_effective_user_prompt(user_prompt, history):
    if not _is_child_table_confirmation(user_prompt, history):
        return user_prompt

    original_request = _extract_last_user_prompt(history)
    clarification = _extract_recent_relation_clarification(history) or {}
    if not original_request:
        return user_prompt

    lines = [
        "This is a follow-up clarification for the immediately previous report request.",
        f"Original report request: {original_request}",
        f"User clarification: {user_prompt}",
        "Generate the SQL for the original request using child-table row granularity where needed by the live schema.",
        "Do not ask the same child-table clarification again.",
    ]

    for relation in clarification.get("relations", []):
        parent_table = relation["parent_table"]
        parent_doctype = parent_table[3:] if parent_table.startswith("tab") else parent_table
        lines.append(
            f"- `{relation['child_table']}` must join to `{parent_table}` with "
            f"`{relation['child_table']}`.`parent` = `{parent_table}`.`name` "
            f"and `{relation['child_table']}`.`parenttype` = '{parent_doctype}'."
        )

    return "\n".join(lines)


def _build_relation_clarification_message(relation_violations, relation_constraints):
    violated_constraints = []
    violation_set = set(relation_violations or [])
    for constraint in relation_constraints or []:
        if constraint.get("message") in violation_set:
            violated_constraints.append(constraint)

    child_tables = []
    for constraint in violated_constraints:
        child_table = constraint.get("child_table")
        if child_table and child_table not in child_tables:
            child_tables.append(child_table)

    if len(child_tables) == 1:
        child_hint = f"Please tell me if you want this report based on `{child_tables[0]}` child rows, or point me to the exact doctype/field to use."
    elif child_tables:
        child_list = ", ".join(f"`{table_name}`" for table_name in child_tables)
        child_hint = f"Please tell me if you want this report based on these child rows: {child_list}, or point me to the exact doctype/field to use."
    else:
        child_hint = "Please tell me if you want this report based on child table rows, or point me to the exact doctype/field to use."

    return (
        "I found a schema relation mismatch before running the report. "
        + " ".join(relation_violations)
        + " "
        + child_hint
    )


def _find_relation_constraint_violations(sql_text, relation_constraints):
    if not sql_text or not relation_constraints:
        return []

    aliases = _extract_table_aliases(sql_text)
    violations = []

    for constraint in relation_constraints:
        if constraint.get("kind") != "child_table":
            continue

        child_table = constraint["child_table"]
        if f"`{child_table}`" not in sql_text:
            continue
        parent_table = constraint["parent_table"]
        if f"`{parent_table}`" not in sql_text:
            continue
        parent_doctype = constraint["parent_doctype"]
        child_ref = aliases.get(child_table, child_table)
        parent_ref = aliases.get(parent_table, parent_table)
        child_ref_pattern = _table_ref_pattern(child_table, child_ref)
        parent_ref_pattern = _table_ref_pattern(parent_table, parent_ref)

        parent_join_pattern = re.compile(
            rf"(?i)(?:"
            rf"{child_ref_pattern}\s*\.\s*`?parent`?\s*=\s*{parent_ref_pattern}\s*\.\s*`?name`?"
            rf"|"
            rf"{parent_ref_pattern}\s*\.\s*`?name`?\s*=\s*{child_ref_pattern}\s*\.\s*`?parent`?"
            rf")"
        )
        parenttype_pattern = re.compile(
            rf"(?i)(?:"
            rf"{child_ref_pattern}\s*\.\s*`?parenttype`?\s*=\s*'{re.escape(parent_doctype)}'"
            rf"|"
            rf"'{re.escape(parent_doctype)}'\s*=\s*{child_ref_pattern}\s*\.\s*`?parenttype`?"
            rf")"
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
        if f"`{child_table}`" not in repaired_sql:
            continue
        parent_table = constraint["parent_table"]
        if f"`{parent_table}`" not in repaired_sql:
            continue
        parent_doctype = constraint["parent_doctype"]
        child_alias = aliases.get(child_table)
        child_table_pattern = re.escape(child_table)
        alias_pattern = ""
        if child_alias and child_alias != child_table:
            alias_pattern = rf"(?:\s+(?:AS\s+)?{re.escape(child_alias)})?"

        join_pattern = re.compile(
            rf"(?is)(((?:LEFT|RIGHT|INNER|OUTER|FULL|CROSS)\s+)*JOIN\s+`{child_table_pattern}`{alias_pattern}\s+ON\s+)(.*?)(?=\bJOIN\b|\bWHERE\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)"
        )
        match = join_pattern.search(repaired_sql)
        if not match:
            continue

        join_prefix = match.group(1)
        on_clause = match.group(3).strip()
        child_ref = _table_ref_for_sql(child_table, aliases)
        parent_ref = _table_ref_for_sql(parent_table, aliases)

        existing_conditions = [
            condition.strip()
            for condition in re.split(r"(?i)\s+AND\s+", on_clause)
            if condition.strip()
        ]

        filtered_conditions = []
        for condition in existing_conditions:
            if _condition_mentions_field_ref(condition, child_table, child_alias, "parent"):
                continue
            if _condition_mentions_field_ref(condition, child_table, child_alias, "parenttype"):
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


def _remove_redundant_sales_invoice_item_joins(sql_text):
    if not sql_text or "`tabSales Invoice Item`" not in sql_text:
        return sql_text

    join_pattern = re.compile(
        r"(?is)\s+JOIN\s+`tabSales Invoice Item`(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?\s+ON\s+.*?(?=\bJOIN\b|\bWHERE\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bUNION\s+ALL\b|$)"
    )
    repaired_sql = sql_text

    for match in reversed(list(join_pattern.finditer(repaired_sql))):
        alias = match.group(1)
        candidate_sql = repaired_sql[:match.start()] + repaired_sql[match.end():]
        sql_without_item_joins = join_pattern.sub("", candidate_sql)

        reference_patterns = [re.compile(r"(?i)`tabSales Invoice Item`\s*\.")]
        if alias:
            reference_patterns.append(re.compile(rf"(?i)\b{re.escape(alias)}\s*\."))

        if any(pattern.search(sql_without_item_joins) for pattern in reference_patterns):
            continue

        repaired_sql = candidate_sql

    repaired_sql = re.sub(
        r"(`[^`]+`)(WHERE|GROUP\s+BY|ORDER\s+BY|LIMIT|UNION\s+ALL)",
        r"\1 \2",
        repaired_sql,
        flags=re.IGNORECASE,
    )
    return repaired_sql


def _extract_last_sql_from_history(history):
    if not history:
        return None

    for item in reversed(history):
        content = str(item.get("content", "")).strip()
        if not content:
            continue

        fenced_match = re.search(r"```sql\s*(.*?)```", content, re.IGNORECASE | re.DOTALL)
        if fenced_match:
            return fenced_match.group(1).strip()

        if content.upper().startswith(("SELECT ", "WITH ")):
            return content

    return None


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

    if history and any(term in prompt_lower for term in ("what logic", "how did you", "explain", "logic behind", "can you explain")):
        return {"intent": "chat"}

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

def generate_sql(user_prompt, history=None, client_id="DEMO_CLIENT_123", app_name=None, currency="USD", currency_symbol="$", erp_version=None):
    effective_user_prompt = _build_effective_user_prompt(user_prompt, history)
    memory_context = get_relevant_schema_context(client_id, effective_user_prompt, app_name=app_name)
    
    dynamic_system_prompt = SYSTEM_PROMPT.format(currency=currency)
    
    # Inject ERPNext version-specific schema notes
    if erp_version:
        version_notes = _get_version_schema_notes(erp_version)
        if version_notes:
            dynamic_system_prompt += f"\n\n{version_notes}"
    
    # Inject Dynamic Database-stored Prompt Segments
    dynamic_segments = _get_dynamic_system_prompt_segments(client_id, app_name)
    if dynamic_segments:
        dynamic_system_prompt += f"\n{dynamic_segments}"
        
    prompt_specific_guidance = build_prompt_specific_guidance(effective_user_prompt, history, client_id, app_name)
    
    from schema_router import get_optimized_schema_context
    from schema_planner import build_relation_constraints
    local_schema = None
    try:
        local_schema = get_local_schema(client_id)
    except Exception as e:
        print(f"[AI Engine] Could not load local schema for router: {e}")
        
    filtered_schema, pass1_tokens, required_tables = get_optimized_schema_context(
        effective_user_prompt,
        GLOBAL_SCHEMA,
        local_schema,
        client_id=client_id,
    )
    if local_schema:
        relation_constraints = build_relation_constraints(required_tables, local_schema)
    else:
        relation_constraints = []
    dynamic_system_prompt += f"\n\n{filtered_schema}"
    
    if memory_context:
        dynamic_system_prompt += f"\n\n{memory_context}"

    if prompt_specific_guidance:
        dynamic_system_prompt += f"\n\n{prompt_specific_guidance}"

    messages = [{"role": "system", "content": dynamic_system_prompt}]
    
    # 1. CLEAN & SANITIZE HISTORY
    sanitized_history = []
    if history:
        for item in history:
            role = item.get("role", "user")
            content = str(item.get("content", "")).strip()
            
            # If the content is an Assistant's Technical Error (Traceback), summarize it
            if role == "assistant" and ("Traceback (most recent call last)" in content or "ERPNext SQL Error" in content):
                # Extract only the last error line if possible, or just a short summary
                last_line = content.splitlines()[-1] if content.strip() else "Unknown Database Error"
                content = f"Error: {last_line}"
            
            # Do not add empty content items to history
            if content:
                sanitized_history.append({"role": role, "content": content})

    # 2. DEDUPLICATE TRAILING USER PROMPT
    # If the last item in the sanitized history is already the same as our current prompt,
    # do not use history to avoid double-prompting some models. 
    # Or better: remove that last duplicate from history before extending.
    if sanitized_history and sanitized_history[-1]["role"] == "user":
        if sanitized_history[-1]["content"].lower() == effective_user_prompt.lower():
            sanitized_history.pop()

    if sanitized_history:
        messages.extend(sanitized_history)
        
    messages.append({"role": "user", "content": effective_user_prompt})

    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            temperature=0
        )
    except Exception as e:
        print(f"[AI Engine] Critical LLM Provider Error: {e}")
        return {
            "sql": None,
            "message": f"I'm sorry, I encountered a server error from the AI provider: {str(e)}",
            "tokens_used": 0,
            "error_type": "provider_500"
        }
    raw_output = response.choices[0].message.content.strip()

    usage = response.usage if hasattr(response, "usage") and response.usage else None
    prompt_tokens = (usage.prompt_tokens if usage else 0) + pass1_tokens
    completion_tokens = usage.completion_tokens if usage else 0
    tokens_used = {
        "total": prompt_tokens + completion_tokens,
        "prompt": prompt_tokens,
        "completion": completion_tokens
    }

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
                "tokens_used": tokens_used.get("total", 0),
                "input_tokens": tokens_used.get("prompt", 0),
                "output_tokens": tokens_used.get("completion", 0),
                "needs_forecast": needs_forecast,
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

        try:
            repair_response = client.chat.completions.create(
                model=AI_MODEL,
                messages=repair_messages,
                temperature=0
            )
            repair_output = repair_response.choices[0].message.content.strip()
            usage = repair_response.usage if hasattr(repair_response, "usage") and repair_response.usage else None
            repair_total = usage.total_tokens if usage else 0
            
            # Correctly update the tokens_used dictionary
            tokens_used["total"] += repair_total
            if usage:
                tokens_used["prompt"] += usage.prompt_tokens
                tokens_used["completion"] += usage.completion_tokens
        except Exception as e:
            print(f"[AI Engine] Error during SQL repair attempt: {e}")
            # If repair fails, fall back to the original raw_output
            repair_output = raw_output
            
        repair_needs_forecast = "FORECAST:" in repair_output
        repaired_result = _parse_sql_response(repair_output, tokens_used, repair_needs_forecast)

        repaired_unknown_tables = _find_unknown_tables(repaired_result.get("sql"), local_schema)
        repaired_relation_violations = _find_relation_constraint_violations(
            repaired_result.get("sql"),
            relation_constraints,
        )

        if not repaired_unknown_tables and not repaired_relation_violations:
            return repaired_result

        clarification_message = _build_relation_clarification_message(
            relation_violations,
            relation_constraints,
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




def _client_has_sales_invoice_followup_guardrail(client_id):
    """
    FIX: This function was previously called but not defined, causing a NameError.
    It serves as a guardrail for specific tenants (like eagle_group) to prevent
    the AI from generating redundant Sales Invoice Item joins in follow-up queries.
    """
    return client_id in ["DEMO_CLIENT_123", "eagle_group"]

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
        if _client_has_sales_invoice_followup_guardrail(client_id):
            repaired_sql = _remove_redundant_sales_invoice_item_joins(repaired_sql)
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
1. **NO HALLUCINATIONS**: You must ONLY use column names that appear as keys in the provided `Data Sample`. Do NOT invent column names.
2. **COLUMN SELECTION**: If the tabular data contains ONLY categorical columns or identifiers (like 'name', 'lead_owner', 'customer_name', 'phone_number'), you MUST NOT plot these directly. Instead, compute an aggregation (like "count") over one of the categorical columns to show a distribution (e.g. Count of leads by territory).
3. **METRIC PLOTTING**: If the table contains real numeric metrics (like 'total_revenue', 'grand_total', 'amount', 'qty', 'stock_value', 'sales'), you should plot these metrics and use aggregations like "sum" or "avg".
4. **NO IDENTIFIERS IN Y-AXIS**: Do NOT use phone numbers, document IDs, or timestamps as numerical Y-axis measures.
5. **CHART TYPE**: Use the best logical `chart_type` based on the data ("Bar", "Line", "Pie", "Donut", "Number"). E.g. time-series data => "Line". Category distribution => "Bar" or "Donut".

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

def generate_chat_response(user_prompt, history=None):
    system_prompt = (
        "You are a helpful and professional ERPNext AI data assistant. "
        "The user is asking a follow-up question, asking for clarification about data logic, or just chatting. "
        "Use the conversation history to provide a thoughtful, clear response in natural language.\n\n"
        "CRITICAL RULES for explanations:\n"
        "1. DO NOT mention internal database table names (e.g., `tabSales Invoice`, `tabItem`). Use business concepts instead (e.g., 'Sales Invoices', 'Items').\n"
        "2. DO NOT mention raw SQL clauses (e.g., avoid 'The WHERE clause filters...'). Explain in user-friendly terms ('It filters records where...').\n"
        "3. FORMAT BEAUTIFULLY. Use markdown bullet points, bold text for key metrics, and ensure double newlines between points so it reads well on the frontend.\n"
        "4. Do NOT output raw SQL queries unless explicitly asked."
    )
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        for msg in history:
            messages.append({"role": msg.get("role"), "content": msg.get("content")})
            
    messages.append({"role": "user", "content": user_prompt})

    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            temperature=0.3
        )
        output = response.choices[0].message.content.strip()
        usage = response.usage if hasattr(response, "usage") and response.usage else None
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        return {
            "message": output,
            "tokens_used": prompt_tokens + completion_tokens,
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "detected_intent": "chat",
            "model_used": AI_MODEL
        }
    except Exception as e:
        print(f"[AI Engine] chat error: {e}")
        return {
            "message": f"I encountered an error trying to process your chat request. ({str(e)})",
            "tokens_used": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "detected_intent": "chat",
            "model_used": AI_MODEL
        }


def auto_extract_context_override(client_id: str, message_id: int, original_prompt: str, feedback_comment: str) -> dict | None:
    """
    Uses AI to parse a user's correction/feedback comment and extract a structured
    ClientContextOverride (term → sql_logic mapping).

    Returns a dict with {term, sql_logic, description, confidence} if something
    extractable was found with confidence >= 70, otherwise returns None.

    This runs as a background task after a user submits negative feedback.
    """
    import json

    system_prompt = """You are an ERP data analyst assistant. A user submitted negative feedback on an AI-generated ERPNext report.
Your job is to read the original query and the user's correction comment, and determine if the user is teaching the AI a reusable business rule.

Examples of extractable rules:
- "use Sales Invoice instead of Purchase Invoice for revenue" → term=Revenue, sql_logic=SELECT ... FROM `tabSales Invoice`
- "our 'profit' is grand_total minus freight_charges on Sales Invoice" → term=profit, sql_logic=SUM(si.grand_total - si.freight_charges)
- "delivery means orders where status='Completed'" → term=delivery, sql_logic=status = 'Completed'

Examples of NON-extractable feedback (just frustration, not a rule):
- "this is wrong"
- "numbers look off"
- "show it differently"

Return ONLY a raw JSON object in this format:
{
  "extractable": true,
  "term": "Revenue",
  "sql_logic": "SUM(`tabSales Invoice`.`grand_total`)",
  "description": "User defines Revenue as the sum of Sales Invoice grand_total",
  "confidence": 85
}

If nothing extractable, return:
{"extractable": false}

Rules:
- confidence is 0-100. Only return extractable=true if you are >= 70 confident.
- sql_logic should be the actual SQL fragment or table name to substitute, not a full query.
- term should be the business concept (1-3 words) the user is redefining.
- Return ONLY the JSON object. No markdown, no explanations.
"""

    user_message = f"Original user prompt: {original_prompt}\n\nUser's correction/feedback: {feedback_comment}"

    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.IGNORECASE | re.DOTALL)
        if match:
            raw = match.group(1).strip()

        result = json.loads(raw)

        if not result.get("extractable"):
            print(f"[AutoExtract] No extractable override found for message_id={message_id}")
            return None

        confidence = int(result.get("confidence", 0))
        if confidence < 70:
            print(f"[AutoExtract] Confidence too low ({confidence}) for message_id={message_id}, skipping.")
            return None

        return {
            "client_id": client_id,
            "source_message_id": message_id,
            "original_prompt": original_prompt,
            "feedback_comment": feedback_comment,
            "term": result.get("term", "")[:200],
            "sql_logic": result.get("sql_logic", ""),
            "description": result.get("description", ""),
            "confidence": confidence,
        }

    except Exception as e:
        print(f"[AutoExtract] Failed to extract context override: {e}")
        return None
