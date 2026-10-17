"use client";

import { Search } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { MEDIA_PAGE, useMediaList, useMediaUpload, type MediaOut } from "@/lib/admin/media";
import { useDebounced } from "@/lib/admin/use-debounced";
import { Pager } from "../pager";
import { MediaEmpty, MediaGrid } from "./media-grid";
import { UploadZone } from "./upload-zone";

interface Props {
  title?: string;
  confirmLabel?: string;
  onSelect: (media: MediaOut) => void;
  onClose: () => void;
}

/** Choose an image from the library, or upload one without leaving the editor. */
export function MediaPicker({
  title = "Choose an image",
  confirmLabel = "Use image",
  onSelect,
  onClose,
}: Props) {
  const [input, setInput] = useState("");
  const q = useDebounced(input.trim());
  const [page, setPage] = useState(1);
  const [chosen, setChosen] = useState<MediaOut | null>(null);
  const list = useMediaList(q, page);
  // A fresh upload is the likely choice: preselect it (it also appears first in the grid).
  const uploads = useMediaUpload(setChosen);

  const items = list.data?.items ?? [];

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90vh] flex-col sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>Pick a photo from the library or upload a new one.</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
          <UploadZone
            compact
            items={uploads.items}
            onFiles={uploads.add}
            onDismiss={uploads.dismiss}
          />
          <div className="relative max-w-sm">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              aria-label="Search media"
              placeholder="Search alt text and captions"
              maxLength={200}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                setPage(1);
              }}
              className="pl-8"
            />
          </div>
          {list.isPending ? (
            <p role="status" className="py-8 text-center text-sm text-muted-foreground">
              Loading…
            </p>
          ) : list.isError ? (
            <div role="alert" className="flex flex-col items-center gap-2 py-8 text-center">
              <p className="text-sm">Could not load media.</p>
              <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
                Retry
              </Button>
            </div>
          ) : items.length === 0 ? (
            <MediaEmpty filtered={q !== ""} />
          ) : (
            <MediaGrid
              label="Library images"
              items={items}
              selectedId={chosen?.id}
              onSelect={setChosen}
            />
          )}
          <Pager page={page} pageSize={MEDIA_PAGE} total={list.data?.total ?? 0} onPage={setPage} />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" disabled={!chosen} onClick={() => chosen && onSelect(chosen)}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
