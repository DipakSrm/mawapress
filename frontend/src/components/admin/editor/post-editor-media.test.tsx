import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { PostOut } from "@/lib/admin/posts";
import { editor, mockSignedIn, renderWithSession, server, setupAdminTest } from "@/test/admin";
import { PostEditor } from "./post-editor";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const MEDIA = {
  id: "11111111-1111-4111-8111-111111111111",
  url: "/media/a.jpg",
  width: 1600,
  height: 900,
  alt_ne: "नदी",
  alt_en: "A river",
  caption: "Koshi in flood",
  variants: { "320": "/media/a-320.webp", "1024": "/media/a-1024.webp" },
};
const ORIGINAL_ONLY = {
  ...MEDIA,
  id: "22222222-2222-4222-8222-222222222222",
  url: "/media/b.jpg",
  alt_ne: null,
  alt_en: null,
  caption: "Only a caption",
  variants: {},
};

const post = {
  id: "p1",
  status: "draft",
  is_breaking: false,
  view_count: 0,
  author_id: editor.id,
  category_id: 1,
  featured_media_id: null,
  featured_media: null,
  published_at: null,
  scheduled_at: null,
  schedule_attempts: 0,
  schedule_last_error: null,
  updated_at: "2026-01-01T10:00:00Z",
  tags: [],
  translations: [
    {
      locale: "ne",
      title: "मोरङमा बाढी",
      slug: "morang",
      status: "draft",
      published_at: null,
      content_json: { type: "doc", content: [{ type: "paragraph" }] },
      content_html: "",
      seo_title: null,
      seo_description: null,
      excerpt: null,
      seo_auto: {},
    },
  ],
} as unknown as PostOut;

function mount() {
  mockSignedIn(editor);
  server.use(
    http.get("*/api/categories", () =>
      HttpResponse.json([
        {
          id: 1,
          slug: "politics",
          name_en: "Politics",
          name_ne: "राजनीति",
          parent_id: null,
          sort: 1,
          seo_description: null,
        },
      ]),
    ),
    http.get("*/api/tags", () => HttpResponse.json([])),
    http.get("*/api/media", () =>
      HttpResponse.json({ items: [MEDIA, ORIGINAL_ONLY], total: 2, limit: 24, offset: 0 }),
    ),
    http.patch("*/api/posts/:id", () => HttpResponse.json(post)),
  );
  renderWithSession(<PostEditor initial={post} />);
  return userEvent.setup();
}

describe("media picker in the editor", () => {
  it("inserts the 1024 variant with the Nepali alt text and the caption", async () => {
    const user = mount();
    await user.click(await screen.findByRole("button", { name: "Image" }));
    const dialog = await screen.findByRole("dialog", { name: "Insert an image" });
    await user.click(await within(dialog).findByRole("button", { name: "नदी" }));
    await user.click(within(dialog).getByRole("button", { name: "Use image" }));

    await waitFor(() => {
      const img = document.querySelector(".ProseMirror img");
      expect(img).toHaveAttribute("src", "/media/a-1024.webp");
      expect(img).toHaveAttribute("alt", "नदी");
    });
    expect(screen.queryByRole("dialog", { name: "Insert an image" })).toBeNull();
  });

  it("falls back to the original and to the caption when there is no variant or alt", async () => {
    const user = mount();
    await user.click(await screen.findByRole("button", { name: "Image" }));
    const dialog = await screen.findByRole("dialog", { name: "Insert an image" });
    await user.click(await within(dialog).findByRole("button", { name: "Only a caption" }));
    await user.click(within(dialog).getByRole("button", { name: "Use image" }));

    await waitFor(() => {
      const img = document.querySelector(".ProseMirror img");
      expect(img).toHaveAttribute("src", "/media/b.jpg");
      expect(img).toHaveAttribute("alt", "Only a caption");
    });
  });

  it("sets and removes the featured image", async () => {
    const user = mount();
    await user.click(await screen.findByRole("button", { name: "Choose image" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose the featured image" });
    await user.click(await within(dialog).findByRole("button", { name: "नदी" }));
    await user.click(within(dialog).getByRole("button", { name: "Use image" }));

    const featured = await screen.findByRole("img", { name: "नदी" });
    expect(featured).toHaveAttribute("src", "/media/a-320.webp");
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.queryByRole("img", { name: "नदी" })).toBeNull();
  });
});
