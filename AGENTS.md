# erp_ai — AI-Powered ERPNext Natural Language to SQL Engine

---

## 🤖 AI Agent Operating Rules

### 🎯 Objective
You are an autonomous AI software engineer. Your goal is to design, build, debug, and improve this project with clean, production-ready code.

Always prioritize:
- **Correctness** — code must work as intended
- **Simplicity** — avoid unnecessary complexity
- **Maintainability** — future developers (including you) should understand it
- **Performance** — efficient queries, minimal overhead

### 🧠 Core Behavior Rules

1. **Think Before Acting** — Analyze the task before writing code. Break problems into smaller steps. Avoid unnecessary complexity.

2. **Code Quality Standards** — Write clean, readable, modular code. Use meaningful names. Follow consistent formatting. DRY principle.

3. **Project Awareness** — Before making changes, read existing files, understand project structure, respect current architecture.
   - DO NOT rewrite entire codebases unnecessarily
   - DO NOT introduce breaking changes without reason

4. **File Handling Rules** — Create new files only when necessary. Update existing files instead of duplicating logic. Keep file structure organized.

### 🏗️ Architecture Guidelines

- **Backend:** Follow modular structure — keep business logic separate from routes, validate all inputs with Pydantic
- **Frontend:** Vanilla JS only (no React/Vue/Angular). Keep components small via template tags. Separate UI and logic.

### 🔐 Security Best Practices

- Never expose API keys or secrets in code
- Use environment variables (`.env`) for all sensitive config
- Validate and sanitize all user input
- Prevent SQL injection — use validated SQL only through `sql_validator.py`
- Mask errors from users via `_simplify_error_message()` — never return `str(e)` directly

### ⚡ Performance Guidelines

- Avoid unnecessary DB queries; batch where possible
- Use background tasks for non-critical operations (telemetry, embeddings)
- Append `LIMIT 1000` to all generated SQL
- Cache ERPNext schemas locally

### 🧪 Testing & Debugging

- Write testable code with clear error handling
- Log meaningful debug information with `print(f"[Module] ...")` convention
- Always run `pip install -r requirements.txt` if adding dependencies

### 🧩 Task Execution Strategy

1. Understand the requirement
2. Check existing implementation (read relevant files)
3. Plan minimal changes
4. Implement step-by-step
5. Verify the result
6. Refactor if needed

### 📚 Documentation Rules

- Add comments only where logic is non-obvious
- This file (`AGENTS.md`) is your primary rulebook
- `docs/` contains detailed project documentation
- Keep `AGENTS.md` updated if major conventions change

### 🚫 What to Avoid

- Overengineering — don't add abstractions before they're needed
- Unnecessary dependencies — check `requirements.txt` first
- Hardcoded values — use env vars or DB config
- Ignoring existing patterns — match the codebase style

### 🧠 Context Memory Strategy

Use project files as long-term memory:
- `AGENTS.md` → rules (this file)
- `docs/` → detailed documentation
- `main.py` → API routes and patterns
- `database.py` → DB models and migrations

### ✅ Output Expectations

Every output should be: **Working**, **Clean**, **Minimal**, **Easy to understand**.

### 🔄 Continuous Improvement

If you see a better approach: suggest it, then implement it safely.

### 🚀 Final Rule

Always act like a senior software engineer who writes code that others can easily understand, use, and scale.

---

## Tech Stack

- **Language:** Python 3.13
- **Web Framework:** FastAPI (Uvicorn)
- **Database:** PostgreSQL 16 (primary), SQLite fallback for local dev
- **ORM:** SQLAlchemy 2.x
- **Validation:** Pydantic v2
- **AI Providers:** OpenAI (gpt-4o, gpt-4o-mini), Groq
- **Data Processing:** Pandas, NumPy, statsmodels (Holt-Winters forecasting)
- **SQL Tooling:** sqlparse, sqlglot
- **Frontend:** Vanilla HTML + CSS + JavaScript (no framework), Chart.js for dashboards
- **HTTP Client:** httpx (async), requests
- **Deployment:** systemd service + nginx reverse proxy

## Project Structure

