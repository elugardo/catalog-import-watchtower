import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <section className="card" aria-labelledby="page-heading">
      <h2 id="page-heading">Page not found</h2>
      <p>
        <Link to="/">Go to the Dashboard</Link>
      </p>
    </section>
  );
}
