import { Link, useParams } from "react-router-dom";
import { getImport, type AgentAction, type Alert, type Attempt, type ImportDetail as Detail } from "../api/client";
import { AlertStatus } from "../components/AlertStatus";
import { ErrorText } from "../components/ErrorText";
import { useRecoveryDisabled } from "../components/Health";
import { ImportStatus } from "../components/ImportStatus";
import { useRequest } from "../components/useRequest";
import { ValidationErrors } from "../components/ValidationErrors";
import { formatUtc, formatUtcOrDash } from "../format";

// Spec F3 import detail: the import, its attempts, its validation errors, its
// incident and the on-call agent's timeline, all from one
// `GET /api/imports/{id}`. The id is sent as it appears in the URL; the API
// answers 404 for an unknown or malformed one.

export function ImportDetail() {
  const { id = "" } = useParams();
  const state = useRequest(() => getImport(id), [id]);

  return (
    <>
      <section className="card" aria-labelledby="page-heading">
        <h2 id="page-heading">Import {id}</h2>
        {state.kind === "loading" && <p role="status">Loading import…</p>}
        {state.kind === "error" && (
          <>
            <ErrorText message={state.message} />
            <p>
              <Link to="/imports">Back to imports</Link>
            </p>
          </>
        )}
        {state.kind === "ready" && <Header detail={state.data} />}
      </section>
      {state.kind === "ready" && <Sections detail={state.data} />}
    </>
  );
}

function Header({ detail }: { detail: Detail }) {
  return (
    <>
      <dl className="facts" aria-label="Import">
        <dt>Status</dt>
        <dd>
          <ImportStatus item={detail} />
        </dd>
        <dt>Vendor</dt>
        <dd>{detail.vendor.display_name}</dd>
        <dt>Filename</dt>
        <dd>{detail.filename}</dd>
        <dt>SHA-256</dt>
        <dd>
          <code>{detail.sha256}</code>
        </dd>
        <dt>Created</dt>
        <dd>{formatUtc(detail.created_at)}</dd>
        <dt>Completed</dt>
        <dd data-testid="completed-at">{formatUtcOrDash(detail.completed_at)}</dd>
        <dt>Rows</dt>
        <dd>{detail.row_count}</dd>
        <dt>Products</dt>
        <dd data-testid="product-count">{detail.product_count ?? ""}</dd>
        {detail.failure_code !== null && (
          <>
            <dt>Failure code</dt>
            <dd>{detail.failure_code}</dd>
          </>
        )}
      </dl>
      {detail.inject_transient_failure && (
        <p className="muted small">
          <span className="label label--warn">Demo failure injected</span> The synthetic failure injector was
          requested for this import; it is not a real storage outage.
        </p>
      )}
    </>
  );
}

function Sections({ detail }: { detail: Detail }) {
  return (
    <>
      {detail.validation_error_count > 0 && (
        <section className="card" aria-labelledby="errors-heading">
          <h2 id="errors-heading">Validation errors</h2>
          <ValidationErrors errors={detail.validation_errors} count={detail.validation_error_count} />
        </section>
      )}

      <section className="card" aria-labelledby="attempts-heading">
        <h2 id="attempts-heading">Attempts</h2>
        <Attempts attempts={detail.attempts} />
      </section>

      <section className="card" aria-labelledby="incident-heading">
        <h2 id="incident-heading">Incident</h2>
        <Incident alert={detail.alert} />
      </section>

      <section className="card" aria-labelledby="timeline-heading">
        <h2 id="timeline-heading">Agent activity</h2>
        <Timeline actions={detail.agent_actions} hasAlert={detail.alert !== null} />
      </section>
    </>
  );
}

function Attempts({ attempts }: { attempts: Attempt[] }) {
  if (attempts.length === 0) return <p className="muted">No attempts</p>;
  return (
    <div className="table-scroll">
      <table className="table" aria-label="Attempts">
        <thead>
          <tr>
            <th scope="col">Attempt</th>
            <th scope="col">Status</th>
            <th scope="col">Error code</th>
            <th scope="col">Started</th>
            <th scope="col">Finished</th>
            <th scope="col">Trace id</th>
          </tr>
        </thead>
        <tbody>
          {attempts.map((attempt) => (
            <tr key={attempt.number}>
              <td className="num">{attempt.number}</td>
              <td>
                <span className="status__value">{attempt.status}</span>
              </td>
              <td>{attempt.error_code ?? ""}</td>
              <td className="nowrap">{formatUtc(attempt.started_at)}</td>
              <td className="nowrap">{attempt.finished_at === null ? "" : formatUtc(attempt.finished_at)}</td>
              <td>
                {/* Plain text; linking it to Grafana is CIW-09.2. */}
                <code className="small">{attempt.trace_id ?? ""}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Incident({ alert }: { alert: Alert | null }) {
  const recoveryDisabled = useRecoveryDisabled();
  if (alert === null) return <p className="muted">No incident</p>;
  return (
    <dl className="facts" aria-label="Incident details">
      <dt>Status</dt>
      <dd>
        <AlertStatus status={alert.status} recoveryDisabled={recoveryDisabled} />
      </dd>
      <dt>Reason</dt>
      <dd>{alert.reason}</dd>
      <dt>Created</dt>
      <dd>{formatUtc(alert.created_at)}</dd>
    </dl>
  );
}

function Timeline({ actions, hasAlert }: { actions: AgentAction[]; hasAlert: boolean }) {
  if (actions.length === 0) {
    return <p className="muted">{hasAlert ? "No agent activity yet" : "No agent activity"}</p>;
  }
  return (
    <div className="table-scroll">
      <table className="table" aria-label="Agent activity">
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Action</th>
            <th scope="col">Tool</th>
            <th scope="col">Reason</th>
            <th scope="col">Result</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((action) => (
            <tr key={action.id}>
              <td className="nowrap">{formatUtc(action.created_at)}</td>
              <td>
                <span className="status__value">{action.action}</span>
              </td>
              <td>{action.tool_name ?? ""}</td>
              <td>{action.reason_summary ?? ""}</td>
              <td>
                <code className="small json">{action.result === null ? "" : JSON.stringify(action.result)}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
