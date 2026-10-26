# Deploy to development: evidence for CIW-10.1 (#14)

The post-merge evidence for issue #14, stage 2 of the two-stage close the PM approved. It covers rubric
rows **8** (Deployment: dev URL and health check) and **9** (CI/CD: PR CI, automatic CD to dev).
Recorded on 2026-10-26, against `main` at `f4a455ed9746746b10549262eb6678402d111374`.

- **Dev URL:** <https://ciw-dev.fly.dev> (Fly app `ciw-dev`, region `ewr`, Neon project in `aws-us-east-1`)
- **Image:** `ghcr.io/elugardo/catalog-import-watchtower:sha-f4a455ed9746746b10549262eb6678402d111374`,
  digest `sha256:d8ee66301e1b6f3cfc49ff709a0c333c3a35de4c85fb875b7220b766a5bbc41f`

All `flyctl` calls below were read-only (`secrets list`, `machines list`, `releases`, `config validate`).
No secret value appears in this report; the secret digest column of `flyctl secrets list` is left out too.

## Workflow runs

| What | Run | Result |
|---|---|---|
| PR CI on the head of PR #52 (`fa97dca`) | [40267315673](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40267315673) | green: all four checks; the one command passed 422 unit, 266 integration, check:api and 49 frontend tests |
| gitleaks on scratch PR #53 with an obviously fake key | [40267327422](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40267327422) | red as intended: `generic-api-key`, `Secret: REDACTED`, `leaks found: 1` |
| pipefail on scratch PR #54 (`exit 3` on the left of `\| tee`) | [40267343588](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40267343588) | red as intended: `Process completed with exit code 3.` |
| `deploy-dev.yml` on the merge of #52 (`d8b90ee`), before provisioning | [40269500510](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40269500510) | red, expected (PM ruling 3 on #14): the fail-early step stopped before any `flyctl` call with `FLY_API_TOKEN is not set in the 'development' environment` |
| `deploy-dev.yml` on the merge of #56 (`f4a455e`) | [40276218575](https://github.com/elugardo/catalog-import-watchtower/actions/runs/40276218575) | **green on attempt 3**; see below |

Run 40276218575 has three attempts. The `publish` job ran once (attempt 1, 05:48 UTC) and the re-runs
reused it; only the deploy job was re-run.

1. Attempt 1 (05:49 UTC): red at the fail-early step, because `FLY_API_TOKEN` was not set yet. Same as the run above.
2. Attempt 2 (11:37 UTC): red at `flyctl deploy`, `Error: Authenticate: token validation error`.
   This is the **BOM incident**: the first pair of deploy tokens (dev and prod) was piped into
   `gh secret set` from Windows PowerShell, which prepended a byte-order mark. Both tokens were
   replaced with clean ones and the bad ones revoked. `_docs/operations.md` -> *Provisioning* now says
   to run that command from Git Bash.
3. Attempt 3 (11:38 UTC): green. Deploy job 42 s.

## Deploy log (run 40276218575, attempt 3)

Digest equality, from the `publish` job (both tags on the one build):

```
built           sha256:d8ee66301e1b6f3cfc49ff709a0c333c3a35de4c85fb875b7220b766a5bbc41f
ghcr.io/elugardo/catalog-import-watchtower:sha-f4a455ed9746746b10549262eb6678402d111374  sha256:d8ee66301e1b6f3cfc49ff709a0c333c3a35de4c85fb875b7220b766a5bbc41f
ghcr.io/elugardo/catalog-import-watchtower:dev     sha256:d8ee66301e1b6f3cfc49ff709a0c333c3a35de4c85fb875b7220b766a5bbc41f
```

`flyctl deploy --image` (no build: the image is found in GHCR), the release command, one `app` machine:

```
Validating fly.toml
✓ Configuration is valid
==> Building image
Searching for image 'ghcr.io/elugardo/catalog-import-watchtower:sha-f4a455ed9746746b10549262eb6678402d111374' remotely...
image found: img_8y6w4zjyj8wgv7rn
Running ciw-dev release_command: alembic upgrade head
✔ release_command e820355c511348 completed successfully
This deployment will:
 * create 1 "app" machine
✔ Machine 837e23a77ed338 [app] update finished: success
NOTE: The machines for [app] have services with 'auto_stop_machines = "stop"' that will be stopped when idling
```

