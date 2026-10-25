import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AlertListItem, Import } from "../api/client";
import { anAlertListItem, anImport, apiCalls, HEALTHY, json, renderAt, stubFetch, type Handler } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

const IMPORTS = "GET /api/imports?limit=100";
const ALERTS = "GET /api/alerts?limit=100";

/** The groom's mixed list: 2 completed, 1 recovered, 2 failed (1 and 2 attempts), 1 processing. */
function mixedImports(): Import[] {
  return [
    anImport({ id: 6, filename: "processing.csv", status: "PROCESSING", completed_at: null, product_count: null }),
    anImport({
      id: 5,
      filename: "failed-twice.csv",
      status: "FAILED",
      failure_code: "TRANSIENT_STORAGE_TIMEOUT",
      attempt_count: 2,
      completed_at: null,
      product_count: null,
    }),
    anImport({
      id: 4,
      filename: "invalid.csv",
      status: "FAILED",
      failure_code: "VALIDATION_ERROR",
      completed_at: null,
      product_count: null,
    }),
    anImport({ id: 3, filename: "recovered.csv", attempt_count: 2, recovered: true }),
    anImport({ id: 2, filename: "update.csv" }),
    anImport({ id: 1, filename: "valid.csv" }),
  ];
}

/** One alert in each of the four statuses, newest first. */
function fourAlerts(): AlertListItem[] {
  return [
    anAlertListItem({ id: 4, import_id: 14, filename: "open.csv", status: "OPEN", reason: "reason open" }),
    anAlertListItem({ id: 3, import_id: 13, filename: "in-progress.csv", status: "IN_PROGRESS" }),
    anAlertListItem({ id: 2, import_id: 12, filename: "needs-attention.csv", status: "NEEDS_ATTENTION" }),
    anAlertListItem({ id: 1, import_id: 11, filename: "resolved.csv", status: "RESOLVED" }),
  ];
}

function stub(routes: { imports?: Handler; alerts?: Handler; health?: Handler } = {}) {
  return stubFetch({
    [IMPORTS]: routes.imports ?? (() => json({ items: mixedImports(), total: 6 })),
    [ALERTS]: routes.alerts ?? (() => json({ items: fourAlerts(), total: 4 })),
    ...(routes.health ? { "GET /api/health": routes.health } : {}),
  });
}

function count(label: string) {
  return screen.getByRole("definition", { name: label });
}

function rowsOf(name: string) {
  return within(screen.getByRole("table", { name })).getAllByRole("row").slice(1);
}

