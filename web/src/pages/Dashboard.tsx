import { Link } from "react-router-dom";
import { listAlerts, listNewestImports, type AlertListItem, type Import, type ImportList } from "../api/client";
import { AlertStatus, isOpenAlert } from "../components/AlertStatus";
import { ErrorText } from "../components/ErrorText";
import { useRecoveryDisabled } from "../components/Health";
import { ImportTable, NoImports } from "../components/ImportTable";
import { useRequest } from "../components/useRequest";
import { formatUtc } from "../format";

// Spec F3 dashboard. Exactly one `GET /api/imports?limit=100` and one
// `GET /api/alerts?limit=100` per visit (plus the shell's health check);
// nothing pages further. Counts are computed over that one imports response
// and say so when there are more imports than it holds.

export const DASHBOARD_LIMIT = 100;
const NEWEST_SHOWN = 10;
const RECENT_SHOWN = 10;

export function Dashboard() {
  const imports = useRequest(() => listNewestImports(DASHBOARD_LIMIT), []);
  const alerts = useRequest(() => listAlerts(DASHBOARD_LIMIT), []);

  return (
    <>
      <section className="card" aria-labelledby="page-heading">
        <h2 id="page-heading">Dashboard</h2>
        {imports.kind === "loading" && <p role="status">Loading imports…</p>}
        {imports.kind === "error" && <ErrorText message={imports.message} />}
        {imports.kind === "ready" && <Counts list={imports.data} />}
      </section>

      <section className="card" aria-labelledby="newest-heading">
        <h2 id="newest-heading">Newest imports</h2>
        {imports.kind === "loading" && <p role="status">Loading imports…</p>}
        {imports.kind === "error" && <ErrorText message={imports.message} />}
        {imports.kind === "ready" && <NewestImports list={imports.data} />}
      </section>

      <section className="card" aria-labelledby="open-heading">
        <h2 id="open-heading">Open incidents</h2>
        {alerts.kind === "loading" && <p role="status">Loading incidents…</p>}
        {alerts.kind === "error" && <ErrorText message={alerts.message} />}
        {alerts.kind === "ready" && (
          <Incidents
            label="Open incidents"
            items={alerts.data.items.filter((alert) => isOpenAlert(alert.status))}
            empty="No open incidents"
          />
        )}
      </section>

      <section className="card" aria-labelledby="recent-heading">
        <h2 id="recent-heading">Recent incidents</h2>
        {alerts.kind === "loading" && <p role="status">Loading incidents…</p>}
        {alerts.kind === "error" && <ErrorText message={alerts.message} />}
        {alerts.kind === "ready" && (
          <Incidents
            label="Recent incidents"
            items={alerts.data.items.filter((alert) => !isOpenAlert(alert.status)).slice(0, RECENT_SHOWN)}
            empty="No recent incidents"
          />
        )}
      </section>
    </>
  );
}

/** Completed, Recovered and Failed never overlap; PROCESSING is in none. */
export function countImports(items: Import[]) {
  let completed = 0;
  let recovered = 0;
  let failed = 0;
  for (const item of items) {
    if (item.status === "COMPLETED") {
      if (item.recovered) recovered += 1;
      else completed += 1;
    } else if (item.status === "FAILED") {
      failed += 1;
    }
  }
  return { completed, recovered, failed };
}

function Counts({ list }: { list: ImportList }) {
  const counts = countImports(list.items);
  const tiles = [
    { key: "completed", label: "Completed", value: counts.completed },
    { key: "recovered", label: "Recovered", value: counts.recovered },
    { key: "failed", label: "Failed", value: counts.failed },
  ];
  return (
    <>
      <dl className="counts">
        {tiles.map((tile) => (
          <div key={tile.key} className={`counts__tile counts__tile--${tile.key}`}>
            <dt id={`count-${tile.key}`}>{tile.label}</dt>
            <dd aria-labelledby={`count-${tile.key}`}>{tile.value}</dd>
          </div>
        ))}
      </dl>
      {list.total > DASHBOARD_LIMIT && (
        <p className="muted small">
          counts cover the newest {list.items.length} of {list.total} imports
        </p>
      )}
    </>
  );
}

function NewestImports({ list }: { list: ImportList }) {
  if (list.items.length === 0) return <NoImports />;
  return (
    <>
      <ImportTable items={list.items.slice(0, NEWEST_SHOWN)} label="Newest imports" />
      {list.total > NEWEST_SHOWN && (
        <p>
          <Link to="/imports">All imports</Link>
        </p>
      )}
    </>
  );
}

function Incidents({ label, items, empty }: { label: string; items: AlertListItem[]; empty: string }) {
  const recoveryDisabled = useRecoveryDisabled();
  if (items.length === 0) return <p className="muted">{empty}</p>;
  return (
    <div className="table-scroll">
      <table className="table" aria-label={label}>
        <thead>
          <tr>
            <th scope="col">Filename</th>
            <th scope="col">Vendor</th>
            <th scope="col">Status</th>
            <th scope="col">Reason</th>
            <th scope="col">Created</th>
          </tr>
        </thead>
        <tbody>
          {items.map((alert) => (
            <tr key={alert.id}>
              <td>
                <Link to={`/imports/${alert.import_id}`}>{alert.filename}</Link>
              </td>
              <td>{alert.vendor_display_name}</td>
              <td>
                <AlertStatus status={alert.status} recoveryDisabled={recoveryDisabled} />
              </td>
              <td>{alert.reason}</td>
              <td className="nowrap">{formatUtc(alert.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
