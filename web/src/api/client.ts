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
export type ApiErrorBody = Schemas["Error"];

type ApiPath = keyof paths;

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

async function request<T>(path: ApiPath, init?: RequestInit): Promise<T> {
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
  return request<Health>("/api/health");
}

/** `GET /api/imports` with the server's defaults (limit 50, no offset). */
export function listImports(): Promise<ImportList> {
  return request<ImportList>("/api/imports");
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
  return request<ImportDetail>("/api/imports", { method: "POST", body: form });
}
