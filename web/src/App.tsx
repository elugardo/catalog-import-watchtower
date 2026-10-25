import { NavLink, Route, Routes } from "react-router-dom";
import { HealthProvider, HealthReadout } from "./components/Health";
import { Dashboard } from "./pages/Dashboard";
import { ImportDetail } from "./pages/ImportDetail";
import { Imports } from "./pages/Imports";
import { NotFound } from "./pages/NotFound";
import { Products } from "./pages/Products";
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
    <HealthProvider>
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
            <Route path="/" element={<Dashboard />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/imports" element={<Imports />} />
            <Route path="/imports/:id" element={<ImportDetail />} />
            <Route path="/products" element={<Products />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>

        <footer className="shell__footer">
          <HealthReadout />
        </footer>
      </div>
    </HealthProvider>
  );
}