Zero-worker step and smoke check:

```
process group / state / image
app	started	ghcr.io/elugardo/catalog-import-watchtower:sha-f4a455ed9746746b10549262eb6678402d111374
[1/30] GET https://ciw-dev.fly.dev/api/health: HTTP 200 {"status":"ok","db":"ok","agent_enabled":false,"version":"sha-f4a455ed9746746b10549262eb6678402d111374"}
smoke check passed
```

The log masks `FLY_API_TOKEN` (`***`) everywhere it appears, and the `flyctl` output contains no
connection string. The job ran with `GITHUB_TOKEN` permissions `Contents: read`, `Metadata: read`
and `Packages: write`.

## Health response

```
$ curl -s https://ciw-dev.fly.dev/api/health
{"status":"ok","db":"ok","agent_enabled":false,"version":"sha-f4a455ed9746746b10549262eb6678402d111374"}
```

Screenshot: [`05-api-health.jpg`](05-api-health.jpg).

## Fly state (read-only)

```
$ flyctl secrets list -a ciw-dev
NAME            STATUS
DATABASE_URL    Deployed

$ flyctl machines list -a ciw-dev          (11:47 UTC, about 8 minutes after the deploy)
1 machines have been retrieved from app ciw-dev.
ID              NAME              STATE    CHECKS  REGION  IMAGE                                                                            PROCESS GROUP  SIZE
837e23a77ed338  falling-pine-7159 stopped  0/1     ewr     elugardo/catalog-import-watchtower:sha-f4a455ed9746746b10549262eb6678402d111374  app            shared-cpu-1x:512MB

$ flyctl releases -a ciw-dev
VERSION  STATUS    DESCRIPTION
v1       complete  Release

$ flyctl config validate --config fly.toml -a ciw-dev
✓ Configuration is valid
```

There is one `app` machine and no `worker` machine. `DATABASE_URL` is the only secret.

**Idle stop and wake.** The machine was `stopped` (above, last updated 11:46:31 UTC). A request then
woke it:

```
2026-10-26T11:48:33Z  GET https://ciw-dev.fly.dev/api/health
{"status":"ok","db":"ok","agent_enabled":false,"version":"sha-f4a455ed9746746b10549262eb6678402d111374"}
HTTP 200 in 11.89s        (cold start of the machine and of the Neon compute)

$ flyctl machines list -a ciw-dev
837e23a77ed338  falling-pine-7159  started  1/1  ewr  ...  app  shared-cpu-1x:512MB   (last updated 11:48:40Z)
```

## Image checks (anonymous pull)

Pulled with an empty Docker config (`DOCKER_CONFIG` pointing at a directory holding only `{}`), so no
GHCR credentials were used:

```
$ docker pull ghcr.io/elugardo/catalog-import-watchtower:sha-f4a455ed9746746b10549262eb6678402d111374
Digest: sha256:d8ee66301e1b6f3cfc49ff709a0c333c3a35de4c85fb875b7220b766a5bbc41f
Status: Downloaded newer image for ghcr.io/elugardo/catalog-import-watchtower:sha-f4a455ed9746746b10549262eb6678402d111374

$ docker run --rm --entrypoint ls <image> -a /app
.  ..  .python-version  .venv  alembic  alembic.ini  app  pyproject.toml  uv.lock

$ docker image inspect <image> --format '{{json .Config.Env}}'
["PATH=/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
 "LANG=C.UTF-8","GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305","PYTHON_VERSION=3.12.15",
 "PYTHON_SHA256=c2c4321961fab0fb999d66e0cecf521c2ab3994c7992873ea99e306c1094fd5a",
 "APP_VERSION=sha-f4a455ed9746746b10549262eb6678402d111374","PYTHONDONTWRITEBYTECODE=1",
 "PYTHONUNBUFFERED=1","UV_PROJECT_ENVIRONMENT=/app/.venv","UV_PYTHON_DOWNLOADS=never",
 "UV_PYTHON=/usr/local/bin/python3.12"]
```

The pulled digest matches the one in the deploy log. `/app` has no `.env`, and `Config.Env` has no
secret. `GPG_KEY` is the public fingerprint of the CPython release signing key, which the `python`
base image sets. `APP_VERSION` is the only value this project adds.

## Public dev environment (screenshots)

