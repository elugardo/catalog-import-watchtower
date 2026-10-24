# Process

How work on Catalog Import Watchtower is organized. Read this before starting a
task and again before closing one. The course grades the *evidence* that this
process was followed (public issues with acceptance criteria, agent comments,
linked PRs, green CI), not the intention, so the record-keeping steps are not
optional.

## The loop, for one issue

1. **Select one open GitHub issue** labelled `final-project`, the lowest number
   whose dependencies in [`backlog.md`](backlog.md) are closed. One issue per
   session; never two at once.
2. **Read the acceptance criteria.** They follow
   [`issue-template.md`](issue-template.md). An issue without checkable
   criteria is not ready: send it back to the PM.
3. **Implement only that issue** on a branch named `fp-<n>-<slug>`
   (`fp-12-scaffold-compose`). Stay inside its *Constraints*. Anything you
   notice outside it becomes a comment or a new issue, not a drive-by change.
4. **Run the tests** that the issue and [`testing.md`](testing.md) name, and
   the single full test command once it exists. Commit at every green point
   with `Refs #<n>` in the body.
5. **Open a pull request** against `main` whose description lists each
   acceptance criterion with how it was checked, and links the issue. CI must
   be green.
6. **Request an independent QA review.** QA runs in a *fresh* session (a new
   subagent or a new terminal) with only the issue, the PR and the docs. It
   posts one comment on the issue ending in `PASS` or `FAIL`.
7. **On FAIL**, the engineer fixes it on the same branch and goes back to
   step 4. The QA comment is the input; do not argue with it in code.
8. **On PASS, request PM approval.** The PM reads the issue, the QA comment
   and the PR description (not the diff), confirms that every acceptance
   criterion has a QA verdict of *met*, that nothing outside the issue's
   scope was built, that the docs named in *Constraints* were updated and
   that the rubric evidence the issue asked for exists, and posts one comment
   ending in `APPROVED` or `CHANGES REQUESTED` (with the list). On
   `CHANGES REQUESTED` the engineer fixes it and the loop goes back to
   step 4.
9. **On APPROVED, the orchestrator merges** with `gh pr merge <pr> --squash
   --delete-branch` once CI is green, then **closes the issue with the
   evidence** in its final comment: the merged PR and commit SHA, the CI
   run, the QA comment, the PM approval, and whatever the rubric row in
   [`rubric.md`](rubric.md) asks for (a screenshot, a URL, a trace id). Then
   it moves on to the next issue whose dependencies are closed. Marcos is
   not a merge gate: he reviews the record asynchronously and reopens an
   issue if something is wrong (decided 2026-10-24; before that, he merged
   every PR by hand).

## Before the loop: building the backlog

The backlog is spec §13, published as individual public issues. This happens
**only after Marcos declares the spec final**; while `spec.md` is still being
written, no issues are created from it and no implementation starts. When
the spec is final, the **PM** publishes the backlog once, following [`team/product-manager.md`](team/product-manager.md):
one issue per row, written with [`issue-template.md`](issue-template.md),
labelled `final-project`, with the spec id in the title
(`[CIW-03] Implement CSV validation + transactional import`) so it survives
GitHub's own numbering. Record the resulting issue numbers in
[`backlog.md`](backlog.md). Split any issue that will not fit one focused
session.

## Conventions

- **Branches:** `fp-<issue>-<slug>`. Never commit feature work to `main`.
- **Commits:** `Final project: <what changed>` on the first line, `Refs #<n>`
  in the body. Small and frequent. Never `Closes #<n>`: that lets GitHub close
  the issue at merge and skips the QA gate.
- **PRs:** one issue per PR, title `[CIW-NN] <issue title>`, body = criteria
  checklist with how each was checked, test output, and what the reviewer
  should look at first.
- **Issue comments are the audit trail.** PM grooming, engineer hand-off, QA
  verdict and the closing evidence are all comments on the issue, so a
  reviewer can read the whole story from the tracker.
