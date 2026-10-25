import type { ValidationError } from "../api/client";
import { errorCountText } from "../format";

/**
 * The validation findings of one import: the count line, then one item per
 * error as `line N, column: message`. Nothing when the count is 0.
 */
export function ValidationErrors({ errors, count }: { errors: ValidationError[]; count: number }) {
  if (count <= 0) return null;
  const shown = errors.length;
  return (
    <div className="validation">
      <p>{count > shown ? `showing ${shown} of ${count} errors` : errorCountText(count)}</p>
      <ul aria-label="Validation errors">
        {errors.map((error, index) => (
          <li key={index}>
            line {error.line}, {error.column}: {error.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
