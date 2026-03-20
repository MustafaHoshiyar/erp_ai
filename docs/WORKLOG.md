# Worklog

## 2026-03-16 - Batch 001

- Phase: Setup
- Scope: `shared`
- Files changed:
  - `docs/CHANGE_PROCESS.md`
  - `docs/WORKLOG.md`
  - `docs/DECISIONS.md`
- Summary:
  - Created a shared documentation workflow to track future changes across `erp_ai` and `motherbrain_admin`.
- Reason:
  - We need a durable record of every implementation step, the files touched, and why each change was made before feature work begins.
- Validation:
  - Documentation files created and ready to be updated with each implementation batch.
- Follow-up:
  - Use this file for every future feature, refactor, and bug fix batch.

## 2026-03-16 - Batch 002

- Phase: Phase 1 Planning
- Scope: `shared`
- Files changed:
  - `docs/PHASE_1_ROADMAP.md`
  - `docs/WORKLOG.md`
  - `docs/DECISIONS.md`
- Summary:
  - Added a concrete Phase 1 roadmap covering intent classification, telemetry enrichment, evaluation dataset setup, and baseline metrics across `erp_ai` and `motherbrain_admin`.
- Reason:
  - We need a precise implementation order and measurable success criteria before starting smart-system improvements.
- Validation:
  - Roadmap reviewed against the current code structure in both projects and aligned with the agreed phased direction.
- Follow-up:
  - Begin implementation with prompt intent classification and conversation-message telemetry updates.

## 2026-03-16 - Batch 003

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `database.py`
  - `migrate_db.py`
  - `ai_engine.py`
  - `main.py`
  - `static/app.js`
  - `docs/WORKLOG.md`
  - `docs/DECISIONS.md`
- Summary:
  - Added lightweight prompt intent classification, stored detected intent and assistant text responses in conversation history, and stopped non-report prompts from being recorded as SQL execution errors.
- Reason:
  - Conversational prompts were polluting failure telemetry with `No SQL generated`, which weakens later learning and makes Motherbrain incident data noisy.
- Validation:
  - Code paths updated so chat and clarification prompts return assistant text without entering SQL execution.
  - Conversation history flow updated so non-SQL responses can be restored cleanly.
- Follow-up:
  - Run the local migration for new columns.
  - Extend Motherbrain ingestion and dashboard filters to consume the new intent signal in the next batch.

## 2026-03-16 - Batch 004

- Phase: Planning Refinement
- Scope: `shared`
- Files changed:
  - `docs/PHASE_1_ROADMAP.md`
  - `docs/DECISIONS.md`
  - `docs/WORKLOG.md`
- Summary:
  - Added clarifying-question behavior to the improvement roadmap and recorded it as an explicit product decision.
- Reason:
  - Ambiguous report requests should lead to targeted clarification instead of false SQL failures or low-confidence query generation.
- Validation:
  - Shared planning docs now include clarification behavior in roadmap outcomes, evaluation expectations, and decision history.
- Follow-up:
  - Keep clarification prompts in scope when we expand telemetry, eval cases, and Motherbrain review logic.

## 2026-03-16 - Batch 005

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `ai_engine.py`
  - `docs/WORKLOG.md`
- Summary:
  - Tightened follow-up intent heuristics so ambiguous column-edit prompts with ordinal references now trigger clarification instead of generating a replacement query automatically.
- Reason:
  - A positional request like `change the third column` can be interpreted incorrectly because the rendered table includes a visible `Sr` column that is not part of the SQL result, making ordinal edits ambiguous without confirmation.
- Validation:
  - Added targeted ordinal-column clarification detection for follow-up edit prompts with SQL history.
- Follow-up:
  - Extend this logic later with result-column awareness so clarification can mention actual prior column names when available.

## 2026-03-16 - Batch 006

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `erp_client.py`
  - `static/app.js`
  - `docs/WORKLOG.md`
- Summary:
  - Added currency decimal metadata to the backend currency-info response and updated the UI formatter so KWD transaction amounts render with 3 decimal places instead of the previous hardcoded 2.
- Reason:
  - Kuwait Dinar amounts require 3 decimal places, and the current UI was truncating them to 2 in tables and totals.
- Validation:
  - Currency formatting logic now uses `decimal_places` from the currency-info payload with a KWD-specific backend mapping.
