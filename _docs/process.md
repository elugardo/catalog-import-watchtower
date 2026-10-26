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
   --delete-branch` once CI is green, and **links the commits and the PR
   on the issue** in its closing comment: the merged PR and its squash
   commit SHA, the green CI run on the PR head, the QA comment, the PM
   approval, and whatever the rubric row in [`rubric.md`](rubric.md) asks
   for (a screenshot, a URL, a trace id). The branch commits already say
   `Refs #<n>` and the PR body links the issue (steps 4 and 5).
10. **Close only after the evidence is recorded.** The orchestrator posts
   that comment first and then runs `gh issue close <n>`. No issue is ever
   closed by a keyword (see *Conventions*). The orchestrator closes every
   backlog issue this way, and a docs follow-up by hand, with a comment
   linking the merged PR, once the docs-only PR that settles it has merged
   (*Docs-only PRs*). The PM closes a QA follow-up that it folds into
   another issue or rules not planned, with
   `gh issue close <n> --reason "not planned"`, right after its ruling
   comment on that follow-up; the ruling comment, which names where the
   work went, is the evidence. Then it moves on
   to the next issue whose dependencies are closed. Marcos is not a merge
   gate: he reviews the record asynchronously and reopens an issue if
   something is wrong (decided 2026-10-24; before that, he merged every PR
   by hand).

## Docs-only PRs

A PM groom or approval comment often decides that `_docs/spec.md`,
`_docs/backlog.md`, another `_docs/` file or a role file must change: the
spec catches up with a decision, a follow-up is folded in, a split is
recorded. That change does not wait for an issue of its own. It runs like
this, as it did from #3 on (PRs #20, #23, #25, #29, #32, #34, #37, #38, #41
and #45):

1. The change goes on a branch named `docs-<topic>` from an up-to-date
   `main`, with commits `Docs: <what changed>` and `Refs #<n>`.
2. The PR body links the PM comment that decided it and says
   `Refs #<n>` for the issue that comment is on.
3. It changes only files under `_docs/`.
4. It merges with `gh pr merge <pr> --squash --delete-branch` on green CI,
   without its own QA or PM approval cycle: the PM comment it carries out
   is the approval.
5. It is merged before any issue's code depends on it, so the spec changes
   before the code (see *When the spec is wrong*).

A docs follow-up issue that such a PR settles is closed by the
orchestrator with a comment linking the merged PR, not by a keyword in the
PR body.

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

- **Branches:** `fp-<issue>-<slug>` for an issue, `docs-<topic>` for a
  docs-only PR. Never commit to `main` directly.
- **Commits:** `Final project: <what changed>` on the first line, `Refs #<n>`
  in the body (`Docs: <what changed>` on a `docs-<topic>` branch). Small and
  frequent.
- **PRs:** one issue per PR, title `[CIW-NN] <issue title>`, body = criteria
  checklist with how each was checked, test output, the green CI run, and
  what the reviewer should look at first. The squash commit on `main` is
  `[CIW-NN] <issue title> (#<pr>)`, the PR title. For a docs-only PR it is
  `Docs: <what> (#<pr>)`; when the PR has a single commit, GitHub takes that
  commit's headline rather than the PR title.
- **No closing keywords.** GitHub closes an issue for `close`, `closes`,
  `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves` or `resolved`
  followed by an issue number anywhere in a commit message, a PR body or a
  PR title, even inside "do not close", and that skips the QA and PM gates.
  Never write those words next to an issue number; write `Refs #<n>`
  (the same rule as [`team/software-engineer.md`](team/software-engineer.md)).
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
recorded. The one exception to "merges only after PASS and APPROVED" is a
docs-only PR (see *Docs-only PRs*): it changes only `_docs/`, carries out a
PM comment, and merges on green CI. The human review is of the record, not
a gate in front of the merge.

Separate roles buy independence, not ceremony: an engineer's green suite proves
the tests pass, not that the criteria are met. A fresh reader checking the
issue rather than the diff catches the gap. It costs more time and tokens than
one engineer in one session; this project spends it because the rubric scores
the evidence of exactly this.

## Deadline mode (from 2026-10-25)

On 2026-10-25 Marcos chose four changes so the backlog fits the submission
deadline of 2026-10-26. Every role and gate stays: groom, implement, code
review, QA, PM approval, merge on green CI, close with evidence.

- **CI is the full run.** After CIW-08.1 a local run of the one test command
  takes about 15 minutes, while CI's `Tests` job takes under 2. Engineers and
  QA run the focused tests for their slice locally; the green CI run of the
  one command on the PR head counts as the full run.
- **Two tracks in parallel.** Track A is #11 → #12 → #13 in the main checkout;
  track B is #14 → #15 in a separate git worktree. #16 runs last. This
  replaces "one issue per session" until submission.
- **Time-boxed roles.** Grooming of an already-detailed issue is short; QA
  checks the acceptance criteria and the edge cases the spec names, without
  open-ended extra hunts; PM approval is a quick check of the record.
- **#44 is parked.** CIW-06.1 earns no rubric points and runs only if time
  remains.
- **Merge on green CI, verdicts after (from 2026-10-26).** Marcos asked that
  merges not wait on him or on the review loop: the orchestrator merges a PR
  as soon as its CI is green after the engineer's hand-off, then runs QA and
  PM approval on the merged code. A FAIL or CHANGES REQUESTED is fixed forward
  in a new PR, and the issue closes only after both verdicts are recorded.
  First applied to #11 (PR #55).

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
