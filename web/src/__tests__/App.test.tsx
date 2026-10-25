import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, renderAt, stubFetch } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App shell", () => {
  it("shows the four navigation links in order and marks the current page", async () => {
    stubFetch({ "GET /api/imports": () => json({ items: [], total: 0 }) });

    renderAt("/imports");

    expect(screen.getByRole("heading", { level: 1, name: "Catalog Import Watchtower" })).toBeInTheDocument();
    const links = within(screen.getByRole("navigation", { name: "Main" })).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Dashboard", "Upload", "Imports", "Products"]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/", "/upload", "/imports", "/products"]);
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([null, null, "page", null]);
    expect(await screen.findByText("No imports yet.", { exact: false })).toBeInTheDocument();
  });

  it("shows version and db from /api/health in the footer", async () => {
    const fetchMock = stubFetch({});

    renderAt("/");

    expect(await screen.findByTestId("health-version")).toHaveTextContent("test-sha");
    expect(screen.getByTestId("health-db")).toHaveTextContent("ok");
    expect(screen.queryByText("database unreachable")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/health", expect.anything());
  });

  it("says database unreachable when db is error", async () => {
    stubFetch({
      "GET /api/health": () => json({ status: "degraded", db: "error", agent_enabled: true, version: "dev" }),
    });

    renderAt("/");

    expect(await screen.findByText("database unreachable")).toBeInTheDocument();
    expect(screen.getByTestId("health-db")).toHaveTextContent("error");
  });

  it("says API unreachable when the health request fails", async () => {
    stubFetch({
      "GET /api/health": () => {
        throw new TypeError("Failed to fetch");
      },
    });

    renderAt("/");

    expect(await screen.findByTestId("health-unreachable")).toHaveTextContent("API unreachable");
  });

  it("renders placeholders naming CIW-04.2 and a not-found page", async () => {
    stubFetch({});

    for (const [path, heading] of [
      ["/", "Dashboard"],
      ["/products", "Products"],
      ["/imports/12", "Import 12"],
    ]) {
      const { unmount } = renderAt(path);
      expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
      expect(screen.getByText(/CIW-04\.2 \(#6\)/)).toBeInTheDocument();
      await screen.findByTestId("health-version");
      unmount();
    }

    renderAt("/nope");
    await screen.findByTestId("health-version");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the Dashboard" })).toHaveAttribute("href", "/");
  });
});
