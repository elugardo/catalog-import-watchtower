# Architecture

What the system is made of and the decisions already taken, so that no issue
has to re-decide them. Spec §6 to §8 are the requirements; this file is how
they are met. Decisions that are hard to reverse have an ADR in
[`adr/`](adr/); the rest are recorded here.

## Stack (fixed)

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite, Vitest + Testing Library | plain CSS; no component framework |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x (sync), Alembic, Pydantic v2, `uv` | one package, one `pyproject.toml`; synchronous import processing (§8) |
| Database | PostgreSQL 16, psycopg 3 | local **and** deployed; never SQLite |
| On-call worker | the same Python package, `python -m app.oncall`; the chosen LLM provider's official SDK with tool calling | same image, different command; no HTTP to the API |
| Telemetry | OpenTelemetry SDK (traces, metrics, logs) → local `grafana/otel-lgtm` | exporter disabled when deployed (ADR-0002) |
| Containers | one multi-stage Dockerfile, Docker Compose | `docker compose up --build` is the one command |
| CI/CD | GitHub Actions; public image in GHCR tagged `sha-<commit>`; Fly.io `ciw-dev` / `ciw-prod`; Neon PostgreSQL | ADR-0002 |

Not in the stack, by spec §8: Redis, Celery or any queue, Kubernetes, nginx,
extra microservices, object storage. Do not add them.

## Components

```
browser ──▶ app (FastAPI: SPA at /, API at /api) ──▶ db (Postgres)
                 │                                     ▲
                 └── OTLP ──▶ otel-lgtm (Grafana)       │
            oncall-agent (same image, python -m app.oncall) ── service layer ──┘
                 │
                 └── LLM provider (tool calling); key lives only in this process
```

- **app** serves the built SPA from `app/static/` and owns every rule: CSV
  parsing and validation, the transactional upsert, import/attempt/alert
  state transitions, the agent tool functions with their guards, telemetry.
  During development the Vite dev server proxies `/api` to it.
- **oncall-agent** is thin: poll, claim, run one LLM conversation with the
  six tool functions, which write their own audit rows. It imports the
  service layer directly; there is no internal HTTP API and no token.
- **db** is the system of record for statuses, attempts, alerts, the audit
  timeline and the bounded source CSV.
- **otel-lgtm** receives OTLP from both processes; dashboards and the alert
  rule are provisioned from `observability/`.

## Folder layout

```
app/
  main.py              FastAPI app, routers, static mount, startup sweep
  settings.py          env-driven config (pydantic-settings)
  db.py                engine, session, Base
  models/              SQLAlchemy models, one module per table group
  schemas/             Pydantic request/response models (mirror openapi.yaml)
  services/
    csv_validation.py  pure: bytes → (rows | errors); no DB
    importer.py        transaction: validate, inject, upsert, attempts, status
    alerts.py          create / claim / transition alerts, stale-claim reset
    agent_tools.py     the six guarded tool functions, each writes its audit row
  routers/             imports, vendors, products, alerts, health
  telemetry.py         OTel setup, metrics, span helpers
  oncall/
    __main__.py        `python -m app.oncall` (worker) and `… tools <tool> …` (maintenance CLI)
    poller.py          poll, claim, dispatch
    llm.py             provider client, tool schemas, the conversation loop
    prompt.py          system prompt, derived from _docs/team/oncall-agent.md
  static/              built SPA, produced by the Dockerfile (git-ignored)
alembic/               migrations
tests/
  unit/                no DB
  integration/         real Postgres
  oncall/              fake LLM, policy, guards
web/                   Vite project: src/ (Dashboard, Upload, Imports, ImportDetail, Products), src/__tests__/
observability/         otel-lgtm config, Grafana provisioning (datasource, dashboard JSON, alert rule)
fixtures/              valid.csv, update.csv, invalid.csv (+ edge-case files used by tests)
Dockerfile             stage 1: node builds web/ → stage 2: python image with app/ and app/static/
compose.yaml           app, oncall-agent, db, otel-lgtm; .env for secrets
pyproject.toml, uv.lock, openapi.yaml, .env.example
```

## Data model decisions

The tables and enums are spec §6. On top of it:

- **Ids** are integer `BIGSERIAL`.
- **Normalization:** `vendors.normalized_name` = trimmed, casefolded display
  name; `products.normalized_sku` = trimmed, casefolded SKU. Uniqueness is
  enforced by the database, not only by application code.
