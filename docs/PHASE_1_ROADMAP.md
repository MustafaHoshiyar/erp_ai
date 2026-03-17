# Phase 1 Roadmap

## Goal

Phase 1 establishes the foundation for a smarter and more reliable ERP reporting assistant.

We are not trying to make the system fully autonomous yet.
We are first making it:

- measurable
- cleaner in telemetry
- more accurate about intent
- safer to improve in later phases

## Phase 1 Outcomes

By the end of Phase 1, we should have:

- cleaner telemetry with less noise
- a clear split between conversational prompts and analytics/report prompts
- a clear path for the assistant to ask clarifying questions when the request is too ambiguous
- a reusable evaluation dataset built from real testing
- baseline metrics for quality and latency
- a Motherbrain dashboard that reflects the cleaner signal

## Workstreams

### 1. Prompt Intent Classification

Purpose:

- detect whether a prompt is chat, reporting, forecasting, unsupported, or needs clarification
- prevent non-report prompts from being logged as SQL failures

Primary files:

- `c:\laragon\www\erp_ai\ai_engine.py`
- `c:\laragon\www\erp_ai\main.py`
- `c:\laragon\www\erp_ai\database.py`

Planned tasks:

- add a lightweight intent classification step before SQL generation
- define initial intent labels:
  - `chat`
  - `report`
  - `forecast`
  - `clarification_needed`
  - `unsupported`
- return a non-error assistant response for `chat`
- return a targeted clarifying question for `clarification_needed` prompts instead of forcing SQL generation
- avoid storing `No SQL generated` as a system failure for non-report prompts
- store the detected intent with each conversation message

Definition of done:

- prompts like `hello` and `what is your name` no longer pollute failure telemetry
- ambiguous follow-up prompts can trigger a useful clarifying question instead of a false error
- report prompts still flow into SQL generation normally

### 2. Telemetry Enrichment

Purpose:

- improve future failure analysis
- support learning, clustering, and retry logic in later phases

Primary files:

- `c:\laragon\www\erp_ai\database.py`
- `c:\laragon\www\erp_ai\main.py`
- `c:\laragon\www\erp_ai\scripts\telemetry_sync.py`
- `c:\laragon\www\motherbrain_admin\backend\database.py`
- `c:\laragon\www\motherbrain_admin\backend\main.py`

Planned tasks:

- add telemetry fields for:
  - detected intent
  - model used
  - stage latency if available
  - schema routing result if available
  - whether SQL was generated
  - whether execution was attempted
  - whether the event is a true failure or only feedback
- sync those fields to Motherbrain
- persist them in Motherbrain for later analysis

Definition of done:

- Motherbrain events can distinguish chat noise from true analytics incidents
- telemetry can explain what happened, not just that something failed

### 3. Evaluation Dataset Pipeline

Purpose:

- convert coworker testing data into a reliable regression suite

Primary files:

- `c:\laragon\www\erp_ai\scripts\golden_dataset.json`
- `c:\laragon\www\erp_ai\scripts\evaluate_ai.py`
- `c:\laragon\www\erp_ai\dataset.jsonl`
- `c:\laragon\www\motherbrain_admin\frontend\src\App.jsx`

Planned tasks:

- define a normalized eval format for gathered prompts
- classify each prompt into:
  - expected response type
  - expected tables
  - expected logic markers
  - expected result quality category
- include prompts that should trigger clarifying questions so we can measure whether the assistant asks when needed
- extend the evaluator to track:
  - generation success
  - intent classification correctness
  - clarification-question correctness
  - required SQL logic markers
- expose baseline eval numbers in docs first, and later in Motherbrain if useful

Definition of done:

- we can replay a real dataset after every major change
- we can compare before and after results with the same prompts

### 4. Baseline Metrics

Purpose:

- measure improvements phase by phase

Primary files:

- `c:\laragon\www\erp_ai\main.py`
- `c:\laragon\www\erp_ai\database.py`
- `c:\laragon\www\motherbrain_admin\backend\main.py`
- `c:\laragon\www\motherbrain_admin\frontend\src\App.jsx`

Metrics to establish:

- total prompts
- reporting prompts
- chat prompts
- SQL generation success rate
- execution success rate
- negative feedback rate
- true-failure rate
- average latency if available

Definition of done:

- we can state the current system baseline before Phase 2 starts

## Suggested Implementation Order

1. Add intent classification in `erp_ai`
2. Update storage schema for intent and telemetry fields
3. Update telemetry sync payload
4. Update Motherbrain ingestion schema and event model
5. Update Motherbrain dashboard filters and stats
6. Upgrade evaluation dataset structure and evaluator
7. Document baseline metrics in shared docs

## Risks To Watch

- over-classifying report prompts as chat or unsupported
- asking clarifying questions too often and slowing down valid report requests
- adding telemetry fields without migration support
- breaking existing feedback and sync flows
- mixing evaluation data from different clients without labeling tenant context

## Success Criteria

Phase 1 is successful if:

- conversational prompts no longer appear as SQL failures
- ambiguous prompts trigger clarification more often than false failures
- telemetry quality is visibly cleaner in Motherbrain
- we have a reusable evaluation dataset from real prompts
- we can measure current performance and compare future phases against it
