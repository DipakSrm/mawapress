import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { ReactElement } from "react";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";
import { setAccessToken } from "@/lib/api";
import { SessionProvider } from "@/lib/auth";
import { nav, router } from "./nav-state";

export { nav, router };

export const ORIGIN = "http://localhost:3000";
export const server = setupServer();

export type TestUser = { id: string; email: string; name: string; role: string; bio: null };
export const reporter: TestUser = {
  id: "u-rep",
  email: "r@mawapress.test",
  name: "Rita Reporter",
  role: "reporter",
  bio: null,
};
export const editor: TestUser = { ...reporter, id: "u-ed", name: "Ed Editor", role: "editor" };
export const admin: TestUser = { ...reporter, id: "u-ad", name: "Ada Admin", role: "admin" };

/** Call once at the top of a test file (hooks register with the file's suite). */
export function setupAdminTest() {
  // The app client is same-origin (relative URLs); Node's fetch needs absolute ones.
  beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
    const realFetch = globalThis.fetch; // MSW's patched fetch, captured after listen()
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      realFetch(typeof input === "string" ? new URL(input, ORIGIN) : input, init),
    );
  });
  afterAll(() => {
    server.close();
    vi.unstubAllGlobals();
  });
  beforeEach(() => {
    setAccessToken(null);
    router.replace.mockClear();
    router.push.mockClear();
    nav.pathname = "/admin";
    nav.search = "";
  });
  afterEach(() => server.resetHandlers());
}

export function mockSignedIn(user: TestUser) {
  server.use(
    http.post("*/api/auth/refresh", () => HttpResponse.json({ access_token: "tok" })),
    http.get("*/api/auth/me", () => HttpResponse.json(user)),
  );
}

export function mockSignedOut() {
  server.use(
    http.post("*/api/auth/refresh", () =>
      HttpResponse.json(
        { error: { code: "INVALID_REFRESH_TOKEN", message: "no", details: {} } },
        { status: 401 },
      ),
    ),
  );
}

export function renderWithSession(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionProvider>{ui}</SessionProvider>
    </QueryClientProvider>,
  );
}
