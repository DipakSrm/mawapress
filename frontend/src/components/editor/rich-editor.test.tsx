import type { Editor, JSONContent } from "@tiptap/react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RichEditor, type EditorLocale } from "./RichEditor";

// jsdom has no ClipboardEvent, which ProseMirror's pasteHTML constructs.
if (typeof globalThis.ClipboardEvent === "undefined") {
  (globalThis as Record<string, unknown>).ClipboardEvent = class extends Event {};
}

const doc = (text: string): JSONContent => ({
  type: "doc",
  content: [{ type: "paragraph", content: text ? [{ type: "text", text }] : [] }],
});

async function setup(opts: { value?: JSONContent; locale?: EditorLocale } = {}) {
  const onChange = vi.fn();
  let editor!: Editor;
  const ui = render(
    <RichEditor
      value={opts.value ?? doc("Hello world")}
      onChange={onChange}
      locale={opts.locale ?? "en"}
      onEditorReady={(e) => {
        editor = e;
      }}
    />,
  );
  await waitFor(() => expect(editor).toBeTruthy());
  const last = () => onChange.mock.calls.at(-1)?.[0] as JSONContent;
  const selectAll = () => act(() => void editor.commands.selectAll());
  return { editor, onChange, last, selectAll, user: userEvent.setup(), ...ui };
}

function collect(node: JSONContent, type: string, found: JSONContent[] = []): JSONContent[] {
  if (node.type === type) found.push(node);
  node.content?.forEach((c) => collect(c, type, found));
  return found;
}

