import type { components } from "@/lib/api";

type PostStatus = components["schemas"]["PostStatus"];
export type Locale = "ne" | "en";

export const PAGE_SIZE = 20;
export const STATUSES: PostStatus[] = ["draft", "in_review", "scheduled", "published", "archived"];
export const LOCALES: Locale[] = ["ne", "en"];

/** The list page's state. It lives in the URL query string, so a view can be shared or reloaded. */
export interface PostFilters {
  status?: PostStatus;
  category?: number;
  author?: string;
  locale?: Locale;
  q: string;
  /** 1-based. */
  page: number;
}

export function parseFilters(params: URLSearchParams): PostFilters {
  const status = params.get("status");
  const locale = params.get("lang");
  const category = Number(params.get("category"));
  const page = Number(params.get("page"));
  return {
    status: STATUSES.find((s) => s === status),
    category: Number.isInteger(category) && category > 0 ? category : undefined,
    author: params.get("author") || undefined,
    locale: LOCALES.find((l) => l === locale),
    q: params.get("q")?.trim() ?? "",
    page: Number.isInteger(page) && page > 1 ? page : 1,
  };
}

/** Query string for the URL (no leading `?`); defaults are omitted. */
export function filtersToSearch(f: PostFilters): string {
  const p = new URLSearchParams();
  if (f.status) p.set("status", f.status);
  if (f.category) p.set("category", String(f.category));
  if (f.author) p.set("author", f.author);
  if (f.locale) p.set("lang", f.locale);
  if (f.q) p.set("q", f.q);
  if (f.page > 1) p.set("page", String(f.page));
  return p.toString();
}

/** Query for `GET /api/posts`. */
export function filtersToApiQuery(f: PostFilters) {
  return {
    status: f.status,
    category_id: f.category,
    author_id: f.author,
    locale: f.locale,
    q: f.q || undefined,
    limit: PAGE_SIZE,
    offset: (f.page - 1) * PAGE_SIZE,
  };
}

export function hasActiveFilters(f: PostFilters): boolean {
  return Boolean(f.status || f.category || f.author || f.locale || f.q);
}
