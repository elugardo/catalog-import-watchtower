import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { errorMessage, getHealth, type Health } from "../api/client";

// The shell's one `GET /api/health` request, shared: the footer shows it and
// the pages read `agent_enabled` from it, so no page asks for health again.

export type HealthState =
  | { kind: "loading" }
  | { kind: "ready"; health: Health }
  | { kind: "failed"; message: string };

const HealthContext = createContext<HealthState>({ kind: "loading" });

export function HealthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((health) => {
        if (!cancelled) setState({ kind: "ready", health });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ kind: "failed", message: errorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <HealthContext.Provider value={state}>{children}</HealthContext.Provider>;
}

export function useHealth(): HealthState {
  return useContext(HealthContext);
}

/**
 * True only when health answered `agent_enabled: false`. While health is
 * loading or has failed nothing is claimed (the footer says API unreachable).
 */
export function useRecoveryDisabled(): boolean {
  const state = useHealth();
  return state.kind === "ready" && !state.health.agent_enabled;
}

export function HealthReadout() {
  const state = useHealth();

  if (state.kind === "loading") {
    return <p className="health">Checking API health…</p>;
  }
  if (state.kind === "failed") {
    // Whatever went wrong with the health request itself, the API is not usable.
    return (
      <p className="health health--bad" role="alert" data-testid="health-unreachable">
        API unreachable
      </p>
    );
  }
  const { health } = state;
  return (
    <p className="health">
      <span>
        version <code data-testid="health-version">{health.version}</code>
      </span>
      <span>
        db{" "}
        <code data-testid="health-db" data-value={health.db}>
          {health.db}
        </code>
      </span>
      {health.db === "error" && (
        <span className="health--bad" role="alert">
          database unreachable
        </span>
      )}
    </p>
  );
}
