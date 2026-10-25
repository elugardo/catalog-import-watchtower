import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentAction, ValidationError } from "../api/client";
import {
  anAction,
  anAlert,
  anAttempt,
  anImportDetail,
  apiCalls,
  HEALTHY,
  json,
  renderAt,
  stubFetch,
} from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

/** `result` is free-form JSON; the generated type cannot say so. */
function result(value: object): AgentAction["result"] {
  return value as AgentAction["result"];
}

function rowsOf(name: string) {
  return within(screen.getByRole("table", { name })).getAllByRole("row").slice(1);
}

function cells(row: HTMLElement) {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

/** Shape (2): FAILED / VALIDATION_ERROR, 20 of 1000 errors, an OPEN alert. */
function shapeValidation() {
  const errors: ValidationError[] = Array.from({ length: 20 }, (_, index) => ({
    line: index + 2,
    column: "quantity",
    message: `must be a whole number of up to 9 digits, got '-${index}'`,
  }));
  return anImportDetail({
    id: 2,
    filename: "invalid.csv",
    status: "FAILED",
    failure_code: "VALIDATION_ERROR",
    row_count: 1000,
    product_count: null,
    completed_at: null,
    validation_errors: errors,
    validation_error_count: 1000,
    attempts: [anAttempt({ status: "FAILED", error_code: "VALIDATION_ERROR", trace_id: null })],
    alert: anAlert({ status: "OPEN", reason: "import failed: VALIDATION_ERROR" }),
  });
}

/** Shape (4), spec scenario 4: recovered after a transient failure, five agent actions. */
function shapeRecovered() {
  return anImportDetail({
    id: 4,
    filename: "valid.csv",
    status: "COMPLETED",
    recovered: true,
    failure_code: null,
    attempt_count: 2,
    inject_transient_failure: true,
    sha256: "ab".repeat(32),
    attempts: [
      anAttempt({
        number: 1,
        status: "FAILED",
        error_code: "TRANSIENT_STORAGE_TIMEOUT",
        trace_id: "1".repeat(32),
        started_at: "2026-10-24T12:00:00Z",
        finished_at: "2026-10-24T12:00:01Z",
      }),
      anAttempt({
        number: 2,
        status: "SUCCEEDED",
        trace_id: "2".repeat(32),
        started_at: "2026-10-24T12:00:05Z",
        finished_at: "2026-10-24T12:00:06Z",
      }),
    ],
    alert: anAlert({ status: "RESOLVED", reason: "import failed: TRANSIENT_STORAGE_TIMEOUT" }),
    agent_actions: [
      anAction({ id: 1, action: "RUN_STARTED" }),
      anAction({ id: 2, action: "TOOL_CALL", tool_name: "get_import_incident", result: result({ status: "FAILED" }) }),
      anAction({ id: 3, action: "TOOL_CALL", tool_name: "retry_failed_import", result: result({ status: "COMPLETED" }) }),
      anAction({ id: 4, action: "DECISION", reason_summary: "transient failure, retried once" }),
      anAction({ id: 5, action: "RUN_FINISHED", result: result({ outcome: "RESOLVED", attempts: 2 }) }),
    ],
  });
}

describe("Import detail page", () => {
  it("shape (2): lists 20 'line N' errors of 1000 and the open incident", async () => {
    const fetchMock = stubFetch({ "GET /api/imports/2": () => json(shapeValidation()) });

    renderAt("/imports/2");

    const list = await screen.findByRole("list", { name: "Validation errors" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(20);
    expect(items[0]).toHaveTextContent("line 2, quantity: must be a whole number of up to 9 digits, got '-0'");
    expect(screen.getByText("showing 20 of 1000 errors")).toBeInTheDocument();
    expect(screen.getByText("VALIDATION_ERROR", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByTestId("completed-at")).toHaveTextContent("—");
    expect(screen.getByTestId("product-count")).toBeEmptyDOMElement();
    expect(screen.queryByText("Recovered")).not.toBeInTheDocument();
    // A null trace id renders empty, never "null".
    expect(cells(rowsOf("Attempts")[0])[5]).toBe("");

    const incident = screen.getByLabelText("Incident details");
    expect(within(incident).getByText("OPEN")).toBeInTheDocument();
    expect(within(incident).getByText("import failed: VALIDATION_ERROR")).toBeInTheDocument();
    await screen.findByTestId("health-version");
    expect(within(incident).getByText("automated recovery disabled")).toBeInTheDocument();
    expect(screen.getByText("No agent activity yet")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/null|undefined|NaN|Invalid Date/);
    expect(apiCalls(fetchMock).map(([input]) => String(input))).toEqual(["/api/imports/2"]);
  });

  it("shape (2) with exactly 20 errors says '20 errors' and nothing about showing", async () => {
    stubFetch({ "GET /api/imports/2": () => json({ ...shapeValidation(), validation_error_count: 20 }) });

    renderAt("/imports/2");

    expect(await screen.findByText("20 errors")).toBeInTheDocument();
    expect(screen.queryByText(/showing/)).not.toBeInTheDocument();
  });

  it("shape (4): Recovered, both attempts in order, RESOLVED, and the five actions in order", async () => {
    stubFetch({
      "GET /api/imports/4": () => json(shapeRecovered()),
      "GET /api/health": () => json({ ...HEALTHY, agent_enabled: false }),
    });

    renderAt("/imports/4");

    expect(await screen.findByText("Recovered")).toHaveClass("label", "label--recovered");
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
    expect(screen.getByText("ab".repeat(32))).toBeInTheDocument();
    expect(screen.queryByText("Failure code")).not.toBeInTheDocument();
    expect(screen.getByText("Demo failure injected")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Validation errors" })).not.toBeInTheDocument();

    const headers = within(screen.getByRole("table", { name: "Attempts" }))
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual(["Attempt", "Status", "Error code", "Started", "Finished", "Trace id"]);
    const attempts = rowsOf("Attempts");
    expect(attempts.map(cells)).toEqual([
      ["1", "FAILED", "TRANSIENT_STORAGE_TIMEOUT", "2026-10-24 12:00:00 UTC", "2026-10-24 12:00:01 UTC", "1".repeat(32)],
      ["2", "SUCCEEDED", "", "2026-10-24 12:00:05 UTC", "2026-10-24 12:00:06 UTC", "2".repeat(32)],
    ]);
    // The trace id is plain text (linking it is CIW-09.2).
    expect(within(attempts[0]).queryByRole("link")).not.toBeInTheDocument();

    await screen.findByTestId("health-version");
    const incident = screen.getByLabelText("Incident details");
    expect(within(incident).getByText("RESOLVED")).toBeInTheDocument();
    expect(screen.queryByText("automated recovery disabled")).not.toBeInTheDocument();

    const actions = rowsOf("Agent activity");
    expect(actions.map((row) => cells(row)[1])).toEqual([
      "RUN_STARTED",
      "TOOL_CALL",
      "TOOL_CALL",
      "DECISION",
      "RUN_FINISHED",
    ]);
    expect(cells(actions[1])[2]).toBe("get_import_incident");
    expect(cells(actions[2])[2]).toBe("retry_failed_import");
    expect(cells(actions[3])[3]).toBe("transient failure, retried once");
    expect(cells(actions[4])[4]).toBe('{"outcome":"RESOLVED","attempts":2}');
    expect(cells(actions[0])).toEqual(["2026-10-24 12:00:03 UTC", "RUN_STARTED", "", "", ""]);
  });

  it("shape (1): completed without an incident", async () => {
    stubFetch({ "GET /api/imports/1": () => json(anImportDetail({ attempts: [anAttempt()] })) });

    renderAt("/imports/1");

    expect(await screen.findByText("No incident")).toBeInTheDocument();
    expect(screen.getByText("No agent activity")).toBeInTheDocument();
    expect(screen.queryByText("Recovered")).not.toBeInTheDocument();
    expect(screen.queryByText("Demo failure injected")).not.toBeInTheDocument();
    expect(screen.getByTestId("completed-at")).toHaveTextContent("2026-10-24 12:00:01 UTC");
  });

  it("shape (3): a transient failure shows its codes, no errors section, and no agent activity yet", async () => {
    stubFetch({
      "GET /api/imports/3": () =>
        json(
          anImportDetail({
            id: 3,
            status: "FAILED",
            failure_code: "TRANSIENT_STORAGE_TIMEOUT",
            product_count: null,
            completed_at: null,
            inject_transient_failure: true,
            attempts: [anAttempt({ status: "FAILED", error_code: "TRANSIENT_STORAGE_TIMEOUT" })],
            alert: anAlert({ status: "OPEN", reason: "import failed: TRANSIENT_STORAGE_TIMEOUT" }),
          }),
        ),
    });

    renderAt("/imports/3");

    expect(await screen.findByText("TRANSIENT_STORAGE_TIMEOUT", { selector: "dd" })).toBeInTheDocument();
    expect(cells(rowsOf("Attempts")[0])[2]).toBe("TRANSIENT_STORAGE_TIMEOUT");
    expect(screen.queryByRole("heading", { name: "Validation errors" })).not.toBeInTheDocument();
    expect(screen.getByText("No agent activity yet")).toBeInTheDocument();
  });

  it("shape (5): PROCESSING with a RUNNING attempt leaves completed, products and finished empty", async () => {
    stubFetch({
      "GET /api/imports/5": () =>
        json(
          anImportDetail({
            id: 5,
            status: "PROCESSING",
            product_count: null,
            completed_at: null,
            attempts: [anAttempt({ status: "RUNNING", finished_at: null, trace_id: null })],
          }),
        ),
    });

    renderAt("/imports/5");

    expect(await screen.findByText("PROCESSING")).toBeInTheDocument();
    expect(screen.getByTestId("completed-at")).toHaveTextContent("—");
    expect(screen.getByTestId("product-count")).toBeEmptyDOMElement();
    const row = cells(rowsOf("Attempts")[0]);
    expect(row[1]).toBe("RUNNING");
    expect(row[4]).toBe("");
    expect(document.body.textContent).not.toMatch(/null|undefined|NaN|Invalid Date/);
  });

  it("says No attempts for an import without attempts", async () => {
    stubFetch({ "GET /api/imports/7": () => json(anImportDetail({ id: 7 })) });

    renderAt("/imports/7");

    expect(await screen.findByText("No attempts")).toBeInTheDocument();
  });

  it("shows the 404 with a link back to the imports, and no detail section", async () => {
    for (const id of ["999999", "abc", "0"]) {
      stubFetch({
        [`GET /api/imports/${id}`]: () =>
          json({ code: "NOT_FOUND", message: `import ${id} not found`, details: [] }, 404),
      });
      const { unmount } = renderAt(`/imports/${id}`);

      expect(await screen.findByText(`NOT_FOUND: import ${id} not found`)).toHaveAttribute("role", "alert");
      expect(screen.getByRole("link", { name: "Back to imports" })).toHaveAttribute("href", "/imports");
      expect(screen.queryByRole("heading", { name: "Attempts" })).not.toBeInTheDocument();
      expect(screen.queryByText("No incident")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("shows any other failure through the error path and no detail section", async () => {
    for (const [handler, text] of [
      [() => json({ code: "INTERNAL_ERROR", message: "internal error", details: [] }, 500), "INTERNAL_ERROR: internal error"],
      [() => new Response("<html>", { status: 200, headers: { "Content-Type": "text/html" } }), "HTTP 200"],
      [
        () => {
          throw new TypeError("Failed to fetch");
        },
        "API unreachable",
      ],
    ] as const) {
      stubFetch({ "GET /api/imports/1": handler });
      const { unmount } = renderAt("/imports/1");

      expect(await screen.findByText(text, { selector: "main p" })).toHaveAttribute("role", "alert");
      expect(screen.queryByRole("heading", { name: "Attempts" })).not.toBeInTheDocument();
      unmount();
    }
  });

  it("shows timestamps in UTC whatever the browser zone", async () => {
    vi.stubEnv("TZ", "America/Los_Angeles");
    expect(new Date("2026-10-24T23:30:07Z").getTimezoneOffset()).not.toBe(0);
    stubFetch({
      "GET /api/imports/1": () => json(anImportDetail({ created_at: "2026-10-24T23:30:07Z" })),
    });

    renderAt("/imports/1");

    expect(await screen.findByText("2026-10-24 23:30:07 UTC")).toBeInTheDocument();
  });
});
