// Shared display formatters (CIW-04.1; CIW-04.2 reuses them).

/**
 * An API timestamp (ISO-8601, UTC) as `YYYY-MM-DD HH:MM:SS UTC`, always in
 * UTC and never in the browser's zone. Unparseable input is returned as is.
 */
export function formatUtc(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const text = date.toISOString(); // 2026-10-24T12:00:00.000Z
  return `${text.slice(0, 10)} ${text.slice(11, 19)} UTC`;
}

/** "1 error", "3 errors". */
export function errorCountText(count: number): string {
  return count === 1 ? "1 error" : `${count} errors`;
}
