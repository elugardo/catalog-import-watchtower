# CIW-04.1 (#5): Upload and Imports UI, 2026-10-25

Rubric row 5 (Application): the frontend connected end to end to the API and
PostgreSQL in the Compose stack.

Commit: branch `fp-5-ui-upload-history`, implementation commit `4c09f3a`
(QA checks out the PR head).

## Steps

1. `docker compose down -v`, then `docker compose up --build -d --wait`
   (fresh volume, `GET /api/imports` -> `{"items":[],"total":0}`).
2. Chrome at `http://localhost:8000/upload`: vendor `<demo vendor>`,
   file `fixtures/valid.csv`, checkbox unchecked, **Import** ->
   `upload-valid.jpg` (COMPLETED, rows 3, products 3, link `/imports/1`).
3. Same form, file `fixtures/invalid.csv` -> `upload-invalid.jpg` (FAILED,
   `VALIDATION_ERROR`, empty products, "1 error",
   `line 4, quantity: must be a whole number of up to 9 digits, got '-2'`,
   link `/imports/2`).
4. Server-side rules exercised from the same page (no client rule blocks a
   submit): empty, whitespace-only and 81-character vendor names ->
   `INVALID_FIELD: vendor_name must be 1 to 80 printable characters`; 80
   characters plus a space on each side with no file ->
   `MISSING_FIELD: file is required`; `notes.txt` ->
   `INVALID_CONTENT_TYPE: file must be a .csv`; a 257 KiB `.csv` ->
   `FILE_TOO_LARGE: CSV exceeds 256 KiB`; a Latin-1 `.csv` ->
   `INVALID_ENCODING: file is not valid UTF-8`. None created a record.
   Then `  <demo vendor>  ` (the same name in lower case, with spaces around it) with `valid.csv`, the checkbox ticked and
   **Import** clicked twice in the same tick: one new import (`total` 2 -> 3),
   shown vendor `<demo vendor>`, `inject_transient_failure: true`,
   status still `COMPLETED` (the fault is #7), and the earlier error cleared.
5. Refresh `/upload`: empty form, checkbox unchecked, no result, `total`
   still 3.
6. `/imports`, browser refresh -> `imports-after-refresh.jpg`: the three
   imports newest first with status, rows and products as uploaded, Created
   as `YYYY-MM-DD HH:MM:SS UTC`.
7. 375 px: each page loaded in a 375 px wide same-origin iframe (the Chrome
   window cannot be made that narrow) -> `upload-375px.png`,
   `imports-375px.png`. Measured in the iframe: `innerWidth` 375 and
   document `scrollWidth` 375 on both pages (no horizontal page scroll); the
   four links end at x = 311; the form ends at x = 338; the table container
   is 302 px wide with 640 px of content (it scrolls inside its own box).
8. Deep links: `/upload`, `/imports`, `/imports/1`, `/nope` answer 200 with
   the SPA on :8000 and under `npm --prefix web run dev` (:5173), and each
   renders its page (the placeholders name CIW-04.2 (#6)).
9. `docker compose stop db`: `/imports` shows `INTERNAL_ERROR: internal error`;
   the footer shows `db error` and **database unreachable**. Then
   `docker compose stop app` with Vite still running: the dev proxy answers
   `500 text/plain`, `/imports` shows `HTTP 500`, the footer shows
   **API unreachable**. After `docker compose up -d --wait` the three imports
   are still listed.