# Real-LLM recovery (issue #11, rubric row 12)

One run of the real on-call worker against a real LLM, made by hand on the
Windows dev machine on 2026-10-26, following
`.agents/skills/incident-response/SKILL.md` §8 and `_docs/operations.md` ->
*The real-LLM demonstration*. It is the only real-LLM use of issue #11: the
test suite, CI and QA use the fake client of `tests/oncall/fake_llm.py`.

## What was run

| | |
|---|---|
| Provider (from `RUN_STARTED`) | `anthropic` (official `anthropic` Python SDK 2.3.0) |
| Model (from `RUN_STARTED`) | `claude-haiku-5-5` |
| Import id | 1 |
| Alert id | 1 |
| Failure code | `TRANSIENT_STORAGE_TIMEOUT`, from the **synthetic** failure injector (*Demo: fail first attempt with transient storage timeout*, `inject_transient_failure=true`); not a real storage outage |
| Alert created | 2026-10-26 04:31:50.739714 UTC (attempt 1 failed) |
| Alert claimed | 2026-10-26 04:32:00.530948 UTC (the next poll, 10 s interval) |
| Alert resolved | 2026-10-26 04:32:04.281341 UTC (`resolve_alert`; alert `updated_at` 04:32:04.293137) |
| Run | 3 tool calls, 3 780 ms (`RUN_FINISHED`) |
| Decision | `resolve_alert`, stated by the model: "The retry completed the import, so I'm resolving the alert: the import is COMPLETED after one retry." |
| Outcome | import `COMPLETED`, `attempt_count: 2`, *Recovered*; alert `RESOLVED`; 3 products |

The model followed policy row 1 of `_docs/team/oncall-agent.md`:
`get_import_incident(1)` -> `retry_failed_import(1)` (attempt 2 `SUCCEEDED`) ->
`resolve_alert(1)`.

## How

The stack ran as a separate, throwaway Compose project (`-p ciw11demo`, its
own `pgdata` volume, app on port 8011, db on 5442, services `db`, `app`,
`oncall-agent` only), because the developer database of the default `ciw`
project still held 18 `OPEN` / `IN_PROGRESS` alerts left by earlier QA
sessions. An enabled worker there would have sent all of them to the LLM,
which would not have been one run. The image and `compose.yaml` are the
branch's, unchanged.

```
$env:AGENT_ENABLED='true'; $env:APP_PORT='8011'; $env:DB_PORT='5442'
docker compose -p ciw11demo up -d --build --wait db app oncall-agent
curl.exe -F "vendor_name=<vendor>" -F "inject_transient_failure=true" -F "file=@fixtures/valid.csv;type=text/csv" http://localhost:8011/api/imports
```

`.env` holds `LLM_PROVIDER`, `LLM_MODEL`, `ANTHROPIC_API_KEY` and
`AGENT_ENABLED=false`; the shell value `true` overrides it for this start only.
The worker logged `polling every 10.0s (provider anthropic, model
claude-haiku-5-5)`, then `claimed alert 1 (import 1)`, three provider requests
and `run on alert 1 finished: RESOLVED after 3 tool calls (closed by model)`.

Checks made without printing any value:

- `GET /api/health` -> `{"status":"ok","db":"ok","agent_enabled":true,"version":"dev"}`.
- `docker compose -p ciw11demo exec -T app sh -c 'test -z "$ANTHROPIC_API_KEY"'`
  -> exit 0: the `app` container has no key.
- `docker compose -p ciw11demo exec -T oncall-agent sh -c 'test -n "$ANTHROPIC_API_KEY"'`
  -> exit 0: the worker has one.

## Files

- `import-detail-attempts-and-timeline.jpg`: the import detail page with the
  two attempts, the resolved incident and the whole agent timeline
  (`RUN_STARTED`, three `TOOL_CALL`s, `DECISION`, `RUN_FINISHED`).
- `import-detail-top.jpg`: the top of the same page (status, *Recovered*,
  *Demo failure injected*).
- `agent-actions.json`: the `agent_actions` rows, the attempts and the alert,
  exported from `GET /api/imports/1`. The vendor, the filename and the
  validation fields of that response are left out.

On both screenshots the *Vendor* and *Filename* values were replaced in the
page's DOM by `[redacted for evidence]` before the capture (no data was
changed), so the folder holds no vendor name and no filename.

The trace and metric screenshots (§8) are added by #13 and #16 once the
observability stack exists; this run had telemetry disabled
(`OTEL_SDK_DISABLED=true`, the default).

## The test suite and a live worker leave each other alone

With the agent enabled and nothing left to claim (0 `OPEN` / `IN_PROGRESS`
alerts after the recovery), the one test command ran once against the same
stack, so the suite and the live worker shared one PostgreSQL server:

```
$env:AGENT_ENABLED='true'; $env:APP_PORT='8011'; $env:DB_PORT='5442'
docker compose -p ciw11demo -f compose.yaml -f compose.test.yaml run --rm --build test
```

```
==== test summary ==========================================
unit         PASSED  415 tests
integration  PASSED  304 tests
check:api    PASSED  1 check
frontend     PASSED  49 tests
==== ALL LAYERS PASSED
exit 0, elapsed 564 s (07:33:03 -> 07:42:27 local, UTC-4)
```

Row counts of the six tables in the stack's `ciw` database, before and after:
`imports` 1 / 1, `import_attempts` 2 / 2, `vendors` 1 / 1, `products` 3 / 3,
`alerts` 1 / 1, `agent_actions` 6 / 6. `docker compose logs --since <start>
oncall-agent` filtered for `claimed|finished|stale|poll failed` printed
nothing: the worker claimed none of the suite's alerts. The suite writes only
to its own `ciw_suite` database (`_docs/testing.md` -> *It leaves your data
alone*), which the worker never polls; the application code has no test-only
branch.

## Privacy checks

Over the other files of this folder (the report itself names the command), the vendor
used for the upload, the three product names and SKUs of `fixtures/valid.csv`,
and the Anthropic key prefix:

```
grep -rniE '<vendor>|<three product names>|<three SKUs>|<key prefix>' _docs/evidence/2026-10-26-real-llm-recovery --exclude=report.md
exit 1   (no match)
```

The JPEG screenshots show the masked *Vendor* and *Filename* fields and no
product rows. The key prefix is also absent from the squashed diff of PR #55
(`git diff origin/main...HEAD`) and so from `main`'s history after the squash
merge. On the PR branch, commit `f50b8ef` held the prefix inside a docs
instruction only (no key); `44dd161` rewords it, and the squash drops the
commit.

## Afterwards

`docker compose -p ciw11demo down -v` removed the throwaway stack and its
volume, and `AGENT_ENABLED` was removed from the shell
(`Remove-Item Env:AGENT_ENABLED`). The default `ciw` project was left as it
was (only its `db` running, the agent never enabled there).

Rubric row 12 (On-Call Agent): a real LLM with tool calling recovered a
transient failure once, through the six allowlisted tools, with the audit
trail above.
