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