- **Prices** are `price_cents BIGINT`, parsed with the grammar in §4 F2.
- **Timestamps** are `TIMESTAMPTZ`, written and read as UTC.
- **`imports.csv_bytes`** is `BYTEA`, capped at 256 KiB before insert;
  `sha256` is computed over the raw bytes and shown in the detail page.
- **Statuses and codes** are `VARCHAR` with a `CHECK` constraint; adding a
  value is an additive migration.
- **`alerts.import_id` is unique**; a retry that fails again updates the
  same alert. `alerts.claimed_at` drives the stale-claim reset.
- **Migrations are additive-only** within the MVP, so a rollback to the
  previous image runs against the newer schema. They run from the container
  entrypoint (`alembic upgrade head`) before the server starts; one instance
  per environment makes that safe.

## Import processing (the one flow that matters)

1. `POST /api/imports` runs the no-parse checks (field presence, vendor name,
   content type and filename, UTF-8, ≤ 256 KiB read with a hard cap) and
   returns 4xx with no record if any fails. Otherwise it finds-or-creates the
   vendor (`ON CONFLICT DO NOTHING` + select) and inserts the import with
   `status = PROCESSING` in its own transaction.
2. `importer.run_attempt(import_id)` inserts `import_attempts` row *n*
   (`RUNNING`, own transaction), starts a span with `import_id` and
   `attempt_number`, then:
   1. parses and validates the whole file (`csv_validation`, pure);
   2. on any validation error: stores the first 20 errors and the total,
      sets `FAILED` / `VALIDATION_ERROR`, creates the alert, marks the
      attempt `FAILED`; no product writes;
   3. opens the upsert transaction; if `inject_transient_failure` and
      *n* = 1 raises the synthetic `TRANSIENT_STORAGE_TIMEOUT` before any
      write; a real `OperationalError` here maps to the same code, anything
      else to `INTERNAL_ERROR`; on failure: rollback, attempt `FAILED`,
      import `FAILED` with the code, alert created (or kept);
   4. otherwise upserts every row by `(vendor_id, normalized_sku)`,
      commits, marks the attempt `SUCCEEDED`, sets `COMPLETED`,
      `product_count`, `completed_at`, clears `failure_code`.
3. The response is `201` with the import resource; its `status` says what
   happened.
4. `agent_tools.retry_failed_import(import_id)` takes `SELECT … FOR UPDATE`
   on the import row, re-reads status, failure code and attempt count,
   refuses (returns the current state, no exception) unless status is
   `FAILED`, the code is `TRANSIENT_STORAGE_TIMEOUT` and the count is 1, then
   runs step 2 with *n* = 2. Two concurrent calls: one proceeds, the other
   waits on the lock, re-reads, and no-ops.
5. On startup, `app` sets any import still `PROCESSING` to `FAILED` /
   `INTERNAL_ERROR` and creates its alert (crash recovery).

## On-call worker loop

1. Every `AGENT_POLL_SECONDS`: reset `IN_PROGRESS` alerts older than
   `AGENT_CLAIM_TIMEOUT_SECONDS` to `OPEN`; claim the oldest `OPEN` alert
   with `UPDATE … SET status='IN_PROGRESS', claimed_at=now() WHERE id=? AND
   status='OPEN'`; zero rows means move on.
2. Write `RUN_STARTED` (provider and model name), start a trace with
   `alert_id`, run one LLM conversation whose tools are the six functions in
   `agent_tools.py`, bounded by `AGENT_MAX_TOOL_CALLS` and
   `AGENT_TIMEOUT_SECONDS`.
3. Each tool function enforces its guard, redacts its output, writes
   `TOOL_CALL`; the loop writes `DECISION` from the model's stated reason and
   `RUN_FINISHED` (or `ERROR`) with the outcome.
4. `python -m app.oncall tools <tool> [args]` runs one tool function by
   hand with the same guards and audit rows; it is how a human triages
   following `.agents/skills/incident-response/SKILL.md`.

## Auth between components

None needed: the worker is in-process with the service layer, and the public
API has no users (spec §2). The only secrets are the database URL and the
LLM key, both in `.env` / provider secrets.

## Decided elsewhere

- **ADR-0001:** the project stays in the course monorepo; the three
  workflow files at the repo root are the only project files outside
  `finalproject/`.
- **ADR-0002:** Fly.io apps `ciw-dev` / `ciw-prod` with `app` and `worker`
  process groups from the same image, Neon PostgreSQL per environment,
  public image in GHCR, telemetry exporter disabled when deployed, agent
  disabled when deployed. Secrets inventory lives there and in
  `operations.md`.
- **Runtime LLM:** provider API with tool calling (spec §4 F5); the key
  exists only locally.
