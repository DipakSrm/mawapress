import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PostOut } from "@/lib/admin/posts";
import {
  editor,
  mockSignedIn,
  renderWithSession,
  reporter,
  server,
  setupAdminTest,
  type TestUser,
} from "@/test/admin";
import { PostEditor } from "./post-editor";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const T0 = "2026-01-01T10:00:00Z";
const T1 = "2026-01-01T10:05:00Z";
const T2 = "2026-01-01T10:09:00Z";

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
  {
    id: 2,
    slug: "sports",
    name_en: "Sports",
    name_ne: "खेलकुद",
    parent_id: null,
    sort: 2,
    seo_description: null,
  },
];

const doc = (text: string) => ({
  type: "doc",
  content: [{ type: "paragraph", content: [{ type: "text", text }] }],
});

type Tr = PostOut["translations"][number];

function translation(locale: "ne" | "en", over: Partial<Tr> = {}): Tr {
  return {
    locale,
    title: locale === "ne" ? "मोरङमा बाढी" : "Flood in Morang",
    slug: locale === "ne" ? "morang-baadhi" : "flood-in-morang",
    status: "draft",
    published_at: null,
    content_json: doc(locale === "ne" ? "बाढीले क्षति पुर्‍यायो" : "The flood caused damage"),
    content_html: "",
    seo_title: null,
    seo_description: null,
    excerpt: null,
    seo_auto: {},
    ...over,
  };
}

function makePost(over: Partial<PostOut> = {}): PostOut {
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
    feedback_note: null,
    feedback_by: null,
    feedback_by_name: null,
    feedback_at: null,
    created_at: T0,
    updated_at: T0,
    translations: [translation("ne")],
    tags: [],
    ...over,
  } as unknown as PostOut;
}

interface Seen {
  method: string;
  url: string;
  ifMatch: string | null;
  body: Record<string, unknown> | undefined;
}

function captureWrites(respond: (seen: Seen, n: number) => Response | Promise<Response>) {
  const calls: Seen[] = [];
  const handle = async ({ request }: { request: Request }) => {
    const text = await request.text();
    const seen: Seen = {
      method: request.method,
      url: new URL(request.url).pathname,
      ifMatch: request.headers.get("if-match"),
      body: text ? (JSON.parse(text) as Record<string, unknown>) : undefined,
    };
    calls.push(seen);
    return respond(seen, calls.length);
  };
  server.use(
    http.patch("*/api/posts/:id", handle),
    http.post("*/api/posts", handle),
    http.post("*/api/posts/:id/:action", handle),
    http.post("*/api/posts/:id/translations/:locale/publish", handle),
  );
  return calls;
}

const patchOk = (post: PostOut) => HttpResponse.json(post);

function mount(post: PostOut | null, user: TestUser = editor) {
  mockSignedIn(user);
  server.use(http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)));
  server.use(http.get("*/api/tags", () => HttpResponse.json([])));
  const ui = renderWithSession(<PostEditor initial={post} />);
  return { ...ui, user: userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) }) };
}

const title = () => screen.findByRole("textbox", { name: "Title" });
const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

