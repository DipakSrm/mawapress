"use client";

import { Check, ImageIcon } from "lucide-react";
import { mediaLabel, mediaThumb, type MediaOut } from "@/lib/admin/media";
import { cn } from "@/lib/utils";

interface Props {
  items: MediaOut[];
  selectedId?: string | null;
  onSelect: (media: MediaOut) => void;
  label: string;
}

export function MediaGrid({ items, selectedId, onSelect, label }: Props) {
  return (
    <ul
      aria-label={label}
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
    >
      {items.map((m, i) => {
        const selected = m.id === selectedId;
        return (
          <li key={m.id}>
            <button
              type="button"
              onClick={() => onSelect(m)}
              aria-pressed={selected}
              aria-label={`${mediaLabel(m)}, ${m.width}×${m.height}, number ${i + 1}`}
              className={cn(
                "group relative block aspect-square w-full overflow-hidden rounded-lg bg-muted ring-1 ring-foreground/10 outline-none focus-visible:ring-3 focus-visible:ring-ring",
                selected && "ring-2 ring-primary",
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={mediaThumb(m)}
                alt=""
                loading="lazy"
                className="size-full object-cover transition-transform group-hover:scale-[1.03]"
              />
              {selected && (
                <span className="absolute top-1.5 right-1.5 flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Check aria-hidden className="size-3.5" />
                </span>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function MediaEmpty({ filtered }: { filtered: boolean }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-14 text-center">
      <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <ImageIcon aria-hidden className="size-6" />
      </span>
      <p className="font-medium">{filtered ? "No images match your search" : "No images yet"}</p>
      <p className="max-w-sm text-sm text-muted-foreground">
        {filtered
          ? "Search looks at alt text and captions."
          : "Upload photos to use them in stories and as featured images."}
      </p>
    </div>
  );
}
