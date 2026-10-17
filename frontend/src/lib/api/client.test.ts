import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  AUTH_EXPIRED_EVENT,
  createApiClient,
  getAccessToken,
  ifMatch,
  setAccessToken,
} from "./client";

const BASE = "http://api.test";
const server = setupServer();
const api = createApiClient({ baseUrl: BASE });

const envelope = (code: string, message = code, details: Record<string, unknown> = {}) => ({
  error: { code, message, details },
});

function clearCookies() {
  for (const c of document.cookie.split(";")) {
    const name = c.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  setAccessToken(null);
  clearCookies();
});
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("responses", () => {
  it("parses JSON bodies and sends the bearer token", async () => {
    setAccessToken("tok-1");
    let auth: string | null = null;
    server.use(
      http.get(`${BASE}/api/auth/me`, ({ request }) => {
        auth = request.headers.get("authorization");
        return HttpResponse.json({ id: 1, email: "a@b.c" });
      }),
    );
    await expect(api.get("/api/auth/me")).resolves.toEqual({ id: 1, email: "a@b.c" });
    expect(auth).toBe("Bearer tok-1");
  });

  it("sends JSON bodies and serialises query arrays, skipping empty values", async () => {
    let url = "";
    let body: unknown;
    server.use(
      http.post(`${BASE}/api/posts`, async ({ request }) => {
        url = request.url;
        body = await request.json();
        expect(request.headers.get("content-type")).toBe("application/json");
        return HttpResponse.json({ ok: true }, { status: 201 });
      }),
    );
    await api.post("/api/posts", { title: "x" }, { query: { tag: [1, 2], q: undefined, n: 0 } });
    expect(new URL(url).search).toBe("?tag=1&tag=2&n=0");
    expect(body).toEqual({ title: "x" });
  });

  it("returns undefined for 204", async () => {
    server.use(http.delete(`${BASE}/api/x`, () => new HttpResponse(null, { status: 204 })));
    await expect(api.delete("/api/x")).resolves.toBeUndefined();
  });

  it("throws ApiError parsed from the backend envelope", async () => {
    server.use(
      http.get(`${BASE}/api/posts/9`, () =>
        HttpResponse.json(envelope("POST_NOT_FOUND", "No such post", { id: 9 }), { status: 404 }),
      ),
    );
    const err = await api.get("/api/posts/9").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 404,
      code: "POST_NOT_FOUND",
      message: "No such post",
      details: { id: 9 },
    });
  });

  it("exposes Retry-After on rate-limit errors", async () => {
    server.use(
      http.post(`${BASE}/api/auth/login`, () =>
        HttpResponse.json(envelope("RATE_LIMITED"), {
          status: 429,
          headers: { "Retry-After": "30" },
        }),
      ),
    );
    const err = await api.post("/api/auth/login", {}, { auth: false }).catch((e) => e);
    expect(err).toMatchObject({ status: 429, code: "RATE_LIMITED", retryAfter: 30 });
  });

  it("falls back to HTTP_<status> for non-envelope error bodies", async () => {
    server.use(
      http.get(
        `${BASE}/api/boom`,
        () => new HttpResponse("<html>bad gateway</html>", { status: 502 }),
      ),
    );
    const err = await api.get("/api/boom").catch((e) => e);
    expect(err).toMatchObject({ status: 502, code: "HTTP_502", details: {} });
  });

  it("maps network failures to NETWORK_ERROR", async () => {
    server.use(http.get(`${BASE}/api/down`, () => HttpResponse.error()));
    const err = await api.get("/api/down").catch((e) => e);
    expect(err).toMatchObject({ status: 0, code: "NETWORK_ERROR" });
  });
});

describe("If-Match", () => {
  it("ifMatch() builds the header and it is sent verbatim", async () => {
    const stamp = "2026-10-17T10:00:00.123456+00:00";
    expect(ifMatch(stamp)).toEqual({ "If-Match": stamp });
    let seen: string | null = null;
    server.use(
      http.patch(`${BASE}/api/posts/1`, ({ request }) => {
        seen = request.headers.get("if-match");
        return HttpResponse.json({ updated_at: "next" });
      }),
    );
    await api.patch("/api/posts/1", { x: 1 }, { headers: ifMatch(stamp) });
    expect(seen).toBe(stamp);
  });

  it("surfaces VERSION_CONFLICT details", async () => {
    server.use(
      http.patch(`${BASE}/api/posts/1`, () =>
        HttpResponse.json(envelope("VERSION_CONFLICT", "changed", { current_updated_at: "T2" }), {
          status: 412,
        }),
      ),
    );
    const err = await api.patch("/api/posts/1", {}, { headers: ifMatch("T1") }).catch((e) => e);
    expect(err).toMatchObject({ status: 412, code: "VERSION_CONFLICT" });
    expect((err as ApiError).details.current_updated_at).toBe("T2");
  });
});

