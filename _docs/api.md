# API

`openapi.yaml` at the project root is the contract (OpenAPI 3.1). Issue 02
wrote it before any endpoint was implemented; CI validates it
(`uv run openapi-spec-validator openapi.yaml`), and a unit test holds the
Pydantic response models in `app/schemas/` to its property names. The
generated-schema drift check, which compares the running app's
`/api/openapi.json` with the YAML, lands in CIW-03.2 (#4); the frontend's
client types are derived from the YAML in CIW-04.1 (#5). This file holds the
conventions and the error catalogue that the YAML alone does not explain. If
the two disagree, `openapi.yaml` wins and this file is fixed.

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
  with `line` the **file line number** (header = 1; a record spanning
  several lines reports the line it starts on), plus
  `validation_error_count` for the total beyond the 20 shown. Validation
  stops at 1 000 errors, so `validation_error_count` is at most 1 000.
  `message` is at most 200 characters. `column` is one of four kinds:
  - a lowercase field name, `sku`, `name`, `price` or `quantity`, for a
    field rule on that row (also when the file's header is `PRICE`);
  - `header` for an invalid header row (missing, unexpected, duplicate or
    empty headers), reported on the header's line as the only error;
  - `row` for a record that is wrong as a whole: a field count different
    from the header's, or a record the `csv` reader cannot parse
    (an unterminated quote, a field over its size limit). Validation stops
    at an unparseable record, so nothing after it is reported;
  - `file` for the file as a whole, always on line 1: an empty file or no
    data rows (`at least one data row`), more than 500 data rows (`file has
    N data rows, limit 500`), or bytes that are not UTF-8 (defensive only,
    because the upload returns 400 `INVALID_ENCODING` first).

  The validator is `app/services/csv_validation.py` (`validate_csv`, pure,
  no database).
- The four list endpoints (`GET /api/imports`, `/api/vendors`,
  `/api/products`, `/api/alerts`) return `{ "items": [...], "total": n }`,
  both required, newest first, with `limit` (default 50, min 1, max 100) and
  `offset` (default 0, min 0); a malformed or out-of-range value is 400
  `INVALID_QUERY`. Only the products list pages in the UI; on the others the
  parameters just bound the response.
- Timestamps are ISO-8601 UTC with `Z`. Money is `price_cents` (integer);
  the frontend formats dollars. No response carries `csv_bytes`, a
  `normalized_*` column or a price in dollars.
- On the import resource, `product_count` is `null` unless the import is
  `COMPLETED`, and `completed_at` is set only on the transition to
  `COMPLETED` (a `FAILED` import's end time is its last attempt's
  `finished_at`). `GET /api/imports/{id}` and the 201 of `POST /api/imports`
  return the **import detail**: the import plus `attempts[]`, `alert`
  (nullable) and `agent_actions[]`.
- Enum values are upper snake case strings exactly as in spec §6.
- `recovered` is a derived boolean on the import resource
  (`status == COMPLETED and attempt_count > 1`), never stored.
- There are **no internal or agent endpoints**. The agent's six tools are
  service-layer functions (`app/services/agent_tools.py`); see
  `architecture.md` and `team/oncall-agent.md`.

## Endpoints (spec §7)

| Method | Route | Purpose | Notable responses |
|---|---|---|---|
| `POST` | `/api/imports` | multipart `vendor_name`, `file`, optional `inject_transient_failure` (`true`/`false`, default `false`) | 201 import detail (for `COMPLETED` and `FAILED` alike); 400 `MISSING_FIELD`, `INVALID_FIELD`, `INVALID_CONTENT_TYPE`, `INVALID_ENCODING`; 413 `FILE_TOO_LARGE` |
| `GET` | `/api/imports` | recent imports, newest 50; `limit`/`offset` | 200 list; 400 `INVALID_QUERY` |
| `GET` | `/api/imports/{id}` | detail: errors (≤ 20 + total), attempts, alert, agent timeline | 200; 404 `NOT_FOUND` |
| `GET` | `/api/vendors` | vendor filter options; `limit`/`offset` | 200 list; 400 `INVALID_QUERY` |
| `GET` | `/api/products` | catalog; optional `vendor_id`; `limit`/`offset` | 200 list; 400 `INVALID_QUERY` |
| `GET` | `/api/alerts` | open and recent alerts with import summary (`import_id`, `import_status`, `failure_code`, `vendor_display_name`, `filename`); `limit`/`offset` | 200 list; 400 `INVALID_QUERY` |
| `GET` | `/api/health` | always 200 while up; `{ status: "ok"\|"degraded", db: "ok"\|"error", agent_enabled, version }`; `status` is `degraded` when `db` is `error` | 200 |

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
