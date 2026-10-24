/** Thin layer over the generated openapi-fetch client: turns non-2xx responses into ApiError (06-api-spec error shape). */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId?: string;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** Plain-sentence cause for the UI. Never a stack trace or raw JSON. */
  userMessage(): string {
    if (this.status === 0) return "The API did not respond.";
    if (this.status >= 500 && this.code === "unknown") return "The API did not respond.";
    if (this.status === 403) return "This API key does not have the scope this action needs.";
    return this.message || "The request failed.";
  }
}

type Envelope = { error?: unknown; data?: unknown; response: Response };

function toApiError(res: Response, body: unknown): ApiError {
  const requestId = res.headers.get("x-request-id") ?? undefined;
  const err = (body as { error?: unknown } | null)?.error;
  if (err && typeof err === "object") {
    const e = err as { code?: string; message?: string; details?: Record<string, unknown> };
    return new ApiError(res.status, e.code ?? "unknown", e.message ?? res.statusText, e.details ?? {}, requestId);
  }
  // The BFF proxy answers 502 {"error": "upstream unreachable"} (a string) when FastAPI is down.
  if (typeof err === "string") return new ApiError(res.status, "unknown", err, {}, requestId);
  return new ApiError(res.status, "unknown", res.statusText, {}, requestId);
}

/** Await an openapi-fetch call and return its data, throwing ApiError on any non-2xx or network failure. */
export async function call<T>(p: Promise<Envelope & { data?: T }>): Promise<T> {
  let r: Envelope & { data?: T };
  try {
    r = await p;
  } catch {
    throw new ApiError(0, "network", "The API did not respond.");
  }
  if (!r.response.ok) throw toApiError(r.response, r.error);
  return r.data as T;
}

/** Fetch binary audio from the preview endpoints through the same BFF proxy. */
export async function fetchAudio(path: string, init?: RequestInit): Promise<Blob> {
  let res: Response;
  try {
    res = await fetch(`/api/proxy${path}`, { method: "POST", ...init });
  } catch {
    throw new ApiError(0, "network", "The API did not respond.");
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw toApiError(res, body);
  }
  return res.blob();
}
