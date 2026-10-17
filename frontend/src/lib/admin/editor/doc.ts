import type { JSONContent } from "@tiptap/react";

export const EMPTY_DOC: JSONContent = { type: "doc", content: [{ type: "paragraph" }] };

/** JSON.stringify with sorted keys, so documents compare equal whatever order their keys arrive in. */
export function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj)
    .filter((k) => obj[k] !== undefined)
    .sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(",")}}`;
}

/**
 * The editor fills in default (null) attributes when it loads a document, so a stored document and the
 * same document after a round trip differ only by `attrs: { x: null }`. Drop those before comparing.
 */
export function normalizeDoc(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeDoc);
  if (value === null || typeof value !== "object") return value;
  const out: Record<string, unknown> = {};
  for (const [key, v] of Object.entries(value as Record<string, unknown>)) {
    if (key === "attrs" && v && typeof v === "object" && !Array.isArray(v)) {
      const attrs = Object.fromEntries(
        Object.entries(v as Record<string, unknown>).filter(
          ([, x]) => x !== null && x !== undefined,
        ),
      );
      if (Object.keys(attrs).length) out.attrs = attrs;
    } else {
      out[key] = normalizeDoc(v);
    }
  }
  return out;
}

export function sameJson(a: unknown, b: unknown): boolean {
  return a === b || stableStringify(normalizeDoc(a)) === stableStringify(normalizeDoc(b));
}

export interface DocStats {
  /** Plain text of the body, one space between blocks. */
  text: string;
  words: number;
  headings: number;
  images: number;
  imagesMissingAlt: number;
}

const BLOCKS = new Set([
  "paragraph",
  "heading",
  "listItem",
  "blockquote",
  "tableCell",
  "tableHeader",
  "codeBlock",
]);

/** One pass over the document: text, word count, headings and images. Words are split on whitespace, which suits Devanagari. */
export function docStats(doc: JSONContent | null | undefined): DocStats {
  const parts: string[] = [];
  let headings = 0;
  let images = 0;
  let imagesMissingAlt = 0;
  const walk = (node: JSONContent) => {
    if (node.type === "text") {
      if (node.text) parts.push(node.text);
      return;
    }
    if (node.type === "heading") headings += 1;
    if (node.type === "image") {
      images += 1;
      const alt = (node.attrs as { alt?: unknown } | undefined)?.alt;
      if (typeof alt !== "string" || !alt.trim()) imagesMissingAlt += 1;
    }
    if (node.type === "hardBreak") parts.push(" ");
    node.content?.forEach(walk);
    if (node.type && BLOCKS.has(node.type)) parts.push(" ");
  };
  if (doc) walk(doc);
  const text = parts.join("").replace(/\s+/g, " ").trim();
  return { text, words: text ? text.split(" ").length : 0, headings, images, imagesMissingAlt };
}
