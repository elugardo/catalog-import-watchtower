# Testing

Read before writing or reviewing tests. Every issue ships with tests; an
issue with no test is not finished. The rubric's Testing row needs unit *and*
integration tests that run with one command and pass; the spec (§9) adds
frontend tests and names the scenarios.

## Layers and where they live

| Layer | Lives in | Runner | Touches |
|---|---|---|---|
| Backend unit | `tests/unit/` | pytest | no database, no network; `csv_validation`, price/quantity parsing, header checks, line numbering, duplicate detection, tool-result redaction |
| Backend integration | `tests/integration/` | pytest against a real PostgreSQL | import API + persistence, atomic rollback, upsert, alert creation, retry idempotency and row lock, tool guards, startup sweep |
| Worker | `tests/oncall/` | pytest with a fake LLM client | policy, tool-call loop, limits, stale-claim reset, misbehaving model |
| Frontend | `web/src/**/__tests__/` | Vitest + Testing Library | upload form submit and result rendering; import detail rendering of errors / attempts / recovered label |

Integration tests use the Compose `db` service (or a throwaway database on
the same server, created per run). No SQLite stand-in: the behaviour under
test is Postgres transactions and unique constraints.

## The one command

```
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test
```

Run it from the repository root. It needs **Docker with Compose v2 and git,
nothing else**: no `uv`, Python or Node on the host. The same line works
unchanged in Windows PowerShell, in Git Bash and on the CI runner (the
`tests` job of `.github/workflows/ci.yml` runs exactly this line). On Windows,
start Docker Desktop first.

**What it starts.** The overlay `compose.test.yaml` adds one service, `test`,
to the stack of `compose.yaml` (same project, `ciw`). `run` starts the
Compose `db` if it is not running yet, or uses the running one as it is (a
stack started with `docker compose up -d --wait` is not recreated), builds
the `ciw-test:local` image from `Dockerfile.test` and runs it once, then
removes the container. Nothing else of the stack is started. The `test`
service has a `test` profile, so `docker compose up` never starts it, even
with the overlay.

**What it runs**, in order, through `scripts/run_tests.py`: backend unit
(`pytest tests/unit`), backend integration against the Compose `db`
(`pytest tests --ignore=tests/unit`, so a new folder such as `tests/oncall/`
joins with no change to the command), `npm --prefix web run check:api` and
Vitest (`npm --prefix web test`). Every layer runs even when an earlier one
failed. The run ends with one summary line per layer and a verdict:

```
==== test summary ==========================================
unit         PASSED  372 tests
integration  PASSED  178 tests
check:api    PASSED  1 check
frontend     PASSED  49 tests
==== ALL LAYERS PASSED
```

The exit code is non-zero when any layer failed. A layer that ran zero tests
counts as failed, and so does the integration layer when the database is
unreachable (its tests error, they are never skipped).

**It leaves your data alone.** The integration tests never truncate, delete
or change rows they did not create: the rollback-only `db` session, the `ns`
per-test vendor token (with cleanup of every row that token leads to) and
`throwaway_url` (a separate database, dropped afterwards) for anything
destructive such as the migration round trip, or `isolated_db` (the same,
migrated, with the app pointed at it). No test uses a fixed vendor
name that demo, fixture or QA data can hold. The `pgdata` volume is kept, so
the demo upload and anything else in your database survive a run, and the
command passes twice in a row with no cleanup. Code under test that touches
rows it did not create runs on its own migrated throwaway database
(`isolated_db`). The startup sweep is such code: it fails *every*
`PROCESSING` import in the database it is pointed at, and it runs whenever
the app's lifespan does, that is whenever a `TestClient` is entered as a
context manager (`with TestClient(create_app()):`). So every test that enters
one against a real database uses `isolated_db`: the sweep tests in
`test_import_sweep.py` and `test_alert_sweep.py`, and
`test_failure_injection.py::test_when_the_failure_write_fails_too_the_sweep_finishes_it`,
and the agent tool tests that run the sweep or reset every stale claim
(`test_agent_retry_races.py`,
`test_agent_third_attempt.py::test_after_the_sweep_failed_attempt_2`,
`test_alert_claims.py::test_reset_stale_claims_returns_only_old_claims_to_open`).
The `client` fixture and `make_client` return a `TestClient` that is not
entered, so they never sweep; the one other test that enters one
(`tests/unit/test_import_errors.py`, startup with the database down) points
at an unreachable database. A new test that needs the lifespan uses
`isolated_db` too.

**Nothing on the host is used or modified.** The image copies the checkout
in (`Dockerfile.test.dockerignore` leaves out `.env`, `.venv/`,
`node_modules/` and build output) and installs its own Python and Node
dependencies, so a Windows `.venv/` or `web/node_modules/` neither breaks nor
changes. Scripts the container runs from the checkout are LF in
`.gitattributes` (`scripts/**`), so a `core.autocrlf=true` checkout works.
The runtime image (`Dockerfile`, `ciw:local`) is unchanged and still has no
`tests/` and no dev dependencies.

