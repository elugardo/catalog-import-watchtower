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
| 03.2 | Implement transactional import and the read API | §4 F1, F2; §7; §9 scenarios 1–3 | 03.1 | P0 | [#4](https://github.com/elugardo/catalog-import-watchtower/issues/4) | `fp-4-csv-import` |
| 04.1 | Build the SPA shell, API client, Upload and Imports pages | §4 F1, F3 (history); §5 | 03.2 | P0 | [#5](https://github.com/elugardo/catalog-import-watchtower/issues/5) | `fp-5-ui-upload-history` |
| 04.2 | Build Dashboard, Import detail and Products pages | §4 F3; §5 | 04.1 | P0 | [#6](https://github.com/elugardo/catalog-import-watchtower/issues/6) | `fp-6-ui-detail-products` |
| 05 | Add failed-import alerts and failure injection | §4 F4, F5 (alert part) | 03.2, 04.2 | P0 | [#7](https://github.com/elugardo/catalog-import-watchtower/issues/7) | `fp-7-alerts-injection` |
| 06 | Add the single test command, scenario coverage and frontend tests | §9 | 03.2, 04.2, 05 | P0 | [#8](https://github.com/elugardo/catalog-import-watchtower/issues/8) | `fp-8-tests` |
| 07 | Create agent team docs + issue workflow evidence | §12 | — (the docs exist; closes after the first full cycle) | P0 | [#9](https://github.com/elugardo/catalog-import-watchtower/issues/9) | `fp-9-team-docs` |
| 08.1 | Add the six guarded agent tools, audit rows and maintenance CLI | §4 F5 (tools); §7 (retry idempotency); §9 scenario 5 | 05, 06 | P1 | [#10](https://github.com/elugardo/catalog-import-watchtower/issues/10) | `fp-10-agent-tools` |
| 08.2 | Add the LLM on-call worker loop and the real-LLM recovery evidence | §4 F5 (agent); §9 scenarios 4–5 | 08.1 | P1 | [#11](https://github.com/elugardo/catalog-import-watchtower/issues/11) | `fp-11-oncall-agent` |
| 09.1 | Instrument the import and agent flows with OpenTelemetry | §10 (instrumentation) | 05, 08.2 | P1 | [#12](https://github.com/elugardo/catalog-import-watchtower/issues/12) | `fp-12-otel-instrumentation` |
| 09.2 | Provision the Grafana dashboard, alert rule and observability walkthrough | §10 (UI, visible alert) | 09.1 | P1 | [#13](https://github.com/elugardo/catalog-import-watchtower/issues/13) | `fp-13-observability-ui` |
| 10.1 | Harden PR CI, publish the image to GHCR and deploy automatically to development | §11, ADR-0002 (PR CI, dev CD) | 01, 06 | P1 | [#14](https://github.com/elugardo/catalog-import-watchtower/issues/14) | `fp-14-ci-dev-deploy` |
| 10.2 | Add manual production promotion and the rehearsed rollback | §11, ADR-0002 (prod, rollback) | 10.1 | P1 | [#15](https://github.com/elugardo/catalog-import-watchtower/issues/15) | `fp-15-prod-promotion` |
| 11 | Prepare README, demo, and rubric evidence | §14 | all | P0 | [#16](https://github.com/elugardo/catalog-import-watchtower/issues/16) | `fp-16-readme-demo` |

## Order

01 → 02 → 03.1 → 03.2 → 04.1 → 04.2 → 05 → 06, then 08.1 → 08.2, then
09.1 → 09.2, then 10.1 → 10.2, then 11. 07 is open from the start and closes
as soon as the first groom → implement → QA → merge cycle has run (expected
right after #1), since its evidence *is* that cycle.

Two deliberate changes from the spec §13 row order, both recorded in the
issues: PR CI (`ci.yml`) was pulled forward into 01, as this file suggested,
so every later PR carries a green run as evidence; and 05 depends on 04.2 as
well as 03.2, because the UI issues build the alert panels and the demo
checkbox against the contract (empty states until 05) and 05 then verifies
the alert end to end and produces the rubric row 11 screenshot. In practice
the lowest-number-first rule gives the same sequence either way.

## Splitting

Split at publication, each into two linked parts with a clean seam and the
second part unverifiable without the first:

- **03** → 03.1 (pure validation grammar, about forty named edge cases, no
  database) and 03.2 (the transaction, the no-parse upload checks, the read
  API).
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
