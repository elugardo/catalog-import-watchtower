import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, listProducts, listVendors, type Product, type Vendor } from "../api/client";
import { ErrorText } from "../components/ErrorText";
import { useRequest } from "../components/useRequest";
import { formatPrice, formatUtc } from "../format";

// Spec F3 products: the catalog, all vendors or one, newest `updated_at`
// first as the API returns it (no client-side sorting). Pages of 50 with
// **Load more**; a response for an earlier vendor choice is dropped, and a
// product id already shown is never shown twice.

export const VENDOR_LIMIT = 100;
export const PRODUCT_PAGE = 50;

interface Listing {
  /** Products rendered, in API order, without repeated ids. */
  items: Product[];
  /** Products the API returned so far, repeats included: the next `offset`. */
  received: number;
  total: number;
}

type FirstPage = { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string };

export function Products() {
  const vendors = useRequest(() => listVendors(VENDOR_LIMIT), []);
  const [vendorId, setVendorId] = useState<number | null>(null);
  const [listing, setListing] = useState<Listing>({ items: [], received: 0, total: 0 });
  const [firstPage, setFirstPage] = useState<FirstPage>({ kind: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  // Bumped on every vendor change: a response carrying an older value is stale.
  const generation = useRef(0);
  // A ref, not only `loadingMore`: two clicks in the same tick send one request.
  const moreInFlight = useRef(false);
  const listingRef = useRef(listing);
  listingRef.current = listing;

  useEffect(() => {
    const mine = ++generation.current;
    moreInFlight.current = false;
    setLoadingMore(false);
    setMoreError(null);
    setFirstPage({ kind: "loading" });
    setListing({ items: [], received: 0, total: 0 });
    listProducts({ vendorId, limit: PRODUCT_PAGE, offset: 0 })
      .then((page) => {
        if (mine !== generation.current) return;
        setListing({ items: dedupe([], page.items), received: page.items.length, total: page.total });
        setFirstPage({ kind: "ready" });
      })
      .catch((error: unknown) => {
        if (mine !== generation.current) return;
        setFirstPage({ kind: "error", message: errorMessage(error) });
      });
  }, [vendorId]);

  const loadMore = useCallback(() => {
    if (moreInFlight.current) return;
    moreInFlight.current = true;
    const mine = generation.current;
    setLoadingMore(true);
    setMoreError(null);
    listProducts({ vendorId, limit: PRODUCT_PAGE, offset: listingRef.current.received })
      .then((page) => {
        if (mine !== generation.current) return;
        setListing((current) => {
          const received = current.received + page.items.length;
          // An empty page means the API has nothing more to give, whatever `total`
          // says (the catalog shrank between pages); stop offering Load more.
          return {
            items: dedupe(current.items, page.items),
            received,
            total: page.items.length === 0 ? received : page.total,
          };
        });
      })
      .catch((error: unknown) => {
        if (mine !== generation.current) return;
        setMoreError(errorMessage(error));
      })
      .finally(() => {
        if (mine !== generation.current) return;
        moreInFlight.current = false;
        setLoadingMore(false);
      });
  }, [vendorId]);

  const vendorList = vendors.kind === "ready" ? vendors.data : null;
  const selected = vendorList?.items.find((vendor) => vendor.id === vendorId) ?? null;
  const hasMore = listing.received < listing.total;

  return (
    <section className="card" aria-labelledby="page-heading">
      <h2 id="page-heading">Products</h2>

      <div className="form__field filter">
        <label htmlFor="vendor-filter">Vendor</label>
        <select
          id="vendor-filter"
          value={vendorId === null ? "" : String(vendorId)}
          onChange={(event) => setVendorId(event.target.value === "" ? null : Number(event.target.value))}
        >
          <option value="">All vendors</option>
          {vendorList?.items.map((vendor: Vendor) => (
            <option key={vendor.id} value={String(vendor.id)}>
              {vendor.display_name}
            </option>
          ))}
        </select>
        {vendors.kind === "loading" && (
          <span className="muted small" role="status">
            Loading vendors…
          </span>
        )}
        {vendorList !== null && vendorList.total > VENDOR_LIMIT && (
          <span className="muted small">
            showing the newest {vendorList.items.length} of {vendorList.total} vendors
          </span>
        )}
      </div>
      {vendors.kind === "error" && <ErrorText message={vendors.message} />}

      {firstPage.kind === "loading" && <p role="status">Loading products…</p>}
      {firstPage.kind === "error" && <ErrorText message={firstPage.message} />}
      {firstPage.kind === "ready" && listing.items.length === 0 && !hasMore && (
        <EmptyProducts vendor={vendorId === null ? null : selected} />
      )}
      {firstPage.kind === "ready" && listing.items.length > 0 && (
        <>
          <p className="muted">
            showing {listing.items.length} of {listing.total} products
          </p>
          <ProductTable items={listing.items} />
        </>
      )}
      {moreError !== null && <ErrorText message={moreError} />}
      {firstPage.kind === "ready" && hasMore && (
        <p>
          <button type="button" onClick={loadMore} disabled={loadingMore}>
            Load more
          </button>
          {loadingMore && (
            <span className="muted small" role="status">
              {" "}
              Loading…
            </span>
          )}
        </p>
      )}
    </section>
  );
}

/** `next` appended to `shown`, minus the ids already shown (the catalog may change between pages). */
function dedupe(shown: Product[], next: Product[]): Product[] {
  const seen = new Set(shown.map((product) => product.id));
  const added: Product[] = [];
  for (const product of next) {
    if (seen.has(product.id)) continue;
    seen.add(product.id);
    added.push(product);
  }
  return added.length === 0 ? shown : [...shown, ...added];
}

function EmptyProducts({ vendor }: { vendor: Vendor | null }) {
  if (vendor === null) {
    return (
      <p>
        No products yet. <Link to="/upload">Upload a CSV</Link>
      </p>
    );
  }
  return <p className="muted">No products for {vendor.display_name}</p>;
}

function ProductTable({ items }: { items: Product[] }) {
  return (
    <div className="table-scroll">
      <table className="table" aria-label="Products">
        <thead>
          <tr>
            <th scope="col">SKU</th>
            <th scope="col">Name</th>
            <th scope="col">Price</th>
            <th scope="col">Quantity</th>
            <th scope="col">Last updated</th>
          </tr>
        </thead>
        <tbody>
          {items.map((product) => (
            <tr key={product.id}>
              <td>{product.sku}</td>
              <td>{product.name}</td>
              <td className="num nowrap">{formatPrice(product.price_cents)}</td>
              <td className="num">{product.quantity}</td>
              <td className="nowrap">{formatUtc(product.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
