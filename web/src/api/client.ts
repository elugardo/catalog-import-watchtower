// The one API client. Types come from `schema.d.ts`, generated from the
// repo-root openapi.yaml by `npm run gen:api` (never edit it by hand; CI's
// `npm run check:api` fails when it drifts). No runtime HTTP library: plain
// `fetch` with relative `/api/...` URLs, so the same bundle works behind the
// Vite proxy (:5173) and served by FastAPI (:8000).

import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type Health = Schemas["Health"];
export type Import = Schemas["Import"];
export type ImportDetail = Schemas["ImportDetail"];
export type ImportList = Schemas["ImportList"];
export type ValidationError = Schemas["ValidationError"];
export type Attempt = Schemas["Attempt"];
export type Alert = Schemas["Alert"];
export type AlertStatus = Schemas["AlertStatus"];
export type AlertListItem = Schemas["AlertListItem"];
export type AlertList = Schemas["AlertList"];
export type AgentAction = Schemas["AgentAction"];
export type Vendor = Schemas["Vendor"];
export type VendorList = Schemas["VendorList"];
export type Product = Schemas["Product"];
export type ProductList = Schemas["ProductList"];
export type ApiErrorBody = Schemas["Error"];

type ApiPath = keyof paths;

/**
 * A path from the contract with its `{id}` filled in and an optional query
 * string. Query values are integers; undefined ones are left out, and the
 * order of the keys is the order of the query string.
 */
function apiUrl(path: ApiPath, options: { id?: string; query?: Record<string, number | undefined> } = {}): string {
  let url: string = path;
  if (options.id !== undefined) url = url.replace("{id}", encodeURIComponent(options.id));
  const pairs = Object.entries(options.query ?? {}).filter(
    (entry): entry is [string, number] => entry[1] !== undefined,
  );
  if (pairs.length > 0) url += `?${pairs.map(([key, value]) => `${key}=${value}`).join("&")}`;
  return url;
}

/**
 * Every failed request ends here, with the text the UI shows:
 * `CODE: message` for the API's error shape, `HTTP <status>` for any other
 * non-2xx (HTML, empty body, a 502 from the dev proxy), and
 * `API unreachable` when `fetch` itself rejects.
 */
export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string | null;

  constructor(message: string, status: number | null, code: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export const API_UNREACHABLE = "API unreachable";

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const body = value as Record<string, unknown>;
  return typeof body.code === "string" && typeof body.message === "string";
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    // Headers, not an object spread: a spread silently drops a Headers instance or a tuple list.
    const headers = new Headers(init?.headers);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(API_UNREACHABLE, null, null);
  }

  const body = await readJson(response);
  if (!response.ok) {
    if (isErrorBody(body)) {
      throw new ApiError(`${body.code}: ${body.message}`, response.status, body.code);
    }
    throw new ApiError(`HTTP ${response.status}`, response.status, null);
  }
  if (body === undefined) {
    // A 2xx that is not JSON (for example the SPA's index.html) is not an API answer.
    throw new ApiError(`HTTP ${response.status}`, response.status, null);
  }
  return body as T;
}

/** The message to show for anything a request threw. */
export function errorMessage(error: unknown): string {
  // Network failures are already ApiError(API_UNREACHABLE); anything else is a
  // bug in the page, and saying "API unreachable" would point at the wrong place.
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

export function getHealth(): Promise<Health> {
  return request<Health>(apiUrl("/api/health"));
}

/** `GET /api/imports` with the server's defaults (limit 50, no offset). */
export function listImports(): Promise<ImportList> {
  return request<ImportList>(apiUrl("/api/imports"));
}

/** `GET /api/imports?limit=N`: the newest N imports (the dashboard asks for 100). */
export function listNewestImports(limit: number): Promise<ImportList> {
  return request<ImportList>(apiUrl("/api/imports", { query: { limit } }));
}

/** `GET /api/imports/{id}`, with the id exactly as it appears in the page URL. */
export function getImport(id: string): Promise<ImportDetail> {
  return request<ImportDetail>(apiUrl("/api/imports/{id}", { id }));
}

/** `GET /api/alerts?limit=N`, newest first. */
export function listAlerts(limit: number): Promise<AlertList> {
  return request<AlertList>(apiUrl("/api/alerts", { query: { limit } }));
}

/** `GET /api/vendors?limit=N`. */
export function listVendors(limit: number): Promise<VendorList> {
  return request<VendorList>(apiUrl("/api/vendors", { query: { limit } }));
}

export interface ProductQuery {
  /** All vendors when null. */
  vendorId: number | null;
  limit: number;
  /** Left out of the URL when 0 (the first page). */
  offset: number;
}

/** `GET /api/products?[vendor_id=..&]limit=..[&offset=..]`, newest `updated_at` first. */
export function listProducts({ vendorId, limit, offset }: ProductQuery): Promise<ProductList> {
  return request<ProductList>(
    apiUrl("/api/products", {
      query: { vendor_id: vendorId ?? undefined, limit, offset: offset > 0 ? offset : undefined },
    }),
  );
}

export interface CreateImportInput {
  /** Sent exactly as typed; the server trims and validates. */
  vendorName: string;
  /** Omitted from the form when null, so the server answers `MISSING_FIELD`. */
  file: File | null;
  injectTransientFailure: boolean;
}

/** `POST /api/imports` as multipart/form-data. A 201 is returned whatever the outcome. */
export function createImport(input: CreateImportInput): Promise<ImportDetail> {
  const form = new FormData();
  form.append("vendor_name", input.vendorName);
  if (input.file) form.append("file", input.file);
  form.append("inject_transient_failure", input.injectTransientFailure ? "true" : "false");
  // No Content-Type header: the browser sets multipart/form-data with its boundary.
  return request<ImportDetail>(apiUrl("/api/imports"), { method: "POST", body: form });
}