**How long.** Measured on the Windows dev machine (Docker Desktop): a cold
run (test image built with no cache, empty volume, base images already
pulled) takes about 2.5 minutes (25 s build, about 2 minutes of tests); the
first pull of the `python`, `node`, `uv` and `postgres` base images adds a few
minutes once. A warm run (image cached, `db` up) takes about 1.5 minutes,
most of it the integration layer (about 1 minute). Since PR #49 (CIW-08.1)
added the concurrency tests, a run on the Windows dev machine takes about 15
minutes, while the CI `Tests` job still takes under 2 minutes; until the local
run is made faster, the green CI run of the one command on a PR's head counts
as the full run (see `process.md` -> *Deadline mode*).

**One layer alone.** Inside the container, name the layers after the service:

```
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python scripts/run_tests.py unit
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python -m pytest tests/integration/test_constraints.py
```

On the host (needs `uv` or Node, with the Compose `db` published on
`localhost:5432` for the integration layer): `uv run pytest tests/unit`,
`uv run pytest tests --ignore=tests/unit`, `npm --prefix web run check:api`,
`npm --prefix web test` (`AGENTS.md` -> *Commands*).

**A wrong database fails.** For example
`docker compose -f compose.yaml -f compose.test.yaml run --rm --build -e DATABASE_URL=postgresql+psycopg://ciw:wrong@db:5432/ciw test`
exits non-zero with the integration layer reported failed.

## What to test (and what each spec scenario maps to)

| Spec §9 scenario | Test |
|---|---|
| 1 happy path | integration: `valid.csv` → 201, `COMPLETED`, 3 products, 1 attempt; re-read confirms persistence |
| 2 upsert | integration: `update.csv` after `valid.csv` → same product count, new price/quantity on `CHAIR-001` |
| 3 atomic validation | integration: `invalid.csv` → `FAILED`, error names row and column, products unchanged (compare full snapshot, not just count) |
| 4 recovery | integration with fake LLM: injected failure → alert → worker → `COMPLETED`, 2 attempts, alert `RESOLVED`, timeline rows, products written exactly once |
| 5 guardrails | unit + integration: validation error → no retry (`test_agent_retry.py::test_refusals_change_nothing[validation_error-…]`); two concurrent retry calls → one attempt (`test_agent_retry.py::test_two_concurrent_retries_make_one_attempt`, and four at once in `test_agent_third_attempt.py::test_concurrent_calls`); third attempt refused as a no-op that returns the current state, no exception, no new attempt row, over every route through the tools and the CLI (`test_agent_third_attempt.py`); `resolve_alert` on a failed import refused (`test_agent_alert_tools.py::test_resolve_alert_is_refused_on_a_failed_import`); redaction of every tool result (`tests/unit/test_agent_tool_results.py`, and the canary test `test_agent_redaction.py::test_no_canary_reaches_a_result_or_an_audit_row`); a live retry against the startup sweep (`test_agent_retry_races.py`, on `isolated_db`) |
| 6 reproducibility | CI job `compose-up`: loads the runtime image the `image` job built from the PR commit (built once per run, GitHub Actions layer cache), `docker compose up --no-build -d --wait` with the real `compose.yaml`, then `GET /api/health` is 200 with `db: ok` and `version` `sha-<commit>`, logs on failure, always `down -v`; CI job `tests`: the one test command passes; deployed: `deploy-dev.yml` smoke-checks `https://ciw-dev.fly.dev/api/health` (`scripts/smoke_check.py`, unit-tested in `tests/unit/test_smoke_check.py`) |

Also always cover: the empty file, header-only file, missing, duplicate and
differently-cased headers, BOM, empty lines in the middle, 256 KiB boundary
(exactly at and one byte over), 500-row boundary (500 passes, 501 is a
validation error), price with three decimals and with a `$`, negative and
decimal quantity, SKU with a space, SKUs differing only in case, vendor name
differing only in case or whitespace, invalid-and-injected file (validation
wins), and redaction of every agent tool result.

## Habits

- **Test behaviour, not implementation.** Assert on responses, rows, and
  rendered text, not on which helper was called.
- **Keep `csv_validation` pure** so most of the rules are unit-tested with no
  database. This is the highest-value test surface in the project.
- **Prove the test can fail.** Before calling a behaviour tested, break the
  line it defends, watch the suite go red *on that test*, restore. A test
  that cannot fail is decoration. Data that cannot discriminate (a tie-break
  test whose inputs sort the same either way) is the usual trap.
- **Mock only the LLM**, at the provider-client boundary, with scripted tool
  calls. Never mock the database or the HTTP layer of our own API in
  integration tests.
- **No real network in tests.** Real-LLM runs are manual demonstrations,
  recorded under `_docs/evidence/`, never part of the suite.
- **Fixtures are data, not code.** `fixtures/valid.csv`, `update.csv`,
  `invalid.csv` are the ones the spec and the demo name; edge-case files live
  next to them with descriptive names. Tests that need a 257 KiB file
  generate it.
- **Frontend tests stay small**: a few per page, one for each outcome the
  page renders (success, validation failure, error response, empty state,
  the Recovered label), through rendered text and roles, with `fetch`
  stubbed and no network.
- **No asserting on exact whitespace** or layout; assert that the important
  text and states are present.