beforeEach(() => {
  window.localStorage.clear();
  vi.useFakeTimers({
    shouldAdvanceTime: true,
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
});
afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

describe("autosave", () => {
  it("saves 10 seconds after a change, sending only the changed field with If-Match", async () => {
    const calls = captureWrites(() => patchOk(makePost({ updated_at: T1 })));
    const { user } = mount(makePost());
    await user.type(await title(), "!");

    await advance(9000);
    expect(calls).toHaveLength(0);
    await advance(1500);
    await waitFor(() => expect(calls).toHaveLength(1));

    expect(calls[0]).toMatchObject({
      method: "PATCH",
      url: "/api/posts/p1",
      ifMatch: T0,
      body: { locale: "ne", title: "मोरङमा बाढी!" },
    });
    expect(Object.keys(calls[0].body!).sort()).toEqual(["locale", "title"]);
    expect(await screen.findByText(/^Saved ·/)).toBeInTheDocument();
  });

  it("uses the updated_at of the last response for the next save", async () => {
    const calls = captureWrites((_, n) => patchOk(makePost({ updated_at: n === 1 ? T1 : T2 })));
    const { user } = mount(makePost());
    await user.type(await title(), "a");
    await advance(10_500);
    await waitFor(() => expect(calls).toHaveLength(1));
    await screen.findByText(/^Saved ·/);

    await user.type(await title(), "b");
    await advance(10_500);
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].ifMatch).toBe(T1);
  });

  it("saves at once with Ctrl+S and when focus leaves the editor", async () => {
    const calls = captureWrites(() => patchOk(makePost({ updated_at: T1 })));
    const { user } = mount(makePost());
    await user.type(await title(), "x");
    await user.keyboard("{Control>}s{/Control}");
    await waitFor(() => expect(calls).toHaveLength(1));

    await user.type(await title(), "y");
    await user.click(document.body); // focus leaves the editing area
    await waitFor(() => expect(calls).toHaveLength(2));
  });

  it("shows 'Not saved — retrying' on a server error and retries with backoff", async () => {
    const calls = captureWrites((_, n) =>
      n === 1
        ? HttpResponse.json(
            { error: { code: "INTERNAL_ERROR", message: "boom", details: {} } },
            { status: 500 },
          )
        : patchOk(makePost({ updated_at: T1 })),
    );
    const { user } = mount(makePost());
    await user.type(await title(), "!");
    await user.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText("Not saved — retrying")).toBeInTheDocument();

    await advance(2500);
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(await screen.findByText(/^Saved ·/)).toBeInTheDocument();
  });

  it("shows Offline instead of retrying while the browser is offline", async () => {
    const online = vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    captureWrites(() => HttpResponse.error());
    const { user } = mount(makePost());
    await user.type(await title(), "!");
    await user.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText("Offline")).toBeInTheDocument();
    online.mockRestore();
  });
});

describe("conflicts", () => {
  const conflict = () =>
    HttpResponse.json(
      {
        error: {
          code: "VERSION_CONFLICT",
          message: "changed",
          details: { current_updated_at: T2 },
        },
      },
      { status: 412 },
    );

  it("offers to overwrite, resending with their updated_at", async () => {
    const calls = captureWrites((_, n) =>
      n === 1 ? conflict() : patchOk(makePost({ updated_at: "2026-01-01T10:20:00Z" })),
    );
    server.use(http.get("*/api/posts/p1", () => HttpResponse.json(makePost({ updated_at: T2 }))));
    const { user } = mount(makePost());
    await user.type(await title(), "!");
    await user.keyboard("{Control>}s{/Control}");

    expect(await screen.findByText("Someone else edited this post")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Overwrite" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].ifMatch).toBe(T2);
    expect(calls[1].body).toMatchObject({ title: "मोरङमा बाढी!" });
    await waitFor(() => expect(screen.queryByText("Someone else edited this post")).toBeNull());
  });

  it("loads their version, keeps my copy locally and offers to restore it", async () => {
    captureWrites(() => conflict());
    server.use(
      http.get("*/api/posts/p1", () =>
        HttpResponse.json(
          makePost({
            updated_at: T2,
            translations: [translation("ne", { title: "Their headline" })],
          }),
        ),
      ),
    );
    const { user } = mount(makePost());
    await user.type(await title(), "!");
    await user.keyboard("{Control>}s{/Control}");
    await user.click(await screen.findByRole("button", { name: "Load their version" }));

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Their headline"),
    );
    expect(screen.queryByText("Someone else edited this post")).toBeNull();
    expect(JSON.parse(window.localStorage.getItem("mawapress:kept:u-ed:p1:ne")!).fields.title).toBe(
      "मोरङमा बाढी!",
    );

    await user.click(await screen.findByRole("button", { name: "Restore unsaved changes" }));
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("मोरङमा बाढी!");
  });
});

