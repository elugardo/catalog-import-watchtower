# Operations

Everything needed to run, observe, deploy, roll back and demonstrate the
system. Sections marked *(issue NN)* are filled in by that issue; the
requirements they must meet are already here.

## Configuration

All configuration is environment variables, documented in `.env.example`
with safe placeholders. The app runs with none of the optional ones set.

| Variable | Process | Required | Purpose |
|---|---|---|---|
| `DATABASE_URL` | app, oncall-agent | yes | `postgresql+psycopg://…`; defaults to the Compose `db` seen from the host (`…@localhost:5432/ciw`) so `uv run` and the tests work with no `.env`; inside Compose the containers always get the `db` hostname |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | app, oncall-agent | no (default `2`) | psycopg connect timeout; `/api/health` gives up on the database probe after this value + 1 s (name resolution of a stopped `db` is not covered by the connect timeout, so the probe runs under its own deadline) |
| `AGENT_ENABLED` | app, oncall-agent | no (default `false`) | worker claims alerts; app reports it on `/api/health` |
| `LLM_PROVIDER`, `LLM_MODEL` | oncall-agent | when enabled | provider id and model name |
| provider key (the chosen provider's variable) | oncall-agent | when enabled | never anywhere else |
| `AGENT_POLL_SECONDS`, `AGENT_CLAIM_TIMEOUT_SECONDS`, `AGENT_MAX_TOOL_CALLS`, `AGENT_TIMEOUT_SECONDS` | oncall-agent | no | 10 / 300 / 8 / 120 |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_SDK_DISABLED` | app, oncall-agent | no | telemetry; disabled in tests and (by default) when deployed |
| `APP_PORT` | compose | no | host port for the app (default 8000) |
| `DB_PORT` | compose | no | host port for the database (default 5432); the containers always use `db:5432` |
| `APP_VERSION` | image **build argument** (`ARG APP_VERSION=dev` in the Dockerfile, passed by `compose.yaml` → `build.args`); also read as an env var by `app.settings` | no (default `dev`) | becomes `version` on `/api/health`; `APP_VERSION=abc123 docker compose build` bakes `abc123` into the image; CI sets it to the commit SHA (issue 10) |
| `STATIC_DIR` | app | no (default `app/static`) | folder of the built SPA that `/` serves; only needed when running uvicorn on the host against a bundle elsewhere |

## Local stack *(issue 09 adds dashboards and the alert rule)*

```
docker compose up --build             # app :8000 (SPA + API), db :5432, Grafana :3000, idle worker
docker compose up --build -d --wait   # detached; returns once app is healthy, i.e. /api/health says db: ok
APP_PORT=8081 docker compose up       # app on host port 8081 instead of 8000
DB_PORT=5433 docker compose up        # db on host port 5433 when a local PostgreSQL owns 5432
docker compose down                   # stop; the database volume survives
docker compose down -v                # stop and drop the data volume
```

The stack needs no `.env`: every `${VAR}` in `compose.yaml` has a default.
`app` waits for the `db` health check (`pg_isready`), runs `alembic upgrade
head` from its entrypoint and only then starts uvicorn, so a cold start shows
no connection-refused traceback and no restart. Its own health check calls
`/api/health` and is healthy only when `db` is `"ok"`. While `db` is stopped
`/api/health` still answers 200 with `db: "error"`, `status: "degraded"`
after the probe deadline, `DATABASE_CONNECT_TIMEOUT_SECONDS` + 1 s (3 s by
default); it recovers by itself when `db` is back.

| Service | URL | Notes |
|---|---|---|
| app | http://localhost:8000 and http://localhost:8000/api/health | SPA and API, same origin; any non-`/api` path serves the SPA (history fallback); unknown `/api/...` is a 404 in the error shape |
| db | `localhost:5432` (`DB_PORT`), user / password / database `ciw` / `ciw` / `ciw` | PostgreSQL 16; named volume `pgdata` |
| Grafana | http://localhost:3000 (health: `/api/health`) | `grafana/otel-lgtm`; anonymous admin, no login form; dashboard and alert rule arrive with issue 09 |
| oncall-agent | `docker compose logs -f oncall-agent` | no port; logs one line and stays idle unless `AGENT_ENABLED=true` (then it logs that the loop is not implemented yet, issue 08) |

Development without rebuilding the image: `docker compose up db` for the
database, `uv run uvicorn app.main:app --reload` for the API on :8000 (`/`
answers 404 `NOT_FOUND` until a bundle exists under `app/static/`), and
`npm run dev` in `web/` for the SPA on :5173 with `/api` proxied to :8000.
`npm run build` in `web/` writes `web/dist/`, which the Dockerfile copies to
`app/static/`.

## Telemetry *(issue 09)*

Requirements (spec §10), to be met and then documented here with the real
names and queries:

- **Traces:** one span per request; a `catalog.import.attempt` span per
  attempt with attributes `import_id`, `attempt_number`, `outcome`,
  `error_code`; child spans for validation and the upsert transaction; the
  agent run as its own trace with `alert_id` and tool-call spans.
- **Logs:** structured (JSON), every record carrying `trace_id`, `span_id`,
  and where relevant `import_id`, `attempt_number`, `alert_id`. The attempt's
  `trace_id` is also stored in `import_attempts.trace_id`, so the detail page
  can link to the trace.

  **Errors are logged by exception type, already before CIW-09.1.** A failed
  attempt logs its `import_id`, attempt number, code and the exception's
  class name. An exception that escapes a request is logged once, at ERROR,
  as `unhandled <ExceptionClass> in <METHOD> <route template>` (plus
  `import_id=<n>` on `/api/imports/{id}`), and the client gets the stable
  500. No error line carries a traceback, an exception message (a Postgres
  message or its `DETAIL` can quote row values) or SQL parameters; the
  engine in `app/db.py`, shared by `app` and `oncall-agent`, is built with
  `hide_parameters=True`, which is not configurable. uvicorn's
  `Exception in ASGI application` traceback therefore never appears (if the
  response had already started, uvicorn adds its own one-line
  `ASGI callable returned without completing response`, also type-free).
  Uvicorn access lines (method, path, status) stay.
- **Metrics:** `catalog_import_attempts_total{outcome,error_category}`,
  `catalog_import_duration_seconds` (histogram),
  `catalog_products_upserted_total`, `catalog_import_alerts_open` (gauge),
  plus the HTTP server duration histogram. Labels are low-cardinality only:
  no ids, no names.
- **Never exported:** CSV content, vendor or product names, SKUs, tokens,
  credentials, request bodies.
- **Pipeline:** both processes → OTLP → the `grafana/otel-lgtm` container
  (Collector, Prometheus, Loki, Tempo, Grafana), provisioned from
  `observability/`. Deployed environments export nothing unless ADR-0002
  adds a hosted backend; the rubric is satisfied by the local stack.
- **Dashboard:** imports by outcome, attempt duration, open alerts, agent
  runs by outcome, recent failed-attempt trace ids.
- **Reviewer path:** from a failed import's detail page, copy the trace id →
  Grafana Explore → Tempo trace → its logs in Loki → the metric panel that
  moved. Screenshot of each stored under `_docs/evidence/`.

Query cheat-sheet (fill in): Loki by `import_id`; Tempo by
`catalog.import.id`; PromQL for each metric.

## Alerting *(issue 05, 09)*

Two layers, both required:

1. **The durable alert** is the `alerts` row the app creates when an import
   ends `FAILED`. It is the user-impact signal, it is shown in the UI, and
   the worker's poll is the only thing that wakes on it. This exists without
   any observability stack.

   It is written in the same short transaction that sets the import
   `FAILED` (validation, injected or real storage failure, unexpected
   error, and the startup sweep), so a `FAILED` import never exists
   without one. One row per import (`alerts.import_id` is unique). A new
   alert is `OPEN`, `claimed_at` null, `created_at` = `updated_at`.

   **Update rule.** If an import that already has an alert fails again
   (a failed attempt 2, or the sweep picking up a crashed attempt 2), that
   same row is updated: `reason` is replaced and `updated_at` advances;
   `status`, `claimed_at` and `created_at` are kept, because the worker
   owns every status change after `OPEN`. A success never touches the
   alert; resolving it is the worker's `resolve_alert`. No endpoint
   creates, acknowledges or resolves an alert. Imports that failed before
   this existed are not backfilled.

   **Reasons.** The `reason` is exactly one of these fixed, content-free
   strings (`<n>` is the attempt number, `<k>` the stored
   `validation_error_count`), at most 200 characters, never quoting a CSV
   cell, a name, a filename, an exception message or the raised exception's type (the fixed word `OperationalError` names the class matched):

   | Failure | `reason` |
   |---|---|
   | validation | `VALIDATION_ERROR on attempt <n>: 1 validation error` (k = 1) or `VALIDATION_ERROR on attempt <n>: <k> validation errors` |
   | injected fault | `TRANSIENT_STORAGE_TIMEOUT on attempt <n> (synthetic demo fault)` |
   | real `OperationalError` | `TRANSIENT_STORAGE_TIMEOUT on attempt <n> (database OperationalError)` |
   | any other exception | `INTERNAL_ERROR on attempt <n> (unexpected error)` |
   | startup sweep | `INTERNAL_ERROR (found PROCESSING at startup)` |

   **The failure injector is synthetic.** The Upload page's checkbox
   *Demo: fail first attempt with transient storage timeout* stores
   `inject_transient_failure` on the import; attempt 1 of that import, and
   only of that import, then fails with `TRANSIENT_STORAGE_TIMEOUT` after
   validation has passed and before any product is written. It is not a
   real storage outage and there is no environment variable for it. Each
   alert write logs one line with `alert_id`, `import_id`, the code and the
   attempt number only.
2. **The visible alert** is a Grafana alert rule on
   `catalog_import_alerts_open > 0`, provisioned from
   `observability/grafana/provisioning/alerting/`, with a dashboard link in
   its annotations. It is what a reviewer watches fire. It has no contact
   point and no webhook; it wakes nothing.

## Secrets

The repository is public. The rule is that no secret is ever in it, in a
workflow file, in an image, or in a log. Full inventory in ADR-0002.

| Secret | Where it lives | How it gets there |
|---|---|---|
| Fly deploy token (app-scoped), `FLY_API_TOKEN` | GitHub Actions secrets of the `development` and `production` environments, each only its own app's token | `flyctl tokens create deploy -a ciw-dev` / `-a ciw-prod`, piped into `gh secret set FLY_API_TOKEN --env <environment>` by Marcos (*Deployment* → *Provisioning*) |
| `DATABASE_URL` per environment | Fly secrets of that app | `flyctl secrets import -a ciw-dev` from Marcos's machine, read from stdin (*Deployment* → *Provisioning*) |
| LLM provider key | local `.env` only | typed by Marcos; never set on Fly or GitHub by default |

Controls: `.env*` gitignored, `.env.example` committed with placeholders;
GitHub secret scanning and push protection (on for public repos); a
`gitleaks` step in PR CI; workflows never print secrets; fork PRs receive
no secrets; CI runs the worker against a fake LLM. If a key is ever pushed
by mistake: rotate it first, then remove it from history.

## Deployment *(issue 10, ADR-0002)*

Fly.io apps `ciw-dev` and `ciw-prod` (prod: #15), each defining the `app`
and `worker` process groups from the same public image
`ghcr.io/elugardo/catalog-import-watchtower:sha-<full commit SHA>`, one Neon
PostgreSQL project per environment, `release_command = "alembic upgrade
head"`, telemetry exporter and agent disabled when deployed. Workflows in
this repository: `.github/workflows/ci.yml`, `deploy-dev.yml`,
`promote-prod.yml` (ADR-0001). The deploy tokens are app-scoped, so these
workflows cannot reach any other Fly app (ADR-0002, "Blast radius").

Requirements from spec §11:

- PR → CI: backend unit + integration tests, frontend tests + build, the
  image build, `openapi.yaml` vs. generated schema check.
- Push to `main` → build the one image tagged `sha-<commit>` (and moving
  `dev`), push to GHCR, deploy to **development**, smoke-check
  `/api/health` for `db: ok`. Migrations run from Fly's `release_command`
  on deploy; the entrypoint also runs them, so the Compose stack migrates on
  start and on Fly that second run is a no-op.
- `workflow_dispatch` "Promote to production" with the image tag as input,
  gated by the GitHub `production` environment's required approval: runs
  `flyctl deploy -a ciw-prod --image <tag>` (no rebuild), separate database.
- Environments have their own URLs and health checks; both are in the README.
- The only GitHub secret is the app-scoped Fly deploy token per environment.

### PR CI (`.github/workflows/ci.yml`)

Four jobs, none of which reads a secret (fork PRs get none from GitHub):

| Job (status check name to require on `main`) | What it does |
|---|---|
| `Secret scan (gitleaks)` | gitleaks 8.21.2 over the whole history (`fetch-depth: 0`), findings redacted. No `.gitleaks.toml`: the default rules pass on `main` with no allowlist. |
| `Tests (the one test command)` | warms the test image from the GitHub Actions layer cache (scope `test`), then runs the one test command unchanged on the same builder |
| `Image build (runtime image, built once per run)` | builds the runtime image once (cache scope `runtime`) with `APP_VERSION=sha-<commit>`, asserts the version and that a planted `.env` is not in `/app`, and hands the image to the next job as an artifact |
| `Scenario 6 (docker compose up --wait, then /api/health)` | loads that image and runs `docker compose up --no-build -d --wait` with the real `compose.yaml`; `/api/health` must be 200, `db: ok`, `version` = `sha-<commit>` |

Every `run:` step uses `shell: bash` (`bash -eo pipefail`), so a pipe fails
when any command in it fails. Branch protection on `main` (Marcos, in the
repository settings): require the four check names above.

### Development deploy (`.github/workflows/deploy-dev.yml`)

On push to `main`, and on `workflow_dispatch`. `GITHUB_TOKEN` permissions
`contents: read`, `packages: write`; concurrency group `deploy-dev` without
cancel, so deploys run one at a time in order and the newest commit ends as
both the `dev` tag and the running release.

1. **publish**: one `docker/build-push-action` build with
   `APP_VERSION=sha-<SHA>`, pushed as `:sha-<SHA>` and `:dev`; the step after
   it compares both tags' digests with `docker buildx imagetools inspect`.
2. **deploy** (GitHub environment `development`, secret `FLY_API_TOKEN`):
   `flyctl deploy --config fly.toml -a ciw-dev --image ghcr.io/elugardo/catalog-import-watchtower:sha-<SHA> --process-groups app --ha=false`.
   Fly pulls the public image; nothing is built on Fly. The release command
   runs `alembic upgrade head` once before any new machine starts; a failing
   migration fails the deploy and the previous release keeps serving.
3. The job then removes any `worker` machine and lists the machines, and
   `scripts/smoke_check.py https://ciw-dev.fly.dev sha-<SHA>` requests
   `/api/health` up to 30 times, 10 s apart (a stopped machine needs a few
   seconds to wake; about 5 to 10 minutes at most), and fails unless one
   answer is 200 with `db: "ok"` and `version: "sha-<SHA>"`.

**`fly.toml` (dev).** `app = "ciw-dev"`, region `ewr`, no `[build]`. The
`app` group serves HTTP on 8000 with a check on `/api/health`,
`auto_stop_machines = "stop"`, `auto_start_machines = true`,
`min_machines_running = 0`: the machine stops when idle and the next request
wakes it (the first request after a stop takes a few seconds). `[env]` holds
`AGENT_ENABLED = "false"` and `OTEL_SDK_DISABLED = "true"`, no secret.

**Zero worker machines on dev.** The `worker` group is defined but runs no
machine: with `AGENT_ENABLED=false` it would only idle, and the UI label
*automated recovery disabled* comes from `/api/health`. The deploy passes
`--process-groups app` and the next step scales `worker` to 0 if a machine
exists. To run a worker on dev anyway: remove the *Keep zero worker
machines* step from `deploy-dev.yml`, then `flyctl scale count worker=1 -a
ciw-dev`. To keep the app machine always on: set `min_machines_running = 1`.

Public URL: <https://ciw-dev.fly.dev> (health: `/api/health`).

### Provisioning (Marcos, once, from his machine)

The workflows only reference what this creates; none of it is in the
repository. Never reuse a token, app or database of another project; never
print a value. `<...>` are placeholders. Tick each step in the PR with the
command used, values redacted.

- [ ] **Fly app.** `flyctl apps create ciw-dev --org <personal-org-slug>`
- [ ] **Neon project.** A *new* project for dev (console or
  `neonctl projects create --name ciw-dev --region-id aws-us-east-1`), with a
  database `ciw`. Use the **direct** (not `-pooler`) connection string.
- [ ] **`DATABASE_URL` Fly secret**, in the SQLAlchemy psycopg form
  `postgresql+psycopg://<role>:<password>@<endpoint-host>/ciw?sslmode=require`
  (a bare `postgresql://` URL does not work: psycopg2 is not installed).
  From Git Bash, without echoing it:
  `read -rs DB_URL && printf 'DATABASE_URL=%s\n' "$DB_URL" | flyctl secrets import -a ciw-dev --stage; unset DB_URL`
- [ ] **GitHub environment.** `gh api -X PUT repos/elugardo/catalog-import-watchtower/environments/development`
  (deployment branches: all, or `main` plus the PR branch for the one
  pre-merge run).
- [ ] **Deploy token**, scoped to `ciw-dev` only, piped straight into the
  environment secret:
  `flyctl tokens create deploy -a ciw-dev --name ciw-dev-github-actions --expiry <e.g. 2160h> | gh secret set FLY_API_TOKEN --env development --repo elugardo/catalog-import-watchtower`
- [ ] **First publish**: run `deploy-dev.yml` (push to `main`, or
  `gh workflow run deploy-dev.yml --ref <branch>` once the file is on
  `main`; GitHub dispatches only workflows that exist on the default
  branch). The deploy job fails until the package is public if it was
  created private.
- [ ] **GHCR package public.** github.com → *Packages* →
  `catalog-import-watchtower` → *Package settings* → *Change visibility* →
  Public. Check: `docker logout ghcr.io; docker pull ghcr.io/elugardo/catalog-import-watchtower:sha-<SHA>`.
  Re-run the failed deploy job if step 6 failed on the pull.
- [ ] **Checks.** `flyctl secrets list -a ciw-dev` shows only `DATABASE_URL`;
  `flyctl machines list -a ciw-dev` shows one `app` machine and no `worker`;
  after some idle minutes it shows `stopped`, and a request to
  <https://ciw-dev.fly.dev/api/health> wakes it.
- [ ] **Branch protection** on `main`: require the four PR check names above.

## Rollback *(issue 10)*

Procedure to document and rehearse once:

1. Find the previous good tag in the deploy workflow history (or
   `flyctl releases -a ciw-prod`).
2. Run "Promote" with that tag, or from a machine with the deploy token:
   `flyctl deploy -a ciw-prod --image ghcr.io/elugardo/catalog-import-watchtower:sha-<previous>`.
3. Migrations: the MVP keeps schema changes backward-compatible (additive,
   defaults), so the previous image runs against the newer schema and no
   down-migration is needed. If a release ever needs a destructive change,
   it ships in two releases (expand, then contract) and the rollback note
   says which one is safe.
4. Verify `/api/health` and one import on the rolled-back environment.

## The real-LLM demonstration *(issue 08, 11)*

CI uses a fake LLM. Exactly one (or more) real run is performed by hand and
recorded, following `.agents/skills/incident-response/SKILL.md` §8, under
`_docs/evidence/<date>-real-llm-recovery/`: provider and model, the import
detail page with two attempts and the agent timeline, the `agent_actions`
rows, the trace, the metric panels before and after. The README links to it.
Without this, the On-Call Agent rubric row is not earned.

## Runbook

| Symptom | Check | Fix |
|---|---|---|
| alert stays `OPEN` forever | `GET /api/health` → `agent_enabled`; if `true`, `docker compose logs oncall-agent` for the idle line (key missing) | set `AGENT_ENABLED=true` and the key in `.env`; restart `oncall-agent` |
| alert stuck `IN_PROGRESS` | worker logs by `alert_id` | the stale-claim timeout (5 min) returns it to `OPEN`; otherwise `docker compose exec -T app python -m app.oncall tools mark_needs_attention <alert_id> "<reason>"` (exit 0 `DONE`; exit 1 `REFUSED` once the alert is back to `OPEN`, since the CLI cannot claim) |
| retry refused (no-op) | `GET /api/imports/{id}` attempts and failure code, or `docker compose exec -T app python -m app.oncall tools get_import_attempts <import_id>` | by design for validation errors and after two attempts (`refused_reason` in the JSON on stdout); operator uploads a corrected file |
| triage by hand | `docker compose exec -T app python -m app.oncall tools <tool> [args]`, one of the six tools (`_docs/architecture.md` -> *On-call worker loop*, step 4); stdout is one JSON object | exit **0** `DONE`, **1** `REFUSED` (guard failed, nothing changed), **2** usage error (nothing touched), **3** `NOT_FOUND`, **4** unexpected error (stderr names the exception type only; check that `db` is up). Every call on an alerted import writes a `TOOL_CALL` row to its timeline |
| import stuck `PROCESSING` | `docker compose logs app`: a 500 on `POST /api/imports` leaves `unhandled <ExceptionClass> in POST /api/imports`, and when the failure write was what failed, the line before it is `import <id> attempt <n> failed: <code> (<ExceptionClass>)`, which names the import (type-only lines, no traceback) | the startup sweep marks it `FAILED` / `INTERNAL_ERROR` on the next start and raises its alert (`INTERNAL_ERROR (found PROCESSING at startup)`; an existing alert keeps its status); `docker compose restart app` |
| no traces in Grafana | otel-lgtm logs; `OTEL_EXPORTER_OTLP_ENDPOINT` | fix endpoint; `docker compose restart app oncall-agent` |
| deploy green but site down | provider health check, migrations job log | roll back to previous tag (above) |
