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
