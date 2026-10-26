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
| Running the loop as the orchestrator (groom, implement, QA, PM approval, merge, close) | [`.claude/skills/work-issue/SKILL.md`](.claude/skills/work-issue/SKILL.md) and the agent definitions in [`.claude/agents/`](.claude/agents/), with [`_docs/process.md`](_docs/process.md) |
| Touching an endpoint, a request/response shape, or an error code | [`_docs/api.md`](_docs/api.md), then [`openapi.yaml`](openapi.yaml) (the contract) |
| Writing or reviewing tests | [`_docs/testing.md`](_docs/testing.md) |
| Telemetry, alerts, env vars, deployment, rollback, the real-LLM demo | [`_docs/operations.md`](_docs/operations.md) |
| Working on the runtime on-call worker, or triaging an incident by hand | [`_docs/team/oncall-agent.md`](_docs/team/oncall-agent.md) and [`.agents/skills/incident-response/SKILL.md`](.agents/skills/incident-response/SKILL.md) |
| Checking that a deliverable earns its points | [`_docs/rubric.md`](_docs/rubric.md), and the reports in [`_docs/evidence/`](_docs/evidence/) that back each row ([`README.md`](_docs/evidence/README.md) says what a report holds) |
| Making a decision that is hard to reverse (provider, repo layout, schema, auth between services) | write an ADR in [`_docs/adr/`](_docs/adr/) first |

## Layout

Planned layout. Folders marked *(issue NN)* do not exist until that issue
lands; whoever creates one updates this section in the same PR.

