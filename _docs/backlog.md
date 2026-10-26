# Backlog

> **Gate open: `_docs/spec.md` v1.1 was declared final by Marcos on
> 2026-10-24.** The PM published this table as GitHub issues on 2026-10-24
> (one pass, in the order below); `/work-issue` may start, lowest number
> first whose dependencies are closed.

Spec §13, as it exists in the public tracker. The **PM** created one public
GitHub issue per row with [`issue-template.md`](issue-template.md) and
recorded the number here; from now on the issues are the backlog and this
file is only the map from spec id to issue number and the dependency order.

| CIW | Title | Spec | Depends on | Pri | Issue # | Branch |
|---|---|---|---|---|---|---|
| 01 | Scaffold app + Docker Compose + passing smoke test (includes the first PR `ci.yml`) | §8 | — | P0 | [#1](https://github.com/elugardo/catalog-import-watchtower/issues/1) | `fp-1-scaffold` |
| 02 | Write OpenAPI contract and DB models | §6, §7 | 01 | P0 | [#2](https://github.com/elugardo/catalog-import-watchtower/issues/2) | `fp-2-contract-models` |
| 03.1 | Implement pure CSV parsing and validation with fixtures | §4 F1 (row limit), F2 | 02 | P0 | [#3](https://github.com/elugardo/catalog-import-watchtower/issues/3) | `fp-3-csv-validation` |
| 03.2a | Implement the transactional import write path and import detail | §4 F1, F2; §9 scenarios 1–3 (write side) | 03.1 | P0 | [#4](https://github.com/elugardo/catalog-import-watchtower/issues/4) | `fp-4-csv-import` |
| 03.2b | Implement the list endpoints and the contract drift test | §4 F3 (read); §7; §9 scenarios 1–3 (API) | 03.2a | P0 | [#24](https://github.com/elugardo/catalog-import-watchtower/issues/24) | `fp-24-read-api` |
| 04.1 | Build the SPA shell, API client, Upload and Imports pages | §4 F1, F3 (history); §5 | 03.2b | P0 | [#5](https://github.com/elugardo/catalog-import-watchtower/issues/5) | `fp-5-ui-upload-history` |
| 04.2 | Build Dashboard, Import detail and Products pages | §4 F3; §5 | 04.1 | P0 | [#6](https://github.com/elugardo/catalog-import-watchtower/issues/6) | `fp-6-ui-detail-products` |
| 05 | Add failed-import alerts and failure injection | §4 F4, F5 (alert part) | 03.2b, 04.2 | P0 | [#7](https://github.com/elugardo/catalog-import-watchtower/issues/7) | `fp-7-alerts-injection` |
| 05.1 | Keep SQL bound parameters and catalog content out of error logs | §10 (privacy); AGENTS.md -> Rules | 05 | P0 | [#40](https://github.com/elugardo/catalog-import-watchtower/issues/40) | `fp-40-log-privacy` |
| 06 | Add the single test command, scenario coverage and frontend tests | §9 | 03.2b, 04.2, 05, 05.1 | P0 | [#8](https://github.com/elugardo/catalog-import-watchtower/issues/8) | `fp-8-tests` |
| 06.1 | Declare the 500 INTERNAL_ERROR on POST /api/imports and GET /api/imports/{id} | §7 | 06 | P1 | [#44](https://github.com/elugardo/catalog-import-watchtower/issues/44) | `fp-44-contract-500` |
| 07 | Create agent team docs + issue workflow evidence | §12 | — (the docs existed; stayed open while the first ten cycles ran, then ran after 06 (#8); its evidence is those cycles, in [`evidence/2026-10-25-agent-workflow/report.md`](evidence/2026-10-25-agent-workflow/report.md)) | P0 | [#9](https://github.com/elugardo/catalog-import-watchtower/issues/9) | `fp-9-team-docs` |
| 08.1 | Add the six guarded agent tools, audit rows and maintenance CLI | §4 F5 (tools); §7 (retry idempotency); §9 scenario 5 | 05, 06 | P1 | [#10](https://github.com/elugardo/catalog-import-watchtower/issues/10) | `fp-10-agent-tools` |
| 08.2 | Add the LLM on-call worker loop and the real-LLM recovery evidence | §4 F5 (agent); §9 scenarios 4–5 | 08.1 | P1 | [#11](https://github.com/elugardo/catalog-import-watchtower/issues/11) | `fp-11-oncall-agent` |
| 09.1 | Instrument the import and agent flows with OpenTelemetry | §10 (instrumentation) | 05, 08.2 | P1 | [#12](https://github.com/elugardo/catalog-import-watchtower/issues/12) | `fp-12-otel-instrumentation` |
| 09.2 | Provision the Grafana dashboard, alert rule and observability walkthrough | §10 (UI, visible alert) | 09.1 | P1 | [#13](https://github.com/elugardo/catalog-import-watchtower/issues/13) | `fp-13-observability-ui` |
| 10.1 | Harden PR CI, publish the image to GHCR and deploy automatically to development | §11, ADR-0002 (PR CI, dev CD) | 01, 06 | P1 | [#14](https://github.com/elugardo/catalog-import-watchtower/issues/14) | `fp-14-ci-dev-deploy` |
| 10.2 | Add manual production promotion and the rehearsed rollback | §11, ADR-0002 (prod, rollback) | 10.1 | P1 | [#15](https://github.com/elugardo/catalog-import-watchtower/issues/15) | `fp-15-prod-promotion` |
| 11 | Prepare README, demo, and rubric evidence | §14 | all | P0 | [#16](https://github.com/elugardo/catalog-import-watchtower/issues/16) | `fp-16-readme-demo` |

## Order

01 → 02 → 03.1 → 03.2a → 03.2b → 04.1 → 04.2 → 05 → 05.1 → 06, then 08.1 → 08.2, then
09.1 → 09.2, then 10.1 → 10.2, then 06.1, then 11. 07 (#9) was open from the start
and was meant to close right after the first cycle (#1); instead it stayed
open while ten cycles ran (#1, #2, #3, #4, #24, #5, #6, #7, #40, #8) and
ran after #8. It has no dependency, so from the close of #4 on it was the
lowest unblocked number and the rule would have picked it ahead of #24,
#5, #6, #7, #40 and #8; the orchestrator states this was its oversight,
following the spec-order chain above instead (the report's *Deviations* records this). Its
evidence is those ten cycles, in
[`evidence/2026-10-25-agent-workflow/report.md`](evidence/2026-10-25-agent-workflow/report.md). #24 (03.2b) runs right after #4 (03.2a)
even though #5 has a lower number, because #5 depends on #24. #40 (05.1)
runs right after #7 (05) even though #8 has a lower number, because #8
depends on #40. #44 (06.1) has the highest number, so the lowest-number rule
runs it after #15 (10.2) and before #16 (11), which depends on all.

Two deliberate changes from the spec §13 row order, both recorded in the
issues: PR CI (`ci.yml`) was pulled forward into 01, as this file suggested,
so every later PR carries a green run as evidence; and 05 depends on 04.2 as
well as 03.2b, because the UI issues build the alert panels and the demo
checkbox against the contract (empty states until 05) and 05 then verifies
the alert end to end and produces the rubric row 11 screenshot. In practice
the lowest-number-first rule gives the same sequence either way.

## Splitting

Split at publication, each into two linked parts with a clean seam and the
second part unverifiable without the first:

- **03** → 03.1 (pure validation grammar, about forty named edge cases, no
  database) and 03.2 (the transaction, the no-parse upload checks, the read
  API).
- **03.2** → 03.2a (write path, upload checks, import detail, startup sweep)
  and 03.2b (list endpoints, health from `app.schemas`, drift test), split
  when grooming #4.
- **04** → 04.1 (shell, generated API client, Upload, Imports) and 04.2
  (Dashboard, Import detail, Products).
- **08** → 08.1 (the six guarded tools, audit rows, CLI, retry lock) and
  08.2 (poller, LLM loop, prompt, fake-LLM tests, the recorded real-LLM run).
- **09** → 09.1 (spans, logs, metrics, privacy test) and 09.2 (Grafana
  provisioning, alert rule, query cheat-sheet, screenshots).
- **10** → 10.1 (PR CI hardening, GHCR publish, dev CD) and 10.2 (prod
  promotion, rollback rehearsal).

01, 02, 05, 06, 07 and 11 were kept whole. A part that still does not fit one
session is split again by the PM when grooming (`CIW-NN.x`), never by the
engineer.

Folded or closed outside the table: #18 (pin otel-lgtm) was folded into #13
and closed; #22 was a docs follow-up of #3, closed by PR #23. #27 (spec
wording for the `COMPLETED` transition, a QA follow-up of #4) was closed by
the docs PR; #28 (a crash during attempt 2) was folded into #10 and closed.
#31 (the integration suite colliding with the `Sample Furnishings` demo
vendor, a QA follow-up of #24) was folded into #8 and closed. #36 (open
incidents older than the newest 100 alerts silently missing from the
dashboard, a QA follow-up of #6) was folded into #7 and closed. #40 (SQL
bound parameters reaching the app log on an unhandled 500, a QA follow-up of
#7) was kept as its own issue, CIW-05.1, and runs before #8. #44
(`POST /api/imports` and `GET /api/imports/{id}` returning a 500
`INTERNAL_ERROR` that `openapi.yaml` does not declare, a QA follow-up of #8)
was kept as its own issue, CIW-06.1. #50 (`AGENTS.md` -> *Layout* missing
`agent_tools.py` / `alerts.py`, and nothing failing when the `api.md`
redaction lists drift from the code, a QA follow-up of CIW-08.1) was folded
into #11 and closed. #44 (CIW-06.1) is parked under deadline mode: it runs
only if time remains before submission.
