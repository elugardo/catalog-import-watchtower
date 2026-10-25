---
name: work-issue
description: Run the full groom → implement → QA → PM approval → merge → close cycle for one GitHub issue of Catalog Import Watchtower as the orchestrator, then continue with the next unblocked issue. Usage - /work-issue <issue number>
---

# Work one issue

You are the orchestrator described in `_docs/process.md`. You delegate; you
do not groom, implement or test yourself. The argument is the issue number.

0. **Check the gate.** If `_docs/backlog.md` still carries the "spec is still
   being written" gate, stop: no issue may be worked yet.
1. **Check readiness.** `gh issue view <n> --comments`. Confirm it is open,
   labelled `final-project`, and that its dependencies in `_docs/backlog.md`
   are closed. If not, stop and say which.
2. **Groom.** If the body is not in the five sections of
   `_docs/issue-template.md`, or has no groom comment, launch the
   `product-manager` agent with "Groom issue #<n>". Never skip this check.
3. **Implement.** Launch the `software-engineer` agent with "Implement issue
   #<n>". Wait for its report: branch, PR, test result.
4. **Verify.** Launch the `qa-engineer` agent, fresh, with "Test issue #<n>,
   PR #<pr>". Wait for PASS or FAIL.
5. **On FAIL**, launch a new `software-engineer` agent with "Fix issue #<n>
   per the QA comment <link>" and go back to step 4. After three FAILs in a
   row, stop and summarize for Marcos instead of looping.
6. **On PASS, get PM approval.** Launch the `product-manager` agent with
   "Approve issue #<n>, PR #<pr>". It posts one comment ending in `APPROVED`
   or `CHANGES REQUESTED`. On `CHANGES REQUESTED`, treat it like a FAIL:
   launch a `software-engineer` agent with "Fix issue #<n> per the PM
   comment <link>" and go back to step 4 (the same three-strikes rule
   applies, counting FAILs and CHANGES REQUESTED together).
7. **On APPROVED, merge.** Confirm the PR's CI is green (`gh pr checks <pr>`),
   then `gh pr merge <pr> --squash --delete-branch`. If CI is red or the
   merge is blocked, stop and tell Marcos why; never bypass a check.
8. **Close with evidence.** Post the closing comment with the evidence listed
   in `_docs/issue-template.md` → *Evidence* (merged PR and commit SHA, CI
   run, QA comment, PM approval, rubric artefacts), then `gh issue close <n>`.
   Pull `main` locally so the next branch starts from the merge. If the
   groom or the approval decided a change under `_docs/`, launch the
   `product-manager` agent to land it as a docs-only PR and merge that on
   green CI before any code depends on it (`_docs/process.md` ->
   *Docs-only PRs*, the one PR that merges without PASS and APPROVED).
9. **Continue.** Tell Marcos in one short paragraph what was merged and the
   links, then pick the lowest-numbered open issue whose dependencies in
   `_docs/backlog.md` are all closed and start again at step 1. Stop only
   when no issue is unblocked, when an issue needs a decision only Marcos
   can make (a spec change, a secret, a provider account), or after three
   strikes on one issue.

Keep your own context small: read reports, not diffs. Every hand-off and
verdict must already be a comment on the issue; if a subagent forgot, ask it
to post it before moving on.
