import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import {
  admin,
  editor,
  mockSignedIn,
  mockSignedOut,
  nav,
  renderWithSession,
  reporter,
  router,
  server,
  setupAdminTest,
} from "@/test/admin";
import { AdminGuard } from "./admin-guard";
import { RequireRole } from "./require-role";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const page = (
  <AdminGuard>
    <p>secret page</p>
  </AdminGuard>
);

describe("admin guard", () => {
  it("shows a skeleton, then redirects to login when unauthenticated", async () => {
    mockSignedOut();
    nav.pathname = "/admin/posts";
    renderWithSession(page);
    expect(screen.getByRole("status", { name: "Loading admin" })).toBeInTheDocument();
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/admin/login?next=%2Fadmin%2Fposts"),
    );
    expect(screen.queryByText("secret page")).not.toBeInTheDocument();
  });

  it("shows a retryable error instead of redirecting when the server is unreachable", async () => {
    server.use(http.post("*/api/auth/refresh", () => HttpResponse.error()));
    nav.pathname = "/admin/posts";
    renderWithSession(page);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not check your session");
    expect(router.replace).not.toHaveBeenCalled();
    mockSignedIn(editor);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("secret page")).toBeInTheDocument();
  });

  it("renders the page inside the shell once signed in", async () => {
    mockSignedIn(editor);
    renderWithSession(page);
    expect(await screen.findByText("secret page")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("hides admin-only nav items from reporters", async () => {
    mockSignedIn(reporter);
    renderWithSession(page);
    await screen.findByText("secret page");
    const sidebar = screen.getAllByRole("navigation", { name: "Admin" })[0];
    for (const label of [
      "Dashboard",
      "Posts",
      "New post",
      "Media",
      "Categories",
      "Tags",
      "Profile",
    ]) {
      expect(within(sidebar).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(within(sidebar).queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("link", { name: "Jobs" })).not.toBeInTheDocument();
  });

  it("shows admin-only nav items to admins", async () => {
    mockSignedIn(admin);
    renderWithSession(page);
    await screen.findByText("secret page");
    const sidebar = screen.getAllByRole("navigation", { name: "Admin" })[0];
    expect(within(sidebar).getByRole("link", { name: "Users" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "Jobs" })).toBeInTheDocument();
  });
});

describe("role gate", () => {
  it("shows the 403 view below the required role", async () => {
    mockSignedIn(reporter);
    renderWithSession(
      <AdminGuard>
        <RequireRole min="admin">
          <p>users page</p>
        </RequireRole>
      </AdminGuard>,
    );
    expect(await screen.findByText(/403/)).toBeInTheDocument();
    expect(screen.queryByText("users page")).not.toBeInTheDocument();
  });

  it("renders children at or above the role", async () => {
    mockSignedIn(admin);
    renderWithSession(
      <AdminGuard>
        <RequireRole min="admin">
          <p>users page</p>
        </RequireRole>
      </AdminGuard>,
    );
    expect(await screen.findByText("users page")).toBeInTheDocument();
  });
});
