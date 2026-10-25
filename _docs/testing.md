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

Issue 06 defines it and writes it into `AGENTS.md` → *Commands*. Requirements:
runs every layer above, exits non-zero on any failure, works on a clean
checkout with Docker available, and is the same command CI runs. The likely
shape is a `compose.test.yaml` profile or a `scripts/test` wrapper; the
engineer chooses, documents, and makes CI call exactly that.

## What to test (and what each spec scenario maps to)

| Spec §9 scenario | Test |
|---|---|
| 1 happy path | integration: `valid.csv` → 201, `COMPLETED`, 3 products, 1 attempt; re-read confirms persistence |
| 2 upsert | integration: `update.csv` after `valid.csv` → same product count, new price/quantity on `CHAIR-001` |
| 3 atomic validation | integration: `invalid.csv` → `FAILED`, error names row and column, products unchanged (compare full snapshot, not just count) |
| 4 recovery | integration with fake LLM: injected failure → alert → worker → `COMPLETED`, 2 attempts, alert `RESOLVED`, timeline rows, products written exactly once |
| 5 guardrails | unit + integration: validation error → no retry; two concurrent retry calls → one attempt; third attempt refused as a no-op that returns the current state (no exception, no new attempt row); `resolve_alert` on a failed import refused |
| 6 reproducibility | CI job: `docker compose up --build -d --wait` then `GET /api/health` is 200; the one test command passes |

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
