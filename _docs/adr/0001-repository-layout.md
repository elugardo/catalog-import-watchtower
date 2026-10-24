# 0001. Repository layout: own public repository

- **Status:** accepted (migration pending Marcos's go-ahead)
- **Date:** 2026-10-24
- **Issue:** CIW-01

## Context

The project started as `finalproject/` inside the public course repository
`elugardo/ai-dev-tools-zoomcamp`, next to four homework modules. The course
needs a public repository, a public issue tracker with acceptance criteria,
PR-triggered CI, CD to a development environment and a manual promotion to
production. Peer reviewers open the repository link and read what they find
at the root. Marcos wants deployments that cannot touch his other projects,
and is fine with a separate repository.

## Options

1. **Stay in the monorepo.** Workflows at the repo root with
   `paths: finalproject/**` filters; issues labelled `final-project`; root
   README links in. Reviewers see homework modules mixed into the README,
   issues and history, and the workflows sit outside the self-contained
   folder.
2. **Own repository** `elugardo/catalog-import-watchtower`. Project at the
   root, clean issue numbering, workflows inside the project, branch
   protection and secret scanning scoped to it. One copy now; the course
   repo keeps a pointer.

## Decision

Option 2. The docs in this folder are written relative to the folder, so
nothing changes on the move. The course repo keeps `finalproject/README.md`
as a pointer only, so there are never two diverging copies.

## Migration (one session, before the backlog is published)

1. `gh repo create elugardo/catalog-import-watchtower --public
   --description "…" --clone`.
2. Copy the contents of `finalproject/` to the new repo root (not the folder
   itself); commit as "Project setup: spec, agent team, process docs".
3. In the course repo replace `finalproject/` with a one-paragraph
   `finalproject/README.md` linking to the new repository, and update the
   course repo's root `AGENTS.md` and `README.md` entries.
4. In the new repo: enable secret scanning + push protection (on by default
   for public repos; verify), protect `main` (PR required, CI required),
   create the `development` and `production` environments (production with
   Marcos as required reviewer), create the `final-project` label.
5. Open sessions from the new repo's root; `.claude/` and `.agents/` are
   picked up there.

## Consequences

- Workflows are `.github/workflows/ci.yml`, `deploy-dev.yml`,
  `promote-prod.yml` at the root of the new repository, no path filters.
- Issue titles keep the `[CIW-NN]` prefix (the spec ids) and the
  `final-project` label, which costs nothing and keeps `backlog.md` stable.
- The submission form points at the new repository and its final commit.
- `AGENTS.md`'s "self-contained" rule becomes simply "this repository is the
  whole project".
