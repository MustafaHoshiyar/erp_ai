# ERPNext v14 Backward Compatibility — Implementation Plan

> **Status:** Approved  
> **Target:** Make `erp_ai` fully compatible with ERPNext v14 while maintaining v15 support  
> **Strategy:** Runtime version detection → dynamic prompt injection → conditional feature paths

---

## Context

### What is erp_ai?

`erp_ai` is a standalone Python FastAPI application that:
1. Receives natural-language prompts from users (e.g., "fetch me all sales invoices of this month")
2. Uses LLMs (OpenAI/Groq) to classify intent and generate SQL queries
3. Validates the SQL and executes it against ERPNext's MariaDB via a custom Frappe app (`smberp_ai`)
4. Returns results as tabular data with optional Chart.js visualizations

### Architecture

```
User → FastAPI (erp_ai) → AI Engine (LLM SQL generation)
                         → SQL Validator (SELECT/WITH only)
                         → erp_client.py → HTTP POST → ERPNext Bench
                                                       └── smberp_ai/api.py
                                                           └── frappe.db.sql(sql)
                         → frappe_insights.py → HTTP POST → ERPNext Bench
                                                           └── Frappe Insights v3 API
```

### Current State

- The project was developed and tested on **ERPNext v15**
- The custom app (`smberp_ai` in `wsl-erp_ai-main/`) is minimal and already v14-compatible
- Core REST API patterns and schema conventions are identical between v14 and v15
- Key differences affect: **stock serial/batch handling**, **Frappe Insights**, and **AI schema knowledge**

### Key Differences Between v14 and v15 Affecting erp_ai

| Area | v14 | v15 | Impact |
|------|-----|-----|--------|
| **Serial/Batch** | `batch_no`/`serial_no` columns directly on `tabStock Ledger Entry` | New `tabSerial and Batch Bundle` + `tabSerial and Batch Entry`; `batch_no` absent on SLE for new entries | AI must know which columns exist |
| **Frappe Insights** | May have v2 or v3 installed | Typically v3 | Different API endpoints |
| **Dunning** | Simple single-invoice link | Child table of overdue payments | SQL join patterns differ |
| **Event cancelled** | `event_type = 'Cancelled'` | `status = 'Cancelled'` | Filter logic differs |

---

## Implementation Steps

### Step 1: Add version endpoint to custom app (`wsl-erp_ai-main/api.py`)

**File:** `wsl-erp_ai-main/wsl-erp_ai-main/api.py`

**Why:** The cleanest way to detect the Frappe version is to ask Frappe directly. We expose `frappe.__version__` through a whitelisted endpoint on the custom app (which is already mandatory for the dashboard to function).

**Change:** Add one new method alongside `run_ai_query`:

```python
@frappe.whitelist()
def get_frappe_version():
    return frappe.__version__
```

This returns a string like `"14.0.0"` or `"15.0.0"`.

**No other changes needed** — the custom app uses legacy `hooks.py` structure (no `pyproject.toml`), Python 3.10 bytecode is already present, and `@frappe.whitelist()` works identically in both versions.

---

### Step 2: Create version detection module (`erp_version.py`)

**File:** `erp_version.py` (new, at project root)

**Why:** Isolate version detection logic so it can be reused by `ai_engine.py`, `frappe_insights.py`, and `main.py` without circular imports.

**Design:**

```
erp_version.py
├── _VERSION_CACHE: dict[str, str]  # per-client in-memory cache
├── get_erp_version(client_id) → "14" | "15" | "unknown"
└── _detect_version(config) → str    # two-method probing
```

Detection strategy (tried in order):
1. **Primary**: Call `get_frappe_version` on the custom app's new endpoint → parse `frappe.__version__`
2. **Fallback**: Schema probe via existing `run_ai_query` — check for v15-specific table `tabSerial and Batch Bundle`
3. If both fail → `"unknown"` (treat conservatively as v14)

Cache is per-client and held in memory for the FastAPI process lifetime (same pattern as `_CURRENCY_CACHE` in `erp_client.py`).

---

### Step 3: Add version function to `erp_client.py`

**File:** `erp_client.py`

**Why:** `erp_client.py` already handles all HTTP communication with the ERPNext instance. Adding a `get_frappe_version()` function here keeps HTTP concerns centralized.

**Change:** Add:

```python
async def get_frappe_version(client_id="DEMO_CLIENT_123"):
    """Get Frappe/ERPNext version for the given client. Delegates to erp_version module."""
    from erp_version import get_erp_version
    return await get_erp_version(client_id)
```

This is a thin async wrapper around the core detection logic.

---

### Step 4: Fetch version early in `/generate-report` (`main.py`)

**File:** `main.py`

**Why:** The version needs to be available to `generate_sql()` which is currently synchronous. By fetching it early in the async request handler and populating the in-memory cache, `generate_sql()` can read it synchronously without awaiting.

**Change:**

After the intent classification block (around line 184), before `generate_sql()` is called:

```python
# Pre-fetch ERP version for schema-aware prompt injection
from erp_version import get_erp_version, _VERSION_CACHE
erp_version = await get_erp_version(client_id)
# Cache is now warm; ai_engine can read it synchronously
```

Also pass `erp_version` to `generate_sql()` as a parameter so it can use it directly without re-fetching:

