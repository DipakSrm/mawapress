/**
 * Cleans HTML pasted from Word, Google Docs or web pages before TipTap parses it. The schema already drops
 * unsupported nodes; this removes Office noise and keeps only style values the backend renderer accepts.
 */

export const FONT_FAMILIES = ["Mukta", "Noto Sans Devanagari", "Inter"] as const;
export const LINE_HEIGHTS = ["1", "1.15", "1.5", "2"] as const;

const COLOR = /^(#[0-9a-f]{3,8}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\))$/i;
// Properties the TipTap parse rules read (bold/italic/underline/strike come from these when tags are absent).
const KEPT = new Set([
  "color",
  "font-size",
  "font-family",
  "font-weight",
  "font-style",
  "text-decoration",
  "text-decoration-line",
  "text-align",
  "line-height",
]);
// Attributes our own nodes use to round-trip through the clipboard (copy/paste inside the editor).
const KEEP_DATA = new Set([
  "data-pm-slice",
  "data-youtube-video",
  "data-embed",
  "data-url",
  "data-caption",
]);
const DROP_TAGS = "style,script,meta,link,xml,title,head,o\\:p,w\\:sdt,v\\:shape,v\\:imagedata";

export function normalizeFontSize(value: string): string | null {
  const m = /^(\d+(?:\.\d+)?)(px|pt)$/i.exec(value.trim());
  if (!m) return null;
  const px = Math.round(m[2].toLowerCase() === "pt" ? (Number(m[1]) * 4) / 3 : Number(m[1]));
  return px >= 8 && px <= 96 ? `${px}px` : null;
}

export function normalizeLineHeight(value: string): string | null {
  const v = value.trim().toLowerCase();
  const n = v.endsWith("%") ? Number(v.slice(0, -1)) / 100 : Number(v);
  if (!v || !Number.isFinite(n)) return null;
  return LINE_HEIGHTS.find((h) => Math.abs(Number(h) - n) < 0.01) ?? null;
}

function firstFamily(value: string): string | null {
  const first = value
    .split(",")[0]
    .trim()
    .replace(/^["']|["']$/g, "");
  return FONT_FAMILIES.find((f) => f.toLowerCase() === first.toLowerCase()) ?? null;
}

function cleanStyle(value: string): string {
  const out: string[] = [];
  for (const decl of value.split(";")) {
    const idx = decl.indexOf(":");
    if (idx < 0) continue;
    const prop = decl.slice(0, idx).trim().toLowerCase();
    const raw = decl
      .slice(idx + 1)
      .replace(/!important/i, "")
      .trim();
    if (!KEPT.has(prop) || !raw) continue; // drops every mso-* property along with the rest
    let next: string | null = raw;
    if (prop === "color") next = COLOR.test(raw) ? raw : null;
    else if (prop === "font-size") next = normalizeFontSize(raw);
    else if (prop === "font-family") next = firstFamily(raw);
    else if (prop === "line-height") next = normalizeLineHeight(raw);
    else if (prop === "text-align") next = /^(left|center|right|justify)$/i.test(raw) ? raw : null;
    if (next) out.push(`${prop}: ${next}`);
  }
  return out.join("; ");
}

function safeHref(href: string): boolean {
  // Browsers ignore control characters and spaces inside a scheme, so strip them before checking.
  return /^(https?:|mailto:)/i.test(href.replace(/[\u0000- ]/g, ""));
}

function safeImageSrc(src: string): boolean {
  return (
    /^https:\/\//i.test(src) ||
    (src.startsWith("/") && !src.startsWith("//") && !src.startsWith("/\\"))
  );
}

export function cleanPastedHtml(html: string): string {
  // Conditional and plain comments (Word wraps content in <!--[if gte mso 9]>...<![endif]-->).
  const stripped = html.replace(/<!--[\s\S]*?-->/g, "");
  const doc = new DOMParser().parseFromString(stripped, "text/html");
  doc.querySelectorAll(DROP_TAGS).forEach((el) => el.remove());
  for (const el of Array.from(doc.body.querySelectorAll("*"))) {
    if (el.tagName === "A" && !safeHref(el.getAttribute("href") ?? "")) {
      el.replaceWith(...Array.from(el.childNodes)); // keep the text, drop the link
      continue;
    }
    if (el.tagName === "IMG" && !safeImageSrc(el.getAttribute("src") ?? "")) {
      el.remove(); // file:, data: and blob: images cannot be rendered on the site
      continue;
    }
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      if (name === "style") {
        const cleaned = cleanStyle(attr.value);
        if (cleaned) el.setAttribute("style", cleaned);
        else el.removeAttribute("style");
      } else if (
        name === "class" ||
        name === "lang" ||
        name === "id" ||
        (name.startsWith("data-") && !KEEP_DATA.has(name)) ||
        name.startsWith("on")
      ) {
        el.removeAttribute(attr.name);
      }
    }
  }
  return doc.body.innerHTML;
}