describe("RichEditor", () => {
  it("round-trips the value and reports edits as JSON", async () => {
    const { editor, last } = await setup();
    expect(editor.getJSON().content?.[0].content).toEqual([{ type: "text", text: "Hello world" }]);
    act(() => void editor.commands.insertContent("!"));
    expect(last().content?.[0].content?.[0].text).toContain("!");
  });

  it("sets the lang attribute from the locale", async () => {
    const { container } = await setup({ locale: "ne" });
    expect(container.querySelector('[contenteditable="true"]')).toHaveAttribute("lang", "ne");
  });

  it("applies bold from the toolbar and shows it as pressed", async () => {
    const { last, selectAll, user } = await setup();
    selectAll();
    await user.click(screen.getByRole("button", { name: "Bold" }));
    expect(last().content?.[0].content?.[0].marks).toEqual([{ type: "bold" }]);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Bold" })).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("applies a text colour from the brand swatches", async () => {
    const { last, selectAll, user } = await setup();
    selectAll();
    await user.click(screen.getByRole("button", { name: "Text colour" }));
    await user.click(await screen.findByRole("button", { name: "Gurans red #c8102e" }));
    expect(last().content?.[0].content?.[0].marks).toEqual([
      { type: "textStyle", attrs: { color: "#c8102e", fontFamily: null, fontSize: null } },
    ]);
  });

  it("applies a custom hex colour and rejects an invalid one", async () => {
    const { last, selectAll, user } = await setup();
    selectAll();
    await user.click(screen.getByRole("button", { name: "Text colour" }));
    const input = await screen.findByLabelText("Text colour custom hex");
    await user.type(input, "nope{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a colour");
    await user.clear(input);
    await user.type(input, "0a0b0c{Enter}");
    expect(last().content?.[0].content?.[0].marks?.[0].attrs?.color).toBe("#0a0b0c");
  });

  it("applies font size and family through the selects", async () => {
    const { last, selectAll, user } = await setup();
    selectAll();
    await user.selectOptions(screen.getByLabelText("Font size"), "24px");
    await user.selectOptions(screen.getByLabelText("Font family"), "Mukta");
    const attrs = last().content?.[0].content?.[0].marks?.[0].attrs;
    expect(attrs).toMatchObject({ fontSize: "24px", fontFamily: "Mukta" });
  });

  it("changes the paragraph style to a heading and to a quote", async () => {
    const { last, user } = await setup();
    await user.selectOptions(screen.getByLabelText("Paragraph style"), "h2");
    expect(last().content?.[0]).toMatchObject({ type: "heading", attrs: { level: 2 } });
    await user.selectOptions(screen.getByLabelText("Paragraph style"), "p");
    await user.selectOptions(screen.getByLabelText("Paragraph style"), "quote");
    expect(last().content?.[0].type).toBe("blockquote");
  });

  it("applies alignment", async () => {
    const { last, user } = await setup();
    await user.click(screen.getByRole("button", { name: "Align centre" }));
    expect(last().content?.[0].attrs?.textAlign).toBe("center");
    await user.click(screen.getByRole("button", { name: "Justify" }));
    expect(last().content?.[0].attrs?.textAlign).toBe("justify");
  });

  it("applies line spacing from the menu", async () => {
    const { last, user } = await setup();
    await user.click(screen.getByRole("button", { name: "Line spacing" }));
    await user.click(await screen.findByRole("menuitemradio", { name: /Double/ }));
    expect(last().content?.[0].attrs?.lineHeight).toBe("2");
  });

  it("inserts a 3x3 table with a header row", async () => {
    const { last, user } = await setup();
    await user.click(screen.getByRole("button", { name: "Table" }));
    await user.click(await screen.findByRole("menuitem", { name: /Insert 3/ }));
    const table = collect(last(), "table")[0];
    expect(table.content).toHaveLength(3);
    expect(table.content?.[0].content?.map((c) => c.type)).toEqual([
      "tableHeader",
      "tableHeader",
      "tableHeader",
    ]);
    expect(table.content?.[1].content).toHaveLength(3);
  });

  it("only offers row and column commands inside a table", async () => {
    const { user } = await setup();
    await user.click(screen.getByRole("button", { name: "Table" }));
    expect(await screen.findByRole("menuitem", { name: "Delete table" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("adds a link and rejects javascript: addresses", async () => {
    const { last, selectAll, user } = await setup();
    selectAll();
    await user.click(screen.getByRole("button", { name: "Link" }));
    const input = await screen.findByLabelText("Web address");
    await user.type(input, "javascript:alert(1){Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Only http, https and mailto");
    expect(JSON.stringify(last() ?? {})).not.toContain("javascript");
    await user.clear(input);
    await user.type(input, "https://mawapress.com{Enter}");
    await waitFor(() =>
      expect(last().content?.[0].content?.[0].marks).toEqual([
        { type: "link", attrs: expect.objectContaining({ href: "https://mawapress.com" }) },
      ]),
    );
  });

  it("embeds a YouTube video and a social post, rejecting other addresses", async () => {
    const { last, user } = await setup();
    await user.click(screen.getByRole("button", { name: "Video or social post" }));
    const input = await screen.findByLabelText("Address");
    await user.type(input, "https://evil.example/video{Enter}");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "https://www.youtube.com/watch?v=dQw4w9WgXcQ{Enter}");
    await waitFor(() => expect(collect(last(), "youtube")).toHaveLength(1));
    expect(collect(last(), "youtube")[0].attrs?.src).toBe(
      "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    );

    await user.click(screen.getByRole("button", { name: "Video or social post" }));
    await user.type(
      await screen.findByLabelText("Address"),
      "https://x.com/someone/status/1{Enter}",
    );
    await waitFor(() => expect(collect(last(), "embed")).toHaveLength(1));
    expect(collect(last(), "embed")[0].attrs).toEqual({
      provider: "x",
      url: "https://x.com/someone/status/1",
    });
  });

  it("inserts an image with a caption from the fallback dialog, and refuses non-https sources", async () => {
    const { last, user } = await setup();
    await user.click(screen.getByRole("button", { name: "Image" }));
    await user.type(
      await screen.findByLabelText("Image address"),
      "http://insecure.example/a.png{Enter}",
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("https://");
    await user.clear(screen.getByLabelText("Image address"));
    await user.type(screen.getByLabelText("Image address"), "https://cdn.mawapress.com/a.webp");
    await user.type(screen.getByLabelText("Alt text"), "Flood");
    await user.type(screen.getByLabelText("Caption"), "Photo: staff{Enter}");
    await waitFor(() => expect(collect(last(), "image")).toHaveLength(1));
    expect(collect(last(), "image")[0].attrs).toMatchObject({
      src: "https://cdn.mawapress.com/a.webp",
      alt: "Flood",
      caption: "Photo: staff",
    });
  });

  it("hands the picked image to the media picker callback", async () => {
    const onChange = vi.fn();
    let editor!: Editor;
    let insert!: (image: { src: string; alt?: string; caption?: string }) => void;
    const user = userEvent.setup();
    render(
      <RichEditor
        value={doc("x")}
        onChange={onChange}
        locale="en"
        onEditorReady={(e) => (editor = e)}
        onRequestImage={(fn) => (insert = fn)}
      />,
    );
    await waitFor(() => expect(editor).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "Image" }));
    act(() => insert({ src: "/media/a.webp", alt: "A" }));
    expect(collect(onChange.mock.calls.at(-1)?.[0], "image")[0].attrs).toMatchObject({
      src: "/media/a.webp",
      alt: "A",
    });
  });

  it("strips Word styles, comments and unsafe content on paste", async () => {
    const { editor, last } = await setup({ value: doc("") });
    const word =
      "<html><head><style>p.MsoNormal{mso-style-name:x}</style></head><body>" +
      "<!--[if gte mso 9]><xml><o:OfficeDocumentSettings/></xml><![endif]-->" +
      '<p class="MsoNormal" style="mso-margin-top-alt:auto">' +
      '<b><span style="mso-bidi-font-family:Arial;font-family:Mukta;font-size:12pt;color:#C8102E">Bold</span></b> <span style="mso-spacerun:yes"> </span><i>italic</i> <o:p></o:p>' +
      '<a href="javascript:alert(1)">bad</a> <a href="https://mawapress.com">good</a></p>' +
      '<img src="file:///C:/temp/x.png"><img src="/media/ok.webp"><img src="//evil.com/x.png"><img src="/\\evil.com/x.png"></body></html>';
    act(() => editor.view.pasteHTML(word));
    const json = last();
    const text = JSON.stringify(json);
    expect(text).not.toMatch(/mso|MsoNormal|o:p|javascript|file:|evil\.com/i);
    expect(collect(json, "image").map((n) => n.attrs?.src)).toEqual(["/media/ok.webp"]);
    const nodes = json.content?.flatMap((p) => p.content ?? []) ?? [];
    const bold = nodes.find((n) => n.text === "Bold");
    expect(bold?.marks?.map((m) => m.type)).toContain("bold");
    const styled = bold?.marks?.find((m) => m.type === "textStyle");
    expect(styled?.attrs).toMatchObject({
      color: "rgb(200, 16, 46)", // the DOM normalises hex; the renderer accepts rgb()
      fontFamily: "Mukta",
      fontSize: "16px",
    });
    expect(nodes.find((n) => n.text === "good")?.marks?.[0].type).toBe("link");
    expect(nodes.find((n) => n.text === "italic")?.marks?.map((m) => m.type)).toContain("italic");
  });

  it("uses a roving tabindex: one tab stop, arrows move between items", async () => {
    const { user } = await setup();
    const toolbar = screen.getByRole("toolbar");
    const stops = () =>
      Array.from(toolbar.querySelectorAll<HTMLElement>("button:not([disabled]), select")).filter(
        (el) => el.tabIndex === 0,
      );
    expect(stops()).toHaveLength(1);
    const bold = screen.getByRole("button", { name: "Bold" });
    bold.focus();
    expect(stops()).toEqual([bold]);
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("button", { name: "Italic" })).toHaveFocus();
    expect(stops()).toHaveLength(1);
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByLabelText("Paragraph style")).toHaveFocus();
    await user.keyboard("{Home}");
    expect(
      toolbar.querySelector<HTMLElement>("button:not([disabled]), select:not([disabled])"),
    ).toHaveFocus();
  });

  it("keeps arrow keys and Escape inside an open colour popover", async () => {
    const { user, editor } = await setup();
    await user.click(screen.getByRole("button", { name: "Text colour" }));
    const swatch = await screen.findByRole("button", { name: "Black #000000" });
    swatch.focus();
    await user.keyboard("{ArrowRight}");
    // The arrow did not leak to the toolbar's roving focus: focus stays on the swatch.
    expect(swatch).toHaveFocus();
    expect(screen.getByRole("button", { name: "Undo" })).not.toHaveFocus();
    expect(screen.getByRole("button", { name: "Redo" })).not.toHaveFocus();
    const focusSpy = vi.spyOn(editor.commands, "focus");
    await user.keyboard("{Escape}");
    expect(focusSpy).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Black #000000" })).not.toBeInTheDocument(),
    );
  });

  it("shows word and character counts", async () => {
    await setup();
    expect(await screen.findByText("2 words")).toBeInTheDocument();
    expect(screen.getByText("11 characters")).toBeInTheDocument();
  });

  it("is read-only without a toolbar", async () => {
    render(<RichEditor value={doc("Read me")} onChange={() => {}} locale="en" readOnly />);
    expect(await screen.findByText("Read me")).toBeInTheDocument();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });
});
