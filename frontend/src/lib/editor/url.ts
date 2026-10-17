/** URL rules shared by the editor dialogs. They mirror what backend/app/modules/posts/render.py accepts. */

export type UrlResult = { ok: true; url: string } | { ok: false; error: string };

const SCHEME = /^([a-z][a-z0-9+.-]*):/i;
const EMAIL = /^[^\s@/:]+@[^\s@/:]+\.[^\s@/:]+$/;
const MAX_URL = 2048;
const BAD_CHARS = /[\s"'<>\\]/;

function parseHttps(raw: string): URL | null {
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    if (url.port && url.port !== "443") return null;
    return url;
  } catch {
    return null;
  }
}

/** Link addresses: http, https or mailto only. A bare "example.com" becomes https, an email becomes mailto. */
export function validateLinkUrl(input: string): UrlResult {
  const value = input.trim();
  if (!value) return { ok: false, error: "Enter a web address." };
  if (value.length > MAX_URL || BAD_CHARS.test(value)) {
    return { ok: false, error: "That address contains characters that are not allowed." };
  }
  const scheme = SCHEME.exec(value)?.[1].toLowerCase();
  if (scheme === "mailto") {
    return EMAIL.test(value.slice(7).split("?")[0])
      ? { ok: true, url: value }
      : { ok: false, error: "Enter a valid email address." };
  }
  if (scheme === "http" || scheme === "https") {
    try {
      const url = new URL(value);
      return url.hostname.includes(".") || url.hostname === "localhost"
        ? { ok: true, url: value }
        : { ok: false, error: "Enter a valid web address." };
    } catch {
      return { ok: false, error: "Enter a valid web address." };
    }
  }
  if (scheme) return { ok: false, error: "Only http, https and mailto links are allowed." };
  if (EMAIL.test(value)) return { ok: true, url: `mailto:${value}` };
  if (value.includes(".") && !value.startsWith(".") && !value.endsWith(".")) {
    return validateLinkUrl(`https://${value}`);
  }
  return { ok: false, error: "Enter a valid web address, like https://example.com." };
}

/** Image sources: https, or a path on this site. */
export function validateImageUrl(input: string): UrlResult {
  const value = input.trim();
  if (!value) return { ok: false, error: "Enter an image address." };
  if (value.length > MAX_URL || BAD_CHARS.test(value)) {
    return { ok: false, error: "That address contains characters that are not allowed." };
  }
  if (value.startsWith("/") && !value.startsWith("//")) return { ok: true, url: value };
  return parseHttps(value)
    ? { ok: true, url: value }
    : { ok: false, error: "Use an https:// image address." };
}

export type EmbedProvider = "facebook" | "x" | "tiktok";

const EMBED_HOSTS: Record<EmbedProvider, string[]> = {
  facebook: ["facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"],
  x: ["x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"],
  tiktok: ["tiktok.com", "www.tiktok.com", "vm.tiktok.com", "m.tiktok.com"],
};
const YT_HOSTS = [
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
  "youtube-nocookie.com",
  "www.youtube-nocookie.com",
  "youtu.be",
];
const YT_ID = /^[A-Za-z0-9_-]{11}$/;

export function isYoutubeUrl(raw: string): boolean {
  const url = parseHttps(raw);
  if (!url || !YT_HOSTS.includes(url.hostname)) return false;
  const parts = url.pathname.split("/").filter(Boolean);
  let id: string | null | undefined;
  if (url.hostname === "youtu.be") id = parts[0];
  else if (parts[0] === "watch") id = url.searchParams.get("v");
  else if (parts.length >= 2 && ["embed", "shorts", "live", "v"].includes(parts[0])) id = parts[1];
  return !!id && YT_ID.test(id);
}

export type MediaTarget =
  { kind: "youtube"; url: string } | { kind: "embed"; provider: EmbedProvider; url: string };

/** Works out what a pasted video or social-post URL should become, or explains why it cannot. */
export function parseMediaUrl(
  input: string,
): { ok: true; target: MediaTarget } | { ok: false; error: string } {
  const value = input.trim();
  if (!value) return { ok: false, error: "Enter a video or post address." };
  if (value.length > MAX_URL || BAD_CHARS.test(value)) {
    return { ok: false, error: "That address contains characters that are not allowed." };
  }
  if (isYoutubeUrl(value)) return { ok: true, target: { kind: "youtube", url: value } };
  const url = parseHttps(value);
  if (url) {
    for (const provider of Object.keys(EMBED_HOSTS) as EmbedProvider[]) {
      if (EMBED_HOSTS[provider].includes(url.hostname)) {
        return { ok: true, target: { kind: "embed", provider, url: value } };
      }
    }
  }
  return {
    ok: false,
    error: "Use an https:// link to a YouTube video, or a Facebook, X or TikTok post.",
  };
}
