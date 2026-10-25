import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type {
  AgentAction,
  Alert,
  AlertListItem,
  Attempt,
  Health,
  Import,
  ImportDetail,
  Product,
} from "../api/client";
import { App, ROUTER_FUTURE } from "../App";

// Test helpers: `fetch` is always stubbed (no network). Not a test file itself.

export type Handler = (url: string, init: RequestInit | undefined) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export const HEALTHY: Health = { status: "ok", db: "ok", agent_enabled: false, version: "test-sha" };

/**
 * Stub `fetch`. `/api/health` answers HEALTHY unless `routes` overrides it;
 * every other URL must be in `routes` (keyed by `METHOD url`), or the test fails.
 */
export function stubFetch(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const key = `${init?.method ?? "GET"} ${url}`;
    const handler = routes[key] ?? (key === "GET /api/health" ? () => json(HEALTHY) : undefined);
    if (!handler) throw new Error(`unexpected request ${key}`);
    return handler(url, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The requests made, minus the shell's health check. */
export function apiCalls(fetchMock: ReturnType<typeof stubFetch>) {
  return fetchMock.mock.calls.filter(([input]) => String(input) !== "/api/health");
}

export function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
      <App />
    </MemoryRouter>,
  );
}

export function anImport(overrides: Partial<Import> = {}): Import {
  return {
    id: 1,
    vendor: { id: 1, display_name: "Sample Furnishings" },
    filename: "valid.csv",
    sha256: "0".repeat(64),
    row_count: 3,
    product_count: 3,
    status: "COMPLETED",
    failure_code: null,
    validation_errors: [],
    validation_error_count: 0,
    inject_transient_failure: false,
    attempt_count: 1,
    recovered: false,
    created_at: "2026-10-24T12:00:00Z",
    completed_at: "2026-10-24T12:00:01Z",
    ...overrides,
  };
}

export function anImportDetail(overrides: Partial<ImportDetail> = {}): ImportDetail {
  return { ...anImport(), attempts: [], alert: null, agent_actions: [], ...overrides };
}

export function anAttempt(overrides: Partial<Attempt> = {}): Attempt {
  return {
    number: 1,
    status: "SUCCEEDED",
    error_code: null,
    trace_id: "4bf92f3577b34da6a3ce929d0e0e4736",
    started_at: "2026-10-24T12:00:00Z",
    finished_at: "2026-10-24T12:00:01Z",
    ...overrides,
  };
}

export function anAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    status: "OPEN",
    reason: "import failed: VALIDATION_ERROR",
    claimed_at: null,
    created_at: "2026-10-24T12:00:02Z",
    updated_at: "2026-10-24T12:00:02Z",
    ...overrides,
  };
}

export function anAlertListItem(overrides: Partial<AlertListItem> = {}): AlertListItem {
  return {
    ...anAlert(),
    import_id: 2,
    import_status: "FAILED",
    failure_code: "VALIDATION_ERROR",
    vendor_display_name: "Sample Furnishings",
    filename: "invalid.csv",
    ...overrides,
  };
}

export function anAction(overrides: Partial<AgentAction> = {}): AgentAction {
  return {
    id: 1,
    action: "RUN_STARTED",
    tool_name: null,
    reason_summary: null,
    result: null,
    created_at: "2026-10-24T12:00:03Z",
    ...overrides,
  };
}

export function aProduct(overrides: Partial<Product> = {}): Product {
  return {
    id: 1,
    vendor_id: 1,
    sku: "SF-001",
    name: "Oak chair",
    price_cents: 14999,
    quantity: 8,
    updated_at: "2026-10-24T12:00:01Z",
    ...overrides,
  };
}

/** A promise with its resolve handle, to hold a stubbed response back. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
