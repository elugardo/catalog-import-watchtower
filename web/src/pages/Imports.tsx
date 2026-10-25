import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, listImports, type ImportList } from "../api/client";
import { ImportStatus } from "../components/ImportStatus";
import { formatUtc } from "../format";

// Import history (the history part of spec F3). The newest page only, in the
// order the API returns; no paging, sorting, search or filters (spec section 3).
// The page keeps no state of its own: every visit reads the API again.

type State = { kind: "loading" } | { kind: "ready"; list: ImportList } | { kind: "error"; message: string };

export function Imports() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    listImports()
      .then((list) => {
        if (!cancelled) setState({ kind: "ready", list });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ kind: "error", message: errorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="card" aria-labelledby="page-heading">
      <h2 id="page-heading">Imports</h2>
      {state.kind === "loading" && <p role="status">Loading imports…</p>}
      {state.kind === "error" && (
        <p className="error" role="alert">
          {state.message}
        </p>
      )}
      {state.kind === "ready" && <ImportsTable list={state.list} />}
    </section>
  );
}

function ImportsTable({ list }: { list: ImportList }) {
  if (list.items.length === 0) {
    return (
      <p>
        No imports yet. <Link to="/upload">Upload a CSV</Link>
      </p>
    );
  }
  return (
    <>
      {list.total > list.items.length && (
        <p className="muted">
          showing the newest {list.items.length} of {list.total} imports
        </p>
      )}
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Vendor</th>
              <th scope="col">Filename</th>
              <th scope="col">Created</th>
              <th scope="col">Status</th>
              <th scope="col">Rows</th>
              <th scope="col">Products</th>
            </tr>
          </thead>
          <tbody>
            {list.items.map((item) => (
              <tr key={item.id}>
                <td>{item.vendor.display_name}</td>
                <td>
                  <Link to={`/imports/${item.id}`}>{item.filename}</Link>
                </td>
                <td className="nowrap">{formatUtc(item.created_at)}</td>
                <td>
                  <ImportStatus item={item} />
                </td>
                <td className="num">{item.row_count}</td>
                <td className="num">{item.product_count ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
