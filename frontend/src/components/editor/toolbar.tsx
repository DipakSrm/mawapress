"use client";

import { useEditorState, type Editor } from "@tiptap/react";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  ArrowUpDown,
  Baseline,
  Bold,
  Ellipsis,
  Highlighter,
  ImagePlus,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  Redo2,
  RemoveFormatting,
  Strikethrough,
  Table2,
  Underline,
  Undo2,
  Video,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { NativeSelect } from "@/components/ui/native-select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { FONT_FAMILIES, LINE_HEIGHTS } from "@/lib/editor/paste";
import { ColorPicker, ToolButton, ToolDivider, ToolGroup, type Swatch } from "./toolbar-controls";

export const TEXT_COLORS: Swatch[] = [
  { name: "Ink", value: "#111827" },
  { name: "Black", value: "#000000" },
  { name: "Grey", value: "#6b7280" },
  { name: "Gurans red", value: "#c8102e" },
  { name: "Flag blue", value: "#003893" },
  { name: "Green", value: "#15803d" },
  { name: "Orange", value: "#c2410c" },
  { name: "Purple", value: "#7e22ce" },
  { name: "Teal", value: "#0f766e" },
  { name: "Brown", value: "#78350f" },
  { name: "Pink", value: "#be185d" },
  { name: "White", value: "#ffffff" },
];

export const HIGHLIGHT_COLORS: Swatch[] = [
  { name: "Yellow", value: "#fef08a" },
  { name: "Green", value: "#bbf7d0" },
  { name: "Blue", value: "#bfdbfe" },
  { name: "Pink", value: "#fbcfe8" },
  { name: "Orange", value: "#fed7aa" },
  { name: "Grey", value: "#e5e7eb" },
];

export const FONT_SIZES = [12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 48];
const BLOCK_STYLES = [
  { value: "p", label: "Paragraph" },
  { value: "h1", label: "Heading 1" },
  { value: "h2", label: "Heading 2" },
  { value: "h3", label: "Heading 3" },
  { value: "h4", label: "Heading 4" },
  { value: "quote", label: "Quote" },
];
const LINE_HEIGHT_LABELS: Record<string, string> = {
  "": "Default",
  "1": "Single (1.0)",
  "1.15": "Tight (1.15)",
  "1.5": "Relaxed (1.5)",
  "2": "Double (2.0)",
};

function snapshot(editor: Editor) {
  const textStyle = editor.getAttributes("textStyle") as {
    fontFamily?: string | null;
    fontSize?: string | null;
    color?: string | null;
  };
  const block = editor.isActive("blockquote")
    ? "quote"
    : ([1, 2, 3, 4].find((level) => editor.isActive("heading", { level })) ?? 0);
  const para = editor.getAttributes(editor.isActive("heading") ? "heading" : "paragraph") as {
    textAlign?: string | null;
    lineHeight?: string | null;
  };
  return {
    block: block === "quote" ? "quote" : block ? `h${block}` : "p",
    fontFamily: textStyle.fontFamily ?? "",
    fontSize: textStyle.fontSize ?? "",
    color: textStyle.color ?? null,
    highlight: (editor.getAttributes("highlight") as { color?: string | null }).color ?? null,
    bold: editor.isActive("bold"),
    italic: editor.isActive("italic"),
    underline: editor.isActive("underline"),
    strike: editor.isActive("strike"),
    bullet: editor.isActive("bulletList"),
    ordered: editor.isActive("orderedList"),
    link: editor.isActive("link"),
    align: para.textAlign || "left",
    lineHeight: para.lineHeight ?? "",
    inTable: editor.isActive("table"),
    canUndo: editor.can().undo(),
    canRedo: editor.can().redo(),
  };
}

/** Collapses the secondary groups into a "More" panel when the toolbar is narrower than `threshold`. */
function useNarrow(ref: RefObject<HTMLElement | null>, threshold: number): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setNarrow(entry.contentRect.width < threshold),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, threshold]);
  return narrow;
}

