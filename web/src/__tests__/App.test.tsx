import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

function stubHealth(body: unknown, status = 200) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    expect(String(input)).toBe("/api/health");
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App shell", () => {
  it("shows the product name and the health values read from /api/health", async () => {
    const fetchMock = stubHealth({ status: "ok", db: "ok", agent_enabled: false, version: "abc123" });

    render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: "Catalog Import Watchtower" })).toBeInTheDocument();
    expect(await screen.findByTestId("health-status")).toHaveTextContent("ok");
    expect(screen.getByTestId("health-db")).toHaveTextContent("ok");
    expect(screen.getByTestId("health-agent-enabled")).toHaveTextContent("false");
    expect(screen.getByTestId("health-version")).toHaveTextContent("abc123");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows degraded when the database is down", async () => {
    stubHealth({ status: "degraded", db: "error", agent_enabled: true, version: "dev" });

    render(<App />);

    expect(await screen.findByTestId("health-status")).toHaveTextContent("degraded");
    expect(screen.getByTestId("health-db")).toHaveTextContent("error");
    expect(screen.getByTestId("health-agent-enabled")).toHaveTextContent("true");
  });

  it("tells the operator when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("Failed to fetch"); }));

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("API unreachable");
  });
});
