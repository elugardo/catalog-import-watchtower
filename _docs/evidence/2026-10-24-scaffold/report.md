# 2026-10-24 - Scaffold: one command brings up the whole stack

**Rubric rows served:** 5 (Application: frontend + backend + persistent storage, one command locally) and 7 (Containerization: the whole system including the database starts with one Compose command). Issue [#1](https://github.com/elugardo/catalog-import-watchtower/issues/1) (CIW-01).

## What was shown

- `docker compose up --build -d --wait` on a clean checkout with no `.env` starts `app`, `oncall-agent`, `db` and `otel-lgtm` and returns only once `app` is healthy, which means `GET /api/health` already reports `db: "ok"`.
- `shell.png`: the React shell served by the FastAPI process at `http://localhost:8000/`, showing the product name and the `status`, `db`, `agent_enabled` and `version` values read from `/api/health`.
- `GET /api/health` -> `{"status":"ok","db":"ok","agent_enabled":false,"version":"dev"}`.
- With `db` stopped, `/api/health` keeps answering 200 with `db: "error"`, `status: "degraded"` within 1-2 s, and goes back to `ok` when `db` starts again, without restarting `app`.
- `oncall-agent` logs one idle line and stays up with a restart count of 0; it stops within the Compose grace period on SIGTERM.
- The database volume survives `docker compose down` and is dropped by `docker compose down -v`.

## How to reproduce

```
docker compose down -v
docker compose up --build -d --wait
docker compose ps
curl http://localhost:8000/api/health
start http://localhost:8000/            # the page in shell.png
docker compose stop db && curl http://localhost:8000/api/health && docker compose start db
```

The screenshot was taken with headless Edge: `msedge --headless=new --window-size=1280,800 --screenshot=shell.png http://localhost:8000/`.

Nothing in this folder contains CSV rows, vendor or product names, tokens or credentials.
