# Agent workflow: ten issue cycles on GitHub

**Built against `main` at `4b15920`** (PR #45 merged, 2026-10-25), for
issue #9 (CIW-07). This is a dated snapshot. It is not kept current; later
cycles (#10 to #16, #44) carry their own evidence in their closing comments,
and #16 (CIW-11) cites this report from the README.

## What it shows

The project was run by a defined agent team through a documented process,
and the GitHub record proves it. For every backlog issue closed so far, a
PM groomed it, an engineer implemented it and handed it off, a QA agent in a
fresh context verified it, the PM approved it, and the orchestrator merged
the PR on green CI and closed the issue with an evidence comment (on #8
the PR closed it first, *Deviations* 1). From #3 on, spec changes went in
through docs-only PRs before the code depended on them, QA
filed follow-ups instead of changing requirements, and on #8 QA caught a
gap the engineer's green suite had missed. Where the record departs from
the process, *Deviations* says so.

**Rubric rows served** (`_docs/rubric.md`):

- **Row 2, product specification:** *Cycles*, *Follow-ups*, *Docs-only PRs*.
- **Row 3, agent team specification:** *Roles and process*, *Independence*,
  *Context per role*.
- **Row 4, context management:** *Spec §12 files*, *Context per role*.

This report links no CI run of its own: a file cannot link the run of the
commit that adds it. The run on the head of the PR that adds this file is
in that PR's body and in the closing comment of #9.

## How to reproduce it

Everything below was read from the GitHub record and `git`, not written
from memory. Run from the repository root:

```
git log --oneline --format="%h %ad %s" --date=iso-strict main
gh issue view <n> --json number,title,state,closedAt,comments,body    # n = 1 2 3 4 24 5 6 7 40 8, and 18 22 27 28 31 36 44
gh pr list --state all --limit 100 --json number,title,state,mergedAt,mergeCommit,headRefName,headRefOid,body
gh pr view <p> --json files,commits,body                              # p = each PR in the tables
gh pr checks <p>                                                      # the CI run of each docs-only PR
gh run view <run> --json databaseId,headSha,conclusion,event          # each head run in Cycles
gh issue list --label final-project --state open --json number
gh issue view <n> --json body                                         # the five section headings of each open issue
```

Each comment link below is the `url` field of the comment in
`gh issue view <n> --json comments`. Each merge SHA was checked with
`git log -1 <sha>` and each run with `gh run view <run>` (all ten are
`success`, event `pull_request`, on the PR head named in the closing
comment).

## Cycles

The ten closed backlog issues, in the order they ran. *Groom* links the PM
groom comment, preceded by any earlier PM edit comment (an edit made while
approving an earlier issue). Every SHA and run id matches the orchestrator's
closing comment on that issue, linked in the last column.

| Issue | CIW | PM edit(s), then groom | Engineer hand-off | QA verdict(s) | PM approval | PR | Squash merge on `main` | Green CI on PR head | Closing comment |
|---|---|---|---|---|---|---|---|---|---|
| #1 | 01 | [groom](https://github.com/elugardo/catalog-import-watchtower/issues/1#issuecomment-6388051906) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/1#issuecomment-6390233927) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/1#issuecomment-6390752013) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/1#issuecomment-6390851408) | [#17](https://github.com/elugardo/catalog-import-watchtower/pull/17) | [`7ec3dd3`](https://github.com/elugardo/catalog-import-watchtower/commit/7ec3dd3fb03d5c114abbde290cb32909bae62239) | [40137674611](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40137674611) (`9e2605e`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/1#issuecomment-6390872715) |
| #2 | 02 | [edit](https://github.com/elugardo/catalog-import-watchtower/issues/2#issuecomment-6390839098), [groom](https://github.com/elugardo/catalog-import-watchtower/issues/2#issuecomment-6392919251) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/2#issuecomment-6393288106) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/2#issuecomment-6393374950) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/2#issuecomment-6393434703) | [#19](https://github.com/elugardo/catalog-import-watchtower/pull/19) | [`09ff0c1`](https://github.com/elugardo/catalog-import-watchtower/commit/09ff0c1c2db1cbbe2e7b59580edf6e3ee136b013) | [40160787266](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40160787266) (`2b81608`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/2#issuecomment-6393454972) |
| #3 | 03.1 | [groom](https://github.com/elugardo/catalog-import-watchtower/issues/3#issuecomment-6393631245) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/3#issuecomment-6393836307) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/3#issuecomment-6393884071) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/3#issuecomment-6393948839) | [#21](https://github.com/elugardo/catalog-import-watchtower/pull/21) | [`9fa56df`](https://github.com/elugardo/catalog-import-watchtower/commit/9fa56df62d3eadd003555649c3ef591a5d400d16) | [40164891212](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40164891212) (`da5348e`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/3#issuecomment-6393960794) |
| #4 | 03.2a | [edit](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6393440039), [edit](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6393931143), [groom](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6394181642) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6394448626) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6394608756) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6394711860) | [#26](https://github.com/elugardo/catalog-import-watchtower/pull/26) | [`e5427a4`](https://github.com/elugardo/catalog-import-watchtower/commit/e5427a4fded7970adcff43e798ff5ea596af9182) | [40169588868](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40169588868) (`65a1195`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6394723426) |
| #24 | 03.2b | [groom](https://github.com/elugardo/catalog-import-watchtower/issues/24#issuecomment-6394927554) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/24#issuecomment-6395302708) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/24#issuecomment-6395541137) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/24#issuecomment-6395601137) | [#30](https://github.com/elugardo/catalog-import-watchtower/pull/30) | [`b0415ae`](https://github.com/elugardo/catalog-import-watchtower/commit/b0415ae661676de25a385407998536e8709d77dd) | [40175892808](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40175892808) (`c6f3f56`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/24#issuecomment-6395611611) |
| #5 | 04.1 | [groom](https://github.com/elugardo/catalog-import-watchtower/issues/5#issuecomment-6395744649) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/5#issuecomment-6396798827) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/5#issuecomment-6396943686) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/5#issuecomment-6397060598) | [#33](https://github.com/elugardo/catalog-import-watchtower/pull/33) | [`1ad0bd5`](https://github.com/elugardo/catalog-import-watchtower/commit/1ad0bd57e3c6a83a1831d9f4bd1eba13dcebbc4e) | [40186920736](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40186920736) (`dafa2a6`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/5#issuecomment-6397073500) |
| #6 | 04.2 | [edit](https://github.com/elugardo/catalog-import-watchtower/issues/6#issuecomment-6397042948), [groom](https://github.com/elugardo/catalog-import-watchtower/issues/6#issuecomment-6397249528) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/6#issuecomment-6397568592) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/6#issuecomment-6397711660) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/6#issuecomment-6397818713) | [#35](https://github.com/elugardo/catalog-import-watchtower/pull/35) | [`c360a3b`](https://github.com/elugardo/catalog-import-watchtower/commit/c360a3b4b18b0d3f1fc68121c48ec2860d62f2c5) | [40192607598](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40192607598) (`a024db1`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/6#issuecomment-6397829534) |
| #7 | 05 | [edit](https://github.com/elugardo/catalog-import-watchtower/issues/7#issuecomment-6397808082), [groom](https://github.com/elugardo/catalog-import-watchtower/issues/7#issuecomment-6398049614) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/7#issuecomment-6398416865) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/7#issuecomment-6398683192) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/7#issuecomment-6398808088) | [#39](https://github.com/elugardo/catalog-import-watchtower/pull/39) | [`c43d5bf`](https://github.com/elugardo/catalog-import-watchtower/commit/c43d5bf597b529db6c8dea3eee24298a72eb830d) | [40198910033](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40198910033) (`eb18f3f`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/7#issuecomment-6398817684) |
| #40 | 05.1 | [groom](https://github.com/elugardo/catalog-import-watchtower/issues/40#issuecomment-6398796862) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/40#issuecomment-6399147450) | [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/40#issuecomment-6399291762) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/40#issuecomment-6399358942) | [#42](https://github.com/elugardo/catalog-import-watchtower/pull/42) | [`013af74`](https://github.com/elugardo/catalog-import-watchtower/commit/013af747a5fa4c94e144783e412e1e1606db00b7) | [40204271950](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40204271950) (`56d6fb2`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/40#issuecomment-6399372480) |
| #8 | 06 | [edit](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6393440548), [edit](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6395591019), [edit](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6397043228), [edit](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6398797329), [groom](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6399594785) | [hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6400709877) | [FAIL](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401056586), [fix](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401198212), [PASS](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401353707) | [APPROVED](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401535771) | [#43](https://github.com/elugardo/catalog-import-watchtower/pull/43) | [`9c4d2f0`](https://github.com/elugardo/catalog-import-watchtower/commit/9c4d2f05b6a0c8d8f46bd5e187fa34e37ab9fb23) | [40219114189](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40219114189) (`8530106`) | [close](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401553212) |

Notes:

- Every QA comment ends with a line that is only `PASS` or `FAIL`, and every
  PM approval with a line that is only `APPROVED`. No approval returned
  `CHANGES REQUESTED`; the only FAIL is on #8 (*Independence*).
- The closing comment of #2 gives the merge SHA in its short form
  (`09ff0c1`); the other nine give it in full. Both forms resolve to the
  same commit.
- On #8 the closing comment was posted after the issue was already closed;
  see *Deviations*.

## Independence

On #8 (CIW-06, the single test command) the engineer's
[hand-off](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6400709877)
reported every layer green and every criterion met, with CI green.

- **[QA FAIL](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401056586)
  on criterion 11** ("leaves no rows, never changes rows it did not
  create"). QA seeded the shared development database with an in-flight
  `PROCESSING` import, ran the one command, and found that the import had
  been turned into `FAILED` / `INTERNAL_ERROR` and that a new alert existed.
  QA traced it to one test in `test_failure_injection.py`, which entered
  the app lifespan, and so the startup sweep, against the shared database.
- **[Engineer fix](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401198212):**
  that test moved to the throwaway `isolated_db` fixture like the two sweep
  tests, and `_docs/testing.md` now states the rule for every test that
  enters the lifespan.
- **[QA re-test PASS](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401353707):**
  with an in-flight import, an `IN_PROGRESS` alert and a vendor with no
  products seeded, every row count and row hash of the six tables was
  identical before and after two runs; all 21 criteria met.

What QA found that the green suite had not: the suite passed because it
only checks the rows it creates, and the engineer's own data check had no
`PROCESSING` row, so nothing showed that the suite rewrote a developer's
in-flight import (criterion 11). A fresh reader checking the criterion,
not the tests, found it.

## Follow-ups

QA files a follow-up issue for a real problem outside the issue's scope;
the PM then decides where it goes. Nobody changed an acceptance criterion
silently. These rows match `_docs/backlog.md` -> *Folded or closed outside
the table*. State is on `main` `4b15920`.

| Found by QA of | Follow-up | Where it went | State |
|---|---|---|---|
| #1 | [#18](https://github.com/elugardo/catalog-import-watchtower/issues/18) pin the `otel-lgtm` image | folded into #13 ([PM ruling](https://github.com/elugardo/catalog-import-watchtower/issues/18#issuecomment-6390839796)) | closed |
| #3 | [#22](https://github.com/elugardo/catalog-import-watchtower/issues/22) spec §4 F2 wording disagrees with #3 | settled by docs PR #23 ([PM decision](https://github.com/elugardo/catalog-import-watchtower/issues/22#issuecomment-6393940522)) | closed at the merge of PR #23 |
| #4 | [#27](https://github.com/elugardo/catalog-import-watchtower/issues/27) spec wording for the `COMPLETED` transition | settled by docs PR #29 ([PM ruling](https://github.com/elugardo/catalog-import-watchtower/issues/27#issuecomment-6394693332)) | closed at the merge of PR #29 |
| #4 | [#28](https://github.com/elugardo/catalog-import-watchtower/issues/28) a crash during attempt 2 | folded into #10 ([PM ruling](https://github.com/elugardo/catalog-import-watchtower/issues/28#issuecomment-6394693706)) | closed |
| #24 | [#31](https://github.com/elugardo/catalog-import-watchtower/issues/31) the integration suite collides with the demo vendor | folded into #8 ([PM ruling](https://github.com/elugardo/catalog-import-watchtower/issues/31#issuecomment-6395591324)) | closed |
| #6 | [#36](https://github.com/elugardo/catalog-import-watchtower/issues/36) incidents beyond the newest 100 alerts | folded into #7 ([PM ruling](https://github.com/elugardo/catalog-import-watchtower/issues/36#issuecomment-6397808404)) | closed |
| #7 | [#40](https://github.com/elugardo/catalog-import-watchtower/issues/40) SQL bound parameters in error logs | kept as its own issue, CIW-05.1 ([PM groom](https://github.com/elugardo/catalog-import-watchtower/issues/40#issuecomment-6398796862)); ran before #8 | closed (its cycle is in *Cycles*) |
| #8 | [#44](https://github.com/elugardo/catalog-import-watchtower/issues/44) undeclared 500 on upload and import detail | kept as its own issue, CIW-06.1 ([PM groom](https://github.com/elugardo/catalog-import-watchtower/issues/44#issuecomment-6401521097)) | open |

## Docs-only PRs

Each of these PRs carries out a PM groom or approval comment, changes only
`_docs/`, and merged on green CI without its own QA or approval cycle
(`_docs/process.md` -> *Docs-only PRs*). They show the spec changing before,
or together with, the code it describes (`_docs/process.md` -> *When the
spec is wrong*). Times are UTC on 2026-10-25.

| PR | Branch | Files under `_docs/` | From the PM comment | Squash merge | CI run | Merged |
|---|---|---|---|---|---|---|
| [#20](https://github.com/elugardo/catalog-import-watchtower/pull/20) | `docs-spec-csv-rules` | `spec.md` | [#3 groom](https://github.com/elugardo/catalog-import-watchtower/issues/3#issuecomment-6393631245) | `a5b25c3` | [40163656928](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40163656928) | 04:56, before #3's code (PR #21, 05:32) |
| [#23](https://github.com/elugardo/catalog-import-watchtower/pull/23) | `docs-spec-22` | `spec.md`, `api.md` | [#22 PM decision](https://github.com/elugardo/catalog-import-watchtower/issues/22#issuecomment-6393940522) (approval of #3) | `958a395` | [40166501130](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40166501130) | 05:43, before #4's code (PR #26) |
| [#25](https://github.com/elugardo/catalog-import-watchtower/pull/25) | `docs-backlog-split-4` | `backlog.md`, `spec.md` | [#4 groom](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6394181642) | `79bf1f5` | [40168057642](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40168057642) | 06:09, before #4's code (PR #26, 07:08) |
| [#29](https://github.com/elugardo/catalog-import-watchtower/pull/29) | `docs-spec-27` | `spec.md`, `api.md`, `architecture.md`, `backlog.md` | [#4 approval](https://github.com/elugardo/catalog-import-watchtower/issues/4#issuecomment-6394711860) and [#27 PM ruling](https://github.com/elugardo/catalog-import-watchtower/issues/27#issuecomment-6394693332) | `cd499ba` | [40172173521](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40172173521) | 07:18, before #24's code (PR #30) |
| [#32](https://github.com/elugardo/catalog-import-watchtower/pull/32) | `docs-spec-24` | `spec.md`, `backlog.md` | [#24 approval](https://github.com/elugardo/catalog-import-watchtower/issues/24#issuecomment-6395601137) | `9b6eba0` | [40178360938](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40178360938) | 08:53, before #5's code (PR #33) |
| [#34](https://github.com/elugardo/catalog-import-watchtower/pull/34) | `docs-spec-5` | `spec.md`, `testing.md` | [#5 approval](https://github.com/elugardo/catalog-import-watchtower/issues/5#issuecomment-6397060598) | `ecd0a77` | [40189595276](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40189595276) | 11:38, before #6's code (PR #35) |
| [#37](https://github.com/elugardo/catalog-import-watchtower/pull/37) | `docs-spec-6` | `spec.md`, `backlog.md`, `operations.md`, `team/oncall-agent.md` | [#6 approval](https://github.com/elugardo/catalog-import-watchtower/issues/6#issuecomment-6397818713) | `10e56ca` | [40195088865](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40195088865) | 12:54, before #7's code (PR #39) |
| [#38](https://github.com/elugardo/catalog-import-watchtower/pull/38) | `docs-spec-7` | `spec.md` | [#7 groom](https://github.com/elugardo/catalog-import-watchtower/issues/7#issuecomment-6398049614) | `ac4db93` | [40196475980](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40196475980) | 13:12, before #7's code (PR #39, 14:22) |
| [#41](https://github.com/elugardo/catalog-import-watchtower/pull/41) | `docs-backlog-40` | `backlog.md` | [#7 approval](https://github.com/elugardo/catalog-import-watchtower/issues/7#issuecomment-6398808088) | `42fc5d1` | [40202022493](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40202022493) | 14:25, before #40's code (PR #42) |
| [#45](https://github.com/elugardo/catalog-import-watchtower/pull/45) | `docs-backlog-44` | `backlog.md`, `issue-template.md`, `team/software-engineer.md` | [#8 approval](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401535771) | `4b15920` | [40222168729](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40222168729) | 18:39, before #9 (this issue) |

Every file path is under `_docs/` (`gh pr view <p> --json files`). Every
body links its PM comment and says `Refs` for the issue that comment is on.
The branch commits are `Docs: <what>`, and the squash commits on `main` are
`Docs: <what> (#<pr>)`.

## Deviations

Where the record departs from `_docs/process.md`, stated from the record.

1. **#8 was closed by its PR, before the evidence was recorded.** The body
   of PR #43 contained a closing keyword followed by `#8`, inside a
   sentence that meant the opposite. GitHub acts on the keyword wherever it
   appears, so the merge of the PR at 18:34:56 UTC on 2026-10-25 also
   shut #8, at 18:34:58, before the orchestrator's
   [evidence comment](https://github.com/elugardo/catalog-import-watchtower/issues/8#issuecomment-6401553212)
   at 18:35:38. QA PASS (18:17:12) and PM APPROVED (18:34:02) came before
   the merge, so no gate was skipped; only the order "record, then close"
   was broken. PR #45 changed `_docs/team/software-engineer.md` to prevent
   it, and #9 adds the same rule to `AGENTS.md` -> *Rules* and
   `_docs/process.md` -> *Conventions*.
2. **Two issues ran ahead of a lower number, by dependency.** #24 ran
   before #5 because #5 depends on #24, and #40 ran before #8 because #8
   depends on #40. `_docs/backlog.md` -> *Order* explains both.
3. **Marcos stopped being a merge gate before the first merge.** Commit
   `2845fc5` ("Process: PM approval replaces the human merge gate",
   2026-10-24 20:36 UTC) came before the first merge, PR #17 at 23:26 UTC.
   So every merge in *Cycles* was the orchestrator's, made after QA PASS
   and PM APPROVED; Marcos reviews the record afterwards.
4. **Two spec commits went straight to `main` without a PR.** `20bae07`
   ("Docs: spec names the health status values and the otel-lgtm service",
   2026-10-24 23:27 UTC, after #1's merge) and `4d78c8f` ("Docs: spec
   clarifies product_count, completed_at and list bounds", 2026-10-25
   04:30 UTC, after #2's merge) each change only `_docs/spec.md`. Every
   docs change from #3 on went through a docs-only PR (*Docs-only PRs*).
5. **Two docs-only PRs closed their follow-up issue by keyword.** The
   bodies of PR #23 and PR #29 used a closing keyword for the docs
   follow-ups they settled (#22 and #27), so those issues closed at the
   merge. That was intended, but it is the habit that later shut #8 too
   early. `_docs/process.md` -> *Docs-only PRs* now says the orchestrator
   closes such an issue by hand, with a link to the merged PR.
6. **Docs-only PRs merged on green CI without QA or PM approval.** Ten PRs
   did this while `_docs/process.md` did not describe it, so it
   contradicted "merges only after PASS and APPROVED". It is now the
   documented exception (`_docs/process.md` -> *Docs-only PRs*, and the
   orchestrator *Rules*).
7. **#9 itself did not run when the lowest-number rule would have picked
   it.** It has no dependency, so from the close of #4 on it was the lowest
   unblocked open issue, and `_docs/backlog.md` had planned to close it
   right after #1. Instead #24, #5, #6, #7, #40 and #8 ran first, and #9
   ran after #8. The backlog row described 07 as open from the start; the
   record has no comment on #9 before its groom on 2026-10-25, so it does
   not say why it was not picked earlier. `_docs/backlog.md` -> *Order*
   now records what happened.

## Roles and process

`_docs/process.md` contains the seven steps spec §12 requires, in order,
plus the PM approval step and the orchestrator rules. Quoted from
`_docs/process.md` -> *The loop, for one issue*, as #9 leaves it:

| Spec §12 step | Line in `_docs/process.md` |
|---|---|
| Select a GitHub issue | 1. "**Select one open GitHub issue** labelled `final-project`, the lowest number whose dependencies in `backlog.md` are closed." |
| Read its acceptance criteria | 2. "**Read the acceptance criteria.** They follow `issue-template.md`." |
| Implement only that issue | 3. "**Implement only that issue** on a branch named `fp-<n>-<slug>`" |
| Run tests | 4. "**Run the tests** that the issue and `testing.md` name, and the single full test command once it exists." |
| Request an independent QA review | 6. "**Request an independent QA review.** QA runs in a *fresh* session" |
| Link commits and PR | 9. "**links the commits and the PR on the issue** in its closing comment: the merged PR and its squash commit SHA" (the commits carry `Refs #<n>` from step 4 and the PR links the issue from step 5) |
| Close only after evidence is recorded | 10. "**Close only after the evidence is recorded.**" |

PM approval is step 8 ("**On PASS, request PM approval.**"). The
orchestrator rules: "step 2 is never skipped; the engineer never closes or
merges; QA never fixes; the PM never writes code; the orchestrator merges
only after PASS *and* APPROVED *and* green CI, and closes only after the
evidence is recorded."

One line per role file, with the sentence that proves the claim:

- `.claude/agents/product-manager.md` loads its role file and writes no
  code: "Read `AGENTS.md`, then `_docs/team/product-manager.md`, and follow
  that file exactly." and "You write no application code and change no
  file outside `_docs/`."
- `.claude/agents/software-engineer.md` loads its role file and does not
  close: "Read `AGENTS.md`, then `_docs/team/software-engineer.md`, and
  follow that file exactly." and "Do not close the issue."
- `.claude/agents/qa-engineer.md` loads its role file, fixes nothing and
  works fresh: "Read `AGENTS.md`, then `_docs/team/qa-engineer.md`, and
  follow that file exactly." and "Use this agent, always in a fresh
  context, to verify one implemented issue against its acceptance criteria
  by running the code. It fixes nothing and ends with PASS or FAIL."
- `.claude/skills/work-issue/SKILL.md` lists the loop with the
  three-strikes stop: "Run the full groom → implement → QA → PM approval →
  merge → close cycle for one GitHub issue of Catalog Import Watchtower as
  the orchestrator, then continue with the next unblocked issue." and
  "After three FAILs in a row, stop and summarize for Marcos instead of
  looping."
- `_docs/team/oncall-agent.md` keeps the runtime agent apart from the three
  development-time roles: "It is not a development-time role: it never
  reads or writes code, never touches the repository, and never talks to a
  human."
- `.claude/skills/incident-response/SKILL.md` points at the canonical file:
  "The canonical skill lives at `.agents/skills/incident-response/SKILL.md`
  (the tool-agnostic location the course asks for)."

## Context per role

What each role is given to read and what it may change. Each agent starts
from `AGENTS.md` and loads only its own role file and the docs it names,
so no role carries another's session.

| Role | Entry | Role file it loads | Docs it is told to read | What it may change |
|---|---|---|---|---|
| Product manager | `.claude/agents/product-manager.md` | `_docs/team/product-manager.md` | `AGENTS.md`, `_docs/spec.md`, `_docs/backlog.md`, `_docs/issue-template.md`, `_docs/rubric.md`; when approving, the issue with its comments and `gh pr view` (not the diff) | GitHub issues (bodies, groom and approval comments, follow-ups); files under `_docs/` only, through docs-only PRs; never code |
| Software engineer | `.claude/agents/software-engineer.md` | `_docs/team/software-engineer.md` | `AGENTS.md`, the issue with `gh issue view <n> --comments`, and the *Read this first* docs for the area (at least `_docs/architecture.md`; `_docs/api.md` and `openapi.yaml` for an endpoint; `_docs/testing.md` for tests) | the files the issue's *Constraints* name, on `fp-<n>-<slug>`; the PR; the hand-off comment; never closes or merges |
| QA engineer | `.claude/agents/qa-engineer.md` (fresh context) | `_docs/team/qa-engineer.md` | `AGENTS.md`, the issue with its comments, the PR diff (only as where to look), `_docs/spec.md` §4 and §9; not the engineer's session | one verdict comment ending in `PASS` or `FAIL`; follow-up issues; no code |
| Orchestrator | `.claude/skills/work-issue/SKILL.md` (`/work-issue <n>`) | none; it follows `_docs/process.md` | `_docs/process.md`, `_docs/backlog.md`, `_docs/issue-template.md` -> *Evidence*; subagent reports, not diffs | launches the three roles; merges a PR after PASS, APPROVED and green CI (a docs-only PR on green CI); posts the closing comment and closes the issue; does not groom, implement or test |
| On-call agent (runtime) | `.agents/skills/incident-response/SKILL.md` (with `.claude/skills/incident-response/SKILL.md` for triage by hand) | `_docs/team/oncall-agent.md` | the incident, read only through its six allowlisted tools; no repository, no catalog content | through those tools only: one retry of a `TRANSIENT_STORAGE_TIMEOUT` import, the alert status and its audit rows; never code |

## Spec §12 files

Every path spec §12 lists, whether it exists on #9's branch (based on
`main` `4b15920`), and where `AGENTS.md` links it. *Read this first* rows
are named by the start of their *When* text.

| Path | Exists | Where `AGENTS.md` links it |
|---|---|---|
| `AGENTS.md` | yes | (the index itself) |
| `_docs/spec.md` | yes | *Read this first* -> "Deciding what to build" |
| `_docs/process.md` | yes | *Read this first* -> "Always, before any task" |
| `_docs/architecture.md` | yes | *Read this first* -> "Touching models, services, Compose" |
| `_docs/api.md` | yes | *Read this first* -> "Touching an endpoint" |
| `_docs/testing.md` | yes | *Read this first* -> "Writing or reviewing tests" |
| `_docs/operations.md` | yes | *Read this first* -> "Telemetry, alerts, env vars" |
| `_docs/team/product-manager.md` | yes | *Read this first* -> "Turning the spec into issues" |
| `_docs/team/software-engineer.md` | yes | *Read this first* -> "Implementing an issue" |
| `_docs/team/qa-engineer.md` | yes | *Read this first* -> "Verifying an issue" |
| `_docs/team/oncall-agent.md` | yes | *Read this first* -> "Working on the runtime on-call worker" |
| `_docs/rubric.md` | yes | *Read this first* -> "Checking that a deliverable earns its points" |
| `_docs/backlog.md` | yes | *Read this first* -> "Turning the spec into issues" |
| `_docs/issue-template.md` | yes | *Read this first* -> "Turning the spec into issues" |
| `_docs/adr/` | yes | *Read this first* -> "Making a decision that is hard to reverse" |
| `.agents/skills/incident-response/SKILL.md` | yes | *Read this first* -> "Working on the runtime on-call worker" |
| `openapi.yaml` | yes | *Read this first* -> "Touching an endpoint" |

## Privacy

This folder holds no CSV rows, vendor or product names, cell values, tokens
or credentials. The check is a grep of this folder for the demo vendor
name, every SKU and product name in `fixtures/*.csv`, and the API-key prefix (`sk` and a hyphen); the
command and its empty output are in the body of the PR that adds this
report.
