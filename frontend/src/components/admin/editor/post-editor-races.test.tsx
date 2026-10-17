import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PostOut } from "@/lib/admin/posts";
import { editor, mockSignedIn, renderWithSession, server, setupAdminTest } from "@/test/admin";
import { PostEditor } from "./post-editor";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const T0 = "2026-01-01T10:00:00Z";
const T1 = "2026-01-01T10:05:00Z";
const T2 = "2026-01-01T10:09:00Z";
const T3 = "2026-01-01T10:12:00Z";

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

type Tr = PostOut["translations"][number];
const doc = (t: string) => ({
  type: "doc",
  content: [{ type: "paragraph", content: [{ type: "text", text: t }] }],
});
const tr = (locale: "ne" | "en", over: Partial<Tr> = {}): Tr => ({
  locale,
  title: locale === "ne" ? "शीर्षक" : "Headline",
  slug: locale === "ne" ? "sheershak" : "headline",
  status: "draft",
  published_at: null,
  content_json: doc("body"),
  content_html: "",
  seo_title: null,
  seo_description: null,
  excerpt: null,
  seo_auto: {},
  ...over,
});
const post = (over: Partial<PostOut> = {}): PostOut =>
  ({
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
    translations: [tr("ne")],
    tags: [],
    ...over,
  }) as unknown as PostOut;

interface Seen {
  method: string;
  url: string;
  ifMatch: string | null;
  body: Record<string, unknown>;
}

/** Records every write; `respond` may return a promise to hold a request in flight. */
function writes(respond: (seen: Seen, n: number) => Response | Promise<Response>) {
  const calls: Seen[] = [];
  const handle = async ({ request }: { request: Request }) => {
    const text = await request.text();
    const seen: Seen = {
      method: request.method,
      url: new URL(request.url).pathname,
      ifMatch: request.headers.get("if-match"),
      body: text ? (JSON.parse(text) as Record<string, unknown>) : {},
    };
    calls.push(seen);
    return respond(seen, calls.length);
  };
  server.use(http.patch("*/api/posts/:id", handle), http.post("*/api/posts", handle));
  return calls;
}

function gate() {
  let release!: () => void;
  const promise = new Promise<void>((r) => (release = r));
  return { promise, release };
}

function mount(initial: PostOut | null) {
  mockSignedIn(editor);
  server.use(
    http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)),
    http.get("*/api/tags", () => HttpResponse.json([])),
  );
  const ui = renderWithSession(<PostEditor initial={initial} />);
  return { ...ui, user: userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) }) };
}

const title = () => screen.findByRole("textbox", { name: "Title" });
const save = (user: ReturnType<typeof userEvent.setup>) => user.keyboard("{Control>}s{/Control}");
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

describe("save races", () => {
  it("keeps edits made during an in-flight save and saves them next", async () => {
    const hold = gate();
    const calls = writes(async (_, n) => {
      if (n === 1) await hold.promise;
      return HttpResponse.json(post({ updated_at: n === 1 ? T1 : T2 }));
    });
    const { user } = mount(post());
    await user.type(await title(), "a");
    await save(user);
    await waitFor(() => expect(calls).toHaveLength(1));

    await user.type(await title(), "b"); // while request 1 is in flight
    hold.release();

    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[0].body.title).toBe("शीर्षकa");
    expect(calls[1]).toMatchObject({ ifMatch: T1, body: { title: "शीर्षकab" } });
    expect(await screen.findByText(/^Saved ·/)).toBeInTheDocument();
  });

  it("a flush that resolves means nothing is left unsaved (edits during the save are included)", async () => {
    const hold = gate();
    const calls = writes(async (_, n) => {
      if (n === 1) await hold.promise;
      return HttpResponse.json(post({ updated_at: n === 1 ? T1 : T2 }));
    });
    const { user } = mount(post());
    await user.type(await title(), "a");
    await user.click(screen.getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    await user.type(await title(), "b");
    server.use(
      http.post("*/api/posts/p1/submit", () => HttpResponse.json(post({ updated_at: T3 }))),
    );
    hold.release();
    // The action only runs after both saves, with the newest If-Match.
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body.title).toBe("शीर्षकab");
  });

  it("sends exactly one create POST when flush is called twice while it is in flight", async () => {
    const hold = gate();
    const calls = writes(async () => {
      await hold.promise;
      return HttpResponse.json(post({ id: "new-id", updated_at: T1 }), { status: 201 });
    });
    const { user } = mount(null);
    await user.type(await title(), "Headline");
    await user.selectOptions(await screen.findByLabelText("Category"), "2");
    await save(user);
    await waitFor(() => expect(calls).toHaveLength(1));
    await save(user);
    await save(user);
    hold.release();
    await waitFor(() => expect(window.location.pathname).toBe("/admin/posts/new-id"));
    await advance(500);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
  });

  it("runs a queued flush after a failed save", async () => {
    const calls = writes((_, n) =>
      n === 1
        ? HttpResponse.json(
            { error: { code: "INTERNAL_ERROR", message: "x", details: {} } },
            { status: 500 },
          )
        : HttpResponse.json(post({ updated_at: T1 })),
    );
    const { user } = mount(post());
    await user.type(await title(), "!");
    await save(user);
    await save(user); // queued behind the first
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2));
    expect(await screen.findByText(/^Saved ·/)).toBeInTheDocument();
    expect(calls[calls.length - 1].body.title).toBe("शीर्षक!");
  });

  it("keeps unsaved changes when switching tabs and back", async () => {
    const calls = writes(() => HttpResponse.json(post({ updated_at: T1 })));
    const { user } = mount(post());
    await user.type(await title(), "!");
    await user.click(screen.getByRole("tab", { name: /English/ }));
    expect(await screen.findByRole("button", { name: "Add English version" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /Nepali/ }));
    expect(await title()).toHaveValue("शीर्षक!");
    await save(user);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body.title).toBe("शीर्षक!");
  });
});

