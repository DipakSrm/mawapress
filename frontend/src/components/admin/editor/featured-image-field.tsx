"use client";

import { ImageIcon, ImagePlus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { MediaOut } from "@/lib/admin/editor/draft";
import { mediaThumb } from "@/lib/admin/media";

interface Props {
  media: MediaOut | null;
  onChange: (media: MediaOut | null) => void;
  /** Opens the media picker. */
  onRequestPick: () => void;
  disabled?: boolean;
}

export function FeaturedImageField({ media, onChange, onRequestPick, disabled }: Props) {
  return (
    <div className="space-y-2">
      {media ? (
        <figure className="overflow-hidden rounded-lg border bg-muted">
          {/* A plain img: the thumbnail is a small variant served by the media route. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={mediaThumb(media)}
            alt={media.alt_ne || media.alt_en || media.caption || "Featured image"}
            width={media.width}
            height={media.height}
            className="aspect-[1200/630] w-full object-cover"
          />
        </figure>
      ) : (
        <div className="flex aspect-[1200/630] w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed bg-muted/40 text-xs text-muted-foreground">
          <ImageIcon aria-hidden className="size-6" />
          No featured image
        </div>
      )}
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRequestPick}
          disabled={disabled}
        >
          <ImagePlus aria-hidden /> {media ? "Change image" : "Choose image"}
        </Button>
        {media && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onChange(null)}
            disabled={disabled}
          >
            <X aria-hidden /> Remove
          </Button>
        )}
      </div>
    </div>
  );
}
