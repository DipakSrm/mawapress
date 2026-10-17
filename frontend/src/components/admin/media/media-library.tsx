"use client";

import { Search } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MEDIA_PAGE, useMediaList, useMediaUpload, type MediaOut } from "@/lib/admin/media";
import { useDebounced } from "@/lib/admin/use-debounced";
import { useSession } from "@/lib/auth";
import { Pager } from "../pager";
import { MediaDetail } from "./media-detail";
import { MediaEmpty, MediaGrid } from "./media-grid";
import { UploadZone } from "./upload-zone";

export function MediaLibrary() {
  const { hasRole } = useSession();
  const [input, setInput] = useState("");
  const q = useDebounced(input.trim());
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<MediaOut | null>(null);
  const list = useMediaList(q, page);
  const uploads = useMediaUpload();

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Media</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Photos for stories and featured images.
        </p>
      </div>

      <UploadZone items={uploads.items} onFiles={uploads.add} onDismiss={uploads.dismiss} />

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
        <div
          role="status"
          aria-label="Loading media"
          className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6"
        >
          {Array.from({ length: 12 }, (_, i) => (
            <div key={i} className="aspect-square animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : list.isError ? (
        <div role="alert" className="flex flex-col items-center gap-3 py-14 text-center">
          <p className="font-medium">Could not load media</p>
          <Button variant="outline" onClick={() => void list.refetch()}>
            Retry
          </Button>
        </div>
      ) : items.length === 0 ? (
        page > 1 ? (
          <div className="flex flex-col items-center gap-3 py-14 text-center">
            <p className="font-medium">That page is past the end</p>
            <Button variant="outline" onClick={() => setPage(1)}>
              Back to the first page
            </Button>
          </div>
        ) : (
          <MediaEmpty filtered={q !== ""} />
        )
      ) : (
        <MediaGrid
          label="Media library"
          items={items}
          selectedId={selected?.id}
          onSelect={setSelected}
        />
      )}

      <Pager page={page} pageSize={MEDIA_PAGE} total={total} onPage={setPage} />

      {selected && (
        <MediaDetail
          key={selected.id}
          media={selected}
          canDelete={hasRole("editor")}
          onChange={setSelected}
          onDeleted={() => setSelected(null)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
