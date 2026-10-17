import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { PostOut } from "@/lib/admin/posts";
import {
  editor,
  mockSignedIn,
  renderWithSession,
  router,
  server,
  setupAdminTest,
} from "@/test/admin";
import { ImportDocxDialog, importErrorMessage } from "./import-docx-dialog";
import { PostEditor } from "./post-editor";
import { ApiError } from "@/lib/api";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const CATEGORIES = [
  {
    id: 1,
    slug: "politics",
    name_en: "Politics",
    name_ne: "राजनीति",
    parent_id: null,
    sort: 1,
    seo_description: null,
  },
];

const docx = () =>
  new File(["PK"], "report.docx", {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });

async function openImport() {
  mockSignedIn(editor);
  server.use(http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)));
  renderWithSession(<ImportDocxDialog onClose={() => {}} />);
  const user = userEvent.setup();
  await screen.findByRole("option", { name: "राजनीति" });
  await user.selectOptions(screen.getByLabelText("Category"), "1");
  return user;
}

const importError = (status: number, code: string, headers: Record<string, string> = {}) =>
  HttpResponse.json({ error: { code, message: code, details: {} } }, { status, headers });

describe("import from Word", () => {
  it("shows the import report warnings, then opens the new draft", async () => {
    let form: FormData | undefined;
    server.use(
      http.post("*/api/import/docx", async ({ request }) => {
        form = await request.formData();
        return HttpResponse.json(
          {
            post: { id: "imp-1" },
            report: { images: 2, warnings: ["Dropped a text box", "Shape approximated"] },
          },
          { status: 201 },
        );
      }),
    );
    const user = await openImport();
    await user.upload(screen.getByLabelText("Word file"), docx());
    await user.click(screen.getByRole("button", { name: "Import" }));

    const warnings = await screen.findByRole("list", { name: "Import warnings" });
    expect(within(warnings).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText(/2 images imported/)).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
    expect(form?.get("locale")).toBe("ne");
    expect(form?.get("category_id")).toBe("1");
    expect((form?.get("file") as File).size).toBe(2);

    await user.click(screen.getByRole("button", { name: "Open draft" }));
    expect(router.push).toHaveBeenCalledWith("/admin/posts/imp-1");
  });

  it("goes straight to the draft when there is nothing to warn about", async () => {
    server.use(
      http.post("*/api/import/docx", () =>
        HttpResponse.json(
          { post: { id: "imp-2" }, report: { images: 0, warnings: [] } },
          { status: 201 },
        ),
      ),
    );
    const user = await openImport();
    await user.upload(screen.getByLabelText("Word file"), docx());
    await user.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/admin/posts/imp-2"));
  });

  it("tells the user when the converter is busy and counts down the retry", async () => {
    server.use(
      http.post("*/api/import/docx", () => importError(503, "IMPORT_BUSY", { "Retry-After": "3" })),
    );
    const user = await openImport();
    await user.upload(screen.getByLabelText("Word file"), docx());
    await user.click(screen.getByRole("button", { name: "Import" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Other Word files are being converted right now.");
    expect(alert).toHaveTextContent("Try again in 3 seconds");
    expect(screen.getByRole("button", { name: "Try again" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled(), {
      timeout: 4500,
    });
  });

  it.each([
    [413, "DOCX_TOO_LARGE", /over 15 MB/],
    [415, "NOT_A_DOCX", /not a Word \(\.docx\) file/],
    [422, "DOCX_UNREADABLE", /could not read that file/],
  ])("explains a %i %s response", async (status, code, text) => {
    server.use(http.post("*/api/import/docx", () => importError(status, code)));
    const user = await openImport();
    await user.upload(screen.getByLabelText("Word file"), docx());
    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("maps the codes to friendly text", () => {
    expect(importErrorMessage(new ApiError(413, "FILE_TOO_LARGE", "x"))).toMatch(/15 MB/);
    expect(importErrorMessage(new ApiError(0, "NETWORK_ERROR", "x"))).toMatch(/Could not reach/);
  });

  it("rejects a file that is not .docx before uploading", async () => {
    const user = await openImport();
    await user.upload(
      screen.getByLabelText("Word file"),
      new File(["x"], "notes.pdf", { type: "application/pdf" }),
      // The file input filters by `accept`; skip that so the extension check is what we test.
    );
    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

const T0 = "2026-01-01T10:00:00Z";
const T1 = "2026-01-01T10:05:00Z";

function post(over: Partial<PostOut> = {}): PostOut {
  return {
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
    updated_at: T0,
    translations: [
      {
        locale: "en",
        title: "Current title",
        slug: "current-title",
        status: "draft",
        published_at: null,
        content_json: {
          type: "doc",
          content: [{ type: "paragraph", content: [{ type: "text", text: "Now" }] }],
        },
        content_html: "",
        seo_title: null,
        seo_description: null,
        excerpt: null,
        seo_auto: {},
      },
    ],
    tags: [],
    ...over,
  } as unknown as PostOut;
}

describe("revisions drawer", () => {
  it("lists revisions, shows one read only and restores it with If-Match", async () => {
    mockSignedIn(editor);
    let restoreHeader: string | null = null;
    server.use(
      http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)),
      http.get("*/api/posts/p1/revisions", ({ request }) => {
        expect(new URL(request.url).searchParams.get("locale")).toBe("en");
        return HttpResponse.json({
          total: 1,
          limit: 10,
          offset: 0,
          items: [
            {
              id: 7,
              locale: "en",
              title: "Older title",
              slug: "older",
              seo_title: null,
              seo_description: null,
              excerpt: null,
              editor_id: editor.id,
              created_at: "2025-12-31T09:00:00Z",
            },
          ],
        });
      }),
      http.get("*/api/posts/p1/revisions/7", () =>
        HttpResponse.json({
          id: 7,
          locale: "en",
          title: "Older title",
          slug: "older",
          seo_title: null,
          seo_description: null,
          excerpt: null,
          editor_id: editor.id,
          created_at: "2025-12-31T09:00:00Z",
          content_json: {
            type: "doc",
            content: [{ type: "paragraph", content: [{ type: "text", text: "Old words" }] }],
          },
        }),
      ),
      http.post("*/api/posts/p1/revisions/7/restore", ({ request }) => {
        restoreHeader = request.headers.get("if-match");
        return HttpResponse.json(
          post({
            updated_at: T1,
            translations: [{ ...post().translations[0], title: "Older title" }],
          } as Partial<PostOut>),
        );
      }),
    );
    renderWithSession(<PostEditor initial={post()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Revisions" }));

    const item = await screen.findByRole("button", { name: /Older title/ });
    expect(item).toHaveTextContent("You");
    await user.click(item);
    expect(await screen.findByText("Old words")).toBeInTheDocument();
    expect(screen.getAllByRole("textbox", { name: "Revision text" })[0]).toHaveAttribute(
      "contenteditable",
      "false",
    );

    await user.click(screen.getByRole("button", { name: "Restore this version" }));
    const dialog = await screen.findByRole("dialog", { name: "Restore this revision?" });
    await user.click(within(dialog).getByRole("button", { name: "Restore" }));

    await waitFor(() => expect(restoreHeader).toBe(T0));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Older title"),
    );
  });

  it("hides Restore from a reporter", async () => {
    mockSignedIn({ ...editor, role: "reporter" });
    server.use(
      http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)),
      http.get("*/api/posts/p1/revisions", () =>
        HttpResponse.json({
          total: 1,
          limit: 10,
          offset: 0,
          items: [
            {
              id: 7,
              locale: "en",
              title: "Older",
              slug: "o",
              seo_title: null,
              seo_description: null,
              excerpt: null,
              editor_id: "x",
              created_at: "2025-12-31T09:00:00Z",
            },
          ],
        }),
      ),
      http.get("*/api/posts/p1/revisions/7", () =>
        HttpResponse.json({
          id: 7,
          locale: "en",
          title: "Older",
          slug: "o",
          seo_title: null,
          seo_description: null,
          excerpt: null,
          editor_id: "x",
          created_at: "2025-12-31T09:00:00Z",
          content_json: { type: "doc", content: [{ type: "paragraph" }] },
        }),
      ),
    );
    renderWithSession(<PostEditor initial={post()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Revisions" }));
    await user.click(await screen.findByRole("button", { name: /Older/ }));
    await screen.findByRole("button", { name: "All revisions" });
    expect(screen.queryByRole("button", { name: "Restore this version" })).toBeNull();
  });
});

describe("tags and featured image", () => {
  it("lets an editor create a tag from the search box and adds it to the post", async () => {
    mockSignedIn(editor);
    let created: unknown;
    server.use(
      http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)),
      http.get("*/api/tags", () => HttpResponse.json([])),
      http.post("*/api/tags", async ({ request }) => {
        created = await request.json();
        return HttpResponse.json(
          { id: 9, slug: "floods", name_ne: "floods", name_en: "floods" },
          { status: 201 },
        );
      }),
    );
    renderWithSession(<PostEditor initial={post()} />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Tags"), "floods");
    await user.click(await screen.findByRole("option", { name: /Create “floods”/ }));
    await waitFor(() => expect(created).toEqual({ name_ne: "floods", name_en: "floods" }));
    expect(await screen.findByRole("button", { name: "Remove tag floods" })).toBeInTheDocument();
  });

  it("does not offer tag creation to a reporter", async () => {
    mockSignedIn({ ...editor, role: "reporter" });
    server.use(
      http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)),
      http.get("*/api/tags", () => HttpResponse.json([])),
    );
    renderWithSession(<PostEditor initial={post()} />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Tags"), "floods");
    await act(async () => {});
    expect(screen.queryByRole("option", { name: /Create/ })).toBeNull();
  });
});

describe("leave guard", () => {
  it("asks before following a link with unsaved changes", async () => {
    mockSignedIn(editor);
    server.use(http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)));
    renderWithSession(<PostEditor initial={post()} />);
    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: "Title" }), "!");
    await user.click(screen.getByRole("link", { name: /Posts/ }));

    const dialog = await screen.findByRole("dialog", { name: "Leave with unsaved changes?" });
    await user.click(within(dialog).getByRole("button", { name: "Leave anyway" }));
    expect(router.push).toHaveBeenCalledWith("/admin/posts");
  });

  it("lets a link through when everything is saved", async () => {
    mockSignedIn(editor);
    server.use(http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)));
    renderWithSession(<PostEditor initial={post()} />);
    const user = userEvent.setup();
    await screen.findByRole("textbox", { name: "Title" });
    const stop = (e: Event) => e.preventDefault(); // jsdom cannot navigate
    document.addEventListener("click", stop);
    await user.click(screen.getByRole("link", { name: /Posts/ }));
    document.removeEventListener("click", stop);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
