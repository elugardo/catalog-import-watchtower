# CIW-04.2 (#6): Dashboard, Import detail and Products UI, 2026-10-25

Rubric row 5 (Application): the frontend connected end to end to the API and
PostgreSQL in the Compose stack, including an import that persists across an
app restart.

Commit: branch `fp-6-ui-detail-products`, implementation commits `eccb9fc`
(pages, components, tests) and `a8b22e8` (docs); the stack was built from
`a8b22e8` (QA checks out the PR head).

## Steps

1. `docker compose down -v`, then `docker compose up --build -d --wait`
   (fresh volume).
2. `valid.csv`, `update.csv`, `invalid.csv` uploaded in that order for vendor
   `Sample Furnishings` (`POST /api/imports`, multipart): imports 1
   `COMPLETED` (3 rows, 3 products), 2 `COMPLETED` (1 row, 1 product),
   3 `FAILED` / `VALIDATION_ERROR`.
3. Chrome at `http://localhost:8000/` -> `dashboard.jpg`: Completed **2**,
   Recovered **0**, Failed **1**; the newest-imports table with the three
   imports newest first; `No open incidents`, `No recent incidents`. The page
   sent exactly `/api/imports?limit=100`, `/api/alerts?limit=100` and
   `/api/health` (Resource Timing entries).
4. `http://localhost:8000/imports/3` loaded directly (deep link, full page
   load) -> `import-detail-invalid.jpg`: `FAILED`, vendor, filename, all 64
   characters of `sha256`, completed `—`, rows 4, empty products,
   `VALIDATION_ERROR`, `1 error`,
   `line 4, quantity: must be a whole number of up to 9 digits, got '-2'`,
   one `FAILED` attempt with an empty trace id.
5. `docker compose restart app`, wait for healthy, then `/products` with the
   Vendor select set to `Sample Furnishings` ->
   `products-after-restart.jpg`: `showing 3 of 3 products`, CHAIR-001 at
   `$129.99` / 20 (the `update.csv` values), LAMP-003 `$39.50` / 12,
   TABLE-002 `$499.00` / 3, last updated in UTC. The import persisted across
   the restart.

## Further checks on the same stack (not screenshots)

- **500 rows, Load more.** A generated 500-row CSV (scratch file, not
  committed) imported for vendor `Bulk Vendor` (import 4, `COMPLETED`, 500
  products, one `updated_at`). Products filtered to it, **Load more** clicked
  twice per page until it disappeared: 9 clicks, 10 requests
  (`vendor_id=4&limit=50`, then `offset=50` ... `offset=450`, from the app
  access log), 500 rows, 500 distinct SKUs, `showing 500 of 500 products`,
  no **Load more** at the end. "All vendors" the same way: 503 rows, 503
  distinct, 11 requests.
- **Alerts before #7.** Three more `invalid.csv` imports (5, 6, 7, vendor
  `Incident Check`), then SQL inserts into the Compose db (listed in the
  hand-off comment on #6; not committed): alert `OPEN` on import 3,
  `IN_PROGRESS` on 5, `NEEDS_ATTENTION` on 6, `RESOLVED` on 7, and four
  agent actions on the alert of import 6. With the default
  `AGENT_ENABLED=false`: Open incidents lists the `IN_PROGRESS` and `OPEN`
  rows (API order), each with `automated recovery disabled`; Recent
  incidents lists `RESOLVED` and `NEEDS_ATTENTION` without it (2 occurrences
  on the page). `/imports/6` shows `NEEDS_ATTENTION` and the four actions in
  order with compact JSON results; `/imports/3` shows `OPEN`,
  `automated recovery disabled` and `No agent activity yet`. After
  `AGENT_ENABLED=true docker compose up -d --wait --no-deps app` (health
  `agent_enabled: true`): the text appears nowhere on the dashboard nor on
  `/imports/3`. The app was then restarted with the default again.
- **404.** `/imports/999999` shows `NOT_FOUND: import 999999 not found`;
  `/imports/abc` and `/imports/0` show `NOT_FOUND: no such resource`; each
  with **Back to imports** (`/imports`) and no detail section.
- **375 px.** Each page loaded in a 375 px wide same-origin iframe:
  `innerWidth` 375; document `scrollWidth` 360 on the dashboard and on
  `/imports/6` (a vertical scrollbar takes 15 px) and 375 on Products, so
  no horizontal page scroll. Wide tables scroll inside their box: dashboard
  286 px boxes holding 640 / 653 / 660 px; detail attempts and timeline
  286 px holding 758 / 640 px; products 302 px holding 640 px.