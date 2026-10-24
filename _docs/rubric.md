# Rubric traceability

The course rubric (12 criteria, 24 points, 10 to pass; source:
`DataTalksClub/ai-dev-tools-zoomcamp/project`, fetched 2026-10-24) mapped to
what in this project earns each point and where the evidence must live.
Target: 24. Every row is checked before submission; the README links the
evidence.

| # | Criterion | Max | What earns the top score | Evidence location | Issue |
|---|---|---|---|---|---|
| 1 | Problem description | 2 | README explains the problem, what the app does, and the expected behaviour, for a reviewer who has not read the spec | `README.md` | 11 |
| 2 | Product specification | 2 | `_docs/spec.md` **plus** public issues with acceptance criteria **plus** visible evidence agents used them (groom / hand-off / QA comments, PR links) | GitHub issues labelled `final-project`; `_docs/backlog.md` | 07 |
| 3 | Agent team specification | 2 | roles defined **and** the process for how they work together | `_docs/team/*.md`, `_docs/process.md`, `.claude/agents/` | 07 |
| 4 | Context management | 2 | `AGENTS.md` describes the project **and** points to modular docs | `AGENTS.md` → `_docs/` | 07 |
| 5 | Application | 2 | frontend + backend + persistent storage, connected end to end, one command locally | `compose.yaml`; README quick start; screenshot of a persisted import after restart | 01, 03, 04 |
| 6 | Testing | 2 | unit **and** integration tests, one command, passing | `AGENTS.md` test command; CI run link | 06 |
| 7 | Containerization | 2 | whole system including the DB starts with one Compose command | `compose.yaml`; Dockerfiles | 01 |
| 8 | Deployment | 2 | reachable public URL (dev and prod) or a clear demo | README URLs; ADR-0002; health-check screenshots | 10 |
| 9 | CI/CD | 3 | CI on every PR **and** automatic CD to dev **and** manual promotion to prod, plus the rollback path | `.github/workflows/*`; links to one PR run, one dev deploy, one promotion run; rollback section in `operations.md` | 10 |
| 10 | Observability | 2 | metrics + traces + structured logs sharing a trace id for the import journey, no customer data in telemetry, viewable in a UI | `observability/`; `_docs/evidence/` screenshots (trace, logs, dashboard); query examples in `operations.md` | 09 |
| 11 | Alerting on user impact | 1 | at least one alert on actual user impact (a `FAILED` import), not host metrics | `alerts` rows in the UI; provisioned Grafana rule; screenshot of it firing | 05, 09 |
| 12 | On-call agent | 2 | an agent wakes on the alert and fixes the issue | `app/oncall/`; `_docs/evidence/<date>-real-llm-recovery/`; import detail with two attempts and the timeline | 08 |

## Submission checklist (course logistics)

- Repository public, README in English, commit SHA recorded in the form.
- Three peer reviews completed in the review week; without them the project
  does not pass.
- Deadlines are on the course platform
  (`courses.datatalks.club/ai-dev-tools-2026/project/project1`); two
  attempts, the second with the same project only if the first did not pass.
- No secrets in the repo; `.env.example` documents how a reviewer gets any key.
- Verify every link and the commit SHA before the form closes; nothing can be
  changed afterwards.

## Where points are most easily lost

- A spec file without public issues, or issues without acceptance criteria,
  caps criterion 2 at 1.
- Tests that need manual setup, or only one kind, cap criterion 6 at 1.
- A single deployed environment caps criterion 9 at 2; do not claim a prod
  promotion that does not exist.
- Telemetry that cannot be followed by one trace id across signals caps
  criterion 10 at 1.
- A hard-coded retry presented as "the agent" scores 0 on criterion 12. The
  real-LLM evidence folder is what proves it.
