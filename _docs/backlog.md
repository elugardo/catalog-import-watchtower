# Backlog

> **Gate: the spec is still being written.** Nothing here is published to
> GitHub until Marcos says `_docs/spec.md` is final. Until then this table is
> a preview of the shape, not a to-do list; the PM must not create issues from
> it, and the orchestrator must not start `/work-issue`.

Spec §13, as it will exist in the public tracker. The **PM** creates one
public GitHub issue per row with [`issue-template.md`](issue-template.md) and
records the number here; after that, the issues are the backlog and this file
is only the map from spec id to issue number and the dependency order.

| CIW | Title | Spec | Depends on | Pri | Issue # | Branch |
|---|---|---|---|---|---|---|
| 01 | Scaffold app + Docker Compose + passing smoke test | §8 | — | P0 | | `fp-<n>-scaffold` |
| 02 | Write OpenAPI contract and DB models | §6, §7 | 01 | P0 | | `fp-<n>-contract-models` |
| 03 | Implement CSV validation + transactional import | §4 F1, F2; §9 scenarios 1–3 | 02 | P0 | | `fp-<n>-csv-import` |
| 04 | Build upload, history, detail, and products UI | §4 F3, §5 | 03 | P0 | | `fp-<n>-ui` |
| 05 | Add failed-import alerts and failure injection | §4 F4, F5 (alert part) | 03 | P0 | | `fp-<n>-alerts-injection` |
| 06 | Add unit/integration/frontend tests + fixtures | §9 | 03, 04, 05 | P0 | | `fp-<n>-tests` |
| 07 | Create agent team docs + issue workflow evidence | §12 | — (the docs exist; this issue records the evidence) | P0 | | `fp-<n>-team-docs` |
| 08 | Add constrained LLM on-call worker + audit trail | §4 F5; §9 scenarios 4–5 | 05 | P1 | | `fp-<n>-oncall-agent` |
| 09 | Add OpenTelemetry + observability UI | §10 | 05 | P1 | | `fp-<n>-observability` |
| 10 | Publish deployment + CI/CD + rollback | §11, ADR-0002 | 01, 06 | P1 | | `fp-<n>-deploy-cicd` |
| 11 | Prepare README, demo, and rubric evidence | §14 | all | P0 | | `fp-<n>-readme-demo` |

## Order

01 → 02 → 03 → {04, 05} → 06, then 08 and 09 (independent of each other),
then 10, then 11. 07 can be opened first and closed as soon as the first
groom → implement → QA cycle has run, since its evidence *is* that cycle.

CI for pull requests (the first level of the CI/CD rubric row) is worth
pulling forward into 01 or right after 06: every later PR then carries a green
run as evidence.

## Splitting

Split any issue that will not fit one focused engineer session; name the
parts `CIW-04.1`, `CIW-04.2` and link them. Likely candidates: 04 (upload +
history vs. detail + products), 09 (instrumentation vs. the Grafana stack),
10 (PR CI + dev CD vs. prod promotion + rollback doc).
