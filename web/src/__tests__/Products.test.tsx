import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Product } from "../api/client";
import { formatPrice } from "../format";
import { aProduct, apiCalls, deferred, json, renderAt, stubFetch, type Handler } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
});

const VENDORS = "GET /api/vendors?limit=100";
const SAMPLE = { id: 1, display_name: "Sample Furnishings" };
const EMPTY_VENDOR = { id: 2, display_name: "Empty Vendor" };

/** Products with ids from `from` down, `count` of them. */
function products(from: number, count: number, extra: Partial<Product> = {}): Product[] {
  return Array.from({ length: count }, (_, index) =>
    aProduct({ id: from - index, sku: `SKU-${from - index}`, ...extra }),
  );
}

function stub(routes: Record<string, Handler>) {
  return stubFetch({ [VENDORS]: () => json({ items: [SAMPLE, EMPTY_VENDOR], total: 2 }), ...routes });
}

function bodyRows() {
  return within(screen.getByRole("table", { name: "Products" })).getAllByRole("row").slice(1);
}

function urls(fetchMock: ReturnType<typeof stubFetch>) {
  return apiCalls(fetchMock).map(([input]) => String(input));
}

describe("formatPrice", () => {
  it("formats integer cents with integer arithmetic", () => {
    expect(formatPrice(0)).toBe("$0.00");
    expect(formatPrice(5)).toBe("$0.05");
    expect(formatPrice(50)).toBe("$0.50");
    expect(formatPrice(14999)).toBe("$149.99");
    expect(formatPrice(100000)).toBe("$1,000.00");
    expect(formatPrice(999999999999)).toBe("$9,999,999,999.99");
  });
});

