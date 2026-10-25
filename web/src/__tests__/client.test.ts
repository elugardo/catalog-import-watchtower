import { afterEach, describe, expect, it, vi } from "vitest";
import { listImports } from "../api/client";

// The one error path every request shares.

afterEach(() => {
  vi.unstubAllGlobals();
});

function stub(response: () => Response) {
  const fetchMock = vi.fn(async () => response());
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("API client error path", () => {
  it("uses a relative /api URL", async () => {
    const fetchMock = stub(() => new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }));
    await listImports();
    expect(fetchMock).toHaveBeenCalledWith("/api/imports", expect.anything());
  });

  it("renders the error shape as CODE: message", async () => {
    stub(() => new Response(JSON.stringify({ code: "INVALID_QUERY", message: "bad", details: [] }), { status: 400 }));
    await expect(listImports()).rejects.toThrow("INVALID_QUERY: bad");
  });

  it("renders a non-JSON or shapeless non-2xx as HTTP <status>", async () => {
    stub(() => new Response("<html>Bad Gateway</html>", { status: 502, headers: { "Content-Type": "text/html" } }));
    await expect(listImports()).rejects.toThrow("HTTP 502");
    stub(() => new Response(null, { status: 503 }));
    await expect(listImports()).rejects.toThrow("HTTP 503");
    stub(() => new Response(JSON.stringify({ detail: "x" }), { status: 500 }));
    await expect(listImports()).rejects.toThrow("HTTP 500");
  });

  it("renders a fetch rejection as API unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(listImports()).rejects.toThrow("API unreachable");
  });
});
