import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { getAccessToken } from "@/lib/api";
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
  const { status, user, role, hasRole, login, logout } = useSession();
  return (
    <div>
      <p data-testid="status">{status}</p>
      <p data-testid="who">{user ? `${user.name}:${role}` : "nobody"}</p>
      <p data-testid="editor">{String(hasRole("editor"))}</p>
      <button onClick={() => void login("a@b.c", "pw").catch(() => {})}>login</button>
      <button onClick={() => void logout()}>logout</button>
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
});