- Follow-up:
  - Extend currency precision handling to KPI/chart formatting later if we want AI-generated summaries to respect the same precision rules.

## 2026-03-16 - Batch 007

- Phase: Phase 1 Implementation
- Scope: `shared`
- Files changed:
  - `scripts/telemetry_sync.py`
  - `c:\laragon\www\motherbrain_admin\backend\database.py`
  - `c:\laragon\www\motherbrain_admin\backend\main.py`
  - `c:\laragon\www\motherbrain_admin\backend\ai_analyzer.py`
  - `c:\laragon\www\motherbrain_admin\frontend\src\App.jsx`
  - `docs/DECISIONS.md`
  - `docs/WORKLOG.md`
- Summary:
  - Switched Motherbrain sync to full unsynced telemetry batches, added tenant-scoped intent and execution metadata, updated Motherbrain storage and dashboard behavior, and recorded the move to a shared multi-tenant ERP AI runtime.
- Reason:
  - Phase 1 needs cleaner telemetry and a central admin surface that can distinguish healthy traffic, clarifications, feedback, and real failures across tenants without mixing their learnings.
- Validation:
  - `python -m py_compile scripts/telemetry_sync.py` passed in `erp_ai`.
  - `python -m py_compile backend/main.py backend/database.py backend/ai_analyzer.py` passed in `motherbrain_admin`.
  - `python -c "from database import init_db; init_db(); print('ok')"` ran successfully in `motherbrain_admin/backend`.
  - `npm run build` completed successfully in `motherbrain_admin/frontend`.
- Follow-up:
  - Verify end-to-end sync from `erp_ai` to `motherbrain_admin`.
  - Use the richer event model to build Phase 1 baseline metrics and the eval pipeline next.

## 2026-03-17 - Batch 008

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `ai_engine.py`
  - `scripts/evaluate_ai.py`
  - `scripts/phase1_regression_dataset.json`
  - `scripts/build_phase1_eval_assets.py`
  - `scripts/phase1_eval_assets/workbook_failures.json`
  - `scripts/phase1_eval_assets/workbook_failure_summary.json`
  - `scripts/phase1_eval_assets/legacy_db_summary.json`
  - `scripts/phase1_eval_assets/eval_candidates.json`
  - `docs/DECISIONS.md`
  - `docs/WORKLOG.md`
- Summary:
  - Processed the coworker workbook and legacy prompt database into structured Phase 1 eval artifacts, expanded the evaluator to handle richer checks, and added workbook-driven SQL guardrails for reorder logic, stock runout filtering, numeric ranking, salesperson semantics, payment-entry semantics, and month-wise comparisons.
- Reason:
  - The attached workbook surfaced repeated ERPNext-specific failure patterns where the model generated valid-looking SQL with the wrong business meaning, and those patterns need to be fixed at the generation layer and preserved as regression tests.
- Validation:
  - `python -m py_compile ai_engine.py scripts/evaluate_ai.py scripts/build_phase1_eval_assets.py` passed.
  - `python scripts/build_phase1_eval_assets.py --workbook "c:\Users\musta\Downloads\Report for testing.xlsx" --legacy-db "c:\Users\musta\Downloads\erp_ai_memory.db"` passed.
  - Generated eval assets show 12 workbook failure cases and a normalized legacy summary with 205 messages, 65 `FORMAT()` SQL rows, and 13 chat-like false failures in the legacy data.
- Follow-up:
  - Run the updated evaluator against the live model once we are ready to spend inference on the regression suite.
  - Use the generated workbook categories to prioritize the next Motherbrain clustering and remediation UI.

## 2026-03-17 - Batch 009

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `schema_fetcher.py`
  - `schema_router.py`
  - `ai_engine.py`
  - `main.py`
  - `schemas/local_schema_cache.json`
  - `docs/DECISIONS.md`
  - `docs/WORKLOG.md`
- Summary:
  - Reworked schema grounding so ERP AI now caches the live DocType inventory from ERPNext, fetches detailed field metadata for routed tables, injects that live schema into generation, and downgrades unknown-table SQL into clarification instead of executing it.
- Reason:
  - A test prompt still produced SQL against a guessed table path, which showed that prompt rules alone were not enough. The system needed a hard grounding step against the real tenant schema before trusting generated SQL.
