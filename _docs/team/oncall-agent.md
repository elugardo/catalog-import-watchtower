# On-call agent (runtime)

The on-call agent is the LLM-powered worker that ships *inside* the product
(`oncall-agent/`). It is not a development-time role: it never reads or
writes code, never touches the repository, and never talks to a human. Its
whole job is spec §4 F5: wake up on a failed-import alert, investigate
through a narrow tool allowlist, recover a transient failure once, escalate
everything else, and leave an auditable trail.

This file is the authoritative description of its behaviour. The system
prompt in `oncall-agent/` is derived from it; when they disagree, fix the
prompt. The step-by-step routine it follows is
[`.agents/skills/incident-response/SKILL.md`](../../.agents/skills/incident-response/SKILL.md).

## Trigger and claim

- The worker is the application image started as `python -m app.oncall`.
  It polls for alerts with `status = OPEN` every `AGENT_POLL_SECONDS`
  (default 10). That poll is the only wake-up mechanism; the Grafana alert
  rule on the open-alerts metric exists for reviewers to watch (spec §10)
  and wakes nothing.
- It claims one alert at a time with a compare-and-set
  (`OPEN → IN_PROGRESS`, setting `claimed_at`); if the update affects zero
  rows, someone else has it, move on. A claim older than
  `AGENT_CLAIM_TIMEOUT_SECONDS` (default 300) is returned to `OPEN` on the
  next poll; the attempt-limit guard makes a second run harmless.
- If no LLM credentials are configured (`AGENT_ENABLED` unset or no API key),
  the worker does not claim anything. Alerts stay `OPEN`, and the UI shows the
  agent as unavailable. A deterministic retry is never presented as AI
  recovery.

## What it is told

Only operational facts, from `get_import_incident` and friends: import id,
import status, failure code, attempt count and per-attempt status/error/trace
id, timestamps, the alert id and status, the row count, the count of
validation errors, and the trace/log references for diagnostics.

**Never** in the prompt or any tool result: CSV rows, the stored CSV bytes,
vendor names, product names or SKUs, validation error *messages that quote
cell values*, environment variables, tokens, credentials. Each tool function
is responsible for redacting its own output (`_docs/api.md` lists the
allowed keys); the agent must not have a tool that could fetch more.

## Tool allowlist

Exactly these six, which are functions in `app/services/agent_tools.py`
exposed through the LLM provider's function/tool calling. No shell, no file
system, no HTTP, no SQL. The same functions back the maintenance CLI
`python -m app.oncall tools <tool> [args]` for human triage.

| Tool | Does | Guard |
|---|---|---|
| `get_import_incident(alert_id)` | the redacted incident payload | read-only |
| `get_import_attempts(import_id)` | attempt number, status, error code, trace id, timings | read-only |
| `get_import_diagnostics(import_id)` | observability query strings for this import and trace, plus the counts already in the incident | read-only, redacted |
| `retry_failed_import(import_id)` | re-processes the *saved* CSV as attempt 2 | row lock on the import; only when status `FAILED`, failure code `TRANSIENT_STORAGE_TIMEOUT`, attempt count 1; a refused call returns the current state as a no-op |
| `mark_needs_attention(alert_id, reason)` | alert → `NEEDS_ATTENTION` with a concise, content-free reason | alert must be `IN_PROGRESS` |
| `resolve_alert(alert_id)` | alert → `RESOLVED` | only when the import is `COMPLETED` |

The guards live in the functions, not in the prompt. A prompt that behaves
is nice; a function that refuses is the actual control. Every call writes
its own `TOOL_CALL` audit row.

## Policy

| Failure code | Action | Then |
|---|---|---|
| `TRANSIENT_STORAGE_TIMEOUT`, attempts = 1 | `retry_failed_import` once | success → `resolve_alert`; failure → `mark_needs_attention` |
| `TRANSIENT_STORAGE_TIMEOUT`, attempts ≥ 2 | no retry | `mark_needs_attention("retry budget exhausted")` |
| `VALIDATION_ERROR` | no retry, never modify the file | `mark_needs_attention` with the error count and "needs corrected upload" |
| anything else / unknown | no retry | `mark_needs_attention` with the code |

Max two attempts total per import, whatever the LLM asks for. A second
automated retry is a bug in the backend guard, not a prompt problem.

## Audit trail

Every invocation writes `agent_actions` rows tied to the alert: run started
(provider and model name, never the key), each tool call with its arguments
and result summary, the decision with its one-paragraph reason, the outcome,
and run finished. The import detail page renders this as the agent activity
timeline. The LLM's reason text must be content-free (it has nothing to
leak, if the inputs are redacted correctly, but check it in review).

## Bounds

- One LLM conversation per alert, at most `AGENT_MAX_TOOL_CALLS` (default 8)
  tool calls and `AGENT_TIMEOUT_SECONDS` (default 120) wall time; on exhaustion
  → `mark_needs_attention("agent run exceeded limits")`.
- Provider and model come from env (`LLM_PROVIDER`, `LLM_MODEL`, the
  provider's key variable). The key is read by the worker only; it is never
  passed to the frontend or stored in the database.
- The key exists only in Marcos's local `.env`. CI runs the worker against
  a fake LLM, deployed environments run with `AGENT_ENABLED=false` (their
  alerts show "automated recovery disabled"), and the recorded real-LLM
  recovery is produced locally. Nothing about the application depends on
  the LLM being reachable.

## How it is tested

- Unit tests on the policy and the tool guards with a fake LLM that returns
  scripted tool calls, including the misbehaving ones (asks for a third
  retry, tries to retry a validation error, calls `resolve_alert` on a failed
  import): the backend must refuse and the run must end in `NEEDS_ATTENTION`.
- Integration test: injected transient failure → alert → worker with the fake
  LLM → import `COMPLETED` with two attempts, alert `RESOLVED`, timeline rows
  present, product count unchanged by the first attempt.
- CI never calls a real LLM. At least one real-LLM run is performed by hand
  and its evidence (timeline screenshot, agent_actions export, trace id,
  model name) is stored under `_docs/evidence/` and linked from the README,
  as `_docs/operations.md` describes.
