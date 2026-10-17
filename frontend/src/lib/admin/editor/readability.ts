import type { DocStats } from "./doc";

export interface ReadabilityItem {
  id: "featured" | "alt" | "length" | "headings" | "title";
  ok: boolean;
  label: string;
}

export const MIN_WORDS = 150;
export const LONG_WORDS = 600;
export const MAX_TITLE = 70;

/** Advisory checks shown beside the editor. Nothing here blocks a save or a publish. */
export function checkReadability(input: {
  title: string;
  stats: DocStats;
  hasFeaturedImage: boolean;
}): ReadabilityItem[] {
  const { title, stats, hasFeaturedImage } = input;
  const missingAlt = stats.imagesMissingAlt;
  return [
    {
      id: "featured",
      ok: hasFeaturedImage,
      label: hasFeaturedImage ? "Has a featured image" : "Add a featured image",
    },
    {
      id: "alt",
      ok: missingAlt === 0,
      label:
        missingAlt === 0
          ? "Every image has alt text"
          : `${missingAlt} image${missingAlt === 1 ? "" : "s"} without alt text`,
    },
    {
      id: "length",
      ok: stats.words >= MIN_WORDS,
      label:
        stats.words >= MIN_WORDS
          ? `${stats.words} words`
          : `Only ${stats.words} words, aim for at least ${MIN_WORDS}`,
    },
    {
      id: "headings",
      ok: !(stats.words > LONG_WORDS && stats.headings === 0),
      label:
        stats.words > LONG_WORDS && stats.headings === 0
          ? `Over ${LONG_WORDS} words with no subheadings`
          : "Subheadings are fine",
    },
    {
      id: "title",
      ok: title.trim().length <= MAX_TITLE,
      label:
        title.trim().length <= MAX_TITLE
          ? "Title length is fine"
          : `Title is ${title.trim().length} characters, keep it under ${MAX_TITLE + 1}`,
    },
  ];
}
