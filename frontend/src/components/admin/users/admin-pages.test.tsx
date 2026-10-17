import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { getAccessToken } from "@/lib/api";
import { admin, mockSignedIn, renderWithSession, server, setupAdminTest } from "@/test/admin";
import { ProfilePage } from "../account/profile-page";
import { JobsPage } from "../jobs/jobs-page";
import { UsersPage } from "./users-page";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const apiError = (status: number, code: string) =>
  HttpResponse.json({ error: { code, message: code, details: {} } }, { status });

const USERS = [
  {
    id: admin.id,
    email: admin.email,
    name: admin.name,
    role: "admin",
    is_active: true,
    bio: null,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "u-2",
    email: "other@mawapress.test",
    name: "Other Admin",
    role: "admin",
    is_active: true,
    bio: null,
    created_at: "2026-01-02T00:00:00Z",
  },
];

describe("users page", () => {
  it("asks before demoting, then shows LAST_ADMIN when the server refuses", async () => {
    mockSignedIn(admin);
    let patches = 0;
    server.use(
      http.get("*/api/users", () => HttpResponse.json(USERS)),
      http.patch("*/api/users/:id", () => {
        patches++;
        return apiError(409, "LAST_ADMIN");
      }),
    );
    renderWithSession(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit Other Admin" }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Role"), "editor");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/will become Editor/);
    await user.click(within(dialog).getByRole("button", { name: "Confirm and save" }));
    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent(
        "At least one active admin must remain",
      ),
    );
    expect(patches).toBe(1);
  });

  it("shows CANNOT_MODIFY_SELF and EMAIL_TAKEN", async () => {
    mockSignedIn(admin);
    server.use(
      http.get("*/api/users", () => HttpResponse.json(USERS)),
      http.patch("*/api/users/:id", () => apiError(409, "CANNOT_MODIFY_SELF")),
      http.post("*/api/users", () => apiError(409, "EMAIL_TAKEN")),
    );
    renderWithSession(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: `Edit ${admin.name}` }));
    let dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Role"), "editor");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await user.click(await within(dialog).findByRole("button", { name: "Confirm and save" }));
    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent(/your own account/),
    );
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("button", { name: "New user" }));
    dialog = await screen.findByRole("dialog", { name: "New user" });
    await user.type(within(dialog).getByLabelText("Name"), "New Person");
    await user.type(within(dialog).getByLabelText("Email"), "other@mawapress.test");
    await user.type(within(dialog).getByLabelText("Password"), "long-enough-pass");
    await user.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/already uses that email/);
  });

  it("refuses a short password before calling the server", async () => {
    mockSignedIn(admin);
    const post = vi.fn();
    server.use(
      http.get("*/api/users", () => HttpResponse.json(USERS)),
      http.post("*/api/users/:id/password", () => {
        post();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithSession(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Reset password for Other Admin" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("New password"), "short");
    await user.click(within(dialog).getByRole("button", { name: "Reset password" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("at least 10");
    expect(post).not.toHaveBeenCalled();
  });
});

describe("jobs page", () => {
  const JOB = {
    id: 5,
    topic: "make_variants",
    attempts: 6,
    last_error: "boom",
    payload: { media_id: "abc" },
    created_at: "2026-01-01T00:00:00Z",
    next_attempt_at: null,
    dead_at: "2026-01-01T01:00:00Z",
  };

  it("retries one job and all dead jobs through the endpoints", async () => {
    mockSignedIn(admin);
    const calls: string[] = [];
    server.use(
      http.get("*/api/admin/jobs", ({ request }) =>
        HttpResponse.json(new URL(request.url).searchParams.get("state") === "dead" ? [JOB] : []),
      ),
      http.post("*/api/admin/jobs/:id/retry", ({ params }) => {
        calls.push(`retry ${params.id as string}`);
        return HttpResponse.json({ ...JOB, dead_at: null, attempts: 0 });
      }),
      http.post("*/api/admin/jobs/retry-dead", () => {
        calls.push("retry-dead");
        return HttpResponse.json({ requeued: 1 });
      }),
    );
    renderWithSession(<JobsPage />);
    const user = userEvent.setup();
    expect(await screen.findByText("Nothing waiting")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Dead letters" }));
    expect(await screen.findByText("make_variants")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show details of job 5" }));
    expect(screen.getByLabelText("Payload of job 5")).toHaveTextContent('"media_id": "abc"');

    await user.click(screen.getByRole("button", { name: "Retry job 5" }));
    await waitFor(() => expect(calls).toEqual(["retry 5"]));
    await user.click(screen.getByRole("button", { name: "Retry all dead" }));
    await waitFor(() => expect(calls).toEqual(["retry 5", "retry-dead"]));
  });
});

describe("profile page", () => {
  it("stores the new access token after a password change", async () => {
    mockSignedIn(admin);
    let body: unknown;
    server.use(
      http.patch("*/api/auth/me", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...admin, access_token: "fresh-token" });
      }),
    );
    renderWithSession(<ProfilePage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Current password"), "old-password-1");
    await user.type(screen.getByLabelText("New password"), "new-password-22");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => expect(getAccessToken()).toBe("fresh-token"));
    expect(body).toEqual({ current_password: "old-password-1", new_password: "new-password-22" });
    expect(screen.getByLabelText("Current password")).toHaveValue("");
  });

  it("treats a password change without a token as a sign-out", async () => {
    mockSignedIn(admin);
    server.use(http.patch("*/api/auth/me", () => HttpResponse.json({ ...admin })));
    renderWithSession(<ProfilePage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Current password"), "old-password-1");
    await user.type(screen.getByLabelText("New password"), "new-password-22");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => expect(getAccessToken()).toBeNull());
  });

  it("shows PASSWORD_UNCHANGED and keeps the current token", async () => {
    mockSignedIn(admin);
    server.use(http.patch("*/api/auth/me", () => apiError(422, "PASSWORD_UNCHANGED")));
    renderWithSession(<ProfilePage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Current password"), "same-password-1");
    await user.type(screen.getByLabelText("New password"), "same-password-1");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must be different");
    expect(getAccessToken()).toBe("tok");
  });

  it("saves name and bio and updates the session user", async () => {
    mockSignedIn(admin);
    server.use(
      http.patch("*/api/auth/me", async ({ request }) => {
        const body = (await request.json()) as { name: string; bio: string };
        return HttpResponse.json({ ...admin, name: body.name, bio: body.bio });
      }),
    );
    renderWithSession(<ProfilePage />);
    const user = userEvent.setup();
    const name = await screen.findByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Ada L.");
    await user.type(screen.getByLabelText("Bio"), "Desk editor");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.getByLabelText("Bio")).toHaveValue("Desk editor"));
    expect(await screen.findByLabelText("Name")).toHaveValue("Ada L.");
  });
});