```
erp_ai/
├── main.py                  # FastAPI app — all API routes (~1320 lines)
├── ai_engine.py             # Core AI: prompt classification, SQL generation, chat (~1473 lines)
├── database.py              # SQLAlchemy models & auto-migration
├── erp_client.py            # HTTP client to ERPNext Frappe API
├── schema_fetcher.py        # Fetches & caches ERPNext DocTypes schema
├── schema_router.py         # LLM-based table routing from prompt
├── schema_planner.py        # Join path planning between tables
├── sql_validator.py         # SQL validation (SELECT/WITH only, blocks DDL)
├── forecaster.py            # Time-series forecasting (Holt-Winters)
├── memory_manager.py        # Embedding generation & cosine similarity (OpenAI)
├── frappe_insights.py       # Frappe Insights API integration
├── ibis_utils.py            # Ibis query builder for Insights v3
├── runtime_config.py        # Per-client config resolution (DB-first, env fallback)
├── migrate_db.py            # SQLite→Postgres migration helper
├── seed_rules.py            # Context override rule seeding
├── requirements.txt
├── .env                     # Environment config (not committed)
├── static/                  # Frontend assets
│   ├── index.html           # Main SPA
│   ├── login.html           # Login page
│   ├── app.js               # Frontend logic (~1642 lines)
│   └── styles.css           # Dark theme CSS (~1663 lines)
├── schemas/                 # ERPNext schema cache (per-client JSON files)
├── scripts/                 # Evaluation & utility scripts
├── deploy/                  # systemd unit + nginx config
└── docs/                    # Documentation (10 markdown files)
```

## Database Models (SQLAlchemy)

- `Conversation` — Chat thread per client/user
- `ConversationMessage` — Individual prompt/response with SQL, status, feedback, tokens
- `SavedReport` — User-saved reports with chart configs
- `ClientConfig` — Per-tenant ERPNext credentials
- `ClientContextOverride` — Term-to-SQL mapping (e.g., "Revenue" → `SUM(grand_total)`)
- `ClientSystemPrompt` — Per-client AI system prompt segments
- `ClientFeatureFlag` — Per-tenant feature toggles
- `PendingContextOverride` — Auto-extracted overrides awaiting admin approval

DB connection is via `DATABASE_URL` env var. PostgreSQL is the production database. Session management uses `Depends(get_db)` with automatic rollback on failure.

## Key API Routes

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/generate-report` | Main endpoint: classifies intent → generates SQL → executes → returns data |
| POST | `/api/generate_chart_config` | Generates Chart.js config from data sample |
| POST | `/api/reports/save` | Save report with chart config |
| GET | `/api/reports/{client_id}` | List saved reports |
| POST | `/api/login` | Authenticate against Frappe/ERPNext |
| POST | `/api/execute-sql` | Re-execute historical SQL |
| POST | `/api/conversations/feedback` | Submit user feedback (triggers auto-learning) |
| POST | `/api/motherbrain/ingest` | Push telemetry to admin backend |
| GET | `/api/metrics/baseline` | Performance metrics |
| GET/POST | `/api/client-configs` | Manage tenant configs |
| GET/POST/DELETE | `/api/context-overrides` | Manage term-to-SQL mappings |

## Architecture & Flow

1. User submits prompt → `/generate-report`
2. `classify_prompt_intent()` → report/chat/clarification/unsupported/forecast
3. If report: `generate_sql()` → AI generates SQL with schema context + overrides
4. `validate_sql()` → blocks DDL/DML, enforces `SELECT`/`WITH` only, appends `LIMIT 1000`
5. `run_query()` → executes against ERPNext MariaDB via Frappe API
6. On failure: error logged, simplified for user, pushed to Motherbrain telemetry
7. On negative feedback: `auto_extract_context_override()` runs in background

## Error Handling Conventions

- User-facing errors are masked via `_simplify_error_message()`
- Raw errors are logged server-side but never exposed in API responses
- DB failures: `db.rollback()` + log, never crash the request
- Telemetry push failures are silently swallowed
- All HTTPException responses should use generic messages, never `str(e)` directly

## Frontend Conventions

- No framework — vanilla JS only
- HTML templates via `<template>` tags for user/AI messages
- localStorage for auth token, user email, client_id
- Dark theme with CSS variables (ChatGPT-like)
- Chart.js via CDN for dashboard rendering
- Axios not used; native `fetch()` API

## Development

```bash
# Run server
uvicorn main:app --reload --host 127.0.0.1 --port 8001

# Dependencies
pip install -r requirements.txt

# Environment
cp env.tmpl .env  # Edit with your values
```

## Common Tasks

- **Add new API route:** Create Pydantic model + endpoint in `main.py`, add DB model in `database.py` if needed
- **Add AI provider:** Extend `ai_engine.py` following OpenAI/Groq pattern
- **Modify error masking:** Update `_simplify_error_message()` in `main.py`
- **Add frontend feature:** Edit `static/app.js` and `static/index.html`; no build step needed
- **Add DB migration:** `database.py` has auto-migration; add column creation in `init_db()`
