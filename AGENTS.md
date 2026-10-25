# AGENTS.md — Catalog Import Watchtower

**Catalog Import Watchtower (CIW)** is a small full-stack web app that imports
vendor product catalogs from CSV files, validates every row before writing
anything, upserts products in one transaction, and keeps a history of imports
and their attempts. A failed import raises a durable **user-impact alert**. A
separate, LLM-powered **on-call worker** reads the incident through a narrow
tool allowlist, retries a transient failure once, escalates everything else,
and leaves an audit trail in the database. It is the final project for the AI
Dev Tools Zoomcamp 2026.

**This repository is the whole project** (ADR-0001; it began as
`finalproject/` in the course repo `elugardo/ai-dev-tools-zoomcamp`). Open
your coding session at the repository root so that `.claude/`, `.agents/`
and this file are picked up. Every path in these docs is relative to the
repository root.

## Read this first

| When | Read |
|---|---|
| Always, before any task | this file, then [`_docs/process.md`](_docs/process.md) |
| Deciding what to build, or whether something is in scope | [`_docs/spec.md`](_docs/spec.md) — the product and engineering spec; the only source of truth for scope |
| Turning the spec into issues, grooming one, or approving a finished one | [`_docs/team/product-manager.md`](_docs/team/product-manager.md), [`_docs/issue-template.md`](_docs/issue-template.md), [`_docs/backlog.md`](_docs/backlog.md) |
| Implementing an issue | [`_docs/team/software-engineer.md`](_docs/team/software-engineer.md) |
| Verifying an issue | [`_docs/team/qa-engineer.md`](_docs/team/qa-engineer.md) |
| Touching models, services, Compose, or the folder layout | [`_docs/architecture.md`](_docs/architecture.md) |
| Touching an endpoint, a request/response shape, or an error code | [`_docs/api.md`](_docs/api.md), then `openapi.yaml` (the contract, from issue 02 on) |
| Writing or reviewing tests | [`_docs/testing.md`](_docs/testing.md) |
| Telemetry, alerts, env vars, deployment, rollback, the real-LLM demo | [`_docs/operations.md`](_docs/operations.md) |
| Working on the runtime on-call worker, or triaging an incident by hand | [`_docs/team/oncall-agent.md`](_docs/team/oncall-agent.md) and [`.agents/skills/incident-response/SKILL.md`](.agents/skills/incident-response/SKILL.md) |
| Checking that a deliverable earns its points | [`_docs/rubric.md`](_docs/rubric.md) |
| Making a decision that is hard to reverse (provider, repo layout, schema, auth between services) | write an ADR in [`_docs/adr/`](_docs/adr/) first |

## Layout

Planned layout. Folders marked *(issue NN)* do not exist until that issue
lands; whoever creates one updates this section in the same PR.

```
<repo root>/
├── AGENTS.md, CLAUDE.md, README.md
├── .github/workflows/     ci.yml (PR checks); deploy-dev.yml, promote-prod.yml (issue 10)
├── openapi.yaml           API contract (OpenAPI 3.1), written before the code; validated in CI
├── compose.yaml           app, oncall-agent, db, otel-lgtm; one command; every ${VAR} has a default
├── Dockerfile, .dockerignore   multi-stage: node builds web/, then the Python image serving SPA + API; APP_VERSION build arg
├── .env.example           every variable, no secrets
├── pyproject.toml, uv.lock, .python-version   one package for app and worker; `[tool.uv] package = false`
├── alembic.ini, alembic/  migrations; env.py reads DATABASE_URL from app.settings and imports app.models; versions/ holds the first revision (the six tables, issue 02); later revisions are additive-only
├── app/                   FastAPI package: main.py, settings.py, db.py (engine, Base with the constraint naming convention), routers/health.py; app/services/ is the service layer (csv_validation.py: pure bytes -> rows | errors; importer in CIW-03.2, #4); app/oncall/ is the worker (idle stub; loop in issue 08); app/static/ is the built SPA (git-ignored)
│   ├── models/            SQLAlchemy models of the six tables (catalog.py, imports.py, incidents.py) and enums.py (the CHECK values)
│   └── schemas/           Pydantic v2 response models mirroring openapi.yaml (a unit test keeps them in step)
├── tests/                 conftest.py, unit/ (no database; contract tests), integration/ (real Postgres on localhost:5432, migrated by Alembic; schema, constraints, migration round trip); oncall/ (issue 08)
├── web/                   React 18 + TypeScript + Vite; Vitest + Testing Library in src/__tests__/; `npm run build` -> dist/, copied into app/static by the Dockerfile
├── observability/         otel-lgtm config + Grafana provisioning, all in-repo (issue 09)
├── fixtures/              valid.csv, update.csv, invalid.csv + edge cases; byte-exact (`.gitattributes`: -text)
├── _docs/                 spec, spec-review, process, architecture, api, testing, operations, rubric, backlog, team/, adr/, evidence/
├── .agents/skills/        incident-response/SKILL.md (canonical skill)
└── .claude/               agents/ (PM, engineer, QA), skills/
```