- Validation:
  - `python -m py_compile ai_engine.py schema_fetcher.py schema_router.py main.py` passed.
  - `get_local_schema()` refreshed the cache successfully and loaded 827 available DocTypes, 7 custom DocTypes, 111 custom fields, and 7 detailed DocType entries.
  - `ensure_doctype_details(['tabItem Reorder'])` confirmed the live ERP metadata includes `warehouse` and `warehouse_reorder_level` on `Item Reorder`.
  - `_find_unknown_tables(\"SELECT * FROM `tabMade Up Table` JOIN `tabItem` ON 1=1\", schema)` correctly flagged `tabMade Up Table` as unavailable.
- Follow-up:
  - Restart the `erp_ai` backend so the new live-schema validation path is active.
  - Re-test the reorder prompt and similar schema-sensitive prompts, then decide whether we want one automatic repair pass before clarification in a later batch.

## 2026-03-17 - Batch 010

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `schema_fetcher.py`
  - `schema_planner.py`
  - `schema_router.py`
  - `ai_engine.py`
  - `docs/DECISIONS.md`
  - `docs/WORKLOG.md`
- Summary:
  - Added a live schema relation planner that builds a graph from tenant DocType metadata, discovers join paths and shared-link hints, and injects that relation plan into SQL generation before the model writes SQL.
- Reason:
  - Live table validation solved the "invented table" problem, but the assistant still needed a stronger way to understand actual relationships like `tabBin -> tabItem -> tabItem Reorder` from tenant metadata instead of relying on prompt rules alone.
- Validation:
  - `python -m py_compile schema_fetcher.py schema_planner.py schema_router.py ai_engine.py main.py` passed.
  - The planner produced a live relation plan for the reorder prompt that included:
    - `tabBin.item_code -> tabItem.name`
    - `tabItem Reorder.parent -> tabItem.name` via the `reorder_levels` child-table relation
    - a shared-warehouse alignment hint between `tabBin` and `tabItem Reorder`
  - `get_optimized_schema_context(...)` now includes the discovered relation plan in the prompt context before SQL generation.
- Follow-up:
  - Restart the `erp_ai` backend and re-test the reorder prompt to see whether the model now follows the discovered join plan consistently.
  - The remaining multi-tenant infrastructure gap is still per-client ERP configuration and per-client schema caching, which we should tackle in a later batch.

## 2026-03-17 - Batch 011

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `schema_planner.py`
  - `schema_router.py`
  - `ai_engine.py`
  - `docs/WORKLOG.md`
- Summary:
  - Added relation-aware SQL validation for child-table joins and a one-shot repair pass so the assistant can catch cases where it found the correct child doctype but still joined it through the wrong field.
- Reason:
  - The reorder prompt still generated a logically incorrect join by connecting `tabItem Reorder.parent` to `tabBin.item_code` instead of the parent `Item` record, which showed we needed enforcement, not only planning hints.
- Validation:
  - `python -m py_compile schema_planner.py schema_router.py ai_engine.py` passed.
  - The exact SQL produced during testing was checked against the live relation constraints and correctly flagged as invalid because `tabItem Reorder` must join through `parent/parenttype` to `tabItem`.
- Follow-up:
  - Restart the `erp_ai` backend and run the reorder prompt again so the model can use the new repair path.
  - If the model still drifts after one repair pass, the next step should be a deterministic SQL rewriter for child-table joins or a stricter schema-plan execution layer.

## 2026-03-17 - Batch 012

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `ai_engine.py`
  - `docs/WORKLOG.md`
- Summary:
  - Added a deterministic child-table join rewriter so known child doctypes can be corrected to their required `parent` and `parenttype` join conditions before execution when the model keeps repeating the wrong join.
- Reason:
  - The reorder prompt continued to generate the same invalid join even after relation planning and one repair pass, so this specific high-confidence schema rule needed to move from prompt guidance into code.
- Validation:
  - `python -m py_compile ai_engine.py` passed.
  - The exact SQL returned during testing was rewritten from `tabBin.item_code = tabItem Reorder.parent` to `tabItem Reorder.parent = tabItem.name AND tabItem Reorder.parenttype = 'Item'` while preserving the warehouse condition.
