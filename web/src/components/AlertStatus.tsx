import type { AlertStatus as AlertStatusValue } from "../api/client";

/** The alert statuses the on-call worker has not finished with yet. */
export function isOpenAlert(status: AlertStatusValue): boolean {
  return status === "OPEN" || status === "IN_PROGRESS";
}

export const RECOVERY_DISABLED = "automated recovery disabled";

/**
 * The raw alert status, plus `automated recovery disabled` on an open
 * alert (`OPEN` or `IN_PROGRESS`) when health reports `agent_enabled: false`.
 */
export function AlertStatus({ status, recoveryDisabled }: { status: AlertStatusValue; recoveryDisabled: boolean }) {
  return (
    <span className="status">
      <span className={`status__value status__value--alert-${status.toLowerCase()}`}>{status}</span>
      {recoveryDisabled && isOpenAlert(status) && <span className="label label--warn">{RECOVERY_DISABLED}</span>}
    </span>
  );
}
