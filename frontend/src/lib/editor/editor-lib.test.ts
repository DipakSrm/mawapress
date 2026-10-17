import { describe, expect, it } from "vitest";
import { cleanPastedHtml, normalizeFontSize, normalizeLineHeight } from "./paste";
import { parseMediaUrl, validateImageUrl, validateLinkUrl } from "./url";

describe("validateLinkUrl", () => {
  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,hi",
    "vbscript:x",
    "ftp://example.com",
  ])("rejects %s", (input) => expect(validateLinkUrl(input).ok).toBe(false));
  it("rejects scheme tricks with whitespace or quotes", () => {
    expect(validateLinkUrl("java\nscript:alert(1)").ok).toBe(false);
    expect(validateLinkUrl('https://a.com/" onclick="x').ok).toBe(false);
  });
  it("accepts http, https, mailto and bare domains", () => {
    expect(validateLinkUrl("https://mawapress.com/a?b=1")).toEqual({
      ok: true,
      url: "https://mawapress.com/a?b=1",
    });
    expect(validateLinkUrl("http://example.com")).toEqual({ ok: true, url: "http://example.com" });
    expect(validateLinkUrl("mailto:desk@mawapress.com")).toEqual({
      ok: true,
      url: "mailto:desk@mawapress.com",
    });
    expect(validateLinkUrl("desk@mawapress.com")).toEqual({
      ok: true,
      url: "mailto:desk@mawapress.com",
    });
    expect(validateLinkUrl("mawapress.com")).toEqual({ ok: true, url: "https://mawapress.com" });
  });
  it("rejects empty and non-addresses", () => {
    expect(validateLinkUrl("  ").ok).toBe(false);
    expect(validateLinkUrl("hello").ok).toBe(false);
  });
});

describe("validateImageUrl", () => {
  it("accepts https and site paths only", () => {
    expect(validateImageUrl("https://cdn.mawapress.com/a.webp").ok).toBe(true);
    expect(validateImageUrl("/media/a.webp").ok).toBe(true);
    expect(validateImageUrl("//evil.com/a.png").ok).toBe(false);
    expect(validateImageUrl("http://a.com/a.png").ok).toBe(false);
    expect(validateImageUrl("data:image/png;base64,AAA").ok).toBe(false);
  });
});

describe("parseMediaUrl", () => {
  it("detects YouTube and social providers", () => {
    expect(parseMediaUrl("https://youtu.be/dQw4w9WgXcQ")).toMatchObject({
      ok: true,
      target: { kind: "youtube" },
    });
    expect(parseMediaUrl("https://www.facebook.com/a/posts/1")).toMatchObject({
      ok: true,
      target: { kind: "embed", provider: "facebook" },
    });
    expect(parseMediaUrl("https://www.tiktok.com/@u/video/1")).toMatchObject({
      ok: true,
      target: { kind: "embed", provider: "tiktok" },
    });
  });
  it("rejects look-alike hosts, http and bad ids", () => {
    for (const bad of [
      "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
      "http://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "https://www.youtube.com/watch?v=short",
      "https://facebook.com.evil.com/a",
      "https://x.com@evil.com/a",
      "https://evil.com/",
    ]) {
      expect(parseMediaUrl(bad).ok, bad).toBe(false);
    }
  });
});

describe("paste normalisation", () => {
  it("converts point sizes to pixels and bounds them", () => {
    expect(normalizeFontSize("12pt")).toBe("16px");
    expect(normalizeFontSize("18px")).toBe("18px");
    expect(normalizeFontSize("2pt")).toBeNull();
    expect(normalizeFontSize("large")).toBeNull();
  });
  it("only keeps line heights the renderer accepts", () => {
    expect(normalizeLineHeight("1.5")).toBe("1.5");
    expect(normalizeLineHeight("115%")).toBe("1.15");
    expect(normalizeLineHeight("107%")).toBeNull();
    expect(normalizeLineHeight("normal")).toBeNull();
  });
  it("removes Office noise but keeps supported formatting", () => {
    const out = cleanPastedHtml(
      '<!--[if gte mso 9]><xml>x</xml><![endif]--><p class="MsoNormal" style="mso-pagination:widow-orphan;color:red;font-family:\'Times New Roman\';text-align:center"><o:p></o:p>Hi</p>',
    );
    expect(out).not.toMatch(/mso|class=|o:p|xml/i);
    expect(out).toContain("text-align: center");
    expect(out).not.toContain("Times");
    expect(out).not.toContain("color");
  });
});