describe("token refresh", () => {
  it("refreshes once on 401 INVALID_TOKEN, with the CSRF header from the cookie, then retries", async () => {
    setAccessToken("old");
    document.cookie = "mawa_csrf=csrf-abc; path=/";
    let csrf: string | null = null;
    let refreshCalls = 0;
    const seenAuth: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/api/auth/me`, ({ request }) => {
        seenAuth.push(request.headers.get("authorization"));
        return request.headers.get("authorization") === "Bearer new"
          ? HttpResponse.json({ id: 1 })
          : HttpResponse.json(envelope("INVALID_TOKEN"), { status: 401 });
      }),
      http.post(`${BASE}/api/auth/refresh`, ({ request }) => {
        refreshCalls++;
        csrf = request.headers.get("x-csrf-token");
        return HttpResponse.json({ access_token: "new", token_type: "bearer" });
      }),
    );
    await expect(api.get("/api/auth/me")).resolves.toEqual({ id: 1 });
    expect(refreshCalls).toBe(1);
    expect(csrf).toBe("csrf-abc");
    expect(seenAuth).toEqual(["Bearer old", "Bearer new"]);
    expect(getAccessToken()).toBe("new");
  });

  it("recovers a session on NOT_AUTHENTICATED when no token is held (page reload)", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, ({ request }) =>
        request.headers.get("authorization") === "Bearer fresh"
          ? HttpResponse.json({ id: 2 })
          : HttpResponse.json(envelope("NOT_AUTHENTICATED"), { status: 401 }),
      ),
      http.post(`${BASE}/api/auth/refresh`, () => HttpResponse.json({ access_token: "fresh" })),
    );
    await expect(api.get("/api/auth/me")).resolves.toEqual({ id: 2 });
  });

  it("shares a single in-flight refresh across concurrent 401s", async () => {
    setAccessToken("old");
    let refreshCalls = 0;
    server.use(
      http.get(`${BASE}/api/a`, ({ request }) =>
        request.headers.get("authorization") === "Bearer new"
          ? HttpResponse.json({ r: "a" })
          : HttpResponse.json(envelope("INVALID_TOKEN"), { status: 401 }),
      ),
      http.get(`${BASE}/api/b`, ({ request }) =>
        request.headers.get("authorization") === "Bearer new"
          ? HttpResponse.json({ r: "b" })
          : HttpResponse.json(envelope("INVALID_TOKEN"), { status: 401 }),
      ),
      http.get(`${BASE}/api/c`, ({ request }) =>
        request.headers.get("authorization") === "Bearer new"
          ? HttpResponse.json({ r: "c" })
          : HttpResponse.json(envelope("INVALID_TOKEN"), { status: 401 }),
      ),
      http.post(`${BASE}/api/auth/refresh`, async () => {
        refreshCalls++;
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ access_token: "new" });
      }),
    );
    const results = await Promise.all([api.get("/api/a"), api.get("/api/b"), api.get("/api/c")]);
    expect(results).toEqual([{ r: "a" }, { r: "b" }, { r: "c" }]);
    expect(refreshCalls).toBe(1);
  });

  it("retries the refresh once after 300 ms on REFRESH_STALE", async () => {
    setAccessToken("old");
    document.cookie = "mawa_csrf=first; path=/";
    const csrfSeen: (string | null)[] = [];
    const times: number[] = [];
    server.use(
      http.get(`${BASE}/api/me`, ({ request }) =>
        request.headers.get("authorization") === "Bearer new"
          ? HttpResponse.json({ ok: 1 })
          : HttpResponse.json(envelope("INVALID_TOKEN"), { status: 401 }),
      ),
      http.post(`${BASE}/api/auth/refresh`, ({ request }) => {
        csrfSeen.push(request.headers.get("x-csrf-token"));
        times.push(Date.now());
        if (csrfSeen.length === 1) {
          // Another tab rotated the cookie in the meantime.
          document.cookie = "mawa_csrf=second; path=/";
          return HttpResponse.json(envelope("REFRESH_STALE"), { status: 401 });
        }
        return HttpResponse.json({ access_token: "new" });
      }),
    );
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    await expect(api.get("/api/me")).resolves.toEqual({ ok: 1 });
    window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    expect(csrfSeen).toEqual(["first", "second"]);
    expect(times[1] - times[0]).toBeGreaterThanOrEqual(280);
    expect(expired).not.toHaveBeenCalled();
  });

  it("REFRESH_REUSED clears the session and emits auth:expired", async () => {
    setAccessToken("old");
    let refreshCalls = 0;
    server.use(
      http.get(`${BASE}/api/me`, () =>
        HttpResponse.json(envelope("INVALID_TOKEN"), { status: 401 }),
      ),
      http.post(`${BASE}/api/auth/refresh`, () => {
        refreshCalls++;
        return HttpResponse.json(envelope("REFRESH_REUSED"), { status: 401 });
      }),
    );
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    const err = await api.get("/api/me").catch((e) => e);
    window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    expect(err).toMatchObject({ status: 401, code: "REFRESH_REUSED" });
    expect(refreshCalls).toBe(1);
    expect(expired).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
  });

  it("clears the session when the retried request is still rejected", async () => {
    setAccessToken("old");
    server.use(
      http.get(`${BASE}/api/me`, () =>
        HttpResponse.json(envelope("INVALID_TOKEN"), { status: 401 }),
      ),
      http.post(`${BASE}/api/auth/refresh`, () => HttpResponse.json({ access_token: "new" })),
    );
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    const err = await api.get("/api/me").catch((e) => e);
    window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    expect(err).toMatchObject({ status: 401, code: "INVALID_TOKEN" });
    expect(expired).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
  });

  it("does not refresh for other 401 codes or for auth:false calls", async () => {
    let refreshCalls = 0;
    server.use(
      http.post(`${BASE}/api/auth/login`, () =>
        HttpResponse.json(envelope("INVALID_CREDENTIALS"), { status: 401 }),
      ),
      http.post(`${BASE}/api/auth/refresh`, () => {
        refreshCalls++;
        return HttpResponse.json({ access_token: "x" });
      }),
    );
    const err = await api.post("/api/auth/login", {}, { auth: false }).catch((e) => e);
    expect(err).toMatchObject({ code: "INVALID_CREDENTIALS" });
    expect(refreshCalls).toBe(0);
  });
});

describe("upload", () => {
  it("posts multipart with the bearer token and parses the response", async () => {
    setAccessToken("tok");
    let auth: string | null = null;
    let content: string | null = null;
    server.use(
      http.post(`${BASE}/api/media`, async ({ request }) => {
        auth = request.headers.get("authorization");
        const form = await request.formData();
        content = await (form.get("file") as Blob).text();
        return HttpResponse.json({ id: 5 }, { status: 201 });
      }),
    );
    const form = new FormData();
    form.append("file", new File(["abc"], "pic.png", { type: "image/png" }));
    await expect(api.upload("/api/media", form)).resolves.toEqual({ id: 5 });
    expect(auth).toBe("Bearer tok");
    expect(content).toBe("abc");
  });

  it("throws ApiError from the envelope and refreshes on 401", async () => {
    setAccessToken("old");
    server.use(
      http.post(`${BASE}/api/media`, ({ request }) =>
        request.headers.get("authorization") === "Bearer new"
          ? HttpResponse.json(envelope("FILE_TOO_LARGE", "big"), { status: 413 })
          : HttpResponse.json(envelope("INVALID_TOKEN"), { status: 401 }),
      ),
      http.post(`${BASE}/api/auth/refresh`, () => HttpResponse.json({ access_token: "new" })),
    );
    const err = await api.upload("/api/media", new FormData()).catch((e) => e);
    expect(err).toMatchObject({ status: 413, code: "FILE_TOO_LARGE" });
  });

  it("reports upload progress as a 0..1 fraction", async () => {
    const instances: FakeXhr[] = [];
    class FakeXhr {
      upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      status = 201;
      responseText = '{"id":1}';
      withCredentials = false;
      constructor() {
        instances.push(this);
      }
      open() {}
      setRequestHeader() {}
      getResponseHeader() {
        return null;
      }
      abort() {}
      send() {
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: 25,
          total: 100,
        } as ProgressEvent);
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: 100,
          total: 100,
        } as ProgressEvent);
        this.onload?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    try {
      const fractions: number[] = [];
      await api.upload("/api/media", new FormData(), { onProgress: (f) => fractions.push(f) });
      expect(fractions).toEqual([0.25, 1]);
      expect(instances).toHaveLength(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
