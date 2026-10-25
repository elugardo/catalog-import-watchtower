import { Link } from "react-router-dom";
import type { Import } from "../api/client";
import { formatUtc } from "../format";
import { ImportStatus } from "./ImportStatus";

/** The imports table of the Imports page and the dashboard, in the order given. */
export function ImportTable({ items, label }: { items: Import[]; label?: string }) {
  return (
    <div className="table-scroll">
      <table className="table" aria-label={label}>
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
          {items.map((item) => (
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
  );
}

/** The empty state of an import list. */
export function NoImports() {
  return (
    <p>
      No imports yet. <Link to="/upload">Upload a CSV</Link>
    </p>
  );
}
