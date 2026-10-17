import { Extension, Node, mergeAttributes, type AnyExtension } from "@tiptap/core";
import Color from "@tiptap/extension-color";
import CharacterCount from "@tiptap/extension-character-count";
import FontFamily from "@tiptap/extension-font-family";
import Highlight from "@tiptap/extension-highlight";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import { Table } from "@tiptap/extension-table";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TableRow from "@tiptap/extension-table-row";
import TextAlign from "@tiptap/extension-text-align";
import TextStyle from "@tiptap/extension-text-style";
import Underline from "@tiptap/extension-underline";
import Youtube from "@tiptap/extension-youtube";
import StarterKit from "@tiptap/starter-kit";
import { ReactNodeViewRenderer } from "@tiptap/react";
import { normalizeFontSize, normalizeLineHeight } from "@/lib/editor/paste";
import { CaptionedImageView } from "./captioned-image-view";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    fontSize: {
      setFontSize: (size: string) => ReturnType;
      unsetFontSize: () => ReturnType;
    };
    lineHeight: {
      setLineHeight: (height: string) => ReturnType;
      unsetLineHeight: () => ReturnType;
    };
    embed: {
      setEmbed: (options: { provider: string; url: string }) => ReturnType;
    };
  }
}

/** Font size as a textStyle attribute, stored like "18px" (the renderer accepts 1-2 digits + px/pt). */
export const FontSize = Extension.create({
  name: "fontSize",
  addGlobalAttributes() {
    return [
      {
        types: ["textStyle"],
        attributes: {
          fontSize: {
            default: null,
            parseHTML: (el) => normalizeFontSize(el.style.fontSize || ""),
            renderHTML: (attrs) =>
              attrs.fontSize ? { style: `font-size: ${attrs.fontSize}` } : {},
          },
        },
      },
    ];
  },
  addCommands() {
    return {
      setFontSize:
        (size) =>
        ({ chain }) =>
          chain().setMark("textStyle", { fontSize: size }).run(),
      unsetFontSize:
        () =>
        ({ chain }) =>
          chain().setMark("textStyle", { fontSize: null }).removeEmptyTextStyle().run(),
    };
  },
});

const LINE_HEIGHT_TYPES = ["paragraph", "heading"];

/** Line spacing on paragraphs and headings: 1, 1.15, 1.5 or 2 (what the renderer accepts). */
export const LineHeight = Extension.create({
  name: "lineHeight",
  addGlobalAttributes() {
    return [
      {
        types: LINE_HEIGHT_TYPES,
        attributes: {
          lineHeight: {
            default: null,
            parseHTML: (el) => normalizeLineHeight(el.style.lineHeight || ""),
            renderHTML: (attrs) =>
              attrs.lineHeight ? { style: `line-height: ${attrs.lineHeight}` } : {},
          },
        },
      },
    ];
  },
  addCommands() {
    return {
      setLineHeight:
        (height) =>
        ({ commands }) =>
          LINE_HEIGHT_TYPES.map((t) => commands.updateAttributes(t, { lineHeight: height })).every(
            Boolean,
          ),
      unsetLineHeight:
        () =>
        ({ commands }) =>
          LINE_HEIGHT_TYPES.map((t) => commands.resetAttributes(t, "lineHeight")).every(Boolean),
    };
  },
});

/** An image with a visible, editable caption. Attrs match the renderer: src, alt, caption. */
export const CaptionedImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      caption: {
        default: null,
        parseHTML: (el) =>
          el.getAttribute("data-caption") ||
          el.closest("figure")?.querySelector("figcaption")?.textContent ||
          null,
        renderHTML: (attrs) => (attrs.caption ? { "data-caption": attrs.caption } : {}),
      },
    };
  },
  addNodeView() {
    return ReactNodeViewRenderer(CaptionedImageView);
  },
});

/** Facebook / X / TikTok post. The public site hydrates the placeholder; the editor shows a card. */
export const Embed = Node.create({
  name: "embed",
  group: "block",
  atom: true,
  draggable: true,
  addAttributes() {
    return {
      provider: { default: null, parseHTML: (el) => el.getAttribute("data-embed") },
      url: { default: null, parseHTML: (el) => el.getAttribute("data-url") },
    };
  },
  parseHTML() {
    return [{ tag: "div[data-embed]" }];
  },
  renderHTML({ node }) {
    const { provider, url } = node.attrs as { provider: string | null; url: string | null };
    return [
      "div",
      mergeAttributes({ "data-embed": provider ?? "", "data-url": url ?? "", class: "embed-card" }),
      ["span", { class: "embed-card-provider" }, providerLabel(provider)],
      ["span", { class: "embed-card-url" }, url ?? ""],
    ];
  },
  addCommands() {
    return {
      setEmbed:
        (options) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: options }),
    };
  },
});

function providerLabel(provider: string | null): string {
  if (provider === "facebook") return "Facebook post";
  if (provider === "x") return "X post";
  if (provider === "tiktok") return "TikTok video";
  return "Embed";
}

export function buildExtensions(placeholder: string): AnyExtension[] {
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3, 4] },
      // The renderer has no code nodes, so the editor must not produce them.
      code: false,
      codeBlock: false,
    }),
    Underline,
    TextStyle,
    Color,
    Highlight.configure({ multicolor: true }),
    FontFamily,
    FontSize,
    LineHeight,
    TextAlign.configure({
      types: ["heading", "paragraph"],
      alignments: ["left", "center", "right", "justify"],
    }),
    Link.configure({
      openOnClick: false,
      autolink: true,
      protocols: ["http", "https", "mailto"],
      HTMLAttributes: { rel: "noopener nofollow", target: "_blank" },
    }),
    CaptionedImage.configure({ inline: false }),
    Table.configure({ resizable: false }),
    TableRow,
    TableHeader,
    TableCell,
    Youtube.configure({ nocookie: true, inline: false, controls: true, width: 640, height: 360 }),
    Embed,
    Placeholder.configure({ placeholder }),
    CharacterCount,
  ];
}