const SHARED = { categoryId: 1, tags: [], featuredMedia: null, isBreaking: false };
const storedFields = (over: Record<string, string>) => ({
  title: "मोरङमा बाढी",
  content: doc("बाढीले क्षति पुर्‍यायो"),
  excerpt: "",
  seoTitle: "",
  seoDescription: "",
  slug: "morang-baadhi",
  ...over,
});

describe("local copy", () => {
  it("offers to restore a newer unsaved copy and applies it", async () => {
    window.localStorage.setItem(
      "mawapress:draft:u-ed:p1:ne",
      JSON.stringify({
        savedAt: Date.now() + 1000,
        locale: "ne",
        fields: {
          title: "Unsaved title",
          content: doc("Unsaved body"),
          excerpt: "",
          seoTitle: "",
          seoDescription: "",
          slug: "morang-baadhi",
        },
        shared: { categoryId: 1, tags: [], featuredMedia: null, isBreaking: false },
      }),
    );
    const { user } = mount(makePost());
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("मोरङमा बाढी");
    await user.click(await screen.findByRole("button", { name: "Restore unsaved changes" }));
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Unsaved title");
    expect(await screen.findByText("Unsaved changes")).toBeInTheDocument();
  });

  it("offers a copy older than the server version, labelled, and restores it as a merge", async () => {
    // The copy was made against the original post (title "मोरङमा बाढी", no excerpt) and only the title
    // was edited. The server has since changed the title and added an excerpt.
    window.localStorage.setItem(
      "mawapress:draft:u-ed:p1:ne",
      JSON.stringify({
        savedAt: Date.parse(T0) - 1000,
        locale: "ne",
        fields: { ...storedFields({ title: "Local title" }) },
        shared: SHARED,
        base: storedFields({}),
        baseShared: SHARED,
      }),
    );
    const server = makePost({
      updated_at: T1,
      translations: [translation("ne", { title: "Server title", excerpt: "Server excerpt" })],
    });
    const { user } = mount(server);
    expect(
      await screen.findByText(/Saved on this device before the latest server version/),
    ).toBeInTheDocument();
    // The offer holds the copy in the kept slot; nothing deleted it.
    expect(JSON.parse(window.localStorage.getItem("mawapress:kept:u-ed:p1:ne")!).fields.title).toBe(
      "Local title",
    );
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Server title");

    await user.click(screen.getByRole("button", { name: "Restore unsaved changes" }));
    // Edited field: the user's value. Untouched field: the server's value.
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Local title");
    expect(screen.getByLabelText("Excerpt")).toHaveValue("Server excerpt");
  });

  it("merges a kept copy with a newer live copy instead of dropping the older one", async () => {
    const base = storedFields({});
    window.localStorage.setItem(
      "mawapress:kept:u-ed:p1:ne",
      JSON.stringify({
        savedAt: Date.now() + 1000,
        locale: "ne",
        fields: storedFields({ title: "Kept title", excerpt: "Kept excerpt" }),
        shared: SHARED,
        base,
        baseShared: SHARED,
      }),
    );
    window.localStorage.setItem(
      "mawapress:draft:u-ed:p1:ne",
      JSON.stringify({
        savedAt: Date.now() + 5000,
        locale: "ne",
        fields: storedFields({ title: "Live title" }),
        shared: SHARED,
        base,
        baseShared: SHARED,
      }),
    );
    const { user } = mount(makePost());
    await user.click(await screen.findByRole("button", { name: "Restore unsaved changes" }));
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Live title"); // newer wins
    expect(screen.getByLabelText("Excerpt")).toHaveValue("Kept excerpt"); // older one's edit survives
  });

  it("never shows another user's local copies", async () => {
    const copy = JSON.stringify({
      savedAt: Date.now() + 1000,
      locale: "ne",
      fields: storedFields({ title: "Reporter's secret draft" }),
      shared: SHARED,
    });
    window.localStorage.setItem("mawapress:draft:u-rep:p1:ne", copy);
    const { user } = mount(makePost()); // signed in as the editor
    await title();
    expect(screen.queryByRole("button", { name: "Restore unsaved changes" })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!");
    await advance(1000);
    // The editor's own copy is under the editor's key; the reporter's is untouched.
    expect(window.localStorage.getItem("mawapress:draft:u-ed:p1:ne")).not.toBeNull();
    expect(window.localStorage.getItem("mawapress:draft:u-rep:p1:ne")).toBe(copy);
  });

  it("ignores copies stored under the old unscoped key", async () => {
    window.localStorage.setItem(
      "mawapress:draft:p1:ne",
      JSON.stringify({
        savedAt: Date.now() + 1000,
        locale: "ne",
        fields: storedFields({ title: "Unscoped" }),
        shared: SHARED,
      }),
    );
    mount(makePost());
    await title();
    expect(screen.queryByRole("button", { name: "Restore unsaved changes" })).toBeNull();
  });

  it("writes the local copy right away when the screen unmounts inside the debounce window", async () => {
    const { user, unmount } = mount(makePost());
    await user.type(await title(), "?");
    expect(window.localStorage.getItem("mawapress:draft:u-ed:p1:ne")).toBeNull(); // still debounced
    unmount();
    expect(
      JSON.parse(window.localStorage.getItem("mawapress:draft:u-ed:p1:ne")!).fields.title,
    ).toBe("मोरङमा बाढी?");
  });

  it("hides Restore (keeping the copy) when the post is read only for the user", async () => {
    window.localStorage.setItem(
      "mawapress:draft:u-rep:p1:ne",
      JSON.stringify({
        savedAt: Date.now() + 1000,
        locale: "ne",
        fields: storedFields({ title: "Mine" }),
        shared: SHARED,
      }),
    );
    mount(makePost({ author_id: "someone-else" }), reporter);
    expect(await screen.findByText("Unsaved changes found")).toBeInTheDocument();
    expect(screen.getByText("Read only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore unsaved changes" })).toBeNull();
    expect(screen.getByRole("button", { name: "Discard" })).toBeInTheDocument();
    expect(window.localStorage.getItem("mawapress:kept:u-rep:p1:ne")).not.toBeNull();
  });

  it("keeps the draft in localStorage while changes are unsaved", async () => {
    const { user } = mount(makePost());
    await user.type(await title(), "?");
    await advance(1000);
    expect(
      JSON.parse(window.localStorage.getItem("mawapress:draft:u-ed:p1:ne")!).fields.title,
    ).toBe("मोरङमा बाढी?");
  });
});

