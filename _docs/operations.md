# Operations

Everything needed to run, observe, deploy, roll back and demonstrate the
system. Sections marked *(issue NN)* are filled in by that issue; the
requirements they must meet are already here.

## Configuration

All configuration is environment variables, documented in `.env.example`
with safe placeholders. The app runs with none of the optional ones set.

| Variable | Process | Required | Purpose |
|---|---|---|---|
| `DATABASE_URL` | app, oncall-agent | yes | `postgresql+psycopg://…` |
| `AGENT_ENABLED` | app, oncall-agent | no (default `false`) | worker claims alerts; app reports it on `/api/health` |
| `LLM_PROVIDER`, `LLM_MODEL` | oncall-agent | when enabled | provider id and model name |
| provider key (the chosen provider's variable) | oncall-agent | when enabled | never anywhere else |
| `AGENT_POLL_SECONDS`, `AGENT_CLAIM_TIMEOUT_SECONDS`, `AGENT_MAX_TOOL_CALLS`, `AGENT_TIMEOUT_SECONDS` | oncall-agent | no | 10 / 300 / 8 / 120 |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_SDK_DISABLED` | app, oncall-agent | no | telemetry; disabled in tests and (by default) when deployed |
| `APP_PORT` | compose | no | host port for the app (default 8000) |

## Local stack *(issue 01, 09)*

```
docker compose up --build          # app :8000 (SPA + API), db :5432, Grafana :3000
docker compose down -v             # also drops the data volume
```

| Service | URL | Notes |
|---|---|---|
| app | http://localhost:8000 and http://localhost:8000/api/health | SPA and API, same origin |
| Grafana | http://localhost:3000 | anonymous admin; provisioned dashboard and alert rule |
| oncall-agent | `docker compose logs -f oncall-agent` | no port; idle unless `AGENT_ENABLED=true` |

Development without rebuilding the image: `uv run uvicorn app.main:app
--reload` plus `npm run dev` in `web/` (Vite proxies `/api`).

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
| Fly deploy token (app-scoped) | GitHub Actions secrets of the `development` and `production` environments | `flyctl tokens create deploy -a ciw-dev` / `-a ciw-prod`, pasted into the repo's environment settings by Marcos |
| `DATABASE_URL` per environment | Fly secrets of that app | `flyctl secrets set -a ciw-dev DATABASE_URL=…` from Marcos's machine |
| LLM provider key | local `.env` only | typed by Marcos; never set on Fly or GitHub by default |

Controls: `.env*` gitignored, `.env.example` committed with placeholders;
GitHub secret scanning and push protection (on for public repos); a
`gitleaks` step in PR CI; workflows never print secrets; fork PRs receive
no secrets; CI runs the worker against a fake LLM. If a key is ever pushed
by mistake: rotate it first, then remove it from history.

## Deployment *(issue 10, ADR-0002)*

Fly.io apps `ciw-dev` and `ciw-prod`, each running the `app` and `worker`
process groups from the same public image
`ghcr.io/elugardo/catalog-import-watchtower:sha-<commit>`, one Neon
PostgreSQL project per environment, `release_command = "alembic upgrade
head"`, telemetry exporter and agent disabled when deployed. Workflows in
this repository: `.github/workflows/ci.yml`, `deploy-dev.yml`,
`promote-prod.yml` (ADR-0001). The deploy tokens are app-scoped, so these
workflows cannot reach any other Fly app (ADR-0002, "Blast radius").

Requirements from spec §11:

- PR → CI: backend unit + integration tests, frontend tests + build, the
  image build, `openapi.yaml` vs. generated schema check.
- Push to `main` → build the one image tagged `sha-<commit>` (and moving
  `dev`), push to GHCR, deploy to **development** (migrations run from the
  entrypoint), smoke-check `/api/health` for `db: ok`.
- `workflow_dispatch` "Promote to production" with the image tag as input,
  gated by the GitHub `production` environment's required approval: runs
  `flyctl deploy -a ciw-prod --image <tag>` (no rebuild), separate database.
- Environments have their own URLs and health checks; both are in the README.
- The only GitHub secret is the app-scoped Fly deploy token per environment.

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
| alert stays `OPEN` forever | `GET /api/health` → `agent_enabled` | set `AGENT_ENABLED=true` and the key; restart `oncall-agent` |
| alert stuck `IN_PROGRESS` | worker logs by `alert_id` | the stale-claim timeout (5 min) returns it to `OPEN`; otherwise `docker compose exec app python -m app.oncall tools mark_needs_attention <alert_id> "<reason>"` |
| retry refused (no-op) | `GET /api/imports/{id}` attempts and failure code | by design for validation errors and after two attempts; operator uploads a corrected file |
| import stuck `PROCESSING` | app logs around the crash | the startup sweep marks it `FAILED` / `INTERNAL_ERROR` on the next start; `docker compose restart app` |
| no traces in Grafana | otel-lgtm logs; `OTEL_EXPORTER_OTLP_ENDPOINT` | fix endpoint; `docker compose restart app oncall-agent` |
| deploy green but site down | provider health check, migrations job log | roll back to previous tag (above) |
