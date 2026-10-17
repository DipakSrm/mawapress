import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import {
  editor,
  mockSignedIn,
  renderWithSession,
  router,
  server,
  setupAdminTest,
} from "@/test/admin";
import { NewPostForm } from "./new-post-form";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const CATEGORIES = [
  { id: 1, slug: "politics", name_en: "Politics", name_ne: "राजनीति", parent_id: null, sort: 1 },
  { id: 2, slug: "sports", name_en: "Sports", name_ne: "खेलकुद", parent_id: null, sort: 2 },
];

function setup() {
  mockSignedIn(editor);
  server.use(http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)));
  renderWithSession(<NewPostForm />);
  return screen.findByRole("option", { name: "Sports" });
}

describe("new post form", () => {
  it("creates the post and goes to its page", async () => {
    let body: unknown;
    server.use(
      http.post("*/api/posts", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "new-id" }, { status: 201 });
      }),
    );
    await setup();
    await userEvent.type(screen.getByLabelText("Title"), "  मोरङमा बाढी ");
    await userEvent.selectOptions(screen.getByLabelText("Category"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/admin/posts/new-id"));
    expect(body).toMatchObject({ locale: "ne", title: "मोरङमा बाढी", category_id: 2 });
    expect((body as { content_json: { type: string } }).content_json.type).toBe("doc");
  });

  it("sends the chosen language", async () => {
    let body: unknown;
    server.use(
      http.post("*/api/posts", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "x" }, { status: 201 });
      }),
    );
    await setup();
    await userEvent.type(screen.getByLabelText("Title"), "Flood");
    await userEvent.selectOptions(screen.getByLabelText("Language"), "en");
    await userEvent.selectOptions(screen.getByLabelText("Category"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(body).toMatchObject({ locale: "en", category_id: 1 });
  });

  it("validates on submit and describes the error on the field", async () => {
    await setup();
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Enter a title.");
    expect(screen.getByLabelText("Title")).toHaveFocus();
    expect(screen.getByLabelText("Title").getAttribute("aria-describedby")).toBe(alert.id);
    await userEvent.type(screen.getByLabelText("Title"), "Story");
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a category.");
    expect(router.push).not.toHaveBeenCalled();
  });

  it("shows the API error and stays on the page", async () => {
    server.use(
      http.post("*/api/posts", () =>
        HttpResponse.json(
          {
            error: { code: "CATEGORY_NOT_FOUND", message: "Category does not exist", details: {} },
          },
          { status: 404 },
        ),
      ),
    );
    await setup();
    await userEvent.type(screen.getByLabelText("Title"), "Story");
    await userEvent.selectOptions(screen.getByLabelText("Category"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Category does not exist");
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Create draft" })).toBeEnabled();
  });
});
