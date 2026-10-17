import type { JSONContent } from "@tiptap/react";
import type { components } from "@/lib/api";
import { EMPTY_DOC, sameJson } from "./doc";
import { SLUG_PATTERN, type Locale } from "./seo";

type PostOut = components["schemas"]["PostOut"];
export type PostUpdate = components["schemas"]["PostUpdate"];
export type PostCreate = components["schemas"]["PostCreate"];
export type TagOut = components["schemas"]["TagOut"];
export type MediaOut = components["schemas"]["MediaOut"];
type Changes = Omit<PostUpdate, "locale">;

export const LOCALES: Locale[] = ["ne", "en"];

/** What the editor holds for one language. Empty strings mean "not set". */
export interface LocaleDraft {
  title: string;
  content: JSONContent;
  excerpt: string;
  seoTitle: string;
  seoDescription: string;
  slug: string;
}

/** Fields shared by every language of the post. */
export interface SharedDraft {
  categoryId: number | null;
  tags: TagOut[];
  featuredMedia: MediaOut | null;
  isBreaking: boolean;
}

export interface PostDraft {
  locales: Partial<Record<Locale, LocaleDraft>>;
  shared: SharedDraft;
}

export function emptyLocaleDraft(): LocaleDraft {
  return { title: "", content: EMPTY_DOC, excerpt: "", seoTitle: "", seoDescription: "", slug: "" };
}

export function emptyDraft(locale: Locale = "ne"): PostDraft {
  return {
    locales: { [locale]: emptyLocaleDraft() },
    shared: { categoryId: null, tags: [], featuredMedia: null, isBreaking: false },
  };
}

export function draftFromPost(post: PostOut): PostDraft {
  const locales: PostDraft["locales"] = {};
  for (const t of post.translations) {
    if (t.locale !== "ne" && t.locale !== "en") continue;
    locales[t.locale] = {
      title: t.title,
      content: t.content_json as JSONContent,
      excerpt: t.excerpt ?? "",
      seoTitle: t.seo_title ?? "",
      seoDescription: t.seo_description ?? "",
      slug: t.slug,
    };
  }
  return {
    locales,
    shared: {
      categoryId: post.category_id,
      tags: post.tags,
      featuredMedia: post.featured_media,
      isBreaking: post.is_breaking,
    },
  };
}

export function sameLocaleDraft(a: LocaleDraft, b: LocaleDraft): boolean {
  return (
    a.title === b.title &&
    a.excerpt === b.excerpt &&
    a.seoTitle === b.seoTitle &&
    a.seoDescription === b.seoDescription &&
    a.slug === b.slug &&
    sameJson(a.content, b.content)
  );
}

const tagIds = (tags: TagOut[]) => tags.map((t) => t.id).join(",");

export function sameShared(a: SharedDraft, b: SharedDraft): boolean {
  return (
    a.categoryId === b.categoryId &&
    a.isBreaking === b.isBreaking &&
    (a.featuredMedia?.id ?? null) === (b.featuredMedia?.id ?? null) &&
    tagIds(a.tags) === tagIds(b.tags)
  );
}

const MEDIA_NODES = new Set(["image", "youtube", "embed", "table"]);

function hasText(doc: JSONContent): boolean {
  if (doc.type === "text") return Boolean(doc.text?.trim());
  if (doc.type && MEDIA_NODES.has(doc.type)) return true;
  return Boolean(doc.content?.some(hasText));
}

export type SavePlan =
  | { kind: "none" }
  | { kind: "blocked"; reason: "title" | "category" }
  | { kind: "create"; body: PostCreate; locale: Locale }
  | { kind: "patch"; requests: { locale: Locale; body: PostUpdate }[] };

/** Only the fields of `cur` that differ from `base`. A language that is not on the server yet needs a title. */
function localeChanges(
  base: LocaleDraft | undefined,
  cur: LocaleDraft,
  published: boolean,
): { body: Changes; blockedByTitle: boolean } | null {
  const title = cur.title.trim();
  if (!base) {
    const touched =
      title || cur.excerpt || cur.seoTitle || cur.seoDescription || hasText(cur.content);
    if (!touched) return null;
    if (!title) return { body: {}, blockedByTitle: true };
    const body: Changes = { title, content_json: cur.content };
    if (cur.excerpt.trim()) body.excerpt = cur.excerpt;
    if (cur.seoTitle.trim()) body.seo_title = cur.seoTitle;
    if (cur.seoDescription.trim()) body.seo_description = cur.seoDescription;
    return { body, blockedByTitle: false };
  }
  const body: Changes = {};
  if (title && title !== base.title) body.title = title;
  if (!sameJson(cur.content, base.content)) body.content_json = cur.content;
  if (cur.excerpt !== base.excerpt) body.excerpt = cur.excerpt.trim() || null;
  if (cur.seoTitle !== base.seoTitle) body.seo_title = cur.seoTitle.trim() || null;
  if (cur.seoDescription !== base.seoDescription) {
    body.seo_description = cur.seoDescription.trim() || null;
  }
  const slug = cur.slug.trim();
  if (published && slug !== base.slug && slug.length <= 80 && SLUG_PATTERN.test(slug)) {
    body.slug = slug;
  }
  const blockedByTitle = !title;
  return Object.keys(body).length || blockedByTitle ? { body, blockedByTitle } : null;
}

