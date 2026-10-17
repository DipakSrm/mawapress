import { ApiError, errorFromResponse } from "./errors";
import {
  expireSession,
  getAccessToken,
  getExpiryEpoch,
  readCsrfCookie,
  setAccessToken,
} from "./session";

export { ApiError, isApiError } from "./errors";
export {
  AUTH_EXPIRED_EVENT,
  expireSession,
  getAccessToken,
  onAuthExpired,
  setAccessToken,
} from "./session";

export type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue | QueryValue[]>;

export interface RequestOptions {
  method?: string;
  /** Plain objects are sent as JSON; FormData is passed through untouched. */
  body?: unknown;
  query?: Query;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Set to false for endpoints that must not carry the bearer token or trigger a refresh (login). */
  auth?: boolean;
}

export interface UploadOptions extends Omit<RequestOptions, "body"> {
  /** Called with a 0..1 fraction while the request body is uploading. */
  onProgress?: (fraction: number) => void;
}

type SimpleOptions = Omit<RequestOptions, "method" | "body">;

/** `If-Match` header for post state changes; pass the `updated_at` of the last response held. */
export function ifMatch(updatedAt: string): Record<string, string> {
  return { "If-Match": updatedAt };
}

interface RawResponse {
  status: number;
  headers: Headers;
  body: unknown;
}

const REFRESH_PATH = "/api/auth/refresh";
const STALE_RETRY_MS = 300;
const REFRESHABLE_CODES = new Set(["INVALID_TOKEN", "NOT_AUTHENTICATED"]);

function buildUrl(baseUrl: string, path: string, query?: Query): string {
  let url = baseUrl + path;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    for (const v of Array.isArray(value) ? value : [value]) {
      if (v !== undefined && v !== null) params.append(key, String(v));
    }
  }
  const qs = params.toString();
  if (qs) url += (url.includes("?") ? "&" : "?") + qs;
  return url;
}

function parseBody(text: string): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface ApiClientOptions {
  /** Prefix for every path. Empty means same-origin (the browser default). */
  baseUrl?: string;
}