describe("Dashboard", () => {
  it("sends one imports and one alerts request and counts 2 / 1 / 2 over the mixed list", async () => {
    const fetchMock = stub();

    renderAt("/");

    expect(await screen.findByRole("definition", { name: "Completed" })).toHaveTextContent("2");
    expect(count("Recovered")).toHaveTextContent("1");
    expect(count("Failed")).toHaveTextContent("2");
    expect(screen.queryByText(/counts cover/)).not.toBeInTheDocument();

    // The newest-imports table: API order, the Imports page's columns, the Recovered label.
    const rows = rowsOf("Newest imports");
    expect(rows.map((row) => within(row).getByRole("link").getAttribute("href"))).toEqual([
      "/imports/6",
      "/imports/5",
      "/imports/4",
      "/imports/3",
      "/imports/2",
      "/imports/1",
    ]);
    const headers = within(screen.getByRole("table", { name: "Newest imports" }))
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual(["Vendor", "Filename", "Created", "Status", "Rows", "Products"]);
    expect(within(rows[3]).getByText("Recovered")).toHaveClass("label--recovered");
    expect(screen.queryByRole("link", { name: "All imports" })).not.toBeInTheDocument();

    await screen.findByTestId("health-version");
    expect(apiCalls(fetchMock).map(([input]) => String(input))).toEqual([
      "/api/imports?limit=100",
      "/api/alerts?limit=100",
    ]);
  });

  it("takes Recovered only from recovered, never from counting attempts", async () => {
    stub({
      imports: () =>
        json({ items: [anImport({ id: 2, attempt_count: 2, recovered: false }), anImport({ id: 1 })], total: 2 }),
    });

    renderAt("/");

    expect(await screen.findByRole("definition", { name: "Completed" })).toHaveTextContent("2");
    expect(count("Recovered")).toHaveTextContent("0");
    expect(screen.queryByText("Recovered", { selector: ".label" })).not.toBeInTheDocument();
  });

  it("separates open from recent incidents and marks open ones when recovery is disabled", async () => {
    stub();

    renderAt("/");

    await screen.findByTestId("health-version");
    const open = await screen.findByRole("table", { name: "Open incidents" });
    const openRows = within(open).getAllByRole("row").slice(1);
    expect(openRows.map((row) => within(row).getByRole("link").textContent)).toEqual(["open.csv", "in-progress.csv"]);
    expect(within(openRows[0]).getByRole("link")).toHaveAttribute("href", "/imports/14");
    expect(within(openRows[0]).getByText("OPEN")).toBeInTheDocument();
    expect(within(openRows[0]).getByText("Sample Furnishings")).toBeInTheDocument();
    expect(within(openRows[0]).getByText("reason open")).toBeInTheDocument();
    expect(within(openRows[0]).getByText("2026-10-24 12:00:02 UTC")).toBeInTheDocument();
    for (const row of openRows) expect(within(row).getByText("automated recovery disabled")).toBeInTheDocument();

    const recentRows = rowsOf("Recent incidents");
    expect(recentRows.map((row) => within(row).getByRole("link").textContent)).toEqual([
      "needs-attention.csv",
      "resolved.csv",
    ]);
    expect(within(screen.getByRole("table", { name: "Recent incidents" })).queryByText(/automated recovery/)).toBeNull();
    expect(screen.getAllByText("automated recovery disabled")).toHaveLength(2);
  });

  it("never says automated recovery disabled when agent_enabled is true or health fails", async () => {
    stub({ health: () => json({ ...HEALTHY, agent_enabled: true }) });
    const { unmount } = renderAt("/");
    await screen.findByTestId("health-version");
    await screen.findByRole("table", { name: "Open incidents" });
    expect(screen.queryByText(/automated recovery disabled/)).not.toBeInTheDocument();
    unmount();

    stub({ health: () => json({ code: "INTERNAL_ERROR", message: "internal error", details: [] }, 500) });
    renderAt("/");
    await screen.findByTestId("health-unreachable");
    await screen.findByRole("table", { name: "Open incidents" });
    expect(screen.queryByText(/automated recovery disabled/)).not.toBeInTheDocument();
  });

  it("shows the empty states with no imports and no alerts", async () => {
    stub({ imports: () => json({ items: [], total: 0 }), alerts: () => json({ items: [], total: 0 }) });

    renderAt("/");

    expect(await screen.findByRole("definition", { name: "Completed" })).toHaveTextContent("0");
    expect(count("Recovered")).toHaveTextContent("0");
    expect(count("Failed")).toHaveTextContent("0");
    expect(screen.getByText("No imports yet.", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload a CSV" })).toHaveAttribute("href", "/upload");
    expect(await screen.findByText("No open incidents")).toBeInTheDocument();
    expect(screen.getByText("No recent incidents")).toBeInTheDocument();
  });

  it("says the counts cover the newest 100 when total is above 100, and shows the first 10", async () => {
    const items = Array.from({ length: 100 }, (_, index) => anImport({ id: 137 - index, filename: `f${137 - index}.csv` }));
    stub({ imports: () => json({ items, total: 137 }) });

    renderAt("/");

    expect(await screen.findByText("counts cover the newest 100 of 137 imports")).toBeInTheDocument();
    expect(count("Completed")).toHaveTextContent("100");
    const rows = rowsOf("Newest imports");
    expect(rows).toHaveLength(10);
    expect(within(rows[0]).getByRole("link")).toHaveAttribute("href", "/imports/137");
    expect(within(rows[9]).getByRole("link")).toHaveAttribute("href", "/imports/128");
    expect(screen.getByRole("link", { name: "All imports" })).toHaveAttribute("href", "/imports");
  });

  it("shows no more than 10 recent incidents", async () => {
    const alerts = Array.from({ length: 12 }, (_, index) =>
      anAlertListItem({ id: 12 - index, filename: `r${12 - index}.csv`, status: index % 2 ? "RESOLVED" : "NEEDS_ATTENTION" }),
    );
    stub({ alerts: () => json({ items: alerts, total: 12 }) });

    renderAt("/");

    await screen.findByRole("table", { name: "Recent incidents" });
    const rows = rowsOf("Recent incidents");
    expect(rows).toHaveLength(10);
    expect(within(rows[0]).getByRole("link")).toHaveTextContent("r12.csv");
    expect(screen.getByText("No open incidents")).toBeInTheDocument();
  });

  it("renders each area on its own when the other request fails", async () => {
    const failure = () => json({ code: "INTERNAL_ERROR", message: "internal error", details: [] }, 500);
    stub({ alerts: failure });
    const { unmount } = renderAt("/");

    expect(await screen.findByRole("definition", { name: "Failed" })).toHaveTextContent("2");
    expect(screen.getByRole("table", { name: "Newest imports" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("INTERNAL_ERROR: internal error")).toHaveLength(2));
    expect(screen.queryByRole("table", { name: "Open incidents" })).not.toBeInTheDocument();
    unmount();

    stub({
      imports: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    renderAt("/");
    expect(await screen.findByRole("table", { name: "Open incidents" })).toBeInTheDocument();
    expect(screen.getAllByText("API unreachable").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole("definition", { name: "Completed" })).not.toBeInTheDocument();
  });

  it("shows a loading text in each area while its request is pending", async () => {
    stub({ imports: () => new Promise<Response>(() => {}), alerts: () => new Promise<Response>(() => {}) });

    renderAt("/");

    expect(screen.getAllByText("Loading imports…")).toHaveLength(2);
    expect(screen.getAllByText("Loading incidents…")).toHaveLength(2);
    await screen.findByTestId("health-version");
  });
});
