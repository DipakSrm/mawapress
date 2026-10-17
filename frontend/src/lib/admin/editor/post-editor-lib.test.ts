import type { JSONContent } from "@tiptap/react";
import { describe, expect, it } from "vitest";
import { docStats, sameJson, stableStringify } from "./doc";
import { emptyDraft, emptyLocaleDraft, planSave, type PostDraft } from "./draft";
import { checkReadability } from "./readability";
import { buildSeoPreview, fromSeoAuto, truncateWords } from "./seo";

const p = (text: string): JSONContent => ({
  type: "paragraph",
  content: [{ type: "text", text }],
});
const doc = (...content: JSONContent[]): JSONContent => ({ type: "doc", content });
const words = (n: number) => Array.from({ length: n }, (_, i) => `w${i}`).join(" ");

describe("truncateWords (same rule as the backend)", () => {
  it("leaves short text alone", () => {
    expect(truncateWords("Short title", 60)).toBe("Short title");
  });

  it("cuts at a word boundary, trims punctuation and adds an ellipsis", () => {
    const out = truncateWords("alpha beta, gamma delta epsilon zeta", 20);
    expect(out).toBe("alpha beta, gamma…");
    expect(out.length).toBeLessThanOrEqual(20);
  });

  it("handles Devanagari text with the danda", () => {
    const out = truncateWords("नेपालमा आज भारी वर्षा । बाढीको जोखिम बढ्यो", 25);
    expect(out.endsWith("…")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(25);
    expect(out).not.toContain("।…");
  });
});

describe("buildSeoPreview", () => {
  const base = {
    locale: "en" as const,
    bodyText: "",
    origin: "https://mawapress.test",
    categorySlug: "politics",
    slug: "flood-hits",
  };

  it("caps the title at 60 characters plus the brand suffix", () => {
    const title = "A very long headline about flooding in the eastern districts that keeps going";
    const { title: out } = buildSeoPreview({ ...base, title });
    expect(out.endsWith(" | MAWAPRESS")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(60 + " | MAWAPRESS".length);
  });

  it("uses the Nepali brand for Nepali", () => {
    expect(buildSeoPreview({ ...base, locale: "ne", title: "शीर्षक" }).title).toBe(
      "शीर्षक | मावाप्रेस",
    );
  });

  it("prefers the overrides and builds the article URL", () => {
    const out = buildSeoPreview({
      ...base,
      title: "T",
      seoTitle: "Custom",
      seoDescription: "Custom description",
    });
    expect(out).toMatchObject({
      title: "Custom",
      description: "Custom description",
      url: "https://mawapress.test/en/politics/flood-hits",
    });
  });

  it("builds the description from the body, at most 155 characters", () => {
    const out = buildSeoPreview({ ...base, title: "T", bodyText: words(200) });
    expect(out.description.length).toBeLessThanOrEqual(155);
    expect(out.description.endsWith("…")).toBe(true);
  });

  it("reads seo_auto from the API", () => {
    expect(fromSeoAuto({})).toBeNull();
    expect(
      fromSeoAuto({
        title: "t",
        description: "d",
        canonical: "https://x/y",
        og_image: "https://x/i.png",
      }),
    ).toEqual({ title: "t", description: "d", url: "https://x/y", image: "https://x/i.png" });
  });
});

describe("readability checklist", () => {
  const items = (title: string, d: JSONContent, featured = true) =>
    Object.fromEntries(
      checkReadability({ title, stats: docStats(d), hasFeaturedImage: featured }).map((i) => [
        i.id,
        i.ok,
      ]),
    );

  it("flags a missing featured image", () => {
    expect(items("T", doc(p(words(200))), false).featured).toBe(false);
    expect(items("T", doc(p(words(200))), true).featured).toBe(true);
  });

  it("flags images without alt text", () => {
    const withImages = doc(
      p(words(200)),
      { type: "image", attrs: { src: "/a.jpg", alt: "a flooded road" } },
      { type: "image", attrs: { src: "/b.jpg", alt: "" } },
      { type: "image", attrs: { src: "/c.jpg" } },
    );
    expect(docStats(withImages)).toMatchObject({ images: 3, imagesMissingAlt: 2 });
    expect(items("T", withImages).alt).toBe(false);
  });

  it("flags fewer than 150 words", () => {
    expect(items("T", doc(p(words(149)))).length).toBe(false);
    expect(items("T", doc(p(words(150)))).length).toBe(true);
  });

  it("flags no subheadings only past 600 words", () => {
    expect(items("T", doc(p(words(600)))).headings).toBe(true);
    expect(items("T", doc(p(words(601)))).headings).toBe(false);
    const heading: JSONContent = {
      type: "heading",
      attrs: { level: 2 },
      content: [{ type: "text", text: "Section" }],
    };
    expect(items("T", doc(heading, p(words(601)))).headings).toBe(true);
  });

  it("flags a title longer than 70 characters", () => {
    expect(items("x".repeat(70), doc(p(words(200)))).title).toBe(true);
    expect(items("x".repeat(71), doc(p(words(200)))).title).toBe(false);
  });

  it("counts Devanagari words by whitespace", () => {
    expect(docStats(doc(p("नेपालमा आज भारी वर्षा"))).words).toBe(4);
  });
});

describe("stable comparison", () => {
  it("ignores key order", () => {
    expect(sameJson({ a: 1, b: { c: 2, d: 3 } }, { b: { d: 3, c: 2 }, a: 1 })).toBe(true);
    expect(stableStringify({ b: undefined, a: 1 })).toBe('{"a":1}');
    expect(sameJson({ a: 1 }, { a: 2 })).toBe(false);
  });
});

describe("planSave", () => {
  const serverDraft = (): PostDraft => ({
    locales: { ne: { ...emptyLocaleDraft(), title: "Old", slug: "old", content: doc(p("body")) } },
    shared: { categoryId: 1, tags: [], featuredMedia: null, isBreaking: false },
  });
  const args = (
    base: PostDraft,
    cur: PostDraft,
    over: Partial<Parameters<typeof planSave>[0]> = {},
  ) => ({
    postId: "p1",
    base,
    cur,
    activeLocale: "ne" as const,
    published: {},
    canBreak: true,
    ...over,
  });

  it("sends nothing when nothing changed, even if key order differs", () => {
    const base = serverDraft();
    const cur = serverDraft();
    cur.locales.ne!.content = {
      content: [{ content: [{ text: "body", type: "text" }], type: "paragraph" }],
      type: "doc",
    };
    expect(planSave(args(base, cur)).kind).toBe("none");
  });

  it("sends only the changed fields", () => {
    const base = serverDraft();
    const cur = serverDraft();
    cur.locales.ne!.title = "New";
    cur.shared.isBreaking = true;
    const plan = planSave(args(base, cur));
    expect(plan).toEqual({
      kind: "patch",
      requests: [{ locale: "ne", body: { locale: "ne", title: "New", is_breaking: true } }],
    });
  });

  it("does not send is_breaking for reporters", () => {
    const base = serverDraft();
    const cur = serverDraft();
    cur.shared.isBreaking = true;
    expect(planSave(args(base, cur, { canBreak: false })).kind).toBe("none");
  });

  it("sends the slug only for a published translation, and only when valid", () => {
    const base = serverDraft();
    const cur = serverDraft();
    cur.locales.ne!.slug = "new-slug";
    expect(planSave(args(base, cur)).kind).toBe("none");
    expect(planSave(args(base, cur, { published: { ne: true } }))).toMatchObject({
      kind: "patch",
      requests: [{ body: { slug: "new-slug" } }],
    });
    cur.locales.ne!.slug = "Not Valid!";
    expect(planSave(args(base, cur, { published: { ne: true } })).kind).toBe("none");
  });

  it("clears an override with null", () => {
    const base = serverDraft();
    base.locales.ne!.seoTitle = "Custom";
    const cur = serverDraft();
    cur.locales.ne!.seoTitle = "";
    expect(planSave(args(base, cur))).toMatchObject({
      requests: [{ body: { seo_title: null } }],
    });
  });

  it("creates a missing translation with title and content, and waits for a title", () => {
    const base = serverDraft();
    const cur = serverDraft();
    cur.locales.en = { ...emptyLocaleDraft(), content: doc(p("hello")) };
    expect(planSave(args(base, cur))).toEqual({ kind: "blocked", reason: "title" });
    cur.locales.en!.title = " Hello ";
    expect(planSave(args(base, cur))).toEqual({
      kind: "patch",
      requests: [
        { locale: "en", body: { locale: "en", title: "Hello", content_json: doc(p("hello")) } },
      ],
    });
  });

  it("ignores an added translation the user never touched", () => {
    const base = serverDraft();
    const cur = serverDraft();
    cur.locales.en = emptyLocaleDraft();
    expect(planSave(args(base, cur)).kind).toBe("none");
  });

  it("creates a new post once it has a title and a category", () => {
    const cur = emptyDraft("ne");
    expect(planSave(args(emptyDraft("ne"), cur, { postId: null })).kind).toBe("none");
    cur.locales.ne!.title = "Headline";
    expect(planSave(args(emptyDraft("ne"), cur, { postId: null }))).toEqual({
      kind: "blocked",
      reason: "category",
    });
    cur.shared.categoryId = 2;
    expect(planSave(args(emptyDraft("ne"), cur, { postId: null }))).toMatchObject({
      kind: "create",
      locale: "ne",
      body: {
        locale: "ne",
        title: "Headline",
        category_id: 2,
        tag_ids: [],
        featured_media_id: null,
      },
    });
  });
});
