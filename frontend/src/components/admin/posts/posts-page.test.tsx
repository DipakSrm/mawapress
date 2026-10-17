import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  admin,
  editor,
  mockSignedIn,
  nav,
  renderWithSession,
  reporter,
  router,
  server,
  setupAdminTest,
  type TestUser,
} from "@/test/admin";
import { PostsPage } from "./posts-page";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

setupAdminTest();

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
const CATEGORIES = [
  { id: 1, slug: "politics", name_en: "Politics", name_ne: "राजनीति", parent_id: null, sort: 1 },
  { id: 2, slug: "sports", name_en: "Sports", name_ne: "खेलकुद", parent_id: null, sort: 2 },
];

type Row = ReturnType<typeof post>;
function post(
  id: string,
  status: string,
  overrides: Partial<{
    author_id: string;
    author_name: string;
    category_id: number;
    scheduled_at: string | null;
    updated_at: string;
    feedback_note: string | null;
    feedback_by_name: string | null;
    translations: { locale: string; slug: string; status: string; title: string }[];
  }> = {},
) {
  return {
    id,
    status,
    author_id: "u-rep",
    author_name: "Rita Reporter",
    category_id: 1,
    published_at: status === "published" ? hoursAgo(5) : null,
    scheduled_at: null as string | null,
    created_at: hoursAgo(3),
    updated_at: hoursAgo(2),
    view_count: 1234,
    feedback_note: null as string | null,
    feedback_by_name: null as string | null,
    feedback_at: null as string | null,
    translations: [
      {
        locale: "ne",
        slug: `slug-${id}`,
        status: status === "published" ? "published" : "draft",
        title: `Title ${id}`,
      },
    ],
    ...overrides,
  };
}

interface Api {
  lists: URL[];
  calls: { url: URL; method: string; ifMatch: string | null; body: unknown }[];
}

/** Serves the list from `rows` (honouring limit/offset) and records every request. */
function mockApi(user: TestUser, rows: Row[], total = rows.length): Api {
  mockSignedIn(user);
  const seen: Api = { lists: [], calls: [] };
  server.use(
    http.get("*/api/categories", () => HttpResponse.json(CATEGORIES)),
    http.get("*/api/users/authors", () =>
      HttpResponse.json([{ id: reporter.id, name: reporter.name }]),
    ),
    http.get("*/api/posts", ({ request }) => {
      const url = new URL(request.url);
      seen.lists.push(url);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      return HttpResponse.json({ items: rows, total, limit: 20, offset });
    }),
    http.post("*/api/posts/:id/:action", async ({ request, params }) => {
      const text = await request.text();
      seen.calls.push({
        url: new URL(request.url),
        method: request.method,
        ifMatch: request.headers.get("if-match"),
        body: text ? JSON.parse(text) : undefined,
      });
      const row = rows.find((r) => r.id === params.id);
      if (row) {
        row.status = params.action === "unpublish" ? "archived" : "published";
        row.updated_at = new Date().toISOString();
      }
      return HttpResponse.json(row);
    }),
  );
  return seen;
}

function renderPage(search = "") {
  nav.live = true;
  nav.pathname = "/admin/posts";
  nav.search = search;
  return renderWithSession(<PostsPage />);
}

async function openMenu(title: string) {
  await userEvent.click(await screen.findByRole("button", { name: `Actions for ${title}` }));
  return screen.findByRole("menu");
}

async function confirmDialog(name: string) {
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name }));
}

const lastUrl = () => router.replace.mock.calls.at(-1)?.[0];

beforeEach(() => {
  vi.mocked(toast.success).mockClear();
  vi.mocked(toast.error).mockClear();
});

