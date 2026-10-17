"use client";

import {
  EditorContent,
  useEditor,
  useEditorState,
  type Editor,
  type JSONContent,
} from "@tiptap/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { cleanPastedHtml } from "@/lib/editor/paste";
import { cn } from "@/lib/utils";
import { ImageDialog, LinkDialog, MediaDialog, type ImageInput } from "./editor-dialogs";
import { buildExtensions } from "./extensions";
import { Toolbar } from "./toolbar";

export type EditorLocale = "ne" | "en";

export interface RichEditorProps {
  value: JSONContent;
  onChange: (json: JSONContent) => void;
  locale: EditorLocale;
  /**
   * Opens the media picker. It receives `insert`, which the picker calls with the chosen image. When omitted,
   * the editor shows a plain "image address" dialog instead.
   */
  onRequestImage?: (
    insert: (image: { src: string; alt?: string; caption?: string }) => void,
  ) => void;
  readOnly?: boolean;
  /** Called once the TipTap editor exists (used by the post form and by tests). */
  onEditorReady?: (editor: Editor) => void;
  className?: string;
  "aria-label"?: string;
}

const PLACEHOLDER: Record<EditorLocale, string> = {
  ne: "लेख्न सुरु गर्नुहोस्…",
  en: "Start writing…",
};

type DialogName = "link" | "image" | "media" | null;

/** Word-like rich text editor. Client only: it renders after mount, so server HTML never mismatches. */
export function RichEditor({
  value,
  onChange,
  locale,
  onRequestImage,
  readOnly = false,
  onEditorReady,
  className,
  "aria-label": ariaLabel = "Article body",
}: RichEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const lastEmitted = useRef<JSONContent | null>(null);
  const onChangeRef = useRef(onChange);
  const [dialog, setDialog] = useState<DialogName>(null);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const extensions = useMemo(() => buildExtensions(PLACEHOLDER[locale]), [locale]);

  const editor = useEditor(
    {
      extensions,
      content: value,
      editable: !readOnly,
      immediatelyRender: false,
      shouldRerenderOnTransaction: false,
      editorProps: {
        attributes: {
          lang: locale,
          role: "textbox",
          "aria-multiline": "true",
          "aria-label": ariaLabel,
          class: "article-body editor-content",
        },
        transformPastedHTML: cleanPastedHtml,
      },
      onUpdate: ({ editor: ed }) => {
        const json = ed.getJSON();
        lastEmitted.current = json;
        onChangeRef.current(json);
      },
    },
    [extensions],
  );

  useEffect(() => {
    if (editor) onEditorReady?.(editor);
  }, [editor, onEditorReady]);

  // Keep the document in step with `value` when the parent replaces it (e.g. switching translation).
  useEffect(() => {
    if (!editor || value === lastEmitted.current) return;
    if (JSON.stringify(value) !== JSON.stringify(editor.getJSON())) {
      editor.commands.setContent(value, false);
    }
  }, [editor, value]);

  useEffect(() => {
    editor?.setEditable(!readOnly);
  }, [editor, readOnly]);

  useEffect(() => {
    if (!editor) return;
    editor.setOptions({
      editorProps: {
        ...editor.options.editorProps,
        attributes: {
          ...(editor.options.editorProps.attributes as Record<string, string>),
          lang: locale,
          "aria-label": ariaLabel,
        },
      },
    });
  }, [editor, locale, ariaLabel]);

  const counts = useEditorState({
    editor,
    selector: ({ editor: ed }) =>
      ed
        ? {
            words: ed.storage.characterCount.words() as number,
            chars: ed.storage.characterCount.characters() as number,
          }
        : { words: 0, chars: 0 },
  });

  function insertImage(image: ImageInput | { src: string; alt?: string; caption?: string }) {
    editor
      ?.chain()
      .focus()
      .setImage({ src: image.src, alt: image.alt || undefined })
      .updateAttributes("image", { caption: image.caption || null })
      .run();
  }

  const linkHref = editor ? ((editor.getAttributes("link") as { href?: string }).href ?? "") : "";

  return (
    <div
      ref={containerRef}
      lang={locale}
      className={cn(
        "rounded-lg border bg-card text-card-foreground focus-within:border-ring/60",
        className,
      )}
    >
      {editor && !readOnly && (
        <Toolbar
          editor={editor}
          containerRef={containerRef}
          onLink={() => setDialog("link")}
          onImage={() => (onRequestImage ? onRequestImage(insertImage) : setDialog("image"))}
          onMedia={() => setDialog("media")}
        />
      )}
      <EditorContent editor={editor} className="min-h-72 px-4 py-3 sm:px-6" />
      {!readOnly && (
        <div
          className="flex items-center justify-end gap-3 border-t px-3 py-1.5 text-xs text-muted-foreground"
          data-testid="editor-footer"
        >
          <span>{counts?.words ?? 0} words</span>
          <span>{counts?.chars ?? 0} characters</span>
        </div>
      )}
      {editor && dialog === "link" && (
        <LinkDialog
          initialUrl={linkHref}
          hasLink={!!linkHref}
          onClose={() => setDialog(null)}
          onApply={(url) => {
            const { empty } = editor.state.selection;
            if (empty && !editor.isActive("link")) {
              editor
                .chain()
                .focus()
                .insertContent({
                  type: "text",
                  text: url,
                  marks: [{ type: "link", attrs: { href: url } }],
                })
                .run();
            } else {
              editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
            }
            setDialog(null);
          }}
          onRemove={() => {
            editor.chain().focus().extendMarkRange("link").unsetLink().run();
            setDialog(null);
          }}
        />
      )}
      {editor && dialog === "image" && (
        <ImageDialog
          onClose={() => setDialog(null)}
          onInsert={(image) => {
            insertImage(image);
            setDialog(null);
          }}
        />
      )}
      {editor && dialog === "media" && (
        <MediaDialog
          onClose={() => setDialog(null)}
          onInsert={(target) => {
            if (target.kind === "youtube")
              editor.chain().focus().setYoutubeVideo({ src: target.url }).run();
            else
              editor.chain().focus().setEmbed({ provider: target.provider, url: target.url }).run();
            setDialog(null);
          }}
        />
      )}
    </div>
  );
}
