# Issue template

Every GitHub issue in the backlog is written in these five sections, nothing
else. The PM writes the first four when creating or grooming the issue; the
orchestrator fills *Evidence* when closing it.

Title: `[CIW-NN] <imperative title>` where `NN` is the id from spec §13 (or
`NN.x` for a split). Label: `final-project`.

## Goal

One or two sentences. What the issue achieves in the operator's or reviewer's
terms, not the implementation's. Name the spec section(s) it delivers
(`spec §4 F2`, `§9 scenario 3`).

## Acceptance criteria

A checklist of statements that are true when the issue is done. Each one must
be **checkable**: someone can run a command, send a request, or look at a
screen and answer yes or no with no judgement call. Prefer concrete inputs
and expected outputs over adjectives. Include the negative cases the spec
names (the empty file, the duplicate SKU, the 257th KiB, the third attempt).

Bad: "Validation works and gives good errors."
Good: "`POST /api/imports` with `fixtures/invalid.csv` returns 201 with
`status: FAILED`, `failure_code: VALIDATION_ERROR`, one error naming row 3 and
column `quantity`, and `GET /api/products?vendor_id=…` is unchanged."

## Out of scope

What this issue deliberately does not cover, especially anything a reader
might assume it includes. Anything moved out because it deserves its own
issue links to that issue.

## Constraints

Which folders and files may be touched, which libraries must or must not be
used, which docs must be updated (`AGENTS.md` layout and commands,
`architecture.md`, `api.md`, `operations.md`), and any project rule that is
easy to violate here. Point at `AGENTS.md` rather than restating it.

## Evidence (filled at close)

- PR: link, merged commit SHA
- CI run: link (green)
- QA verdict: link to the PASS comment
- Rubric artefacts, if the row in `_docs/rubric.md` asks for them: screenshot
  path under `_docs/evidence/`, public URL, trace id, dashboard link
