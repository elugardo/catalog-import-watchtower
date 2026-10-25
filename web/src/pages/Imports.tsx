import { listImports, type ImportList } from "../api/client";
import { ErrorText } from "../components/ErrorText";
import { ImportTable, NoImports } from "../components/ImportTable";
import { useRequest } from "../components/useRequest";

// Import history (the history part of spec F3). The newest page only, in the
// order the API returns; no paging, sorting, search or filters (spec section 3).
// The page keeps no state of its own: every visit reads the API again.

export function Imports() {
  const state = useRequest(listImports, []);

  return (
    <section className="card" aria-labelledby="page-heading">
      <h2 id="page-heading">Imports</h2>
      {state.kind === "loading" && <p role="status">Loading imports…</p>}
      {state.kind === "error" && <ErrorText message={state.message} />}
      {state.kind === "ready" && <ImportsList list={state.data} />}
    </section>
  );
}

function ImportsList({ list }: { list: ImportList }) {
  if (list.items.length === 0) return <NoImports />;
  return (
    <>
      {list.total > list.items.length && (
        <p className="muted">
          showing the newest {list.items.length} of {list.total} imports
        </p>
      )}
      <ImportTable items={list.items} />
    </>
  );
}
