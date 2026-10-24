# Architecture decision records

One file per decision that is hard to reverse: provider, repository layout,
schema shape, auth between services, a dependency that pulls others in.
Smaller choices go straight into `architecture.md`.

Copy [`0000-template.md`](0000-template.md) to `NNNN-short-title.md`, fill it
in, set the status, link it from the issue that needed it. Statuses:
`proposed` (needs Marcos's decision), `accepted`, `superseded by NNNN`.

| ADR | Title | Status | Needed by |
|---|---|---|---|
| [0001](0001-repository-layout.md) | Repository layout: own public repository `catalog-import-watchtower` | accepted, migration pending | before the backlog |
| [0002](0002-deployment-provider.md) | Deployment: Fly.io apps, Neon PostgreSQL, public image in GHCR, secrets inventory | accepted | issue 10 (exporter flag in 09) |
