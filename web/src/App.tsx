import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { errorMessage, getHealth, type Health } from "./api/client";
import { Imports } from "./pages/Imports";
import { NotFound } from "./pages/NotFound";
import { DashboardPlaceholder, ImportDetailPlaceholder, ProductsPlaceholder } from "./pages/Placeholders";
import { Upload } from "./pages/Upload";

/** Opt in to React Router v7 behaviour now (silences the v6 future-flag warnings). */
export const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/upload", label: "Upload", end: false },
  { to: "/imports", label: "Imports", end: false },
  { to: "/products", label: "Products", end: false },
] as const;

/** The shell: header with the four links, the page, and the health readout. Needs a router around it. */
export function App() {
  return (
    <div className="shell">
      <header className="shell__header">
        <h1>Catalog Import Watchtower</h1>
        <nav aria-label="Main" className="nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className="nav__link">
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="shell__main">
        <Routes>
          <Route path="/" element={<DashboardPlaceholder />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/imports" element={<Imports />} />
          <Route path="/imports/:id" element={<ImportDetailPlaceholder />} />
          <Route path="/products" element={<ProductsPlaceholder />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="shell__footer">
        <HealthReadout />
      </footer>
    </div>
  );
}

type HealthState =
  | { kind: "loading" }
  | { kind: "ready"; health: Health }
  | { kind: "failed"; message: string };

function HealthReadout() {
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
