# Rubric row 6 (Testing): the one test command, 2026-10-25

Issue #8 (CIW-06), PR #43. Recorded on the Windows dev machine (Docker
Desktop, Compose v5.0.2, `core.autocrlf=true`) and on GitHub Actions.

## The command

```
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test
```

Needs only Docker with Compose v2 and git. It runs, in order, backend unit
tests, backend integration tests against the Compose `db`, `check:api` and
Vitest, then prints one line per layer (`_docs/testing.md` -> *The one command*).

## Per-layer counts (green run)

```
==== test summary ==========================================
unit         PASSED  372 tests
integration  PASSED  178 tests
check:api    PASSED  1 check
frontend     PASSED  49 tests
==== ALL LAYERS PASSED
```

600 checks in all: 550 pytest tests, 1 generated-types check and 49 Vitest tests.

## Two runs in a row

On a Compose database holding the rubric row 5 demo data (the demo vendor with
`fixtures/valid.csv`, plus an injected failure with its `OPEN` alert),
with `docker compose up -d --wait` already running:

| | run 1 | run 2 |
|---|---|---|
| exit code | 0 | 0 |
| summary | ALL LAYERS PASSED | ALL LAYERS PASSED |

The row counts of the six tables were the same before and after both runs
(`vendors 1, products 3, imports 2, import_attempts 2, alerts 1,
agent_actions 0`). So were the SHA-256 hashes of the demo vendor's
`GET /api/products` body and of `GET /api/imports/{id}` for the demo import.
No `ciw_throwaway_*` database was left behind. Afterwards `docker compose ps`
showed the same `db` and `app` containers with the same created times, and
the `ciw_pgdata` volume was still there. Running `uv run pytest
tests/integration` on the host twice gave the same results.

Also recorded: a clean clone, after `docker compose down -v`, passed on the
first try (about 1.5 minutes). A wrong `DATABASE_URL` for the `test` service
gave exit code 1 with `integration FAILED 178 tests, 0 failed, 177 errors`.

## How to reproduce

Start Docker Desktop, then from the repository root run the command above. For
the data check, upload `fixtures/valid.csv` through the UI or `POST /api/imports`
first, count the rows of the six tables, run the command twice and count again.

## CI

- Green run of the PR's code (commit `f9f68f5`; all three jobs, `tests`,
  `compose-up` and `image`, green):
  https://github.com/elugardo/catalog-import-watchtower/actions/runs/40214956125
- The run of the PR's last commit (the commit that adds this file) is linked
  in PR #43 and in the closing comment of #8.
- Deliberate red runs, one break at a time:
  - unit (plus a scenario 6 health-check break in the same commit): https://github.com/elugardo/catalog-import-watchtower/actions/runs/40214320747
  - integration: https://github.com/elugardo/catalog-import-watchtower/actions/runs/40214556631
  - frontend: https://github.com/elugardo/catalog-import-watchtower/actions/runs/40214691324
  - check:api (hand edit to `schema.d.ts`): https://github.com/elugardo/catalog-import-watchtower/actions/runs/40214826886