describe("language tabs", () => {
  it("adds a missing translation and creates it on the first save", async () => {
    const calls = captureWrites(() =>
      patchOk(makePost({ updated_at: T1, translations: [translation("ne"), translation("en")] })),
    );
    const { user } = mount(makePost());
    expect(await screen.findByRole("tab", { name: /English, not added/ })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /English/ }));
    await user.click(await screen.findByRole("button", { name: "Add English version" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "Flood in Morang");
    await user.keyboard("{Control>}s{/Control}");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toMatchObject({ locale: "en", title: "Flood in Morang" });
    expect(calls[0].body!.content_json).toMatchObject({ type: "doc" });
    expect(calls[0].ifMatch).toBe(T0);
  });

  it("shows each tab's own status", async () => {
    mount(
      makePost({
        translations: [translation("ne", { status: "published" }), translation("en")],
      } as Partial<PostOut>),
    );
    expect(await screen.findByRole("tab", { name: "Nepali, published" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "English, draft" })).toBeInTheDocument();
  });
});

describe("new post", () => {
  it("creates the post on the first save and moves to its address without remounting", async () => {
    const created = makePost({ id: "new-id", updated_at: T1 });
    const calls = captureWrites(() => HttpResponse.json(created, { status: 201 }));
    const { user } = mount(null);
    const input = await title();
    await user.type(input, "मोरङमा बाढी");
    await user.selectOptions(await screen.findByLabelText("Category"), "2");
    await user.keyboard("{Control>}s{/Control}");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({
      method: "POST",
      url: "/api/posts",
      body: { locale: "ne", title: "मोरङमा बाढी", category_id: 2 },
    });
    await waitFor(() => expect(window.location.pathname).toBe("/admin/posts/new-id"));
    expect(screen.getByRole("textbox", { name: "Title" })).toBe(input);
  });

  it("asks for a category before it can save", async () => {
    const { user } = mount(null);
    await user.type(await title(), "Headline");
    await user.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText("Choose a category to start saving")).toBeInTheDocument();
  });
});