- Follow-up:
  - Restart the `erp_ai` backend and run the reorder prompt again to confirm the production path now returns the corrected SQL.
  - If more relation classes show the same pattern, extend deterministic repair beyond child tables to other high-confidence join types.

## 2026-03-17 - Batch 013

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `ai_engine.py`
  - `main.py`
  - `docs/WORKLOG.md`
- Summary:
  - Added a backend normalization step in the main request flow so live-schema SQL repair is enforced before validation, storage, and response, even if the model still returns the wrong child-table join.
- Reason:
  - The user continued seeing the bad SQL in the app, which meant we needed the correction to run again in the execution path itself instead of relying only on the generation-time repair branch.
- Validation:
  - `python -m py_compile ai_engine.py main.py` passed.
  - `normalize_sql_with_live_schema(...)` rewrote the exact reorder SQL sample to the correct `parent` and `parenttype` join against `tabItem`.
- Follow-up:
  - Restart the `erp_ai` backend and test the reorder prompt again in the UI.
  - If the displayed SQL still shows the old join after restart, we should inspect the frontend rendering path next.

## 2026-03-20 - Batch 014

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `static/app.js`
  - `docs/WORKLOG.md`
- Summary:
  - Fixed the frontend numeric formatter so quantity-style columns are no longer rendered with currency symbols just because their header contains broad words like `total` or `rate`.
- Reason:
  - The UI was formatting quantity columns as money, which is misleading and makes otherwise-correct query output look wrong to users.
- Validation:
  - `node --check static/app.js` passed.
  - Representative checks now classify `qty`, `total_qty`, and `warehouse_reorder_qty` as non-currency while keeping `grand_total`, `valuation_rate`, and `amount` as currency fields.
- Follow-up:
  - Refresh the browser and test reports that include both amount columns and quantity columns.
  - If KPI cards or AI-generated text still show quantity values as money, tighten the chart/KPI formatting layer in a later batch.

## 2026-03-20 - Batch 015

- Phase: Phase 1 Implementation
- Scope: `erp_ai`
- Files changed:
  - `database.py`
  - `migrate_db.py`
  - `ai_engine.py`
  - `main.py`
  - `scripts/telemetry_sync.py`
  - `scripts/generate_phase1_baseline.py`
  - `docs/DECISIONS.md`
  - `docs/WORKLOG.md`
- Summary:
  - Finished the remaining Phase 1 measurement layer by storing model/routing/latency telemetry per message, syncing those fields to Motherbrain, and exposing a baseline metrics endpoint plus a snapshot script.
- Reason:
  - We needed a measurable baseline before moving deeper into autonomous learning, and the existing telemetry still could not explain which model ran, which schema tables were chosen, or how long the generation/execution stages took.
- Validation:
  - `python -m py_compile ai_engine.py main.py database.py migrate_db.py scripts/telemetry_sync.py scripts/generate_phase1_baseline.py` passed.
  - `python migrate_db.py` added the new telemetry columns to the local database.
  - Directly calling `get_baseline_metrics(...)` returned a working baseline snapshot from the current DB, including totals, rates, and latency buckets.
- Follow-up:
  - Restart the `erp_ai` backend so new messages start filling `model_used`, `routing_tables`, `generation_ms`, `execution_ms`, and `total_duration_ms`.
  - Run `python scripts/generate_phase1_baseline.py` after collecting a few fresh prompts to save the first post-telemetry baseline snapshot.

## 2026-03-20 - Batch 016

- Phase: Phase 2 Planning
- Scope: `shared`
- Files changed:
  - `docs/PHASE_2_ROADMAP.md`
  - `docs/DECISIONS.md`
  - `docs/WORKLOG.md`
- Summary:
  - Defined Phase 2 so it begins with true multi-tenant architecture across `erp_ai` and `motherbrain_admin`, and recorded that smarter execution/autonomy work comes after the tenant-safe runtime is complete.
- Reason:
  - The current product is tenant-aware but not yet fully multi-tenant at the infrastructure/runtime level, and the user wants that architecture finished before continuing the broader improvement phases.
- Validation:
  - The roadmap now covers client configuration, per-client ERP runtime selection, per-client schema infrastructure, tenant-bound learning, and multi-tenant Motherbrain workflows in implementation order.
- Follow-up:
  - Start Phase 2 implementation with the `erp_ai` client configuration model and per-client ERP connection refactor.
