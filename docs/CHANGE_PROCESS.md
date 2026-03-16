# Change Tracking Process

This document defines how we will track implementation work across both projects:

- `erp_ai`
- `motherbrain_admin`

The goal is to keep a clear record of:

- what changed
- why it changed
- which files were touched
- how we verified it
- what follow-up work remains

## Files We Will Maintain

- `docs/WORKLOG.md`
  Daily implementation log with grouped changes.
- `docs/DECISIONS.md`
  Important product and technical decisions with rationale.

## Rules For Every Change Batch

For each implementation batch, we will add one entry to `docs/WORKLOG.md` with:

- date
- phase or milestone
- project name
- files changed
- summary of what changed
- reason for the change
- validation performed
- open follow-ups or risks

## When To Add A Decision Entry

Add an entry to `docs/DECISIONS.md` when a change affects:

- architecture
- data flow
- telemetry design
- AI behavior or routing
- memory strategy
- client isolation
- evaluation methodology
- automation or safety policy

## Scope Guidance

Use these labels in worklog entries:

- `erp_ai`
- `motherbrain_admin`
- `shared`

Use these labels in decision entries:

- `accepted`
- `superseded`
- `proposed`

## Working Agreement

- We will document changes before or immediately after implementation.
- We will group closely related file edits into one change batch.
- We will always include the reason behind a change, not just the diff.
- We will track both projects from this shared docs folder unless a project later needs its own local docs too.