describe("a language with text but no title", () => {
  it("stays unsaved: keeps dirty, the stored copy, and the leave guard", async () => {
    const calls = writes(() => HttpResponse.json(post({ updated_at: T1 })));
    const { user } = mount(post());
    await user.type(await title(), "!");
    await user.click(screen.getByRole("tab", { name: /English/ }));
    await user.click(await screen.findByRole("button", { name: "Add English version" }));
    await user.type(screen.getByLabelText("Excerpt"), "English summary, no title yet");
    await save(user);

    await waitFor(() => expect(calls).toHaveLength(1)); // the Nepali edit is saved
    expect(await screen.findByText("Add a title to save the English version")).toBeInTheDocument();
    expect(screen.queryByText(/^Saved ·/)).toBeNull();
    const kept = JSON.parse(window.localStorage.getItem("mawapress:draft:u-ed:p1:en")!);
    expect(kept.fields.excerpt).toBe("English summary, no title yet");

    await user.click(screen.getByRole("link", { name: /Posts/ }));
    expect(
      await screen.findByRole("dialog", { name: "Leave with unsaved changes?" }),
    ).toBeInTheDocument();
  });
});

describe("the kept copy", () => {
  it("survives load-theirs, new edits, a successful autosave and a remount", async () => {
    server.use(
      http.get("*/api/posts/p1", () =>
        HttpResponse.json(
          post({ updated_at: T2, translations: [tr("ne", { title: "Their title" })] }),
        ),
      ),
    );
    const calls = writes((_, n) =>
      n === 1
        ? HttpResponse.json(
            {
              error: {
                code: "VERSION_CONFLICT",
                message: "x",
                details: { current_updated_at: T2 },
              },
            },
            { status: 412 },
          )
        : HttpResponse.json(
            post({ updated_at: T3, translations: [tr("ne", { title: "Their titlez" })] }),
          ),
    );
    const first = mount(post());
    await first.user.type(await title(), "mine");
    await save(first.user);
    await first.user.click(await screen.findByRole("button", { name: "Load their version" }));
    await screen.findByRole("button", { name: "Restore unsaved changes" });

    await first.user.type(await title(), "z"); // new edit while the offer is on screen
    await save(first.user);
    await waitFor(() => expect(calls).toHaveLength(2));
    await screen.findByText(/^Saved ·/);
    await advance(2000);

    const kept = () => window.localStorage.getItem("mawapress:kept:u-ed:p1:ne");
    expect(JSON.parse(kept()!).fields.title).toBe("शीर्षकmine");

    cleanup();
    mount(post({ updated_at: T3, translations: [tr("ne", { title: "Their titlez" })] }));
    expect(
      await screen.findByRole("button", { name: "Restore unsaved changes" }),
    ).toBeInTheDocument();
    expect(JSON.parse(kept()!).fields.title).toBe("शीर्षकmine");
  });

  it("asks before discarding the kept copy", async () => {
    window.localStorage.setItem(
      "mawapress:draft:u-ed:p1:ne",
      JSON.stringify({
        savedAt: Date.now() + 1000,
        locale: "ne",
        fields: {
          title: "Unsaved",
          content: doc("x"),
          excerpt: "",
          seoTitle: "",
          seoDescription: "",
          slug: "sheershak",
        },
        shared: { categoryId: 1, tags: [], featuredMedia: null, isBreaking: false },
      }),
    );
    const { user } = mount(post());
    await user.click(await screen.findByRole("button", { name: "Discard" }));
    expect(window.localStorage.getItem("mawapress:kept:u-ed:p1:ne")).not.toBeNull();
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Keep it" }),
    );
    expect(window.localStorage.getItem("mawapress:kept:u-ed:p1:ne")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard" }),
    );
    expect(window.localStorage.getItem("mawapress:kept:u-ed:p1:ne")).toBeNull();
    expect(window.localStorage.getItem("mawapress:draft:u-ed:p1:ne")).toBeNull();
  });
});

