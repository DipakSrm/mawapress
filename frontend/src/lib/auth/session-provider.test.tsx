import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { expireSession, getAccessToken } from "@/lib/api";
import {
  admin,
  mockSignedIn,
  mockSignedOut,
  nav,
  reporter,
  renderWithSession,
  router,
  server,
  setupAdminTest,
} from "@/test/admin";
import { useSession } from "./session-provider";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

function Probe() {
  const { status, user, role, hasRole, login, logout, retry } = useSession();
  return (
    <div>
      <p data-testid="status">{status}</p>
      <p data-testid="who">{user ? `${user.name}:${role}` : "nobody"}</p>
      <p data-testid="editor">{String(hasRole("editor"))}</p>
      <button onClick={() => void login("a@b.c", "pw").catch(() => {})}>login</button>
      <button onClick={() => void logout()}>logout</button>
      <button onClick={retry}>retry</button>
    </div>
  );
}

describe("session provider", () => {
  it("restores the session through a silent refresh on load", async () => {
    mockSignedIn(admin);
    renderWithSession(<Probe />);
    expect(screen.getByTestId("status")).toHaveTextContent(/^loading$/);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^authenticated$/));
    expect(screen.getByTestId("who")).toHaveTextContent("Ada Admin:admin");
    expect(screen.getByTestId("editor")).toHaveTextContent("true");
    expect(getAccessToken()).toBe("tok");
  });

  it("ranks reporter below editor", async () => {
    mockSignedIn(reporter);
    renderWithSession(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^authenticated$/));
    expect(screen.getByTestId("editor")).toHaveTextContent("false");
  });

  it("redirects to login with next when there is no session", async () => {
    mockSignedOut();
    nav.pathname = "/admin/posts";
    window.history.replaceState(null, "", "/admin/posts?status=draft");
    renderWithSession(<Probe />);
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent(/^unauthenticated$/),
    );
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith(
        "/admin/login?next=%2Fadmin%2Fposts%3Fstatus%3Ddraft",
      ),
    );
  });

  it("does not redirect while already on the login page", async () => {
    mockSignedOut();
    nav.pathname = "/admin/login";
    renderWithSession(<Probe />);
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent(/^unauthenticated$/),
    );
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("login keeps the token in memory and loads the profile", async () => {
    mockSignedOut();
    server.use(
      http.post("*/api/auth/login", () => HttpResponse.json({ access_token: "fresh" })),
      http.get("*/api/auth/me", () => HttpResponse.json(admin)),
    );
    nav.pathname = "/admin/login";
    renderWithSession(<Probe />);
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent(/^unauthenticated$/),
    );
    await userEvent.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^authenticated$/));
    expect(getAccessToken()).toBe("fresh");
    expect(JSON.stringify(localStorage)).not.toContain("fresh");
  });

  it("logout calls the API with the CSRF header and clears the session", async () => {
    mockSignedIn(admin);
    document.cookie = "mawa_csrf=csrf-1; path=/";
    let csrf: string | null = null;
    server.use(
      http.post("*/api/auth/logout", ({ request }) => {
        csrf = request.headers.get("x-csrf-token");
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithSession(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^authenticated$/));
    await userEvent.click(screen.getByText("logout"));
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent(/^unauthenticated$/),
    );
    expect(csrf).toBe("csrf-1");
    expect(getAccessToken()).toBeNull();
    expect(screen.getByTestId("who")).toHaveTextContent("nobody");
    document.cookie = "mawa_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });

  it("redirects to login when the API client reports auth:expired", async () => {
    mockSignedIn(admin);
    nav.pathname = "/admin/posts";
    window.history.replaceState(null, "", "/admin/posts");
    renderWithSession(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^authenticated$/));
    act(() => expireSession());
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent(/^unauthenticated$/),
    );
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/admin/login?next=%2Fadmin%2Fposts"),
    );
  });

  it("calls refresh once under StrictMode's double mount", async () => {
    let refreshes = 0;
    mockSignedIn(admin);
    server.use(
      http.post("*/api/auth/refresh", () => {
        refreshes++;
        return HttpResponse.json({ access_token: "tok" });
      }),
    );
    renderWithSession(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^authenticated$/));
    expect(refreshes).toBe(1);
  });

  it("explicit logout goes to plain /admin/login without next", async () => {
    mockSignedIn(admin);
    nav.pathname = "/admin/posts";
    window.history.replaceState(null, "", "/admin/posts?status=draft");
    server.use(http.post("*/api/auth/logout", () => new HttpResponse(null, { status: 204 })));
    renderWithSession(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^authenticated$/));
    await userEvent.click(screen.getByText("logout"));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/admin/login"));
    expect(router.replace).not.toHaveBeenCalledWith(expect.stringContaining("next="));
  });

  it("shows an error state, not a redirect, on a network failure; retry recovers", async () => {
    server.use(http.post("*/api/auth/refresh", () => HttpResponse.error()));
    nav.pathname = "/admin/posts";
    renderWithSession(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^error$/));
    expect(router.replace).not.toHaveBeenCalled();
    mockSignedIn(admin);
    await userEvent.click(screen.getByText("retry"));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^authenticated$/));
  });

  it("treats a 5xx from /me as an error state, not a sign-out", async () => {
    server.use(
      http.post("*/api/auth/refresh", () => HttpResponse.json({ access_token: "tok" })),
      http.get("*/api/auth/me", () =>
        HttpResponse.json(
          { error: { code: "INTERNAL", message: "x", details: {} } },
          { status: 503 },
        ),
      ),
    );
    nav.pathname = "/admin/posts";
    renderWithSession(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^error$/));
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("treats a 5xx from refresh as an error state", async () => {
    server.use(
      http.post("*/api/auth/refresh", () =>
        HttpResponse.json(
          { error: { code: "INTERNAL", message: "x", details: {} } },
          { status: 502 },
        ),
      ),
    );
    nav.pathname = "/admin/posts";
    renderWithSession(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(/^error$/));
    expect(router.replace).not.toHaveBeenCalled();
  });
});
