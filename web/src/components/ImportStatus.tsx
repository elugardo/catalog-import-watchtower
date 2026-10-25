import type { Import } from "../api/client";

/**
 * The raw status, plus the **Recovered** label exactly when the API says
 * `recovered: true`. The label is never a status and is never derived from
 * counting attempts.
 */
export function ImportStatus({ item }: { item: Pick<Import, "status" | "recovered"> }) {
  return (
    <span className="status">
      <span className={`status__value status__value--${item.status.toLowerCase()}`}>{item.status}</span>
      {item.recovered && <span className="label label--recovered">Recovered</span>}
    </span>
  );
}