describe("overwrite", () => {
  it("shows a toast and keeps the banner when loading the current version fails", async () => {
    writes(() =>
      HttpResponse.json(
        { error: { code: "VERSION_CONFLICT", message: "x", details: { current_updated_at: T2 } } },
        { status: 412 },
      ),
    );
    server.use(http.get("*/api/posts/p1", () => HttpResponse.error()));
    const { user } = mount(post());
    await user.type(await title(), "!");
    await save(user);
    await user.click(await screen.findByRole("button", { name: "Overwrite" }));
    expect(screen.getByText("Someone else edited this post")).toBeInTheDocument();
  });

  it("takes the server's values for fields I did not touch", async () => {
    const calls = writes((_, n) =>
      n === 1
        ? HttpResponse.json(
            {
              error: {
                code: "VERSION_CONFLICT",
                message: "x",
                details: { current_updated_at: T2 },
              },
            },
            { status: 412 },
          )
        : HttpResponse.json(post({ updated_at: T3 })),
    );
    server.use(
      http.get("*/api/posts/p1", () =>
        HttpResponse.json(
          post({ updated_at: T2, translations: [tr("ne", { excerpt: "Their excerpt" })] }),
        ),
      ),
    );
    const { user } = mount(post());
    await user.type(await title(), "!");
    await save(user);
    await user.click(await screen.findByRole("button", { name: "Overwrite" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toMatchObject({ ifMatch: T2, body: { title: "शीर्षक!" } });
    expect(calls[1].body).not.toHaveProperty("excerpt"); // their excerpt is adopted, not overwritten
    expect(screen.getByLabelText("Excerpt")).toHaveValue("Their excerpt");
  });
});

describe("create idempotency", () => {
  it("adopts the post a failed create already made instead of posting again", async () => {
    let lookups = 0;
    const calls = writes((seen) =>
      seen.method === "POST"
        ? HttpResponse.json(
            { error: { code: "INTERNAL_ERROR", message: "x", details: {} } },
            { status: 500 },
          )
        : HttpResponse.json(post({ id: "made", updated_at: T3 })),
    );
    server.use(
      http.get("*/api/posts", ({ request }) => {
        lookups += 1;
        expect(new URL(request.url).searchParams.get("author_id")).toBe(editor.id);
        return HttpResponse.json({
          total: 1,
          limit: 10,
          offset: 0,
          items: [
            {
              id: "made",
              created_at: new Date().toISOString(),
              translations: [{ title: "Headline" }],
            },
          ],
        });
      }),
      http.get("*/api/posts/made", () =>
        HttpResponse.json(
          post({ id: "made", updated_at: T3, translations: [tr("ne", { title: "Headline" })] }),
        ),
      ),
    );
    const { user } = mount(null);
    await user.type(await title(), "Headline");
    await user.selectOptions(await screen.findByLabelText("Category"), "1");
    await save(user);
    await screen.findByText("Not saved — retrying");
    await advance(2500); // the automatic retry
    await waitFor(() => expect(window.location.pathname).toBe("/admin/posts/made"));
    expect(lookups).toBe(1);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  /** A create that fails with a 500 once, then a lookup that returns `items`; returns what the editor did. */
  async function failedCreateThenLookup(items: { id: string; created_at: string }[]) {
    const calls = writes(() =>
      HttpResponse.json(
        { error: { code: "INTERNAL_ERROR", message: "x", details: {} } },
        { status: 500 },
      ),
    );
    server.use(
      http.get("*/api/posts", () =>
        HttpResponse.json({
          total: items.length,
          limit: 10,
          offset: 0,
          items: items.map((i) => ({ ...i, translations: [{ title: "Headline" }] })),
        }),
      ),
      http.get("*/api/posts/:id", ({ params }) =>
        HttpResponse.json(
          post({
            id: String(params.id),
            updated_at: T3,
            translations: [tr("ne", { title: "Headline" })],
          }),
        ),
      ),
    );
    const { user } = mount(null);
    await user.type(await title(), "Headline");
    await user.selectOptions(await screen.findByLabelText("Category"), "1");
    await save(user);
    await screen.findByText("Not saved — retrying");
    await advance(2500);
    return calls;
  }

  it("does not adopt anything when several recent posts match; it fails safe", async () => {
    const now = new Date().toISOString();
    const calls = await failedCreateThenLookup([
      { id: "a", created_at: now },
      { id: "b", created_at: now },
    ]);
    expect(
      await screen.findByText(/Could not tell whether this post was already created/),
    ).toBeInTheDocument();
    expect(window.location.pathname).not.toBe("/admin/posts/a");
    expect(window.location.pathname).not.toBe("/admin/posts/b");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1); // no second create either
  });

  it("ignores a same-titled post created more than two minutes ago", async () => {
    const old = new Date(Date.now() - 10 * 60_000).toISOString();
    const calls = await failedCreateThenLookup([{ id: "old", created_at: old }]);
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2)); // creates a fresh one
    expect(window.location.pathname).not.toBe("/admin/posts/old");
  });
});

describe("a successful create", () => {
  it("clears the new-post live copy for the user and leaves other users alone", async () => {
    const stored = JSON.stringify({
      savedAt: Date.now(),
      locale: "ne",
      fields: {
        title: "Old unsaved idea",
        content: { type: "doc", content: [{ type: "paragraph" }] },
        excerpt: "",
        seoTitle: "",
        seoDescription: "",
        slug: "",
      },
      shared: { categoryId: null, tags: [], featuredMedia: null, isBreaking: false },
    });
    window.localStorage.setItem("mawapress:draft:u-ed:new:en", stored);
    window.localStorage.setItem("mawapress:kept:u-rep:new:ne", stored); // another user's: stays
    const calls = writes(() =>
      HttpResponse.json(
        post({ id: "made", updated_at: T1, translations: [tr("ne", { title: "Headline" })] }),
      ),
    );
    const { user } = mount(null);
    await user.type(await title(), "Headline");
    await user.selectOptions(await screen.findByLabelText("Category"), "1");
    await save(user);
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(1));
    await waitFor(() => expect(window.location.pathname).toBe("/admin/posts/made"));
    expect(window.localStorage.getItem("mawapress:draft:u-ed:new:en")).toBeNull();
    expect(window.localStorage.getItem("mawapress:kept:u-rep:new:ne")).toBe(stored);
  });
});

describe("a pending kept:new offer", () => {
  it("survives a successful create and is offered again on a remount of /new", async () => {
    const stored = JSON.stringify({
      savedAt: Date.now(),
      locale: "ne",
      fields: {
        title: "Old unsaved idea",
        content: { type: "doc", content: [{ type: "paragraph" }] },
        excerpt: "",
        seoTitle: "",
        seoDescription: "",
        slug: "",
      },
      shared: { categoryId: null, tags: [], featuredMedia: null, isBreaking: false },
    });
    window.localStorage.setItem("mawapress:kept:u-ed:new:ne", stored);
    const calls = writes(() =>
      HttpResponse.json(
        post({ id: "made", updated_at: T1, translations: [tr("ne", { title: "Headline" })] }),
      ),
    );
    const first = mount(null);
    expect(await screen.findByText("Unsaved changes found")).toBeInTheDocument();
    await first.user.type(await title(), "Headline");
    await first.user.selectOptions(await screen.findByLabelText("Category"), "1");
    await save(first.user);
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(1));
    await waitFor(() => expect(window.location.pathname).toBe("/admin/posts/made"));
    expect(window.localStorage.getItem("mawapress:kept:u-ed:new:ne")).toBe(stored);

    first.unmount();
    mount(null);
    expect(await screen.findByText("Unsaved changes found")).toBeInTheDocument();
  });
});
