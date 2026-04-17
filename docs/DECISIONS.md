# Decisions

## DEC-001 - Shared Documentation Hub

- Date: 2026-03-16
- Status: accepted
- Scope: `shared`

### Decision

Use the `erp_ai/docs` folder as the shared documentation hub for tracking implementation work across both `erp_ai` and `motherbrain_admin`.

### Reason

- The current workspace already has write access in `erp_ai`.
- We need one consistent place to record changes before we start larger feature work.
- A single shared log is easier to maintain than fragmented notes across both projects.

### Consequences

- All implementation batches must be recorded in `docs/WORKLOG.md`.
- Any major architecture or product decision must be recorded in `docs/DECISIONS.md`.
- Entries may reference files from either codebase.

## DEC-002 - Phase 1 Focus

- Date: 2026-03-16
- Status: accepted
- Scope: `shared`

### Decision

Phase 1 will focus on telemetry cleanup, prompt intent classification, dataset-based evaluation, and baseline measurement before adding autonomous repair or broader self-learning behavior.

### Reason

- The current system still mixes conversational prompts with true reporting failures.
- Future autonomous learning will be unreliable if it learns from noisy or weakly labeled telemetry.
- A measurable baseline is required before later phases can be judged accurately.

### Consequences

- The first implementation work should happen in the request classification and telemetry flow.
- Motherbrain should be updated to consume cleaner metadata before it becomes more autonomous.
- Later phases should build on Phase 1 metrics rather than intuition alone.

## DEC-003 - Intent Gate Before SQL

- Date: 2026-03-16
- Status: accepted
- Scope: `erp_ai`

### Decision

Add a lightweight prompt intent gate before SQL generation so clearly conversational, unsupported, or clarification-seeking prompts return assistant text without entering the SQL execution path.

### Reason

- The product was treating prompts like `hello` as execution failures.
- That behavior polluted telemetry and made failed-query analysis less trustworthy.
- A lightweight gate improves both speed and signal quality without introducing a second model call.

### Consequences

- Conversation history now needs to store assistant text replies, not only SQL and errors.
- `execution_status = "skipped"` is now a valid non-error state for some prompts.
- Motherbrain should later consume the stored intent signal so its review queue reflects true reporting incidents more accurately.

## DEC-004 - Clarifying Questions Are First-Class Behavior

- Date: 2026-03-16
- Status: accepted
- Scope: `shared`

### Decision

Treat clarifying questions as a core part of the improvement cycle so the assistant can ask for missing context instead of forcing a low-confidence SQL attempt.

### Reason

- Many reporting prompts are not fully specified on the first turn.
- A wrong SQL query is more harmful than a short clarifying question.
- Later learning and evaluation will be stronger if the system can distinguish ambiguity from failure.

### Consequences

- The phased roadmap and eval dataset should include clarification behavior explicitly.
- Future metrics should track clarification-question rate and clarification accuracy.
- We should tune the assistant to ask clarifying questions only when the ambiguity is material, not for routine prompts.

## DEC-005 - Shared Multi-Tenant ERP AI

- Date: 2026-03-16
- Status: accepted
- Scope: `shared`

### Decision

Use one shared `erp_ai` runtime for multiple clients and keep tenant-specific conversations, memory, overrides, telemetry, and evaluations isolated by client rather than deploying one full ERP AI instance per client.

### Reason

- Separate deployments per client create avoidable operational overhead.
- A shared runtime is easier to improve, monitor, and maintain alongside one centralized Motherbrain Admin.
- The current codebase already uses `client_id` in several flows, which makes a multi-tenant direction practical.

### Consequences

- Tenant isolation must be treated as a hard system rule across memory, telemetry, schema context, and review workflows.
- Motherbrain should ingest full tenant-scoped telemetry and avoid mixing client-specific learnings into shared logic by default.
- Evaluation and remediation flows should use the original `client_id` when replaying or reviewing prompts.

## DEC-006 - Real-World Failures Become Regression Inputs

- Date: 2026-03-17
- Status: accepted
- Scope: `erp_ai`

### Decision

Use the coworker workbook and the legacy `erp_ai_memory.db` as curated evaluation sources for Phase 1, and translate repeated failure patterns into explicit SQL-generation guardrails plus repeatable regression cases.

### Reason

- The workbook captures real prompts where the system looked correct syntactically but still misunderstood ERPNext business semantics.
- The legacy database gives us production-like prompt history, failure rates, and feedback signals that are more representative than hand-written toy tests.
- Fixes driven by real prompts are more likely to improve the product meaningfully than prompt-engineering guesses alone.

### Consequences

- The evaluator now needs to support richer expectations like forbidden SQL patterns, clarification behavior, and non-SQL replies.
- We should keep generating structured eval artifacts from future testing rounds instead of relying on one-off spreadsheets.
- Prompt-generation rules should be updated only when the underlying failure pattern is clear enough to justify a reusable guardrail.

