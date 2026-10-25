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

/** What a null timestamp or value shows where a dash is wanted. */
export const DASH = "—";

/** `formatUtc`, or a dash for null. */
export function formatUtcOrDash(iso: string | null): string {
  return iso === null ? DASH : formatUtc(iso);
}

/**
 * Integer cents as dollars, `$1,234.56`, whatever the browser locale. Built
 * from the digits of the integer (whole dollars and the last two digits as
 * cents), never from a division into a float: 5 -> `$0.05`,
 * 999999999999 -> `$9,999,999,999.99`. A value that is not a safe integer
 * is returned as its plain text rather than guessed at.
 */
export function formatPrice(cents: number): string {
  if (!Number.isSafeInteger(cents)) return String(cents);
  const sign = cents < 0 ? "-" : "";
  const digits = String(Math.abs(cents)).padStart(3, "0");
  const dollars = digits.slice(0, -2).replace(/\B(?=(\d{3})+$)/g, ",");
  return `${sign}$${dollars}.${digits.slice(-2)}`;
}

/** "1 error", "3 errors". */
export function errorCountText(count: number): string {
  return count === 1 ? "1 error" : `${count} errors`;
}
