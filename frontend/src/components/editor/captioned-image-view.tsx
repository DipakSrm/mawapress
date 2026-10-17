"use client";

import { NodeViewWrapper, type NodeViewProps } from "@tiptap/react";

/** Image + caption input inside the editor; the caption is stored on the image node (attr `caption`). */
export function CaptionedImageView({ node, updateAttributes, selected, editor }: NodeViewProps) {
  const { src, alt, caption } = node.attrs as {
    src: string;
    alt: string | null;
    caption: string | null;
  };
  const editable = editor.isEditable;
  return (
    <NodeViewWrapper as="figure" className={selected ? "is-selected" : undefined} data-drag-handle>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt ?? ""} draggable={false} />
      {editable ? (
        <input
          type="text"
          className="figcaption-input"
          aria-label="Image caption"
          placeholder="Add a caption"
          value={caption ?? ""}
          maxLength={300}
          onChange={(e) => updateAttributes({ caption: e.target.value || null })}
          onKeyDown={(e) => e.stopPropagation()}
        />
      ) : (
        caption && <figcaption>{caption}</figcaption>
      )}
    </NodeViewWrapper>
  );
}