function sharedChanges(base: SharedDraft, cur: SharedDraft, canBreak: boolean): Changes {
  const body: Changes = {};
  if (cur.categoryId !== null && cur.categoryId !== base.categoryId) {
    body.category_id = cur.categoryId;
  }
  if (tagIds(cur.tags) !== tagIds(base.tags)) body.tag_ids = cur.tags.map((t) => t.id);
  if ((cur.featuredMedia?.id ?? null) !== (base.featuredMedia?.id ?? null)) {
    body.featured_media_id = cur.featuredMedia?.id ?? null;
  }
  if (canBreak && cur.isBreaking !== base.isBreaking) body.is_breaking = cur.isBreaking;
  return body;
}

/**
 * Decides what the next save sends. A post that is not on the server yet is created (which needs a title
 * and a category); after that only changed fields go out, one PATCH per language.
 */
export function planSave(args: {
  postId: string | null;
  base: PostDraft;
  cur: PostDraft;
  activeLocale: Locale;
  published: Partial<Record<Locale, boolean>>;
  canBreak: boolean;
}): SavePlan {
  const { postId, base, cur, activeLocale, published, canBreak } = args;
  if (!postId) {
    const order = [activeLocale, ...LOCALES.filter((l) => l !== activeLocale)];
    const locale = order.find((l) => cur.locales[l]?.title.trim()) ?? null;
    if (!locale) {
      const typed = order.some((l) => {
        const d = cur.locales[l];
        return d !== undefined && hasText(d.content);
      });
      return typed ? { kind: "blocked", reason: "title" } : { kind: "none" };
    }
    if (cur.shared.categoryId === null) return { kind: "blocked", reason: "category" };
    const d = cur.locales[locale]!;
    return {
      kind: "create",
      locale,
      body: {
        locale,
        title: d.title.trim(),
        content_json: d.content,
        category_id: cur.shared.categoryId,
        tag_ids: cur.shared.tags.map((t) => t.id),
        featured_media_id: cur.shared.featuredMedia?.id ?? null,
      },
    };
  }

  const requests: { locale: Locale; body: PostUpdate }[] = [];
  let blocked = false;
  for (const locale of LOCALES) {
    const d = cur.locales[locale];
    if (!d) continue;
    const change = localeChanges(base.locales[locale], d, Boolean(published[locale]));
    if (!change) continue;
    if (change.blockedByTitle) blocked = true;
    if (Object.keys(change.body).length)
      requests.push({ locale, body: { locale, ...change.body } });
  }
  const shared = sharedChanges(base.shared, cur.shared, canBreak);
  if (Object.keys(shared).length) {
    const carrier = requests[0];
    if (carrier) Object.assign(carrier.body, shared);
    else {
      const locale = base.locales[activeLocale]
        ? activeLocale
        : (LOCALES.find((l) => base.locales[l]) ?? activeLocale);
      requests.push({ locale, body: { locale, ...shared } });
    }
  }
  if (requests.length) return { kind: "patch", requests };
  return blocked ? { kind: "blocked", reason: "title" } : { kind: "none" };
}

/** Copy the fields a request sent into the baseline, so they stop counting as changes. */
export function acknowledge(
  base: PostDraft,
  snapshot: PostDraft,
  locale: Locale,
  body: Changes,
): PostDraft {
  const next: PostDraft = { locales: { ...base.locales }, shared: { ...base.shared } };
  const snap = snapshot.locales[locale];
  if (snap) {
    const l = { ...(next.locales[locale] ?? emptyLocaleDraft()) };
    if (body.title) l.title = snap.title.trim();
    if (body.content_json) l.content = snap.content;
    if ("excerpt" in body) l.excerpt = snap.excerpt;
    if ("seo_title" in body) l.seoTitle = snap.seoTitle;
    if ("seo_description" in body) l.seoDescription = snap.seoDescription;
    if (body.slug) l.slug = snap.slug;
    next.locales[locale] = l;
  }
  if (body.category_id !== undefined) next.shared.categoryId = snapshot.shared.categoryId;
  if (body.tag_ids !== undefined) next.shared.tags = snapshot.shared.tags;
  if ("featured_media_id" in body) next.shared.featuredMedia = snapshot.shared.featuredMedia;
  if (body.is_breaking !== undefined && body.is_breaking !== null) {
    next.shared.isBreaking = snapshot.shared.isBreaking;
  }
  return next;
}

// ---- localStorage copy of unsaved work ------------------------------------------------------

export interface StoredDraft {
  savedAt: number;
  locale: Locale;
  fields: LocaleDraft;
  shared: SharedDraft;
}

export const draftKey = (postId: string | null, locale: Locale) =>
  `mawapress:draft:${postId ?? "new"}:${locale}`;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function readStoredDraft(postId: string | null, locale: Locale): StoredDraft | null {
  try {
    const raw = storage()?.getItem(draftKey(postId, locale));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredDraft;
    return parsed && typeof parsed.savedAt === "number" && parsed.fields ? parsed : null;
  } catch {
    return null;
  }
}

export function writeStoredDraft(postId: string | null, record: StoredDraft): void {
  try {
    storage()?.setItem(draftKey(postId, record.locale), JSON.stringify(record));
  } catch {
    // Storage full or blocked: the server copy stays the source of truth.
  }
}

export function clearStoredDraft(postId: string | null, locale?: Locale): void {
  try {
    for (const l of locale ? [locale] : LOCALES) storage()?.removeItem(draftKey(postId, l));
  } catch {
    // ignore
  }
}