export interface ToolbarProps {
  editor: Editor;
  containerRef: RefObject<HTMLDivElement | null>;
  onLink: () => void;
  onImage: () => void;
  onMedia: () => void;
}

export function Toolbar({ editor, containerRef, onLink, onImage, onMedia }: ToolbarProps) {
  const s = useEditorState({ editor, selector: ({ editor }) => snapshot(editor) });
  const narrow = useNarrow(containerRef, 760);
  const run = () => editor.chain().focus();

  function onBlock(value: string) {
    if (value === "quote") {
      if (!editor.isActive("blockquote")) run().setParagraph().setBlockquote().run();
    } else {
      if (editor.isActive("blockquote")) run().lift("blockquote").run();
      if (value === "p") run().setParagraph().run();
      else
        run()
          .setHeading({ level: Number(value[1]) as 1 | 2 | 3 | 4 })
          .run();
    }
  }

  const rootRef = useRef<HTMLDivElement>(null);
  const activeItem = useRef<HTMLElement | null>(null);

  const toolbarItems = () =>
    Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), select:not([disabled])",
      ) ?? [],
    );

  // Roving tabindex (WAI-ARIA toolbar): exactly one item is a tab stop; arrows move between items.
  useLayoutEffect(() => {
    const items = toolbarItems();
    if (!activeItem.current || !items.includes(activeItem.current))
      activeItem.current = items[0] ?? null;
    for (const el of items) el.tabIndex = el === activeItem.current ? 0 : -1;
  });

  function onFocus(e: FocusEvent<HTMLDivElement>) {
    const target = e.target as HTMLElement;
    if (!toolbarItems().includes(target) || target === activeItem.current) return;
    activeItem.current = target;
    for (const el of toolbarItems()) el.tabIndex = el === target ? 0 : -1;
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    // React events bubble through portals (colour popover, menus); only act on the toolbar's own items.
    const target = e.target as HTMLElement;
    if (!e.currentTarget.contains(target)) return;
    const items = toolbarItems();
    const i = items.indexOf(target);
    if (i < 0) return;
    if (e.key === "Escape") {
      editor.commands.focus();
      return;
    }
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    let next: HTMLElement | undefined;
    if (step) next = items[(i + step + items.length) % items.length];
    else if (e.key === "Home") next = items[0];
    else if (e.key === "End") next = items[items.length - 1];
    else return;
    next?.focus();
    e.preventDefault();
  }

  const sizeOptions = FONT_SIZES.map((n) => `${n}px`);
  if (s.fontSize && !sizeOptions.includes(s.fontSize)) sizeOptions.push(s.fontSize);

  const styleGroup = (
    <ToolGroup label="Style">
      <NativeSelect
        aria-label="Paragraph style"
        className="h-7 text-[0.8rem]"
        value={s.block}
        onChange={(e) => onBlock(e.target.value)}
      >
        {BLOCK_STYLES.map((b) => (
          <option key={b.value} value={b.value}>
            {b.label}
          </option>
        ))}
      </NativeSelect>
    </ToolGroup>
  );

  const fontGroup = (
    <ToolGroup label="Font">
      <NativeSelect
        aria-label="Font family"
        className="h-7 text-[0.8rem]"
        value={s.fontFamily}
        onChange={(e) =>
          e.target.value ? run().setFontFamily(e.target.value).run() : run().unsetFontFamily().run()
        }
      >
        <option value="">Default font</option>
        {FONT_FAMILIES.map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </NativeSelect>
      <NativeSelect
        aria-label="Font size"
        className="h-7 w-[4.5rem] text-[0.8rem]"
        value={s.fontSize}
        onChange={(e) =>
          e.target.value ? run().setFontSize(e.target.value).run() : run().unsetFontSize().run()
        }
      >
        <option value="">Size</option>
        {sizeOptions.map((size) => (
          <option key={size} value={size}>
            {parseInt(size, 10)}
          </option>
        ))}
      </NativeSelect>
    </ToolGroup>
  );

  const textGroup = (
    <ToolGroup label="Text formatting">
      <ToolButton
        label="Bold"
        keys="Mod+B"
        active={s.bold}
        onClick={() => run().toggleBold().run()}
      >
        <Bold />
      </ToolButton>
      <ToolButton
        label="Italic"
        keys="Mod+I"
        active={s.italic}
        onClick={() => run().toggleItalic().run()}
      >
        <Italic />
      </ToolButton>
      <ToolButton
        label="Underline"
        keys="Mod+U"
        active={s.underline}
        onClick={() => run().toggleUnderline().run()}
      >
        <Underline />
      </ToolButton>
    </ToolGroup>
  );

  const decorateGroup = (
    <ToolGroup label="Text decoration">
      <ToolButton
        label="Strikethrough"
        keys="Mod+Shift+S"
        active={s.strike}
        onClick={() => run().toggleStrike().run()}
      >
        <Strikethrough />
      </ToolButton>
      <ColorPicker
        label="Text colour"
        icon={<Baseline />}
        swatches={TEXT_COLORS}
        current={s.color}
        resetLabel="Automatic colour"
        onPick={(c) => run().setColor(c).run()}
        onReset={() => run().unsetColor().removeEmptyTextStyle().run()}
      />
      <ColorPicker
        label="Highlight colour"
        icon={<Highlighter />}
        swatches={HIGHLIGHT_COLORS}
        current={s.highlight}
        resetLabel="No highlight"
        onPick={(c) => run().setHighlight({ color: c }).run()}
        onReset={() => run().unsetHighlight().run()}
      />
    </ToolGroup>
  );

  const alignGroup = (
    <ToolGroup label="Alignment and spacing">
      {(
        [
          ["left", "Align left", "Mod+Shift+L", <AlignLeft key="l" />],
          ["center", "Align centre", "Mod+Shift+E", <AlignCenter key="c" />],
          ["right", "Align right", "Mod+Shift+R", <AlignRight key="r" />],
          ["justify", "Justify", "Mod+Shift+J", <AlignJustify key="j" />],
        ] as const
      ).map(([value, label, keys, icon]) => (
        <ToolButton
          key={value}
          label={label}
          keys={keys}
          active={s.align === value}
          onClick={() => run().setTextAlign(value).run()}
        >
          {icon}
        </ToolButton>
      ))}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Line spacing"
              data-active={s.lineHeight ? "true" : undefined}
              className="text-foreground/80 hover:text-foreground data-[active=true]:bg-primary/10 data-[active=true]:text-primary"
              onMouseDown={(e) => e.preventDefault()}
            />
          }
        >
          <ArrowUpDown />
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuRadioGroup
            value={s.lineHeight}
            onValueChange={(v) =>
              v ? run().setLineHeight(String(v)).run() : run().unsetLineHeight().run()
            }
          >
            {["", ...LINE_HEIGHTS].map((h) => (
              <DropdownMenuRadioItem key={h || "default"} value={h}>
                {LINE_HEIGHT_LABELS[h]}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </ToolGroup>
  );

  const listGroup = (
    <ToolGroup label="Lists">
      <ToolButton
        label="Bulleted list"
        keys="Mod+Shift+8"
        active={s.bullet}
        onClick={() => run().toggleBulletList().run()}
      >
        <List />
      </ToolButton>
      <ToolButton
        label="Numbered list"
        keys="Mod+Shift+7"
        active={s.ordered}
        onClick={() => run().toggleOrderedList().run()}
      >
        <ListOrdered />
      </ToolButton>
    </ToolGroup>
  );

  const insertPrimary = (
    <ToolGroup label="Link and image">
      <ToolButton label="Link" keys="Mod+K" active={s.link} onClick={onLink}>
        <Link2 />
      </ToolButton>
      <ToolButton label="Image" onClick={onImage}>
        <ImagePlus />
      </ToolButton>
    </ToolGroup>
  );

  const insertSecondary = (
    <ToolGroup label="Insert">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Table"
              data-active={s.inTable ? "true" : undefined}
              className="text-foreground/80 hover:text-foreground data-[active=true]:bg-primary/10 data-[active=true]:text-primary"
              onMouseDown={(e) => e.preventDefault()}
            />
          }
        >
          <Table2 />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="min-w-48">
          <DropdownMenuItem
            onClick={() => run().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}
          >
            Insert 3 × 3 table
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled={!s.inTable} onClick={() => run().addRowBefore().run()}>
            Add row above
          </DropdownMenuItem>
          <DropdownMenuItem disabled={!s.inTable} onClick={() => run().addRowAfter().run()}>
            Add row below
          </DropdownMenuItem>
          <DropdownMenuItem disabled={!s.inTable} onClick={() => run().deleteRow().run()}>
            Delete row
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled={!s.inTable} onClick={() => run().addColumnBefore().run()}>
            Add column left
          </DropdownMenuItem>
          <DropdownMenuItem disabled={!s.inTable} onClick={() => run().addColumnAfter().run()}>
            Add column right
          </DropdownMenuItem>
          <DropdownMenuItem disabled={!s.inTable} onClick={() => run().deleteColumn().run()}>
            Delete column
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled={!s.inTable} onClick={() => run().toggleHeaderRow().run()}>
            Toggle header row
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={!s.inTable}
            variant="destructive"
            onClick={() => run().deleteTable().run()}
          >
            Delete table
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ToolButton label="Video or social post" onClick={onMedia}>
        <Video />
      </ToolButton>
      <ToolButton label="Horizontal line" onClick={() => run().setHorizontalRule().run()}>
        <Minus />
      </ToolButton>
      <ToolButton
        label="Clear formatting"
        onClick={() => run().unsetAllMarks().clearNodes().unsetTextAlign().unsetLineHeight().run()}
      >
        <RemoveFormatting />
      </ToolButton>
    </ToolGroup>
  );

  const secondary: ReactNode = (
    <>
      {fontGroup}
      {decorateGroup}
      {alignGroup}
      {insertSecondary}
    </>
  );

  return (
    <div
      role="toolbar"
      aria-label="Formatting"
      aria-orientation="horizontal"
      ref={rootRef}
      onFocus={onFocus}
      onKeyDown={onKeyDown}
      className="sticky top-0 z-20 flex flex-wrap items-center gap-x-1 gap-y-1 rounded-t-lg border-b bg-card/95 px-2 py-1.5 backdrop-blur supports-backdrop-filter:bg-card/80"
    >
      <ToolGroup label="History">
        <ToolButton
          label="Undo"
          keys="Mod+Z"
          disabled={!s.canUndo}
          onClick={() => run().undo().run()}
        >
          <Undo2 />
        </ToolButton>
        <ToolButton
          label="Redo"
          keys="Mod+Shift+Z"
          disabled={!s.canRedo}
          onClick={() => run().redo().run()}
        >
          <Redo2 />
        </ToolButton>
      </ToolGroup>
      <ToolDivider />
      {styleGroup}
      {textGroup}
      <ToolDivider />
      {listGroup}
      {insertPrimary}
      <ToolDivider />
      {narrow ? (
        <Popover>
          <PopoverTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label="More formatting"
                onMouseDown={(e) => e.preventDefault()}
              />
            }
          >
            <Ellipsis aria-hidden />
            More
          </PopoverTrigger>
          <PopoverContent
            align="end"
            className="flex w-[min(22rem,calc(100vw-1rem))] flex-wrap gap-1.5"
          >
            {secondary}
          </PopoverContent>
        </Popover>
      ) : (
        secondary
      )}
    </div>
  );
}