```
<repo root>/
├── AGENTS.md, CLAUDE.md, README.md
├── .github/workflows/     ci.yml (PR checks: gitleaks, the one test command, runtime image built once, scenario 6); deploy-dev.yml (push to main: GHCR sha-<SHA> + dev, flyctl deploy to ciw-dev, smoke check); promote-prod.yml (issue 15)
├── fly.toml               Fly config of ciw-dev (region ewr, release_command migrates, stops when idle, zero worker machines); no secret, no build
├── openapi.yaml           API contract (OpenAPI 3.1), written before the code; validated in CI
├── compose.yaml           app, oncall-agent, db, otel-lgtm; one command; every ${VAR} has a default
├── compose.test.yaml      test overlay: only the `test` service of the one test command; never part of `up`
├── Dockerfile.test, Dockerfile.test.dockerignore   the test image (never deployed); its own ignore file keeps tests/ out of the runtime context
├── scripts/run_tests.py   entry point of the `test` container: every layer in order, one summary line each
├── scripts/smoke_check.py deployed /api/health check with bounded retries (deploy-dev.yml); stdlib only
├── .gitattributes         fixtures/*.csv unconverted; scripts/** LF
├── Dockerfile, .dockerignore   multi-stage: node builds web/, then the Python image serving SPA + API; APP_VERSION build arg
├── .env.example           every variable, no secrets
├── pyproject.toml, uv.lock, .python-version   one package for app and worker; `[tool.uv] package = false`
├── alembic.ini, alembic/  migrations; env.py reads DATABASE_URL from app.settings and imports app.models; versions/ holds the first revision (the six tables); later revisions are additive-only
├── app/                   FastAPI package: main.py, settings.py, db.py (engine, Base with the constraint naming convention), main.py also maps every error to the one shape (never 422) and runs the startup sweep, and strips the 422 from the generated schema; routers/ (health.py; imports.py: POST /api/imports, GET /api/imports and GET /api/imports/{id}; vendors.py, products.py, alerts.py: the other three lists); schemas/ (response models; upload.py: the no-parse upload checks; query.py: the list query parameters and their integer grammar); app/services/ is the service layer (csv_validation.py: pure bytes -> rows | errors; importer.py: create_import, run_attempt(import_id, attempt_number), the startup sweep, the import detail and the shared import summary; vendors.py: vendor find-or-create; lists.py: the read-only list queries); app/oncall/ is the worker (idle stub; loop in issue 08); app/static/ is the built SPA (git-ignored)
│   ├── models/            SQLAlchemy models of the six tables (catalog.py, imports.py, incidents.py) and enums.py (the CHECK values)
│   └── schemas/           Pydantic v2 response models mirroring openapi.yaml (a unit test keeps them in step)
├── tests/                 conftest.py, unit/ (no database; contract tests), integration/ (real Postgres on localhost:5432, migrated by Alembic; schema, constraints, migration round trip; the import API, whose tests commit and clean up after themselves through the `ns` fixture, helpers in integration/importing.py); oncall/ (issue 08)
├── web/                   React 18 + TypeScript + Vite + react-router-dom; src/App.tsx is the shell (nav, routes, health footer; the one /api/health request is shared with the pages); src/api/ (client.ts: the one fetch client and error path; schema.d.ts: generated by `npm run gen:api` from openapi.yaml, never edited, drift-checked in CI); src/pages/ (Upload, Imports, Dashboard, ImportDetail, Products); src/components/ (shared status labels, tables, error text, health context, useRequest); src/format.ts (shared UTC and integer-cents price formatters); Vitest + Testing Library in src/__tests__/; `npm run build` -> dist/, copied into app/static by the Dockerfile
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
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test   # THE test command: unit, integration, check:api, Vitest; needs only Docker (_docs/testing.md)
uv run pytest tests/unit                              # one layer on the host (needs uv): backend unit tests; no database needed
uv run pytest tests --ignore=tests/unit               # one layer on the host (needs uv): integration against the Compose db (localhost:5432); runs `alembic upgrade head` first
uv run openapi-spec-validator openapi.yaml            # validate the OpenAPI 3.1 contract (in the test command via tests/unit/test_openapi_contract.py)
uv run alembic upgrade head                           # apply migrations to DATABASE_URL (the app entrypoint does this too)
uv run alembic check                                  # fails if the models and the migrations differ
uv run alembic revision --autogenerate -m "<what>"    # draft a new, additive-only revision; review it before committing
gh workflow run deploy-dev.yml --ref main             # publish sha-<SHA> + dev to GHCR and deploy it to ciw-dev (also runs on every push to main)
python scripts/smoke_check.py https://ciw-dev.fly.dev sha-<SHA>   # the deploy's health smoke check, by hand
npm --prefix web run dev                              # Vite dev server :5173, proxies /api to the API on :8000
npm --prefix web run gen:api                          # regenerate web/src/api/schema.d.ts from openapi.yaml (commit the result)
npm --prefix web run check:api                        # one layer on the host (needs Node): fails when schema.d.ts differs from openapi.yaml
npm --prefix web test                                 # one layer on the host (needs Node): frontend tests (Vitest + Testing Library, fetch stubbed)
npm --prefix web run build                            # typecheck + production bundle in web/dist (in CI through the image build)
docker compose exec -T app python -m app.oncall tools <tool> [args]   # run one of the six agent tools by hand: same guards and audit rows; JSON on stdout; exit 0 DONE, 1 REFUSED, 2 usage, 3 NOT_FOUND, 4 error (_docs/architecture.md -> On-call worker loop)
```

## Rules

Short, because the spec is long. Each rule here is one that is easy to break
while looking right.

- **No issue, no work.** Every change belongs to an open GitHub issue with
  acceptance criteria. Reference it as `Refs #N` in commits **and in PR
  bodies**. Never write a closing keyword (`close`, `closes`, `closed`,
  `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`) next to an
  issue number in a commit, a PR title or a PR body, not even negated:
  GitHub closes the issue at merge. The orchestrator closes a backlog issue
  after QA PASS **and** PM approval, and a docs follow-up by hand once the
  docs-only PR that settles it merges; the PM closes a QA follow-up it folds
  or rules not planned, right after its ruling comment (`_docs/process.md`
  step 10).
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
