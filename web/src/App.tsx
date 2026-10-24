import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "./api";

type HealthState =
  | { kind: "loading" }
  | { kind: "ready"; health: Health }
  | { kind: "unreachable"; message: string };

export function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((health) => {
        if (!cancelled) setState({ kind: "ready", health });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ kind: "unreachable", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="shell">
      <header className="shell__header">
        <h1>Catalog Import Watchtower</h1>
        <p className="shell__tagline">
          Vendor CSV imports, validated whole-file and written in one transaction, with an on-call
          agent watching the failures.
        </p>
      </header>

      <section className="card" aria-labelledby="health-heading">
        <h2 id="health-heading">API health</h2>
        {state.kind === "loading" && <p role="status">Checking /api/health…</p>}
        {state.kind === "unreachable" && (
          <p role="alert">API unreachable: {state.message}</p>
        )}
        {state.kind === "ready" && <HealthTable health={state.health} />}
      </section>

      <p className="shell__note">
        Pages for uploads, imports, products and alerts arrive with CIW-04.1 and CIW-04.2.
      </p>
    </main>
  );
}

function HealthTable({ health }: { health: Health }) {
  return (
    <dl className="health">
      <div className="health__row">
        <dt>status</dt>
        <dd data-testid="health-status" data-value={health.status}>
          {health.status}
        </dd>
      </div>
      <div className="health__row">
        <dt>db</dt>
        <dd data-testid="health-db" data-value={health.db}>
          {health.db}
        </dd>
      </div>
      <div className="health__row">
        <dt>agent_enabled</dt>
        <dd data-testid="health-agent-enabled">{String(health.agent_enabled)}</dd>
      </div>
      <div className="health__row">
        <dt>version</dt>
        <dd data-testid="health-version">{health.version}</dd>
      </div>
    </dl>
  );
}