describe("Products page", () => {
  it("fills the vendor filter and shows the first page with its columns and prices", async () => {
    const prices = [0, 5, 50, 14999, 100000, 999999999999];
    const items = prices.map((price_cents, index) => aProduct({ id: 10 - index, sku: `P${index}`, price_cents }));
    const fetchMock = stub({ "GET /api/products?limit=50": () => json({ items, total: 6 }) });

    renderAt("/products");

    const select = screen.getByRole("combobox", { name: "Vendor" });
    expect(await screen.findByRole("option", { name: "Sample Furnishings" })).toBeInTheDocument();
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All vendors",
      "Sample Furnishings",
      "Empty Vendor",
    ]);
    expect(select).toHaveValue("");

    await screen.findByRole("table", { name: "Products" });
    const headers = within(screen.getByRole("table", { name: "Products" }))
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual(["SKU", "Name", "Price", "Quantity", "Last updated"]);
    const rows = bodyRows();
    expect(rows.map((row) => within(row).getAllByRole("cell")[2].textContent)).toEqual([
      "$0.00",
      "$0.05",
      "$0.50",
      "$149.99",
      "$1,000.00",
      "$9,999,999,999.99",
    ]);
    expect(within(rows[0]).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "P0",
      "Oak chair",
      "$0.00",
      "8",
      "2026-10-24 12:00:01 UTC",
    ]);
    expect(screen.getByText("showing 6 of 6 products")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(urls(fetchMock)).toEqual(["/api/vendors?limit=100", "/api/products?limit=50"]);
  });

  it("loads more with offset, sends one request on a double click, and disappears after the last page", async () => {
    const second = deferred<Response>();
    const fetchMock = stub({
      "GET /api/products?limit=50": () => json({ items: products(120, 50), total: 120 }),
      "GET /api/products?limit=50&offset=50": () => second.promise,
      "GET /api/products?limit=50&offset=100": () => json({ items: products(20, 20), total: 120 }),
    });

    renderAt("/products");

    const button = await screen.findByRole("button", { name: "Load more" });
    expect(screen.getByText("showing 50 of 120 products")).toBeInTheDocument();
    fireEvent.click(button);
    fireEvent.click(button);
    expect(button).toBeDisabled();
    await act(async () => second.resolve(json({ items: products(70, 50), total: 120 })));
    expect(await screen.findByText("showing 100 of 120 products")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load more" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("showing 120 of 120 products")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(120);
    expect(within(bodyRows()[50]).getAllByRole("cell")[0]).toHaveTextContent("SKU-70");

    expect(urls(fetchMock).filter((url) => url.startsWith("/api/products"))).toEqual([
      "/api/products?limit=50",
      "/api/products?limit=50&offset=50",
      "/api/products?limit=50&offset=100",
    ]);
  });

  it("never renders a product id twice when a later page repeats one", async () => {
    stub({
      "GET /api/products?limit=50": () => json({ items: products(60, 50), total: 60 }),
      // The catalog changed: the next page starts with the last two ids again.
      "GET /api/products?limit=50&offset=50": () => json({ items: products(12, 10), total: 60 }),
    });

    renderAt("/products");

    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("showing 58 of 60 products")).toBeInTheDocument();
    const skus = bodyRows().map((row) => within(row).getAllByRole("cell")[0].textContent);
    expect(new Set(skus).size).toBe(skus.length);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("keeps the rows and offers Load more again after a failed Load more", async () => {
    let fail = true;
    stub({
      "GET /api/products?limit=50": () => json({ items: products(60, 50), total: 60 }),
      "GET /api/products?limit=50&offset=50": () =>
        fail
          ? json({ code: "INTERNAL_ERROR", message: "internal error", details: [] }, 500)
          : json({ items: products(10, 10), total: 60 }),
    });

    renderAt("/products");

    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("INTERNAL_ERROR: internal error")).toHaveAttribute("role", "alert");
    expect(bodyRows()).toHaveLength(50);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("showing 60 of 60 products")).toBeInTheDocument();
    expect(screen.queryByText("INTERNAL_ERROR: internal error")).not.toBeInTheDocument();
  });

  it("resets to a fresh first page on a vendor change and drops a late answer for the old vendor", async () => {
    const lateMore = deferred<Response>();
    const fetchMock = stub({
      "GET /api/products?limit=50": () => json({ items: products(200, 50), total: 120 }),
      "GET /api/products?limit=50&offset=50": () => lateMore.promise,
      "GET /api/products?vendor_id=1&limit=50": () => json({ items: products(3, 3, { vendor_id: 1 }), total: 3 }),
    });

    renderAt("/products");

    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
    await screen.findByRole("option", { name: "Sample Furnishings" });
    fireEvent.change(screen.getByRole("combobox", { name: "Vendor" }), { target: { value: "1" } });
    expect(await screen.findByText("showing 3 of 3 products")).toBeInTheDocument();

    // The Load more for "All vendors" answers now; it must not be mixed in.
    await act(async () => lateMore.resolve(json({ items: products(150, 50), total: 120 })));
    expect(screen.getByText("showing 3 of 3 products")).toBeInTheDocument();
    expect(bodyRows().map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual(["SKU-3", "SKU-2", "SKU-1"]);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(urls(fetchMock)).toContain("/api/products?vendor_id=1&limit=50");
  });

  it("drops a late first page for the previous vendor", async () => {
    const lateFirst = deferred<Response>();
    stub({
      "GET /api/products?limit=50": () => lateFirst.promise,
      "GET /api/products?vendor_id=1&limit=50": () => json({ items: products(3, 3), total: 3 }),
    });

    renderAt("/products");

    await screen.findByRole("option", { name: "Sample Furnishings" });
    fireEvent.change(screen.getByRole("combobox", { name: "Vendor" }), { target: { value: "1" } });
    expect(await screen.findByText("showing 3 of 3 products")).toBeInTheDocument();
    await act(async () => lateFirst.resolve(json({ items: products(500, 50), total: 500 })));
    expect(screen.getByText("showing 3 of 3 products")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(3);
  });

  it("shows the empty states for no products at all and for a vendor without products", async () => {
    stub({
      "GET /api/products?limit=50": () => json({ items: [], total: 0 }),
      "GET /api/products?vendor_id=2&limit=50": () => json({ items: [], total: 0 }),
    });

    renderAt("/products");

    expect(await screen.findByText("No products yet.", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload a CSV" })).toHaveAttribute("href", "/upload");
    await screen.findByRole("option", { name: "Empty Vendor" });
    fireEvent.change(screen.getByRole("combobox", { name: "Vendor" }), { target: { value: "2" } });
    expect(await screen.findByText("No products for Empty Vendor")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("offers only All vendors without vendors, and says when there are more than 100", async () => {
    stubFetch({
      [VENDORS]: () => json({ items: [], total: 0 }),
      "GET /api/products?limit=50": () => json({ items: [], total: 0 }),
    });
    const { unmount } = renderAt("/products");
    await screen.findByText("No products yet.", { exact: false });
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["All vendors"]);
    unmount();

    const many = Array.from({ length: 100 }, (_, index) => ({ id: index + 1, display_name: `V${index + 1}` }));
    stubFetch({
      [VENDORS]: () => json({ items: many, total: 130 }),
      "GET /api/products?limit=50": () => json({ items: [], total: 0 }),
    });
    renderAt("/products");
    expect(await screen.findByText("showing the newest 100 of 130 vendors")).toBeInTheDocument();
  });

  it("shows failed vendors and products requests without crashing", async () => {
    stubFetch({
      [VENDORS]: () => json({ code: "INTERNAL_ERROR", message: "internal error", details: [] }, 500),
      "GET /api/products?limit=50": () => new Response("", { status: 502 }),
    });

    renderAt("/products");

    expect(await screen.findByText("INTERNAL_ERROR: internal error")).toHaveAttribute("role", "alert");
    expect(await screen.findByText("HTTP 502")).toHaveAttribute("role", "alert");
    expect(screen.getByRole("combobox", { name: "Vendor" })).toBeInTheDocument();
  });
});