describe("posts list", () => {
  it("shows ne title first, language badges, category, author, status, updated and views", async () => {
    mockApi(editor, [
      post("a", "published", {
        translations: [
          { locale: "en", slug: "flood", status: "draft", title: "Flood in Morang" },
          { locale: "ne", slug: "badhi", status: "published", title: "मोरङमा बाढी" },
        ],
      }),
      post("b", "scheduled", {
        category_id: 2,
        scheduled_at: new Date(Date.now() + 86_400_000).toISOString(),
      }),
    ]);
    renderPage();
    const link = await screen.findByRole("link", { name: "मोरङमा बाढी" });
    expect(link).toHaveAttribute("lang", "ne");
    expect(link).toHaveAttribute("href", "/admin/posts/a");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByLabelText("Nepali, published")).toBeInTheDocument();
    expect(within(row).getByLabelText("English, draft")).toBeInTheDocument();
    expect(within(row).getByText("Flood in Morang")).toBeInTheDocument();
    expect(within(row).getAllByText("Rita Reporter").length).toBeGreaterThan(0);
    expect(within(row).getByText("Published")).toBeInTheDocument();
    expect(within(row).getByText("2 hours ago")).toBeInTheDocument();
    expect(within(row).getByText("1,234")).toBeInTheDocument();
    await waitFor(() => expect(within(row).getByText("Politics")).toBeInTheDocument());
    const scheduled = screen.getByText("Title b").closest("tr") as HTMLElement;
    expect(within(scheduled).getByText("Scheduled")).toBeInTheDocument();
    expect(scheduled.querySelector("time[datetime]")).not.toBeNull();
    await waitFor(() => expect(within(scheduled).getByText("Sports")).toBeInTheDocument());
  });

  it("shows loading skeletons, then an empty state", async () => {
    mockApi(editor, []);
    server.use(
      http.get("*/api/posts", async () => {
        await delay(150);
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 });
      }),
    );
    renderPage();
    expect(await screen.findByRole("status", { name: "Loading posts" })).toBeInTheDocument();
    expect(await screen.findByText("No posts yet")).toBeInTheDocument();
    for (const link of screen.getAllByRole("link", { name: /New post/ })) {
      expect(link).toHaveAttribute("href", "/admin/posts/new");
    }
  });

  it("shows a filtered empty state with a way to clear the filters", async () => {
    const seen = mockApi(editor, []);
    renderPage("?status=archived");
    expect(await screen.findByText("No posts match these filters")).toBeInTheDocument();
    expect(seen.lists[0].searchParams.get("status")).toBe("archived");
    const clear = screen.getAllByRole("button", { name: "Clear filters" });
    await userEvent.click(clear[clear.length - 1]); // the empty state one
    await waitFor(() => expect(lastUrl()).toBe("/admin/posts"));
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.has("status")).toBe(false));
  });

  it("reads the filters from the URL into the request", async () => {
    const seen = mockApi(editor, [post("a", "draft")]);
    renderPage("?status=in_review&category=2&lang=en&q=flood&page=3");
    await screen.findByText("Title a");
    const q = seen.lists[0].searchParams;
    expect(Object.fromEntries(q)).toEqual({
      status: "in_review",
      category_id: "2",
      locale: "en",
      q: "flood",
      limit: "20",
      offset: "40",
    });
    expect(screen.getByLabelText("Status")).toHaveValue("in_review");
    expect(screen.getByLabelText("Search titles")).toHaveValue("flood");
  });

  it("filters update the URL and the request", async () => {
    const seen = mockApi(editor, [post("a", "draft")]);
    renderPage();
    await screen.findByText("Title a");
    await screen.findByRole("option", { name: "Sports" });

    await userEvent.selectOptions(screen.getByLabelText("Status"), "draft");
    await waitFor(() => expect(lastUrl()).toBe("/admin/posts?status=draft"));
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.get("status")).toBe("draft"));

    await userEvent.selectOptions(screen.getByLabelText("Category"), "2");
    await waitFor(() => expect(lastUrl()).toBe("/admin/posts?status=draft&category=2"));
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.get("category_id")).toBe("2"));

    await userEvent.selectOptions(screen.getByLabelText("Language"), "en");
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.get("locale")).toBe("en"));
    expect(lastUrl()).toBe("/admin/posts?status=draft&category=2&lang=en");
  });

  it("debounces the search box by 300 ms", async () => {
    const seen = mockApi(editor, [post("a", "draft")]);
    renderPage();
    await screen.findByText("Title a");
    const before = seen.lists.length;
    await userEvent.type(screen.getByLabelText("Search titles"), "flood");
    expect(router.replace).not.toHaveBeenCalled();
    expect(seen.lists.length).toBe(before);
    await waitFor(() => expect(lastUrl()).toBe("/admin/posts?q=flood"));
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.get("q")).toBe("flood"));
    expect(router.replace).toHaveBeenCalledTimes(1);
  });

  it("paginates with limit and offset", async () => {
    const seen = mockApi(editor, [post("a", "draft")], 45);
    renderPage();
    await screen.findByText("Title a");
    expect(screen.getByText("Showing 1–20 of 45")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Previous/ })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(lastUrl()).toBe("/admin/posts?page=2"));
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.get("offset")).toBe("20"));
    await screen.findByText("Showing 21–40 of 45");

    await userEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.get("offset")).toBe("40"));
    await screen.findByText("Showing 41–45 of 45");
    expect(screen.getByRole("button", { name: /Next/ })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /Previous/ }));
    await waitFor(() => expect(lastUrl()).toBe("/admin/posts?page=2"));
  });

  it("changing a filter returns to page 1", async () => {
    mockApi(editor, [post("a", "draft")], 45);
    renderPage("?page=2");
    await screen.findByText("Title a");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "draft");
    await waitFor(() => expect(lastUrl()).toBe("/admin/posts?status=draft"));
  });

  it("lets editors filter by clicking an author", async () => {
    const seen = mockApi(editor, [post("a", "draft")]);
    renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: "Show posts by Rita Reporter" }),
    );
    await waitFor(() => expect(lastUrl()).toBe("/admin/posts?author=u-rep"));
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.get("author_id")).toBe("u-rep"));
    await waitFor(() => expect(screen.getByLabelText("Author")).toHaveValue("u-rep"));
  });

  it.each([
    ["editors", editor],
    ["admins", admin],
  ])("gives %s an author select fed by the authors endpoint", async (_name, user) => {
    const seen = mockApi(user, [post("a", "draft")]);
    renderPage();
    await screen.findByText("Title a");
    await screen.findByRole("option", { name: "Rita Reporter" });
    await userEvent.selectOptions(screen.getByLabelText("Author"), "u-rep");
    await waitFor(() => expect(seen.lists.at(-1)?.searchParams.get("author_id")).toBe("u-rep"));
  });

  it("offers reporters no author filter", async () => {
    mockApi(reporter, [post("a", "draft")]);
    renderPage();
    await screen.findByText("Title a");
    expect(screen.queryByLabelText("Author")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show posts by/ })).not.toBeInTheDocument();
  });
});