- **Secrets never appear** in issues, PRs, comments, screenshots, or telemetry.

## Roles

Role definitions live in [`team/`](team/). Adopt one only when asked for it by
name. The first three are *development-time* roles; the fourth is the
*runtime* agent inside the product and must not be confused with them.

- **Product Manager** — turns the spec into issues and keeps them honest
  ([`team/product-manager.md`](team/product-manager.md)). Owns scope, the
  acceptance criteria and the spec. Writes no code.
- **Software Engineer** — implements one issue at a time
  ([`team/software-engineer.md`](team/software-engineer.md)). Builds against
  the criteria without changing them, writes tests, updates the docs that the
  change makes stale, opens the PR, does not close the issue.
- **QA Engineer** — verifies finished work in a fresh context
  ([`team/qa-engineer.md`](team/qa-engineer.md)). Exercises the behaviour,
  hunts the edge cases the spec names, fixes nothing, opens follow-up issues,
  returns PASS or FAIL.
- **On-call agent (runtime)** — the LLM worker shipped with the app
  ([`team/oncall-agent.md`](team/oncall-agent.md)). Receives failed-import
  alerts, uses six allowlisted tools, never writes code.

## The orchestrator

The main Claude Code session is the orchestrator. It launches the PM, the
engineer and QA as subagents (the definitions in `.claude/agents/` load the
role files) and does not groom, implement or test itself. Shortcuts:

- `Groom issue #12` → PM subagent.
- `Implement issue #12` → engineer subagent.
- `Test issue #12` → QA subagent, fresh context.
- `Approve issue #12` → PM subagent, after QA PASS.
- `/work-issue 12` → the whole cycle for one issue, through the merge
  ([`.claude/skills/work-issue/SKILL.md`](../.claude/skills/work-issue/SKILL.md)).

```
  PM groom ──▶ Engineer ──▶ QA ──PASS──▶ PM approve ──APPROVED──▶ merge ──▶ close with evidence
                  ▲          │                 │
                  ├───FAIL───┘                 │
                  └──────CHANGES REQUESTED─────┘
```

Rules: step 2 is never skipped; the engineer never closes or merges; QA never
fixes; the PM never writes code; the orchestrator merges only after PASS
*and* APPROVED *and* green CI, and closes only after the evidence is
recorded. The human review is of the record, not a gate in front of the
merge.

Separate roles buy independence, not ceremony: an engineer's green suite proves
the tests pass, not that the criteria are met. A fresh reader checking the
issue rather than the diff catches the gap. It costs more time and tokens than
one engineer in one session; this project spends it because the rubric scores
the evidence of exactly this.

## Order and dependencies

From spec §13: start with 01; finish 02, 03, 04 and 06 before any visual
polish; do 08 (agent), 09 (observability) and 10 (deployment) early enough to
demonstrate them, since they carry rubric points and are not stretch goals. 11
(README and demo) is last, but its evidence is collected throughout. Exact
dependencies and issue numbers are in [`backlog.md`](backlog.md).

## When the spec is wrong

If an issue turns out to be mis-scoped, contradicts [`spec.md`](spec.md), or
needs something §3 rules out, stop and say so in an issue comment. The PM
decides, edits `spec.md` (and writes an ADR if the decision is hard to
reverse), updates the issue, and only then does the work continue. No one
widens scope quietly.

## Definition of done, for the project

Spec §14 is the checklist, and [`rubric.md`](rubric.md) maps each item to the
rubric row it earns and the evidence it needs. The project is submitted when
every row has its evidence linked from the README.

## Keeping the documents alive

After any session where you were told "don't do it that way", update the
document that should have said so, in the same PR: `AGENTS.md` for a rule,
`testing.md` for a testing habit, `spec.md` for a scope decision, `adr/` for a
hard-to-reverse choice, this file for a process change.