describe("SEO panel", () => {
  it("previews the Google title with the brand suffix and a 60 character cap", async () => {
    const long = "A very long headline about flooding in the eastern districts that keeps going on";
    mount(makePost({ translations: [translation("en", { title: long })] } as Partial<PostOut>));
    const serp = await screen.findByTestId("serp-title");
    expect(serp.textContent!.endsWith(" | MAWAPRESS")).toBe(true);
    expect(serp.textContent!.length).toBeLessThanOrEqual(72);
  });

  it("shows seo_auto from the API once saved", async () => {
    mount(
      makePost({
        translations: [
          translation("en", {
            seo_auto: {
              title: "From the API | MAWAPRESS",
              description: "API description",
              canonical: "https://mawapress.com/en/politics/flood-in-morang",
              og_image: "",
            },
          }),
        ],
      } as Partial<PostOut>),
    );
    expect(await screen.findByTestId("serp-title")).toHaveTextContent("From the API | MAWAPRESS");
    expect(screen.getByTestId("serp-description")).toHaveTextContent("API description");
  });

  it("builds the preview URL from NEXT_PUBLIC_SITE_URL when it is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://mawapress.example/");
    try {
      const { user } = mount(null);
      await user.type(await title(), "Headline");
      expect((await screen.findAllByText(/mawapress\.example/)).length).toBeGreaterThan(0);
      expect(screen.queryByText(/localhost/)).toBeNull();
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("disables the slug for a draft and says why", async () => {
    const { user } = mount(makePost());
    await user.click(await screen.findByRole("button", { name: "Edit SEO" }));
    expect(screen.getByLabelText(/^Slug/)).toBeDisabled();
    expect(
      screen.getByText(/follows the title until this version is published/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("SEO title")).toBeEnabled();
  });

  it("lets an editor edit the slug of a published translation", async () => {
    const { user } = mount(
      makePost({
        status: "published",
        translations: [translation("ne", { status: "published" })],
      } as Partial<PostOut>),
    );
    await user.click(await screen.findByRole("button", { name: "Edit SEO" }));
    expect(screen.getByLabelText(/^Slug/)).toBeEnabled();
  });

  it("keeps the slug locked for a reporter even when published", async () => {
    const { user } = mount(
      makePost({
        status: "published",
        author_id: reporter.id,
        translations: [translation("ne", { status: "published" })],
      } as Partial<PostOut>),
      reporter,
    );
    await user.click(await screen.findByRole("button", { name: "Edit SEO" }));
    expect(screen.getByLabelText(/^Slug/)).toBeDisabled();
    expect(screen.getByText(/Only editors can change the address/)).toBeInTheDocument();
  });

  it("counts characters for the overrides", async () => {
    const { user } = mount(makePost());
    await user.click(await screen.findByRole("button", { name: "Edit SEO" }));
    await user.type(screen.getByLabelText("SEO title"), "Hello");
    expect(screen.getByText("5/120")).toBeInTheDocument();
  });
});

describe("readability checklist", () => {
  it("lists the advisory warnings for a short post with no image", async () => {
    mount(makePost());
    const list = await screen.findByRole("list", { name: "Readability checks" });
    expect(within(list).getByText("Add a featured image")).toBeInTheDocument();
    expect(within(list).getByText(/Only \d+ words/)).toBeInTheDocument();
  });
});

describe("workflow", () => {
  it("lists the translations that go live, then publishes with If-Match", async () => {
    const calls = captureWrites(() =>
      patchOk(
        makePost({
          status: "published",
          updated_at: T1,
          translations: [
            translation("ne", { status: "published" }),
            translation("en", { status: "published" }),
          ],
        } as Partial<PostOut>),
      ),
    );
    const { user } = mount(makePost({ translations: [translation("ne"), translation("en")] }));
    await user.click(await screen.findByRole("button", { name: "Publish" }));

    const dialog = await screen.findByRole("dialog");
    const items = within(dialog).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Nepali · goes live");
    expect(items[0]).toHaveTextContent("मोरङमा बाढी");
    expect(items[1]).toHaveTextContent("English · goes live");

    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "POST", url: "/api/posts/p1/publish", ifMatch: T0 });
  });

  it("saves pending edits before running an action", async () => {
    const calls = captureWrites((seen) =>
      patchOk(makePost({ updated_at: seen.method === "PATCH" ? T1 : T2 })),
    );
    const { user } = mount(makePost());
    await user.type(await title(), "!");
    await user.click(screen.getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map((c) => c.method + " " + c.url)).toEqual([
      "PATCH /api/posts/p1",
      "POST /api/posts/p1/submit",
    ]);
    expect(calls[1].ifMatch).toBe(T1);
  });

  it("offers 'Publish translation' for a draft translation of a live post", async () => {
    const calls = captureWrites(() => patchOk(makePost({ status: "published", updated_at: T1 })));
    const { user } = mount(
      makePost({
        status: "published",
        translations: [translation("ne", { status: "published" }), translation("en")],
      } as Partial<PostOut>),
    );
    await user.click(await screen.findByRole("tab", { name: /English/ }));
    await user.click(await screen.findByRole("button", { name: "Publish translation" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(1);
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls[0]?.url).toBe("/api/posts/p1/translations/en/publish"));
    expect(calls[0].ifMatch).toBe(T0);
  });

  it("hides editor-only actions from a reporter", async () => {
    mount(makePost({ author_id: reporter.id }), reporter);
    await screen.findByRole("button", { name: "Submit for review" });
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
    expect(screen.queryByLabelText("Breaking news")).toBeNull();
  });

  it("makes someone else's draft read only for a reporter", async () => {
    mount(makePost({ author_id: "someone-else" }), reporter);
    expect(await screen.findByText("Read only")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveAttribute("readonly");
  });
});

describe("send-back feedback and unpublish", () => {
  it("shows the editor's feedback on a draft that was sent back", async () => {
    mount(
      makePost({
        feedback_note: "Add a second source",
        feedback_by_name: "Ed Editor",
        feedback_at: T1,
      } as Partial<PostOut>),
    );
    expect(await screen.findByText("Feedback from Ed Editor")).toBeInTheDocument();
    expect(screen.getByText("Add a second source")).toBeInTheDocument();
  });

  it("shows no feedback callout once the post is not a draft", async () => {
    mount(
      makePost({
        status: "in_review",
        feedback_note: "Add a second source",
        feedback_by_name: "Ed Editor",
      } as Partial<PostOut>),
    );
    await title();
    expect(screen.queryByText(/Feedback from/)).toBeNull();
  });

  it("asks before unpublishing, and does nothing on Cancel", async () => {
    const calls = captureWrites(() => patchOk(makePost({ status: "archived", updated_at: T1 })));
    const { user } = mount(
      makePost({
        status: "published",
        translations: [translation("ne", { status: "published" })],
      } as Partial<PostOut>),
    );
    await user.click(await screen.findByRole("button", { name: "Unpublish" }));
    const dialog = await screen.findByRole("dialog", { name: "Unpublish this post?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Unpublish" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Unpublish" }),
    );
    await waitFor(() => expect(calls[0]?.url).toBe("/api/posts/p1/unpublish"));
    expect(calls[0].ifMatch).toBe(T0);
  });
});
