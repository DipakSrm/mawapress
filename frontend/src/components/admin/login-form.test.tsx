import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import {
  admin,
  mockSignedOut,
  nav,
  renderWithSession,
  router,
  server,
  setupAdminTest,
} from "@/test/admin";
import { LoginForm } from "./login-form";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

async function fillAndSubmit() {
  nav.pathname = "/admin/login";
  mockSignedOut();
  renderWithSession(<LoginForm />);
  await userEvent.type(screen.getByLabelText("Email"), "ed@mawapress.test");
  await userEvent.type(screen.getByLabelText("Password"), "hunter2hunter2");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

const failure = (status: number, code: string, headers: Record<string, string> = {}) =>
  HttpResponse.json({ error: { code, message: code, details: {} } }, { status, headers });

function mockLoginOk() {
  server.use(
    http.post("*/api/auth/login", () => HttpResponse.json({ access_token: "t" })),
    http.get("*/api/auth/me", () => HttpResponse.json(admin)),
  );
}

describe("login page", () => {
  it("signs in and redirects to the admin home", async () => {
    mockLoginOk();
    await fillAndSubmit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/admin"));
  });

  it("redirects to a safe next path", async () => {
    nav.search = "?next=%2Fadmin%2Fposts%3Fstatus%3Ddraft";
    mockLoginOk();
    await fillAndSubmit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/admin/posts?status=draft"));
  });

  it("ignores an off-site next path", async () => {
    nav.search = "?next=%2F%2Fevil.example";
    mockLoginOk();
    await fillAndSubmit();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/admin"));
  });

  it("shows a message for invalid credentials", async () => {
    server.use(http.post("*/api/auth/login", () => failure(401, "INVALID_CREDENTIALS")));
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("shows the wait time on a 429", async () => {
    server.use(
      http.post("*/api/auth/login", () => failure(429, "RATE_LIMITED", { "Retry-After": "90" })),
    );
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 2 minutes.");
  });

  it("shows seconds for a short wait", async () => {
    server.use(
      http.post("*/api/auth/login", () => failure(429, "RATE_LIMITED", { "Retry-After": "30" })),
    );
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 30 seconds.");
  });

  it("keeps the button enabled and validates on submit", async () => {
    nav.pathname = "/admin/login";
    mockSignedOut();
    renderWithSession(<LoginForm />);
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter your email address.");
    expect(screen.getByLabelText("Email")).toHaveFocus();
    await userEvent.type(screen.getByLabelText("Email"), "ed@mawapress.test");
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter your password.");
    expect(screen.getByLabelText("Password")).toHaveFocus();
  });

  it("points the inputs at the error with aria-describedby", async () => {
    server.use(http.post("*/api/auth/login", () => failure(401, "INVALID_CREDENTIALS")));
    await fillAndSubmit();
    const alert = await screen.findByRole("alert");
    for (const label of ["Email", "Password"]) {
      const input = screen.getByLabelText(label);
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(input.getAttribute("aria-describedby")).toBe(alert.id);
    }
  });
});