describe("row actions", () => {
  const cases: {
    name: string;
    status: string;
    item: string;
    path: string;
    message: string;
    /** Button in the confirmation dialog, for actions that ask first. */
    confirm?: string;
  }[] = [
    {
      name: "submit",
      status: "draft",
      item: "Submit for review",
      path: "submit",
      message: "Submitted for review",
    },
    {
      name: "publish",
      status: "in_review",
      item: "Publish now",
      path: "publish",
      message: "Published",
      confirm: "Publish",
    },
    {
      name: "unschedule",
      status: "scheduled",
      item: "Unschedule",
      path: "unschedule",
      message: "Unscheduled, back to draft",
    },
    {
      name: "unpublish",
      status: "published",
      item: "Unpublish",
      path: "unpublish",
      message: "Unpublished",
      confirm: "Unpublish",
    },
    {
      name: "unarchive",
      status: "archived",
      item: "Unarchive",
      path: "unarchive",
      message: "Restored from the archive",
    },
  ];

  it.each(cases)("$name posts to the endpoint with If-Match and refreshes", async (c) => {
    const row = post("p1", c.status, { author_id: editor.id });
    const original = row.updated_at;
    const seen = mockApi(editor, [row]);
    renderPage();
    await openMenu("Title p1");
    const listsBefore = seen.lists.length;
    await userEvent.click(screen.getByRole("menuitem", { name: c.item }));
    if (c.confirm) {
      await userEvent.click(
        within(await screen.findByRole("dialog")).getByRole("button", { name: c.confirm }),
      );
    }
    await waitFor(() => expect(seen.calls).toHaveLength(1));
    expect(seen.calls[0]).toMatchObject({ method: "POST", ifMatch: original });
    expect(seen.calls[0].url.pathname).toBe(`/api/posts/p1/${c.path}`);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(c.message));
    await waitFor(() => expect(seen.lists.length).toBeGreaterThan(listsBefore));
  });

  it("publish now works for a draft and a scheduled post", async () => {
    const seen = mockApi(editor, [post("d", "draft"), post("s", "scheduled")]);
    renderPage();
    await openMenu("Title s");
    await userEvent.click(screen.getByRole("menuitem", { name: "Publish now" }));
    await confirmDialog("Publish");
    await waitFor(() => expect(seen.calls.at(-1)?.url.pathname).toBe("/api/posts/s/publish"));
    await openMenu("Title d");
    expect(screen.getByRole("menuitem", { name: "Publish now" })).toBeInTheDocument();
  });

  it("send back asks for an optional note and posts it", async () => {
    const row = post("r", "in_review");
    const original = row.updated_at;
    const seen = mockApi(editor, [row]);
    renderPage();
    await openMenu("Title r");
    await userEvent.click(screen.getByRole("menuitem", { name: /Send back/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Note/), "Needs a source");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send back" }));
    await waitFor(() => expect(seen.calls).toHaveLength(1));
    expect(seen.calls[0].url.pathname).toBe("/api/posts/r/send-back");
    expect(seen.calls[0].ifMatch).toBe(original);
    expect(seen.calls[0].body).toEqual({ note: "Needs a source" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("send back without a note sends no note", async () => {
    const seen = mockApi(editor, [post("r", "in_review")]);
    renderPage();
    await openMenu("Title r");
    await userEvent.click(screen.getByRole("menuitem", { name: /Send back/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send back" }));
    await waitFor(() => expect(seen.calls).toHaveLength(1));
    expect(seen.calls[0].body).toBeUndefined();
  });

  it("a second action uses the fresh updated_at returned by the first", async () => {
    const row = post("p", "draft");
    const original = row.updated_at;
    const seen = mockApi(editor, [row]);
    renderPage();
    await openMenu("Title p");
    await userEvent.click(screen.getByRole("menuitem", { name: "Publish now" }));
    await confirmDialog("Publish");
    await waitFor(() => expect(seen.calls).toHaveLength(1));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Actions for Title p" })).toBeEnabled(),
    );
    await openMenu("Title p");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Unpublish" }));
    await confirmDialog("Unpublish");
    await waitFor(() => expect(seen.calls).toHaveLength(2));
    expect(seen.calls[1].ifMatch).not.toBe(original);
    expect(Date.parse(seen.calls[1].ifMatch ?? "")).toBeGreaterThan(Date.parse(original));
  });

  it("a 412 shows the conflict message and refetches", async () => {
    const seen = mockApi(editor, [post("p", "draft")]);
    server.use(
      http.post("*/api/posts/:id/publish", () =>
        HttpResponse.json(
          { error: { code: "VERSION_CONFLICT", message: "Post was changed", details: {} } },
          { status: 412 },
        ),
      ),
    );
    renderPage();
    await openMenu("Title p");
    const before = seen.lists.length;
    await userEvent.click(screen.getByRole("menuitem", { name: "Publish now" }));
    await confirmDialog("Publish");
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("This post changed — refresh"));
    expect(toast.success).not.toHaveBeenCalled();
    await waitFor(() => expect(seen.lists.length).toBeGreaterThan(before));
  });

  it("copies the public link of a published post", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    mockApi(editor, [
      post("p", "published", {
        translations: [{ locale: "ne", slug: "badhi", status: "published", title: "बाढी" }],
      }),
    ]);
    renderPage();
    await screen.findByText("बाढी");
    await within(screen.getByRole("table")).findAllByText("Politics");
    await openMenu("बाढी");
    await userEvent.click(screen.getByRole("menuitem", { name: "Copy public link" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/ne/politics/badhi`),
    );
    expect(toast.success).toHaveBeenCalledWith("Link copied");
  });

  it("builds the public link from NEXT_PUBLIC_SITE_URL when it is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://mawapress.example/");
    try {
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
      mockApi(editor, [
        post("p", "published", {
          translations: [{ locale: "ne", slug: "badhi", status: "published", title: "बाढी" }],
        }),
      ]);
      renderPage();
      await screen.findByText("बाढी");
      await within(screen.getByRole("table")).findAllByText("Politics");
      await openMenu("बाढी");
      await userEvent.click(screen.getByRole("menuitem", { name: "Copy public link" }));
      await waitFor(() =>
        expect(writeText).toHaveBeenCalledWith("https://mawapress.example/ne/politics/badhi"),
      );
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("links Edit to the editor", async () => {
    mockApi(editor, [post("p", "draft")]);
    renderPage();
    await openMenu("Title p");
    expect(screen.getByRole("menuitem", { name: "Edit" })).toHaveAttribute(
      "href",
      "/admin/posts/p",
    );
  });
});

describe("role and status visibility", () => {
  async function items(title: string) {
    const menu = await openMenu(title);
    return within(menu)
      .getAllByRole("menuitem")
      .map((i) => i.textContent?.trim());
  }

  it("reporters get Edit and Submit on their own draft, and nothing editorial", async () => {
    mockApi(reporter, [post("p", "draft", { author_id: reporter.id })]);
    renderPage();
    expect(await items("Title p")).toEqual(["Edit", "Submit for review"]);
  });

  it("reporters get only Edit on an in-review, scheduled or published post", async () => {
    mockApi(reporter, [
      post("r", "in_review", { author_id: reporter.id }),
      post("s", "scheduled", { author_id: reporter.id }),
    ]);
    renderPage();
    expect(await items("Title r")).toEqual(["Edit"]);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(await items("Title s")).toEqual(["Edit"]);
  });

  it("editors do not get Submit on someone else's draft", async () => {
    mockApi(editor, [post("p", "draft")]);
    renderPage();
    expect(await items("Title p")).toEqual(["Edit", "Publish now", "Schedule…"]);
  });

  it("editors see the full set on an in-review post and a scheduled post", async () => {
    mockApi(editor, [post("r", "in_review"), post("s", "scheduled")]);
    renderPage();
    expect(await items("Title r")).toEqual(["Edit", "Send back…", "Publish now", "Schedule…"]);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(await items("Title s")).toEqual(["Edit", "Publish now", "Reschedule…", "Unschedule"]);
  });

  it("offers Unpublish (and the link) for published, Unarchive for archived", async () => {
    mockApi(editor, [post("p", "published"), post("a", "archived")]);
    renderPage();
    await screen.findByText("Title p");
    await within(screen.getByRole("table")).findAllByText("Politics");
    expect(await items("Title p")).toEqual(["Edit", "Unpublish", "Copy public link"]);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(await items("Title a")).toEqual(["Edit", "Unarchive"]);
  });
});

describe("schedule dialog", () => {
  async function openSchedule(rows: Row[] = [post("p", "draft")]) {
    const seen = mockApi(editor, rows);
    renderPage();
    await openMenu("Title p");
    await userEvent.click(screen.getByRole("menuitem", { name: /schedule…/i }));
    const dialog = await screen.findByRole("dialog");
    return { seen, dialog, input: within(dialog).getByLabelText("Publish at") as HTMLInputElement };
  }

  const localValue = (d: Date) => {
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  };

  it("rejects a past time on the client and sends nothing", async () => {
    const { seen, dialog, input } = await openSchedule();
    fireEvent.change(input, { target: { value: "2020-01-01T10:00" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Schedule" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /at least a minute from now/,
    );
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(seen.calls).toHaveLength(0);
  });

  it("rejects an empty value", async () => {
    const { seen, dialog } = await openSchedule();
    await userEvent.click(within(dialog).getByRole("button", { name: "Schedule" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Choose a date and time.");
    expect(seen.calls).toHaveLength(0);
  });

  it("sends the local time as ISO with an offset, with If-Match", async () => {
    const row = post("p", "draft");
    const original = row.updated_at;
    const { seen, dialog, input } = await openSchedule([row]);
    const when = new Date(Date.now() + 2 * 86_400_000);
    when.setSeconds(0, 0);
    fireEvent.change(input, { target: { value: localValue(when) } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Schedule" }));
    await waitFor(() => expect(seen.calls).toHaveLength(1));
    const call = seen.calls[0];
    expect(call.url.pathname).toBe("/api/posts/p/schedule");
    expect(call.ifMatch).toBe(original);
    const sent = (call.body as { scheduled_at: string }).scheduled_at;
    expect(sent).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00[+-]\d{2}:\d{2}$/);
    expect(new Date(sent).getTime()).toBe(when.getTime());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows backend validation errors inside the dialog and keeps it open", async () => {
    const { dialog, input } = await openSchedule();
    server.use(
      http.post("*/api/posts/:id/schedule", () =>
        HttpResponse.json(
          {
            error: {
              code: "INVALID_SCHEDULE_TIME",
              message: "scheduled_at must be at most one year ahead",
              details: {},
            },
          },
          { status: 422 },
        ),
      ),
    );
    fireEvent.change(input, { target: { value: localValue(new Date(Date.now() + 86_400_000)) } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Schedule" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "scheduled_at must be at most one year ahead",
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("prefills the current time when rescheduling", async () => {
    const at = new Date(Date.now() + 3 * 86_400_000);
    at.setSeconds(0, 0);
    const { input } = await openSchedule([
      post("p", "scheduled", { scheduled_at: at.toISOString() }),
    ]);
    expect(input.value).toBe(localValue(at));
  });
});

describe("confirmations", () => {
  const bilingual = (id: string, status: string) =>
    post(id, status, {
      translations: [
        { locale: "ne", slug: "badhi", status: "draft", title: "मोरङमा बाढी" },
        { locale: "en", slug: "flood", status: "draft", title: "Flood in Morang" },
      ],
    });

  it("Publish now lists every translation and sends nothing until confirmed", async () => {
    const seen = mockApi(editor, [bilingual("d", "draft")]);
    renderPage();
    await openMenu("मोरङमा बाढी");
    await userEvent.click(screen.getByRole("menuitem", { name: "Publish now" }));
    const dialog = await screen.findByRole("dialog", { name: "Publish this post?" });
    const list = within(dialog).getByRole("list", { name: "Versions going live" });
    const entries = within(list).getAllByRole("listitem");
    expect(entries).toHaveLength(2);
    expect(entries[0]).toHaveTextContent("मोरङमा बाढी");
    expect(entries[1]).toHaveTextContent("Flood in Morang");
    expect(seen.calls).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(seen.calls).toHaveLength(0);
  });

  it("Unpublish asks first and does nothing on Cancel", async () => {
    const seen = mockApi(editor, [post("p", "published")]);
    renderPage();
    await openMenu("Title p");
    await userEvent.click(screen.getByRole("menuitem", { name: "Unpublish" }));
    const dialog = await screen.findByRole("dialog", { name: "Unpublish this post?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(seen.calls).toHaveLength(0);
  });
});

describe("dialogs on failure", () => {
  it("send back stays open with the note and the error after a server failure", async () => {
    const seen = mockApi(editor, [post("r", "in_review")]);
    server.use(
      http.post("*/api/posts/:id/send-back", () =>
        HttpResponse.json(
          { error: { code: "INTERNAL_ERROR", message: "Server exploded", details: {} } },
          { status: 500 },
        ),
      ),
    );
    renderPage();
    await openMenu("Title r");
    await userEvent.click(screen.getByRole("menuitem", { name: /Send back/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Note/), "Needs a source");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send back" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Server exploded");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Note/)).toHaveValue("Needs a source");
    expect(within(dialog).getByRole("button", { name: "Send back" })).toBeEnabled();
    expect(seen.calls).toHaveLength(0);
  });

  it("send back stays open after a network error", async () => {
    mockApi(editor, [post("r", "in_review")]);
    server.use(http.post("*/api/posts/:id/send-back", () => HttpResponse.error()));
    renderPage();
    await openMenu("Title r");
    await userEvent.click(screen.getByRole("menuitem", { name: /Send back/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Note/), "keep me");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send back" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/reach the server/);
    expect(within(dialog).getByLabelText(/Note/)).toHaveValue("keep me");
  });

  it("schedule stays open with the chosen time after a network error", async () => {
    mockApi(editor, [post("p", "draft")]);
    server.use(http.post("*/api/posts/:id/schedule", () => HttpResponse.error()));
    renderPage();
    await openMenu("Title p");
    await userEvent.click(screen.getByRole("menuitem", { name: /schedule…/i }));
    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByLabelText("Publish at") as HTMLInputElement;
    const d = new Date(Date.now() + 86_400_000);
    const p2 = (n: number) => String(n).padStart(2, "0");
    const when = `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}`;
    fireEvent.change(input, { target: { value: when } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Schedule" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/reach the server/);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(input.value).toBe(when);
  });

  it("keeps each row busy on its own while two actions run at once", async () => {
    const rows = [
      post("a", "draft", { author_id: reporter.id }),
      post("b", "draft", { author_id: reporter.id }),
    ];
    mockApi(reporter, rows);
    const releases: Record<string, () => void> = {};
    server.use(
      http.post("*/api/posts/:id/:action", async ({ params }) => {
        await new Promise<void>((r) => (releases[String(params.id)] = r));
        return HttpResponse.json({ ...rows.find((x) => x.id === params.id), status: "in_review" });
      }),
    );
    renderPage();
    for (const id of ["a", "b"]) {
      await openMenu(`Title ${id}`);
      await userEvent.click(screen.getByRole("menuitem", { name: "Submit for review" }));
    }
    const row = (id: string) => screen.getByRole("button", { name: `Actions for Title ${id}` });
    await waitFor(() => expect(row("a")).toBeDisabled());
    expect(row("b")).toBeDisabled();
    await waitFor(() => expect(releases.a).toBeDefined());
    releases.a();
    await waitFor(() => expect(row("a")).toBeEnabled());
    expect(row("b")).toBeDisabled(); // finishing A must not clear B
    await waitFor(() => expect(releases.b).toBeDefined());
    releases.b();
    await waitFor(() => expect(row("b")).toBeEnabled());
  });
});

describe("run error handling", () => {
  it("shows a generic toast for a failure that is not an API error, with no unhandled rejection", async () => {
    const { usePostActions } = await import("@/lib/admin/posts");
    const { renderHook, act } = await import("@testing-library/react");
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    const api = await import("@/lib/api");
    const spy = vi.spyOn(api.api, "post").mockRejectedValueOnce(new TypeError("boom"));
    const client = new QueryClient();
    const { result } = renderHook(() => usePostActions(), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    let outcome: Awaited<ReturnType<typeof result.current.run>> | undefined;
    await act(async () => {
      outcome = await result.current.run({ id: "x", updated_at: hoursAgo(1) }, { type: "submit" });
    });
    spy.mockRestore();
    expect(outcome?.ok).toBe(false);
    expect(toast.error).toHaveBeenCalledWith("Something went wrong. Try again.");
    expect(result.current.pendingIds.size).toBe(0);
  });
});

describe("feedback and small screens", () => {
  it("flags a draft that an editor sent back, and not other statuses", async () => {
    mockApi(reporter, [
      post("f", "draft", {
        author_id: reporter.id,
        feedback_note: "Add a second source",
        feedback_by_name: "Ed Editor",
      }),
      post("g", "in_review", {
        author_id: reporter.id,
        feedback_note: "stale note",
        feedback_by_name: "Ed Editor",
      }),
    ]);
    renderPage();
    expect(await screen.findByText("Feedback from Ed Editor")).toBeInTheDocument();
    expect(screen.getAllByText(/Feedback from/)).toHaveLength(1);
  });

  it("lets an editor filter by author from the title cell below lg, where the column is hidden", async () => {
    mockApi(editor, [post("p", "draft")]);
    renderPage();
    const byline = (await screen.findByTestId("mobile-author")) as HTMLElement;
    expect(byline).toHaveClass("lg:hidden");
    await userEvent.click(
      within(byline).getByRole("button", { name: /Show posts by Rita Reporter/ }),
    );
    expect(lastUrl()).toContain("author=u-rep");
    // The select itself is always rendered, not hidden at any width.
    expect(screen.getByLabelText("Author")).toBeVisible();
  });
});
