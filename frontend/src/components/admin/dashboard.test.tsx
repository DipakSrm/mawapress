import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import {
  editor,
  mockSignedIn,
  renderWithSession,
  reporter,
  server,
  setupAdminTest,
  type TestUser,
} from "@/test/admin";
import { Dashboard } from "./dashboard";

vi.mock("next/navigation", async () =>
  (await import("@/test/next-navigation-mock")).navigationMock(),
);

setupAdminTest();

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

function post(id: string, status: string, title: string) {
  return {
    id,
    author_id: "u-rep",
    author_name: "Rita Reporter",
    category_id: 1,
    published_at: null,
    scheduled_at: null,
    status,
    translations: [{ locale: "ne", slug: id, status: "draft", title }],
    updated_at: hoursAgo(1),
    view_count: 0,
  };
}

const totals = (total: number) => HttpResponse.json({ items: [], total, limit: 1, offset: 0 });

function mockPosts(user: TestUser) {
  mockSignedIn(user);
  const seen: URLSearchParams[] = [];
  server.use(
    http.get("*/api/posts", ({ request }) => {
      const q = new URL(request.url).searchParams;
      seen.push(q);
      switch (q.get("status")) {
        case "draft":
          return totals(7);
        case "in_review":
          return totals(3);
        case "scheduled":
          return totals(2);
        case "published":
          return q.get("published_after") ? totals(2) : totals(40);
        default:
          return HttpResponse.json({
            items: [post("r1", "draft", "मोरङको खबर"), post("r2", "in_review", "Budget day")],
            total: 2,
            limit: 10,
            offset: 0,
          });
      }
    }),
  );
  return seen;
}

describe("dashboard", () => {
  it("renders counts from the API totals for an editor", async () => {
    const seen = mockPosts(editor);
    renderWithSession(<Dashboard />);
    await waitFor(() => expect(screen.getByTestId("stat-My drafts")).toHaveTextContent("7"));
    expect(screen.getByTestId("stat-In review")).toHaveTextContent("3");
    expect(screen.getByTestId("stat-Scheduled")).toHaveTextContent("2");
    expect(screen.getByTestId("stat-Published (24 h)")).toHaveTextContent("2");
    const pub = seen.find((q) => q.get("status") === "published");
    expect(Date.now() - Date.parse(pub?.get("published_after") ?? "")).toBeLessThan(
      60_000 + 86_400_000,
    );
    expect(Date.now() - Date.parse(pub?.get("published_after") ?? "")).toBeGreaterThan(86_300_000);
    expect(seen.find((q) => q.get("status") === "draft")?.get("author_id")).toBe("u-ed");
  });

  it("lists recent posts with Nepali titles tagged as such", async () => {
    mockPosts(editor);
    renderWithSession(<Dashboard />);
    const nepali = await screen.findByText("मोरङको खबर");
    expect(nepali).toHaveAttribute("lang", "ne");
    expect(screen.getByText("Budget day")).toBeInTheDocument();
    expect(screen.getByText("Recent activity")).toBeInTheDocument();
  });

  it("hides the In review card from reporters and does not request it", async () => {
    const seen = mockPosts(reporter);
    renderWithSession(<Dashboard />);
    await waitFor(() => expect(screen.getByTestId("stat-My drafts")).toHaveTextContent("7"));
    expect(screen.queryByTestId("stat-In review")).not.toBeInTheDocument();
    expect(seen.some((q) => q.get("status") === "in_review")).toBe(false);
  });
});
