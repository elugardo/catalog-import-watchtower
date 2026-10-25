import type { ReactNode } from "react";
import { useParams } from "react-router-dom";

// Pages delivered by CIW-04.2 (#6). Until then each route shows what will be here.

function Placeholder({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card" aria-labelledby="page-heading">
      <h2 id="page-heading">{title}</h2>
      <p className="muted">{children}</p>
    </section>
  );
}

export function DashboardPlaceholder() {
  return <Placeholder title="Dashboard">The dashboard arrives with CIW-04.2 (#6).</Placeholder>;
}

export function ProductsPlaceholder() {
  return <Placeholder title="Products">The products page arrives with CIW-04.2 (#6).</Placeholder>;
}

export function ImportDetailPlaceholder() {
  const { id } = useParams();
  return (
    <Placeholder title={`Import ${id ?? ""}`}>
      The detail page for import {id} arrives with CIW-04.2 (#6).
    </Placeholder>
  );
}
