# Catalog Import Watchtower

A small full-stack app that imports vendor product catalogs from CSV,
validates every row before writing anything, upserts products in one
transaction, and keeps a history of imports and their attempts. A failed
import raises a user-impact alert, and an LLM-powered on-call agent with a
six-tool allowlist retries transient failures once, escalates everything
else, and records what it did.

Final project for the AI Dev Tools Zoomcamp 2026 (the course work lives in [`elugardo/ai-dev-tools-zoomcamp`](https://github.com/elugardo/ai-dev-tools-zoomcamp)).

**Status: spec final, backlog published, ten issues closed through the
agent loop.** The backlog is public as GitHub issues labelled
`final-project`, and ten of them (#1 to #8, #24, #40) have run groom,
implement, QA, PM approval, merge and close, as recorded in
[`_docs/evidence/2026-10-25-agent-workflow/report.md`](_docs/evidence/2026-10-25-agent-workflow/report.md).
This README is rewritten by #16 (CIW-11) into the reviewer walkthrough
(problem, architecture, quick start, tests, deployment, observability, AI
workflow, limitations).

- Development deployment: <https://ciw-dev.fly.dev> (health:
  [`/api/health`](https://ciw-dev.fly.dev/api/health)); deployed by
  `.github/workflows/deploy-dev.yml` on every push to `main`
- Specification: [`_docs/spec.md`](_docs/spec.md)
- How work is organized: [`AGENTS.md`](AGENTS.md) and
  [`_docs/process.md`](_docs/process.md)
- Backlog: [`_docs/backlog.md`](_docs/backlog.md) → GitHub issues labelled
  `final-project`
- Rubric traceability: [`_docs/rubric.md`](_docs/rubric.md)
