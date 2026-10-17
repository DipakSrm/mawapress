/** Error thrown for every non-2xx response, parsed from the backend envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  /** Seconds from the `Retry-After` header (429, 503), when present. */
  readonly retryAfter?: number;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.retryAfter = retryAfter;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Build an ApiError from a parsed response body, tolerating non-envelope bodies. */
export function errorFromResponse(status: number, body: unknown, headers: Headers): ApiError {
  const header = headers.get("retry-after");
  const retry = Number(header);
  const retryAfter = header !== null && Number.isFinite(retry) ? retry : undefined;
  const env =
    body && typeof body === "object" && "error" in body
      ? (body as { error?: unknown }).error
      : undefined;
  if (env && typeof env === "object") {
    const e = env as { code?: unknown; message?: unknown; details?: unknown };
    const details =
      e.details && typeof e.details === "object" ? (e.details as Record<string, unknown>) : {};
    return new ApiError(
      status,
      typeof e.code === "string" ? e.code : `HTTP_${status}`,
      typeof e.message === "string" ? e.message : `Request failed (${status})`,
      details,
      retryAfter,
    );
  }
  return new ApiError(status, `HTTP_${status}`, `Request failed (${status})`, {}, retryAfter);
}
