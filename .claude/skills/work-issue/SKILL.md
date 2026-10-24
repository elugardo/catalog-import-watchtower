---
name: work-issue
description: Run the full groom → implement → QA cycle for one GitHub issue of Catalog Import Watchtower as the orchestrator, stopping at the human merge gate. Usage - /work-issue <issue number>
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
6. **On PASS**, stop. Tell Marcos the PR is ready to review and merge, with
   the PR link, the QA comment link, and the CI run link. Do not merge.
7. **After Marcos merges** (he will say so, or you see the PR merged on the
   next run): post the closing comment with the evidence listed in
   `_docs/issue-template.md` → *Evidence*, then `gh issue close <n>`.

Keep your own context small: read reports, not diffs. Every hand-off and
verdict must already be a comment on the issue; if a subagent forgot, ask it
to post it before moving on.