## Commands

Run from the repository root. Commands marked *(issue NN)* become real when that
issue lands; the engineer who makes one work replaces the placeholder here.

```
gh issue list --label final-project --state open     # the backlog
gh issue view <n> --comments                          # one issue with its groom / QA comments
docker compose up --build                             # app :8000 (SPA + API), db :5432, Grafana :3000, idle worker
docker compose up --build -d --wait                   # same, detached; returns once /api/health reports db: ok
docker compose down -v                                # stop and drop the data volume
uv run pytest tests/unit                              # backend unit tests; no database needed
uv run pytest tests/integration                       # backend integration tests against the Compose db (localhost:5432); runs `alembic upgrade head` first
uv run openapi-spec-validator openapi.yaml            # validate the OpenAPI 3.1 contract (also a CI step)
uv run alembic upgrade head                           # apply migrations to DATABASE_URL (the app entrypoint does this too)
uv run alembic check                                  # fails if the models and the migrations differ
uv run alembic revision --autogenerate -m "<what>"    # draft a new, additive-only revision; review it before committing
npm --prefix web test                                 # frontend tests (Vitest + Testing Library)
<single test command>                                 # all of the above in one go (issue 06)
docker compose exec app python -m app.oncall tools <tool> [args]   # run one agent tool by hand (issue 08)
```

## Rules

Short, because the spec is long. Each rule here is one that is easy to break
while looking right.

- **No issue, no work.** Every change belongs to an open GitHub issue with
  acceptance criteria. Reference it as `Refs #N` in commits; never `Closes #N`
  (closing happens after QA, see `_docs/process.md`).
- **Scope is `_docs/spec.md`.** Section 3 lists the non-goals; they stay out.
  If the spec is wrong or silent, stop and say so; the PM changes the spec, then
  the issue, then the code.
- **Validate the whole file, then write everything or nothing.** One invalid
  row means zero product changes. The batch is one database transaction.
- **Upsert by `(vendor_id, normalized_sku)`; never full replacement.** SKUs
  missing from a later upload are left alone.
- **Money is integer cents. Timestamps are UTC.** No floats for price, ever.
- **`Recovered` is a UI label**, not a status. Statuses are `PROCESSING`,
  `COMPLETED`, `FAILED`; a `COMPLETED` import with more than one attempt shows
  as recovered.
- **The on-call agent is a real LLM with tool calling**, limited to the six
  allowlisted tools in `_docs/team/oncall-agent.md`. It retries only
  `TRANSIENT_STORAGE_TIMEOUT`, at most once (two attempts total). Nothing else
  is retried automatically. Without credentials the app still works and the
  alert stays open with the agent marked unavailable.
- **Never send catalog content to the LLM or to telemetry.** No CSV rows,
  vendor names, product names, tokens, or credentials in prompts, spans, logs,
  or metric labels. Metric labels are low-cardinality only; `import_id` and
  `trace_id` go in logs and spans, not labels.
- **The failure injector is synthetic and is described as such** in the UI
  label, the README and the demo.
- **Secrets live in `.env`, which is never committed.** `.env.example` lists
  every variable with a safe placeholder.
- **Dependencies** go through `uv add` (one `pyproject.toml` for the app and
  the worker) and `npm install` (web), with the lock files committed. Do not
  add a queue, a cache, nginx, an extra service, or a UI framework; the stack
  is fixed in `_docs/architecture.md`. PostgreSQL everywhere, never SQLite.
- **One image, two processes.** The worker is `python -m app.oncall` on the
  same image and calls the service layer; there are no internal HTTP
  endpoints and no internal token.
- **Everything is configuration in the repo.** Compose, Collector, Grafana
  dashboards and alert rules, CI workflows. Nothing is clicked together by hand.
- **These documents are living.** After a correction ("don't do it that way"),
  update the document that should have prevented it, in the same PR.
