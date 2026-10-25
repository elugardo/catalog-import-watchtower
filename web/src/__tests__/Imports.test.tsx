import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { formatUtc } from "../format";
import { anImport, apiCalls, json, renderAt, stubFetch } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Imports page", () => {
  it("shows Recovered only on the recovered: true row", async () => {
    const fetchMock = stubFetch({
      "GET /api/imports": () =>
        json({
          items: [
            anImport({ id: 3, filename: "recovered.csv", attempt_count: 2, recovered: true }),
            anImport({
              id: 2,
              filename: "failed-twice.csv",
              status: "FAILED",
              failure_code: "TRANSIENT_STORAGE_TIMEOUT",
              attempt_count: 2,
              product_count: null,
              recovered: false,
            }),
            anImport({ id: 1, filename: "plain.csv", attempt_count: 2, recovered: false }),
          ],
          total: 3,
        }),
    });

    renderAt("/imports");

    const table = await screen.findByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers).toEqual(["Vendor", "Filename", "Created", "Status", "Rows", "Products"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getByRole("link").getAttribute("href"))).toEqual([
      "/imports/3",
      "/imports/2",
      "/imports/1",
    ]);
    expect(within(rows[0]).getByText("Recovered")).toBeInTheDocument();
    expect(within(rows[1]).queryByText("Recovered")).not.toBeInTheDocument();
    expect(within(rows[1]).getByText("FAILED")).toBeInTheDocument();
    expect(within(rows[2]).queryByText("Recovered")).not.toBeInTheDocument();
    expect(within(rows[0]).getByText("2026-10-24 12:00:00 UTC")).toBeInTheDocument();
    expect(screen.getAllByText("Recovered")).toHaveLength(1);
    expect(screen.queryByText(/showing the newest/)).not.toBeInTheDocument();
    expect(apiCalls(fetchMock)[0][0]).toBe("/api/imports");
  });

  it("shows the empty state for an empty list", async () => {
    stubFetch({ "GET /api/imports": () => json({ items: [], total: 0 }) });

    renderAt("/imports");

    expect(screen.getByRole("status")).toHaveTextContent("Loading imports");
    expect(await screen.findByText("No imports yet.", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload a CSV" })).toHaveAttribute("href", "/upload");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says how many are shown when total is above the page", async () => {
    stubFetch({ "GET /api/imports": () => json({ items: [anImport()], total: 120 }) });

    renderAt("/imports");

    expect(await screen.findByText("showing the newest 1 of 120 imports")).toBeInTheDocument();
  });

  it("renders the 500 the list returns while the database is down", async () => {
    stubFetch({
      "GET /api/imports": () => json({ code: "INTERNAL_ERROR", message: "internal error", details: [] }, 500),
    });

    renderAt("/imports");

    expect(await screen.findByText("INTERNAL_ERROR: internal error")).toHaveAttribute("role", "alert");
  });
});

describe("formatUtc", () => {
  it("renders UTC with an explicit suffix, never the browser zone", () => {
    expect(formatUtc("2026-10-24T12:00:00Z")).toBe("2026-10-24 12:00:00 UTC");
    expect(formatUtc("2026-10-24T23:59:59.900Z")).toBe("2026-10-24 23:59:59 UTC");
  });
});
