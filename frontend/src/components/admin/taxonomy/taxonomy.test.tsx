import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { buildTree, flattenTree, subtreeIds, type Category } from "@/lib/admin/taxonomy";
import { editor, mockSignedIn, renderWithSession, server, setupAdminTest } from "@/test/admin";
import { CategoriesPage } from "./categories-page";
import { TagsPage } from "./tags-page";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const cat = (id: number, parent_id: number | null, en: string, sort = 0): Category => ({
  id,
  parent_id,
  slug: en.toLowerCase(),
  name_en: en,
  name_ne: `${en}-ne`,
  sort,
  seo_description: null,
});
const CATS = [cat(1, null, "News"), cat(2, null, "Sports", 1), cat(3, 1, "Local")];

const apiError = (status: number, code: string, details: Record<string, unknown> = {}) =>
  HttpResponse.json({ error: { code, message: code, details } }, { status });

describe("category tree helpers", () => {
  it("nests children under their parent, ordered by sort", () => {
    const rows = flattenTree(buildTree(CATS)).map((n) => [n.category.name_en, n.depth]);
    expect(rows).toEqual([
      ["News", 1],
      ["Local", 2],
      ["Sports", 1],
    ]);
  });

  it("finds a subtree", () => {
    expect([...subtreeIds(CATS, 1)].sort()).toEqual([1, 3]);
  });
});

describe("categories page", () => {
  it("shows the cycle error when the server refuses a move", async () => {
    mockSignedIn(editor);
    server.use(
      http.get("*/api/categories", () => HttpResponse.json(CATS)),
      http.patch("*/api/categories/:id", () => apiError(409, "CATEGORY_CYCLE")),
    );
    renderWithSession(<CategoriesPage />);
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Parent of Sports"), "1");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Could not move “Sports”.*cannot be moved under itself/,
    );
  });

  it("shows the counts when a category is still in use", async () => {
    mockSignedIn(editor);
    server.use(
      http.get("*/api/categories", () => HttpResponse.json(CATS)),
      http.delete("*/api/categories/:id", () =>
        apiError(409, "CATEGORY_IN_USE", { posts: 4, children: 1 }),
      ),
    );
    renderWithSession(<CategoriesPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete News" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("4 posts and 1 subcategory");
  });

  it("creates a category and explains that the slug is permanent", async () => {
    mockSignedIn(editor);
    let body: unknown;
    server.use(
      http.get("*/api/categories", () => HttpResponse.json(CATS)),
      http.post("*/api/categories", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(cat(9, null, "Culture"), { status: 201 });
      }),
    );
    renderWithSession(<CategoriesPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "New category" }));
    expect(screen.getByText(/cannot be changed later/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Name (नेपाली)"), "संस्कृति");
    await user.type(screen.getByLabelText("Name (English)"), "Culture");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await vi.waitFor(() =>
      expect(body).toMatchObject({ name_ne: "संस्कृति", name_en: "Culture", parent_id: null }),
    );
  });
});

describe("tags page", () => {
  it("lists, searches and renames a tag", async () => {
    mockSignedIn(editor);
    const seen: string[] = [];
    let patch: unknown;
    server.use(
      http.get("*/api/tags", ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("q") ?? "");
        return HttpResponse.json([{ id: 1, slug: "flood", name_en: "Flood", name_ne: "बाढी" }]);
      }),
      http.patch("*/api/tags/:id", async ({ request }) => {
        patch = await request.json();
        return HttpResponse.json({ id: 1, slug: "flood", name_en: "Floods", name_ne: "बाढी" });
      }),
    );
    renderWithSession(<TagsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Rename Flood" }));
    expect(screen.getByLabelText("Address (slug)")).toHaveAttribute("readonly");
    const en = screen.getByLabelText("Name (English)");
    await user.clear(en);
    await user.type(en, "Floods");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(patch).toEqual({ name_ne: "बाढी", name_en: "Floods" }));
    expect(seen[0]).toBe("");
  });
});
