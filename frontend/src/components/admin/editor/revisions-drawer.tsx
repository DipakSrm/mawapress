"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { RichEditor } from "@/components/editor/RichEditor";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import type { Locale } from "@/lib/admin/editor/seo";
import { formatDateTime, timeAgo } from "@/lib/admin/post-display";
import type { PostOut } from "@/lib/admin/posts";
import { api, ifMatch, isApiError, type components } from "@/lib/api";
import type { JSONContent } from "@tiptap/react";

type RevisionList = components["schemas"]["RevisionListOut"];
type RevisionOut = components["schemas"]["RevisionOut"];

const PAGE = 10;
const NAME: Record<string, string> = { ne: "Nepali", en: "English" };

interface Props {
  postId: string;
  locale: Locale;
  viewerId: string;
  /** Editors can restore a revision. */
  canRestore: boolean;
  /** Saves pending edits first, so the restore starts from a known version. Resolves false when that failed. */
  prepare: () => Promise<boolean>;
  getUpdatedAt: () => string | null;
  onRestored: (post: PostOut) => void;
  onConflict: (currentUpdatedAt: string | null) => void;
  onClose: () => void;
}

function editorLabel(id: string, viewerId: string) {
  return id === viewerId ? "You" : "Another editor";
}

/** Paginated revision history for the open language, a read-only view of one, and restore. */
export function RevisionsDrawer({
  postId,
  locale,
  viewerId,
  canRestore,
  prepare,
  getUpdatedAt,
  onRestored,
  onConflict,
  onClose,
}: Props) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const list = useQuery({
    queryKey: ["revisions", postId, locale, offset],
    queryFn: () =>
      api.get<RevisionList>(`/api/posts/${postId}/revisions`, {
        query: { locale, limit: PAGE, offset },
      }),
    placeholderData: keepPreviousData,
    gcTime: 0,
  });
  const detail = useQuery({
    queryKey: ["revision", postId, selected],
    queryFn: () => api.get<RevisionOut>(`/api/posts/${postId}/revisions/${selected}`),
    enabled: selected !== null,
    gcTime: 0,
  });

  const total = list.data?.total ?? 0;

  async function restore() {
    if (selected === null || restoring) return;
    setRestoring(true);
    try {
      if (!(await prepare())) {
        toast.error("Fix the saving problem first, then restore.");
        return;
      }
      const out = await api.post<PostOut>(
        `/api/posts/${postId}/revisions/${selected}/restore`,
        undefined,
        { headers: ifMatch(getUpdatedAt() ?? "") },
      );
      toast.success("Revision restored");
      onRestored(out);
      onClose();
    } catch (e) {
      if (isApiError(e) && e.status === 412) {
        const current = e.details.current_updated_at;
        onConflict(typeof current === "string" ? current : null);
        onClose();
      } else {
        toast.error(isApiError(e) ? e.message : "Could not restore the revision");
      }
    } finally {
      setRestoring(false);
      setConfirming(false);
    }
  }

  return (
    <>
      <Sheet open onOpenChange={(open) => !open && !restoring && onClose()}>
        <SheetContent side="right" className="w-full gap-0 sm:max-w-2xl">
          <div className="border-b p-4 pr-12">
            <SheetTitle>Revisions</SheetTitle>
            <SheetDescription>
              Earlier saved versions of the {NAME[locale]} text. Restoring one keeps the current
              text in the history.
            </SheetDescription>
          </div>

          {selected === null ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {list.isPending ? (
                  <p className="p-4 text-sm text-muted-foreground">Loading…</p>
                ) : list.isError ? (
                  <div className="space-y-2 p-4 text-sm">
                    <p role="alert">Could not load the revisions.</p>
                    <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
                      Try again
                    </Button>
                  </div>
                ) : list.data.items.length === 0 ? (
                  <p className="p-4 text-sm text-muted-foreground">
                    No revisions yet. One is kept each time the text is saved.
                  </p>
                ) : (
                  <ul aria-label="Revisions">
                    {list.data.items.map((rev) => (
                      <li key={rev.id}>
                        <button
                          type="button"
                          onClick={() => setSelected(rev.id)}
                          className="flex w-full flex-col gap-0.5 rounded-lg px-3 py-2.5 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                        >
                          <span lang={rev.locale} className="truncate text-sm font-medium">
                            {rev.title}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            <time dateTime={rev.created_at} title={rev.created_at}>
                              {formatDateTime(rev.created_at)} · {timeAgo(rev.created_at)}
                            </time>{" "}
                            · {editorLabel(rev.editor_id, viewerId)} ·{" "}
                            {NAME[rev.locale] ?? rev.locale}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {total > PAGE && (
                <div className="flex items-center justify-between border-t p-3 text-xs text-muted-foreground">
                  <span>
                    {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
                  </span>
                  <div className="flex gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={offset === 0}
                      onClick={() => setOffset(Math.max(0, offset - PAGE))}
                    >
                      <ChevronLeft aria-hidden /> Newer
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={offset + PAGE >= total}
                      onClick={() => setOffset(offset + PAGE)}
                    >
                      Older <ChevronRight aria-hidden />
                    </Button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="flex items-center justify-between gap-2 border-b px-4 py-2">
                <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
                  <ArrowLeft aria-hidden /> All revisions
                </Button>
                {canRestore && (
                  <Button size="sm" disabled={!detail.data} onClick={() => setConfirming(true)}>
                    <RotateCcw aria-hidden /> Restore this version
                  </Button>
                )}
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                {detail.isPending ? (
                  <p className="text-sm text-muted-foreground">Loading…</p>
                ) : detail.isError ? (
                  <p role="alert" className="text-sm">
                    Could not load this revision.
                  </p>
                ) : (
                  <div className="space-y-3">
                    <h2 lang={detail.data.locale} className="text-xl font-semibold">
                      {detail.data.title}
                    </h2>
                    <RichEditor
                      key={detail.data.id}
                      readOnly
                      locale={detail.data.locale === "en" ? "en" : "ne"}
                      value={detail.data.content_json as JSONContent}
                      onChange={() => {}}
                      aria-label="Revision text"
                    />
                  </div>
                )}
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>

      {confirming && (
        <Dialog open onOpenChange={(open) => !open && !restoring && setConfirming(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Restore this revision?</DialogTitle>
              <DialogDescription>
                The {NAME[locale]} text goes back to this version. The text you have now is kept as
                a revision, so you can return to it.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={restoring}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
              <Button type="button" disabled={restoring} onClick={() => void restore()}>
                {restoring && <Loader2 aria-hidden className="animate-spin" />}
                Restore
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
