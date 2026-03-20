# Phase 2 Roadmap

## Goal

Phase 2 starts by finishing the real multi-tenant architecture for both `erp_ai` and `motherbrain_admin`.

We are not treating tenant awareness in prompts and telemetry as sufficient.
Before we push further into autonomous learning, we need the runtime itself to be tenant-safe.

Phase 2 should make the platform:

- truly multi-tenant at runtime
- safer for shared deployment
- easier to operate across many clients
- ready for later autonomous improvements without cross-client leakage

## Phase 2 Outcomes

By the end of Phase 2, we should have:

- per-client ERP connection configuration in `erp_ai`
- per-client schema cache and schema refresh flow
- per-client runtime routing so one shared `erp_ai` instance can safely talk to many ERP sites
- tenant-bound auth/session handling in the app layer
- tenant-safe Motherbrain ingestion, filtering, and remediation workflows
- a clean separation between:
  - global product intelligence
  - client-specific learning
  - per-session conversation context

## Workstreams

### 1. Multi-Tenant Runtime In ERP AI

Purpose:

- remove the remaining global single-client assumptions from the runtime
- make one `erp_ai` deployment serve multiple tenants safely

Primary files:

- `c:\laragon\www\erp_ai\database.py`
- `c:\laragon\www\erp_ai\main.py`
- `c:\laragon\www\erp_ai\erp_client.py`
- `c:\laragon\www\erp_ai\schema_fetcher.py`
- `c:\laragon\www\erp_ai\memory_manager.py`

Planned tasks:

- add a `clients` or equivalent configuration table
- store per-client ERP URL, API credentials, app name, and status
- stop relying on one global ERP URL/API token from environment variables for all tenants
- pass the active client configuration through request handling, schema fetching, and query execution
- ensure background jobs and memory backfills run in the correct tenant context

Definition of done:

- one running `erp_ai` instance can safely execute against different ERP backends depending on `client_id`
- no tenant depends on a shared global ERP connection at runtime

### 2. Per-Client Schema Infrastructure

Purpose:

- prevent schema leakage and schema confusion across tenants

Primary files:

- `c:\laragon\www\erp_ai\schema_fetcher.py`
- `c:\laragon\www\erp_ai\schema_router.py`
- `c:\laragon\www\erp_ai\schema_planner.py`
- `c:\laragon\www\erp_ai\schemas\`

Planned tasks:

- move from one shared schema cache file to per-client schema cache storage
- ensure schema refresh runs for the requested tenant only
- keep routed tables, live doctype details, and relation plans tenant-scoped
- expose admin-safe schema refresh and schema health status per tenant

Definition of done:

- schema metadata and relation plans never mix across clients
- a schema refresh for one tenant cannot affect another tenant’s runtime behavior

### 3. Tenant-Bound Learning And Memory

Purpose:

- keep learning isolated while still allowing future global promotion workflows

Primary files:

- `c:\laragon\www\erp_ai\database.py`
- `c:\laragon\www\erp_ai\memory_manager.py`
- `c:\laragon\www\erp_ai\main.py`
- `c:\laragon\www\motherbrain_admin\backend\main.py`
- `c:\laragon\www\motherbrain_admin\backend\database.py`

Planned tasks:

- formalize memory layers:
  - global
  - client-specific
  - session-specific
- ensure overrides, saved reports, semantic examples, and feedback remain tenant-scoped by default
- add explicit promotion rules for moving a repeated pattern from client-local to global candidate
- label all learning artifacts with tenant scope in Motherbrain

Definition of done:

- client-specific business logic cannot silently affect another tenant
- global learning only happens through an explicit promotion path

### 4. Multi-Tenant Motherbrain Admin

Purpose:

- make Motherbrain the central admin surface for many tenants without mixing their incidents

Primary files:

- `c:\laragon\www\motherbrain_admin\backend\database.py`
- `c:\laragon\www\motherbrain_admin\backend\main.py`
- `c:\laragon\www\motherbrain_admin\backend\ai_analyzer.py`
- `c:\laragon\www\motherbrain_admin\frontend\src\App.jsx`

Planned tasks:

- add tenant-aware filters, health views, and incident queues
- separate tenant-local remediation actions from global improvement candidates
- show schema/app/environment context per incident
- support per-tenant replay/evaluation and per-tenant override management

Definition of done:

- Motherbrain can monitor many tenants from one admin panel without mixing failures, overrides, or resolutions

### 5. Smarter Execution Layers After Multi-Tenancy

Purpose:

- continue the product improvements only after the platform is tenant-safe

Planned tasks after the architecture work:

- one safe self-repair retry on SQL failure
- faster schema routing and execution smoothing
- better clarification behavior on low-confidence prompts
- stronger evaluation automation from Motherbrain-reviewed incidents

Definition of done:

- Phase 2 architecture is complete first
- intelligence improvements resume on top of a tenant-safe base

## Suggested Implementation Order

1. Add client configuration storage in `erp_ai`
2. Refactor ERP connection and schema fetch/runtime to use client-specific config
3. Move schema cache and relation planning to per-client storage
4. Tighten tenant-bound learning and memory rules
5. Upgrade Motherbrain views and actions for many tenants
6. Resume smarter execution improvements like retries and self-healing

## Risks To Watch

- accidentally keeping hidden single-tenant assumptions in utility modules
- leaking schema cache or memory context between clients
- mixing tenant-specific fixes into global logic too early
- making auth/client selection too loose in the shared UI
- introducing operational complexity without enough health visibility

## Success Criteria

Phase 2 is successful if:

- `erp_ai` can safely serve multiple ERP clients from one deployment
- schema, memory, telemetry, and remediation remain tenant-scoped
- Motherbrain can review all tenants centrally without mixing their learnings
- later autonomous improvements can be added on top of that shared runtime safely