```python
result = generate_sql(
    request.prompt, 
    request.history, 
    client_id, 
    app_name=app_name,
    currency=currency_info["code"], 
    currency_symbol=currency_info["symbol"],
    erp_version=erp_version  # NEW
)
```

---

### Step 5: Modify AI engine for version-conditional prompts (`ai_engine.py`)

**File:** `ai_engine.py`

**Why:** The LLM system prompt has hardcoded schema rules. Injecting version-specific guidance ensures generated SQL matches the target ERPNext's actual database schema.

**Changes:**

**5a. `generate_sql()` signature** (line 960):

Add `erp_version=None` parameter. Default `None` makes it backward-compatible with existing callers.

**5b. Version-conditional schema injection** (after line 964):

After the base `SYSTEM_PROMPT` is formatted, inject version-specific notes:

```python
if erp_version:
    version_notes = _get_version_schema_notes(erp_version)
    if version_notes:
        dynamic_system_prompt += f"\n\n{version_notes}"
```

**5c. New helper `_get_version_schema_notes()`:**

```python
def _get_version_schema_notes(erp_version: str) -> str:
    if erp_version == "15":
        return _V15_SCHEMA_NOTES
    elif erp_version == "14":
        return _V14_SCHEMA_NOTES
    return ""
```

**5d. Version-specific prompt constants:**

```python
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
```

---

### Step 6: Modify Frappe Insights integration (`frappe_insights.py`)

**File:** `frappe_insights.py`

**Why:** All Insights endpoints use `v3` doctype suffixes (`Insights Query v3`, `Insights Chart v3`, `Insights Dashboard v3`). If the target v14 instance has Insights v2 instead, these calls will 404.

**Changes:**

**6a. Add Insights version detection helper:**

```python
_INSIGHTS_VERSION_CACHE = {}

async def _get_insights_version(client_id: str) -> str:
    """Detect which Insights version is installed. Returns 'v3', 'v2', or None."""
    if client_id in _INSIGHTS_VERSION_CACHE:
        return _INSIGHTS_VERSION_CACHE[client_id]
    
    config = _get_insights_runtime_config(client_id)
    headers = {
        "Authorization": f"token {config['api_key']}:{config['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        # Probe v3 endpoint first
        res = await client.get(
            f"{config['site_url']}/api/resource/Insights Query v3",
            headers=headers,
            params={"limit_page_length": 1},
            timeout=10.0
        )
        if res.status_code == 200:
            _INSIGHTS_VERSION_CACHE[client_id] = "v3"
            return "v3"
        
        # Fall back to v2 probe
        res = await client.get(
            f"{config['site_url']}/api/method/insights.api.get_queries",
            headers=headers,
            timeout=10.0
        )
        if res.status_code == 200:
            _INSIGHTS_VERSION_CACHE[client_id] = "v2"
            return "v2"
    
    _INSIGHTS_VERSION_CACHE[client_id] = None
    return None
```

**6b. Add early guard in export functions:**

At the start of `export_query_to_insights()` and `export_chart_and_dashboard_to_insights()`, check:

```python
insights_version = await _get_insights_version(client_id)
if insights_version != "v3":
    raise Exception(
        "Frappe Insights v3 is required for dashboard export. "
        "Please install/upgrade the Insights app to version 3 on your ERPNext instance."
    )
```

This gives a clear user-facing error instead of a cryptic 404.

---

## Execution Order & Dependencies

```
Step 1 (api.py)            # No dependencies, can do first
   ↓
Step 2 (erp_version.py)    # Depends on Step 1 for primary detection
   ↓
Step 3 (erp_client.py)     # Thin wrapper around Step 2
   ↓
Step 4 (main.py)           # Consumes Step 2's cache
   ↓
Step 5 (ai_engine.py)      # Consumes version from Step 4
   ↓
Step 6 (frappe_insights.py) # Consumes version from Step 2
```

Steps 2 and 3 can be implemented together (they're closely related).
Steps 5 and 6 are independent and can be done in parallel after Step 4.

---

## Files Not Requiring Changes

| File | Reason |
|------|--------|
| `schema_fetcher.py` | Standard REST API endpoints, identical in v14/v15 |
| `schema_router.py` | No direct Frappe API calls |
| `schema_planner.py` | No direct Frappe API calls; child table conventions identical |
| `sql_validator.py` | Pure Python, no Frappe dependency |
| `ibis_utils.py` | Vendored Insights v3 internal code, imported by nothing |
| `insights_query_v3.py` | Vendored Insights v3 internal code, imported by nothing |
| `runtime_config.py` | No version-specific logic |

---

## Testing Verification

After all changes are implemented, verify with:

1. **Against v15 instance**: No regressions — version detection returns `"15"`, v15 prompt injected, Insights v3 works
2. **Against v14 instance**: Version detection returns `"14"`, v14 prompt injected, Insights gracefully errors with upgrade message
3. **Custom app on v14 bench**: `get_frappe_version()` returns `"14.x.x"`; `run_ai_query()` executes SQL correctly
4. **Schema probe fallback**: If `get_frappe_version()` endpoint is missing, `tabSerial and Batch Bundle` probe correctly identifies v14 vs v15

---

## Rollback Strategy

Each step is fully independent:
- If Step 1 cannot be deployed to the v14 bench, Steps 2's fallback probe handles detection
- If version detection fails entirely, Steps 5 and 6 default to conservative behavior (v14 schema notes, Insights disabled)
- All changes are additive — no existing code paths are modified, only extended