export function createApiClient({ baseUrl = "" }: ApiClientOptions = {}) {
  let refreshing: Promise<string> | null = null;

  async function fetchTransport(
    method: string,
    path: string,
    opts: {
      query?: Query;
      headers?: Record<string, string>;
      body?: BodyInit;
      signal?: AbortSignal;
    },
  ): Promise<RawResponse> {
    let res: Response;
    try {
      res = await fetch(buildUrl(baseUrl, path, opts.query), {
        method,
        headers: opts.headers,
        body: opts.body,
        signal: opts.signal,
        credentials: "include",
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw new ApiError(0, "NETWORK_ERROR", "Could not reach the server");
    }
    return { status: res.status, headers: res.headers, body: parseBody(await res.text()) };
  }

  function xhrTransport(
    method: string,
    path: string,
    form: FormData,
    opts: UploadOptions,
    token: string | null,
  ): Promise<RawResponse> {
    return new Promise((resolve, reject) => {
      const aborted = () => new DOMException("Upload aborted", "AbortError");
      if (opts.signal?.aborted) {
        reject(aborted());
        return;
      }
      const xhr = new XMLHttpRequest();
      xhr.open(method, buildUrl(baseUrl, path, opts.query));
      xhr.withCredentials = true;
      xhr.setRequestHeader("Accept", "application/json");
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      for (const [k, v] of Object.entries(opts.headers ?? {})) xhr.setRequestHeader(k, v);
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && ev.total > 0) opts.onProgress?.(ev.loaded / ev.total);
      };
      const onAbort = () => xhr.abort();
      const settle = () => opts.signal?.removeEventListener("abort", onAbort);
      xhr.onload = () => {
        settle();
        const headers = new Headers();
        const retry = xhr.getResponseHeader("Retry-After");
        if (retry) headers.set("Retry-After", retry);
        resolve({ status: xhr.status, headers, body: parseBody(xhr.responseText) });
      };
      xhr.onerror = () => {
        settle();
        reject(new ApiError(0, "NETWORK_ERROR", "Could not reach the server"));
      };
      xhr.onabort = () => {
        settle();
        reject(aborted());
      };
      opts.signal?.addEventListener("abort", onAbort, { once: true });
      xhr.send(form);
    });
  }

  /** One refresh call. Throws ApiError on a non-2xx response. */
  async function refreshOnce(): Promise<string> {
    const csrf = readCsrfCookie();
    const headers: Record<string, string> = { Accept: "application/json" };
    if (csrf) headers["X-CSRF-Token"] = csrf;
    const raw = await fetchTransport("POST", REFRESH_PATH, { headers });
    if (raw.status >= 200 && raw.status < 300) {
      const token = (raw.body as { access_token?: unknown } | undefined)?.access_token;
      if (typeof token === "string") return token;
    }
    throw errorFromResponse(raw.status, raw.body, raw.headers);
  }

  async function doRefresh(): Promise<string> {
    try {
      let token: string;
      try {
        token = await refreshOnce();
      } catch (e) {
        // Another tab rotated the cookie a moment ago; the browser now holds the new one.
        // The CSRF cookie is re-read inside refreshOnce.
        if (e instanceof ApiError && e.code === "REFRESH_STALE") {
          await sleep(STALE_RETRY_MS);
          token = await refreshOnce();
        } else {
          throw e;
        }
      }
      setAccessToken(token);
      return token;
    } catch (e) {
      // A network failure says nothing about the session: keep the token and let a later request retry.
      if (!(e instanceof ApiError && e.status === 0)) expireSession();
      throw e;
    }
  }

  /** Concurrent callers share one in-flight refresh. */
  function refresh(): Promise<string> {
    if (!refreshing) {
      refreshing = doRefresh().finally(() => {
        refreshing = null;
      });
    }
    return refreshing;
  }

  /**
   * Runs `attempt` with the current token. On a refreshable 401 it refreshes once (shared
   * across concurrent callers) and retries the original request once.
   */
  async function withAuth<T>(
    auth: boolean,
    attempt: (token: string | null) => Promise<RawResponse>,
  ): Promise<T> {
    const sentWith = auth ? getAccessToken() : null;
    const epoch = getExpiryEpoch();
    let raw = await attempt(sentWith);
    if (auth && raw.status === 401) {
      const err = errorFromResponse(raw.status, raw.body, raw.headers);
      // If the session expired while this request was in flight, fail fast: no second refresh.
      if (REFRESHABLE_CODES.has(err.code) && getExpiryEpoch() === epoch) {
        // If another request already refreshed while ours was in flight, just use the new token.
        const current = getAccessToken();
        const token = current && current !== sentWith ? current : await refresh();
        raw = await attempt(token);
        if (raw.status === 401 && getExpiryEpoch() === epoch) expireSession();
      }
    }
    if (raw.status >= 200 && raw.status < 300) return raw.body as T;
    throw errorFromResponse(raw.status, raw.body, raw.headers);
  }

  function request<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
    const { method = "GET", body, query, headers, signal, auth = true } = opts;
    const isForm = typeof FormData !== "undefined" && body instanceof FormData;
    return withAuth<T>(auth, (token) => {
      const h: Record<string, string> = { Accept: "application/json", ...headers };
      if (token) h.Authorization = `Bearer ${token}`;
      let payload: BodyInit | undefined;
      if (body !== undefined) {
        if (isForm) {
          payload = body as FormData;
        } else {
          h["Content-Type"] = "application/json";
          payload = JSON.stringify(body);
        }
      }
      return fetchTransport(method, path, { query, headers: h, body: payload, signal });
    });
  }

  /** Multipart upload with progress (XMLHttpRequest, because fetch cannot report upload progress). */
  function upload<T = unknown>(path: string, form: FormData, opts: UploadOptions = {}): Promise<T> {
    const { method = "POST", auth = true } = opts;
    return withAuth<T>(auth, (token) => xhrTransport(method, path, form, opts, token));
  }

  return {
    request,
    upload,
    get: <T = unknown>(path: string, opts?: SimpleOptions) =>
      request<T>(path, { ...opts, method: "GET" }),
    post: <T = unknown>(path: string, body?: unknown, opts?: SimpleOptions) =>
      request<T>(path, { ...opts, method: "POST", body }),
    put: <T = unknown>(path: string, body?: unknown, opts?: SimpleOptions) =>
      request<T>(path, { ...opts, method: "PUT", body }),
    patch: <T = unknown>(path: string, body?: unknown, opts?: SimpleOptions) =>
      request<T>(path, { ...opts, method: "PATCH", body }),
    delete: <T = unknown>(path: string, opts?: SimpleOptions) =>
      request<T>(path, { ...opts, method: "DELETE" }),
    /** For the auth provider: restore a session from the refresh cookie on page load. */
    refresh,
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** Default same-origin client used by the app. */
export const api = createApiClient();
