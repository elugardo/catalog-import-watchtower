# API

`openapi.yaml` at the project root is the contract. Issue 02 writes it before
any endpoint is implemented; after that the backend's generated schema is
checked against it in CI, and the frontend's client types are derived from
it. This file holds the conventions and the error catalogue that the YAML
alone does not explain. If the two disagree, `openapi.yaml` wins and this file
is fixed.

## Conventions

- Root `/api`. JSON everywhere except the multipart upload. The SPA is
  served from `/` by the same process.
- `POST /api/imports` returns **201** whenever the import record was
  created, even if processing ended `FAILED`; the processing outcome is in
  the body. 4xx is reserved for requests that could not create a record at
  all (spec §4 F1 lists them).
- Errors use one shape:

  ```json
  { "code": "FILE_TOO_LARGE", "message": "CSV exceeds 256 KiB", "details": [] }
  ```

  `details` is a list of objects. Validation feedback inside an import
  resource (not an HTTP error) is
  `{ "line": 3, "column": "quantity", "message": "must be a whole number, got '-2'" }`
  with `line` the **file line number** (header = 1), plus
  `validation_error_count` for the total beyond the 20 shown.
- Lists return `{ "items": [...], "total": n }` with `limit` (default 50,
  max 100) and `offset`. Newest first.
- Timestamps are ISO-8601 UTC with `Z`. Money is `price_cents` (integer);
  the frontend formats dollars.
- Enum values are upper snake case strings exactly as in spec §6.
- `recovered` is a derived boolean on the import resource
  (`status == COMPLETED and attempt_count > 1`), never stored.
- There are **no internal or agent endpoints**. The agent's six tools are
  service-layer functions (`app/services/agent_tools.py`); see
  `architecture.md` and `team/oncall-agent.md`.

## Endpoints (spec §7)

| Method | Route | Purpose | Notable responses |
|---|---|---|---|
| `POST` | `/api/imports` | multipart `vendor_name`, `file`, optional `inject_transient_failure` (`true`/`false`) | 201 import; 400 `MISSING_FIELD`, `INVALID_FIELD`, `INVALID_CONTENT_TYPE`, `INVALID_ENCODING`; 413 `FILE_TOO_LARGE` |
| `GET` | `/api/imports` | recent imports, newest 50 | 200 list |
| `GET` | `/api/imports/{id}` | detail: errors (≤ 20 + total), attempts, alert, agent timeline | 200; 404 `NOT_FOUND` |
| `GET` | `/api/vendors` | vendor filter options | 200 list |
| `GET` | `/api/products` | catalog; optional `vendor_id`; `limit`/`offset` | 200 list; 400 `INVALID_QUERY` |
| `GET` | `/api/alerts` | open and recent alerts with import summary | 200 list |
| `GET` | `/api/health` | always 200 while up; `{ status, db: "ok"\|"error", agent_enabled, version }` | 200 |

## Codes

Import `failure_code` (persisted, drives the agent policy):

| Code | Meaning | Retried by agent |
|---|---|---|
| `VALIDATION_ERROR` | headers or rows invalid (including > 500 rows); nothing written | never |
| `TRANSIENT_STORAGE_TIMEOUT` | synthetic fault on attempt 1, or a real `OperationalError` in the upsert transaction | once |
| `INTERNAL_ERROR` | anything unexpected, or an import found `PROCESSING` after a restart | never (needs attention) |

HTTP error `code` values: `MISSING_FIELD`, `INVALID_FIELD`,
`INVALID_CONTENT_TYPE`, `INVALID_ENCODING`, `FILE_TOO_LARGE`,
`INVALID_QUERY`, `NOT_FOUND`, `INTERNAL_ERROR`.

Validation messages are short, name the rule, and may quote the offending
value, because they are shown only to the operator in the UI. The agent's
tool results carry counts and column names, never values.

## Redaction contract for the agent tools

`get_import_incident`, `get_import_attempts` and `get_import_diagnostics`
may return only: `alert_id`, `alert_status`, `import_id`, `import_status`,
`failure_code`, `attempt_count`, `attempts[] {number, status, error_code,
trace_id, started_at, finished_at}`, `row_count`,
`validation_error_count`, `validation_error_columns[]`, `created_at`,
`completed_at`, `diagnostics {log_query, trace_query}`. A unit test asserts
that no key outside this list, and no vendor name, product name, SKU or cell
value, appears in any tool result.
