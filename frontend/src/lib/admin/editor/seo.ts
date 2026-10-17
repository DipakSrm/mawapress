export type Locale = "ne" | "en";

export const BRAND: Record<Locale, string> = { ne: "मावाप्रेस", en: "MAWAPRESS" };
export const SEO_TITLE_MAX = 120;
export const SEO_DESCRIPTION_MAX = 320;
export const EXCERPT_MAX = 300;
export const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** Same rule as the backend (`truncate_words`): cut at a word boundary and end with an ellipsis. */
export function truncateWords(text: string, limit: number): string {
  if (text.length <= limit) return text;
  let cut = text.slice(0, limit - 1);
  if (cut.includes(" ")) cut = cut.slice(0, cut.lastIndexOf(" "));
  return `${cut.replace(/[ ,.;:–—।]+$/, "")}…`;
}

export interface SeoPreviewInput {
  locale: Locale;
  title: string;
  bodyText: string;
  seoTitle?: string;
  seoDescription?: string;
  slug?: string;
  categorySlug?: string;
  origin: string;
  imageUrl?: string | null;
}

export interface SeoPreview {
  title: string;
  description: string;
  url: string;
  image: string | null;
}

/** The snippet the backend would generate, for live feedback before a save. */
export function buildSeoPreview(input: SeoPreviewInput): SeoPreview {
  const { locale, title } = input;
  const seoTitle = input.seoTitle?.trim();
  const seoDescription = input.seoDescription?.trim();
  return {
    title: seoTitle || `${truncateWords(title.trim(), 60)} | ${BRAND[locale]}`,
    description: seoDescription || truncateWords(input.bodyText, 155) || title.trim(),
    url: `${input.origin}/${locale}/${input.categorySlug || "category"}/${input.slug || "new-article"}`,
    image: input.imageUrl ?? null,
  };
}

/** `seo_auto` as the API returns it (title, description, canonical, og_image), or null when it is empty. */
export function fromSeoAuto(auto: Record<string, unknown> | undefined): SeoPreview | null {
  if (!auto || typeof auto.title !== "string" || typeof auto.description !== "string") return null;
  return {
    title: auto.title,
    description: auto.description,
    url: typeof auto.canonical === "string" ? auto.canonical : "",
    image: typeof auto.og_image === "string" ? auto.og_image : null,
  };
}
