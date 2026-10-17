"use client";

import { ImageIcon, ImagePlus, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { MediaOut } from "@/lib/admin/editor/draft";

/** Opens a media picker. The picker calls `select` with the chosen item. */
export type MediaPickRequest = (select: (media: MediaOut) => void) => void;

interface Props {
  media: MediaOut | null;
  onChange: (media: MediaOut | null) => void;
  /** The media library hooks in here. Without it the field shows a placeholder dialog. */
  onRequestPick?: MediaPickRequest;
  disabled?: boolean;
}

export function mediaThumb(media: MediaOut): string {
  return media.variants["320"] ?? media.variants["640"] ?? media.url;
}

export function FeaturedImageField({ media, onChange, onRequestPick, disabled }: Props) {
  const [placeholder, setPlaceholder] = useState(false);

  function pick() {
    if (onRequestPick) onRequestPick(onChange);
    else setPlaceholder(true);
  }

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
        <Button type="button" variant="outline" size="sm" onClick={pick} disabled={disabled}>
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
      {placeholder && (
        <Dialog open onOpenChange={(open) => !open && setPlaceholder(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Media library</DialogTitle>
              <DialogDescription>
                Picking from the media library arrives in the next step. For now, inline images can
                be added from the editor toolbar.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button type="button" onClick={() => setPlaceholder(false)}>
                Close
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
