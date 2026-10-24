# 0002. Deployment: Fly.io apps, Neon PostgreSQL, public image in GHCR

- **Status:** accepted
- **Date:** 2026-10-24
- **Issue:** CIW-10 (exporter configuration in CIW-09)

## Context

Spec §11 asks for persistent PostgreSQL, two environments with separate
databases, automatic deploy to development on push to `main`, a manually
triggered promotion of the *same image* to production, a documented
rollback, public URLs and health checks. Marcos's other projects
(`comic-predictor`, `next-role`) already run on **Fly.io with Neon
PostgreSQL**, deployed by `flyctl` from GitHub Actions with a
`release_command` for Alembic migrations, so the tooling and accounts exist.

The repository is public and the overriding constraint is that **no secret
can be exposed**: not in the repo, not in workflow files, not in images, not
in logs.

## Options

1. **Fly.io, one app per environment, Neon per environment, image built in
   GitHub Actions and pushed to GHCR as a public package;** `flyctl deploy
   --image ghcr.io/…:sha-<commit>` for both the dev deploy and the prod
   promotion. Matches existing habits; the image needs no registry
   credentials on Fly's side because it is public and contains no secrets.
2. Fly.io with Fly's remote builder (`flyctl deploy --remote-only`), as in
   `comic-predictor`. Simpler workflow, but prod would be rebuilt rather than
   promoted, which breaks the "exact tested image" requirement.
3. Render / Railway. No existing account or habits; image promotion less
   scriptable.
4. Deploy manually from Marcos's machine and keep no deploy workflow in
   GitHub. Removes nothing security-wise (workflow files hold no secrets)
   and caps the CI/CD rubric row at 1 of 3 points.

## Decision

Option 1.

- Fly apps `ciw-dev` and `ciw-prod` (region `ewr`), each with two process
  groups from the same image: `app` (HTTP, `/api/health` check) and
  `worker` (`python -m app.oncall`, no HTTP). `release_command = "alembic
  upgrade head"`.
- One Neon project per environment (free tier), connection string stored
  only as a Fly secret `DATABASE_URL` on that app.
- Image `ghcr.io/elugardo/catalog-import-watchtower:sha-<commit>`, public,
  built once per push to `main`; prod promotion is `workflow_dispatch` with
  the tag as input, gated by a GitHub `production` environment that
  requires Marcos's approval; it runs `flyctl deploy -a ciw-prod --image
  <tag>` with no build step.
- Deployed telemetry: exporter disabled (`OTEL_SDK_DISABLED=true`); the
  observability rubric row is met with the local stack (spec §10).
- **The LLM key never leaves Marcos's machine.** Deployed environments run
  with `AGENT_ENABLED=false`; alerts there show "automated recovery
  disabled". The recorded real-LLM recovery is produced locally. If a live
  deployed recovery is ever wanted for a demo, the key is set as a Fly
  secret for that hour and unset afterwards.

## Blast radius: nothing here can touch other projects

- The Fly apps `ciw-dev` and `ciw-prod` are new apps. The deploy tokens
  are created **per app** (`flyctl tokens create deploy -a ciw-dev`), so a
  token can deploy that one app and nothing else; it cannot list, deploy,
  scale or read secrets of `comic-predictor-api`, `next-role`, or any other
  app, even if it leaked.
- Each environment has its own Neon project; no connection string of any
  other project is used anywhere.
- The workflows live only in this project's repository (ADR-0001) and
  reference only these two apps by name; a mistaken edit cannot deploy
  somewhere else.
- `flyctl` on Marcos's machine is logged in with his personal account, so
  manual commands can reach other apps; the workflows never run with that
  login, only with the app-scoped tokens.

## Secrets inventory and controls

| Secret | Lives in | Never in |
|---|---|---|
| `FLY_API_TOKEN`, a deploy token scoped to the two apps (`flyctl tokens create deploy -a ciw-dev`, same for prod) | GitHub Actions secrets of the `development` and `production` environments | repo, logs, PR builds from forks (GitHub withholds secrets from fork PRs) |
| `DATABASE_URL` per environment | Fly secrets of that app; locally the Compose default in `.env` | repo, image, telemetry |
| LLM provider key | local `.env` only (plus a spending cap on the provider side; revoked after the course) | repo, GitHub, Fly by default, CI (CI uses a fake LLM) |

Controls: `.env*` gitignored with `.env.example` committed; GitHub secret
scanning and push protection are on for public repositories; the PR
workflow runs `gitleaks` so a leaked string fails CI; workflows never
`echo` secrets; images receive configuration only at runtime; Fly deploy
tokens are app-scoped so a leak cannot reach other apps.

## Consequences

- CIW-10 creates `fly.dev.toml` and `fly.prod.toml` (or one `fly.toml`
  deployed with `-a`), the two Neon projects, the GitHub environments, and
  `.github/workflows/ci.yml`, `deploy-dev.yml`, `promote-prod.yml` in the
  project repository (ADR-0001); it rehearses one rollback
  (`flyctl deploy -a ciw-dev --image <previous sha tag>`) and records it in
  `operations.md`.
- CIW-09 reads `OTEL_SDK_DISABLED` so the same image runs with and without
  telemetry.
- `architecture.md` records that the SPA is served by the app process in
  every environment (no proxy anywhere).
- Revisit if Fly's free allowance does not cover two always-on apps for
  the course period (`auto_stop_machines = "stop"` with
  `min_machines_running = 0` on dev keeps it near zero).
