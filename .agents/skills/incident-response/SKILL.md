---
name: incident-response
description: Diagnose and recover a failed catalog import in Catalog Import Watchtower. The routine the runtime on-call agent follows, and the one to follow by hand when triaging an open alert.
---

# Incident response: failed catalog import

This skill is project-specific to Catalog Import Watchtower. It is the single
routine for a failed-import alert, whether it is run by the LLM on-call
worker (through its six tools) or by a person or coding agent triaging by
hand (through the UI, `curl`, and the observability UI). The policy and the
guards it relies on are defined in `_docs/team/oncall-agent.md`; this file is
the order of operations.

Principles: work from recorded facts, not guesses; change nothing but alert
status and the one allowed retry; write down every step; never look at
catalog content you do not need (the agent cannot; a human should not have
to).

## 1. Claim

Take the alert `OPEN → IN_PROGRESS`. If that fails, someone else has it: stop.
Record `run_started` with who or what is handling it (worker: provider and
model; human: name).

## 2. Read the incident

`get_import_incident(alert_id)` (worker) or
`docker compose exec app python -m app.oncall tools get_import_incident <alert_id>`
(human; every CLI call has the same guards and writes the same audit rows).
Note:

- import id, import status, failure code
- attempt count and the per-attempt list from `get_import_attempts`
- alert created/updated times
- the trace id of the failed attempt

Do not fetch the CSV, the vendor, or the products. They are not needed to
decide, and the worker has no tool for them by design.

## 3. Classify

| Failure code | Class | Automatic recovery? |
|---|---|---|
| `TRANSIENT_STORAGE_TIMEOUT` | transient infrastructure fault | yes, once |
| `VALIDATION_ERROR` | data error, needs a corrected file from the operator | never |
| anything else or missing | unknown | never |

Also check the budget: attempts so far. Two attempts means the one automated
retry has already been spent.

## 4. Decide

Write the decision and its reason *before* acting, as an `agent_actions`
row (worker) or a note (human):

- transient and attempts = 1 → retry once
- transient and attempts ≥ 2 → needs attention, "retry budget exhausted"
- validation → needs attention, "N validation errors; operator must upload a
  corrected file"; do not retry, do not touch the file
- unknown → needs attention with the code

## 5. Act

- Retry: `retry_failed_import(import_id)` (CLI: `… tools
  retry_failed_import <import_id>`). It reuses the saved CSV, refuses if
  the guards fail, and is safe to call twice (the second call is a no-op
  returning the current state). Expect one new `import_attempts` row.
- Escalate: `mark_needs_attention(alert_id, reason)` (CLI: `… tools
  mark_needs_attention <alert_id> "<reason>"`).

## 6. Verify

Re-read `get_import_attempts(import_id)` and the import status:

- status `COMPLETED` and attempt 2 `SUCCEEDED` → `resolve_alert(alert_id)`
- still `FAILED` → `mark_needs_attention` with the new attempt's error code

Never resolve an alert whose import is not `COMPLETED`.

## 7. Record

End the run with `run_finished` carrying the outcome
(`RESOLVED`, `NEEDS_ATTENTION`) and totals (tool calls, duration). The import
detail page's agent activity timeline must now tell the full story without
any other source.

## 8. Report (human triage and demos)

For a hand-run incident or the documented real-LLM demonstration, capture
under `_docs/evidence/<date>-<import_id>/`:

- the import detail page showing two attempts and the agent timeline
- the `agent_actions` rows (JSON export or screenshot)
- the failed attempt's trace in the observability UI, with the log lines
  that share its trace id
- the metrics before and after (`catalog_import_attempts_total` by outcome,
  `catalog_import_alerts_open`)
- provider and model name used

And a short `report.md`: what the operator saw, the failure code, the
decision, the action, the outcome, and links to the evidence above. Never
include CSV rows, vendor or product names, or tokens in the report.

## Observability queries

Filled in by issue 09 and kept current in `_docs/operations.md`: the Loki
query for one import's logs, the Tempo search for a failed attempt, and the
Prometheus queries for the four metrics.
