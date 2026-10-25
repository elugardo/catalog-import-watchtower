import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { createImport, errorMessage, type ImportDetail } from "../api/client";
import { ImportStatus } from "../components/ImportStatus";
import { ValidationErrors } from "../components/ValidationErrors";

// Spec F1 + the Upload half of F4. The server is the one source of the upload
// rules (vendor name, file type, size, encoding): nothing here blocks a submit,
// and whatever the server answers is shown.

type Outcome = { kind: "none" } | { kind: "result"; detail: ImportDetail } | { kind: "error"; message: string };

export function Upload() {
  const [vendorName, setVendorName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [inject, setInject] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>({ kind: "none" });
  // A ref, not only `busy`: two clicks in the same tick must still send one request.
  const inFlight = useRef(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setOutcome({ kind: "none" });
    try {
      const detail = await createImport({ vendorName, file, injectTransientFailure: inject });
      setOutcome({ kind: "result", detail });
    } catch (error) {
      setOutcome({ kind: "error", message: errorMessage(error) });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card" aria-labelledby="page-heading">
        <h2 id="page-heading">Upload a catalog</h2>
        <form className="form" onSubmit={onSubmit} autoComplete="off" noValidate>
          <div className="form__field">
            <label htmlFor="vendor-name">Vendor name</label>
            <input
              id="vendor-name"
              name="vendor_name"
              type="text"
              value={vendorName}
              onChange={(event) => setVendorName(event.target.value)}
              aria-describedby="vendor-name-hint"
            />
            <span id="vendor-name-hint" className="muted small">
              1 to 80 characters
            </span>
          </div>

          <div className="form__field">
            <label htmlFor="csv-file">CSV file</label>
            <input
              id="csv-file"
              name="file"
              type="file"
              accept=".csv"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>

          <div className="form__field form__field--check">
            <input
              id="inject-transient-failure"
              name="inject_transient_failure"
              type="checkbox"
              checked={inject}
              onChange={(event) => setInject(event.target.checked)}
              aria-describedby="inject-note"
            />
            <label htmlFor="inject-transient-failure">Demo: fail first attempt with transient storage timeout</label>
            <p id="inject-note" className="muted small form__note">
              This is a synthetic failure injector for the demo, not a real storage outage.
            </p>
          </div>

          <div>
            <button type="submit" disabled={busy}>
              Import
            </button>
            {busy && (
              <span className="muted small" role="status">
                {" "}
                Uploading…
              </span>
            )}
          </div>
        </form>
      </section>

      {outcome.kind === "error" && (
        <p className="card error" role="alert">
          {outcome.message}
        </p>
      )}
      {outcome.kind === "result" && <ImportResult detail={outcome.detail} />}
    </>
  );
}

function ImportResult({ detail }: { detail: ImportDetail }) {
  return (
    <section className="card" aria-labelledby="result-heading" data-testid="import-result">
      <h2 id="result-heading">Import result</h2>
      <dl className="facts">
        <dt>Status</dt>
        <dd>
          <ImportStatus item={detail} />
        </dd>
        <dt>Vendor</dt>
        <dd>{detail.vendor.display_name}</dd>
        <dt>Filename</dt>
        <dd>{detail.filename}</dd>
        <dt>Rows</dt>
        <dd>{detail.row_count}</dd>
        <dt>Products</dt>
        <dd>{detail.product_count ?? ""}</dd>
        {detail.failure_code && (
          <>
            <dt>Failure code</dt>
            <dd>{detail.failure_code}</dd>
          </>
        )}
      </dl>

      <ValidationErrors errors={detail.validation_errors} count={detail.validation_error_count} />

      <p>
        <Link to={`/imports/${detail.id}`}>View import {detail.id}</Link>
      </p>
    </section>
  );
}