Taken in Chrome against <https://ciw-dev.fly.dev>. The data is the committed synthetic fixture
`fixtures/valid.csv` (3 rows) under the vendor name `Demo Vendor`. There is no real catalog content.

| File | Shows |
|---|---|
| [`01-dev-spa-dashboard.jpg`](01-dev-spa-dashboard.jpg) | the SPA served by the dev app: an empty dashboard, footer `version sha-f4a455e…  db ok` |
| [`02-valid-csv-import-completed.jpg`](02-valid-csv-import-completed.jpg) | `fixtures/valid.csv` uploaded through the dev UI: import 1, `COMPLETED`, 3 rows, 3 products |
| [`03-products-after-reload.jpg`](03-products-after-reload.jpg) | a fresh page load of `/products`: the 3 products persisted in Neon (`showing 3 of 3 products`) |
| [`04-injected-failure-recovery-disabled.jpg`](04-injected-failure-recovery-disabled.jpg) | `valid.csv` again with the synthetic failure injector on. Import 2 is `FAILED` with `TRANSIENT_STORAGE_TIMEOUT` after one attempt, under the *Demo failure injected* label. Its incident is `OPEN` with **automated recovery disabled** (`AGENT_ENABLED=false`, no worker) |
| [`05-api-health.jpg`](05-api-health.jpg) | `GET /api/health`: `status ok`, `db ok`, `agent_enabled false`, `version sha-f4a455e…` |

The browser extension could not reach the upload form's file input while the page was still
loading, so the file was attached from the page itself: a `File` built from the exact 126 bytes of
`fixtures/valid.csv`. Its SHA-256, `54e303eb…dbcf3d`, is the one the import detail shows. The form
was then submitted with its own **Import** button, so the request went through the SPA and the API
as a user's would. Import 2 stays `FAILED` with an open incident on dev, which is the expected state
with the agent off.

## Provisioning checklist (`ciw-dev`, values redacted)

From `_docs/operations.md` -> *Deployment* -> *Provisioning*. The orchestrator provisioned dev
after Marcos approved it on 2026-10-26.

- [x] **Fly app.** `flyctl apps create ciw-dev --org <personal-org-slug>`
- [x] **Neon project.** A new project for dev, region `aws-us-east-1`, database `ciw`, direct (not
  `-pooler`) connection string. It is not shared with prod: a second, separate project backs `ciw-prod`.
- [x] **`DATABASE_URL` Fly secret**, `postgresql+psycopg://<role>:<redacted>@<endpoint-host>/ciw?sslmode=require`,
  staged with `flyctl secrets import -a ciw-dev --stage` and never echoed. `flyctl secrets list` shows
  it `Deployed`.
- [x] **GitHub environment** `development` (exists; no protection rules).
- [x] **Deploy token**, `flyctl tokens create deploy -a ciw-dev` (app-scoped), stored as
  `FLY_API_TOKEN` in the `development` environment. `gh secret list --env development` shows the
  name, updated 2026-10-26T11:38:21Z. The first token carried a PowerShell BOM and failed with
  `token validation error`; it was replaced and revoked (see *Workflow runs*).
- [x] **First publish**: `deploy-dev.yml` ran on `main` (run 40276218575; attempt 3 green).
- [x] **GHCR package public**: the anonymous pull above works.
- [x] **Checks**: one secret (`DATABASE_URL`); one `app` machine and no `worker`; the machine is
  `stopped` when idle, and a request to `/api/health` wakes it.
- [ ] **Branch protection** on `main` with the four required check names: **not done.**
  `gh api repos/elugardo/catalog-import-watchtower/branches/main/protection` shows protection with no
  `required_status_checks`. This step is Marcos's; the QA verdict does not count it as a blocker.

## Still open for #14

- **Two quick pushes.** Merging this PR pushes a new commit to `main`, which starts a second
  `deploy-dev.yml` run. That run (and #15) checks that the newest commit becomes both the `dev` tag
  and the running release.

## Reproduce

```
gh run view 40276218575 --attempt 3 --log
flyctl secrets list -a ciw-dev ; flyctl machines list -a ciw-dev
curl -s https://ciw-dev.fly.dev/api/health
DOCKER_CONFIG=<empty dir> docker pull ghcr.io/elugardo/catalog-import-watchtower:sha-<SHA>
```