# Catalog Import Watchtower

A small full-stack app that imports vendor product catalogs from CSV,
validates every row before writing anything, upserts products in one
transaction, and keeps a history of imports and their attempts. A failed
import raises a user-impact alert, and an LLM-powered on-call agent with a
six-tool allowlist retries transient failures once, escalates everything
else, and records what it did.

Final project for the AI Dev Tools Zoomcamp 2026.

**Status: set-up phase.** The agent team and the process are in place and
the specification is being finalized; the backlog is published and
application code starts with issue CIW-01 only once the spec is final. This README is
rewritten by issue CIW-11 into the reviewer walkthrough (problem,
architecture, quick start, tests, deployment, observability, AI workflow,
limitations).

- Specification: [`_docs/spec.md`](_docs/spec.md)
- How work is organized: [`AGENTS.md`](AGENTS.md) and
  [`_docs/process.md`](_docs/process.md)
- Backlog: [`_docs/backlog.md`](_docs/backlog.md) → GitHub issues labelled
  `final-project`
- Rubric traceability: [`_docs/rubric.md`](_docs/rubric.md)