## DEC-007 - Ground SQL Generation In Live Tenant Schema

- Date: 2026-03-17
- Status: accepted
- Scope: `erp_ai`

### Decision

Upgrade the schema cache from a custom-only snapshot to a live tenant schema inventory, fetch detailed metadata for routed DocTypes on demand, and block SQL that references tables not present in the connected ERP.

### Reason

- The model can still generate plausible but ungrounded ERPNext tables if it only sees a static global schema plus custom-field fragments.
- Real reliability requires knowing which DocTypes and relationships exist in the connected ERP before executing SQL.
- It is safer to ask for clarification on an unknown table than to execute misleading SQL that appears valid.

### Consequences

- Schema refresh now needs to cache live available DocTypes as well as custom schema.
- The router should prefer real tenant DocTypes and inject detailed field metadata for the routed tables.
- If generated SQL references unavailable tables, the app should return a clarification-style response instead of storing a false execution failure.

## DEC-008 - Use A Schema Relation Planner Before SQL

- Date: 2026-03-17
- Status: accepted
- Scope: `erp_ai`

### Decision

Build a relation-planning layer from live DocType metadata so ERP AI can inject discovered join paths, child-table relations, and shared link hints into the SQL-generation prompt before writing SQL.

### Reason

- Knowing that a table exists is not enough; the assistant also needs to understand how routed tables connect in this tenant.
- ERPNext often stores business logic through child tables and Link fields, which can be inferred from metadata more reliably than from prompt heuristics alone.
- A discovered relation plan reduces the chance of valid-looking but logically wrong joins.

### Consequences

- The routing path now includes a schema graph and a tenant-specific relation plan in addition to the filtered schema.
- Future repair and validation steps can reuse the same graph instead of re-deriving join logic from scratch.
- Multi-tenant quality will still depend on making the schema cache and ERP connection fully client-scoped in a later phase.

## DEC-009 - Finish Phase 1 With Richer Telemetry And Baselines

- Date: 2026-03-20
- Status: accepted
- Scope: `erp_ai`

### Decision

Capture richer per-message telemetry in `erp_ai` itself, including model name, routed tables, and latency timings, and expose a baseline metrics endpoint/script so Phase 1 ends with measurable quality and performance numbers.

### Reason

- We now have cleaner intent handling and better schema reasoning, but we still need a reproducible baseline to measure future improvements.
- Motherbrain can only analyze the journey well if each event explains which model ran, what schema slice was selected, and how long each stage took.
- Baseline metrics are the bridge between one-off bug fixing and phased product improvement.

### Consequences

- New messages will carry richer telemetry than older historical rows, so some baseline fields will remain empty until fresh traffic accumulates.
- The telemetry sync payload needs to include the new fields so downstream analysis can use them.
- Future phases should compare against the baseline endpoint/script instead of relying on anecdotal prompt tests.

## DEC-010 - Phase 2 Starts With True Multi-Tenant Architecture

- Date: 2026-03-20
- Status: accepted
- Scope: `shared`

### Decision

Make true multi-tenant runtime architecture the first priority of Phase 2 for both `erp_ai` and `motherbrain_admin`, and only continue with later intelligence improvements after that architecture is in place.

### Reason

- The current system is tenant-aware in memory, telemetry, and review flows, but still has runtime single-tenant assumptions in ERP connectivity and schema caching.
- Autonomous learning and self-healing are too risky on top of a partially shared runtime because cross-client leakage would be expensive and hard to unwind.
- A strong multi-tenant foundation makes every later improvement safer to deploy and easier to measure.

### Consequences

- Phase 2 implementation should begin with client configuration, tenant-specific ERP runtime selection, and per-client schema infrastructure.
- Motherbrain should continue to be the shared admin surface, but its actions and insights must remain explicitly tenant-scoped by default.
- Later Phase 2 work like retries, smoother execution, and more autonomous learning should wait until the runtime is properly tenant-safe.

## DEC-011 - Phase 2 Begins With Per-Client Runtime Configuration

- Date: 2026-03-20
- Status: accepted
- Scope: `shared`

### Decision

Start the Phase 2 implementation by introducing a `client_configs` runtime model in `erp_ai`, moving ERP connectivity and schema caching to client-aware lookup paths, and updating Motherbrain to surface the richer telemetry fields produced in Phase 1.

### Reason

- Runtime multi-tenancy cannot happen until `erp_ai` can resolve ERP URL, credentials, and schema cache from `client_id` instead of only environment globals.
- The Motherbrain side should reflect the new telemetry immediately so Phase 1 gains are visible while Phase 2 work is underway.
- This is the smallest safe vertical slice that advances both the shared runtime architecture and the central admin panel together.

### Consequences

- Existing tenants can still fall back to environment-based ERP config until explicit client config rows are added.
- Schema cache files are now expected to become client-specific artifacts instead of one shared cache.
- Motherbrain dashboards and diagnostics can now include model, routed-table, and latency context when triaging incidents.
