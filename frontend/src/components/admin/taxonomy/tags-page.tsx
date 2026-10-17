"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Plus, Search, Tags, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
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
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { describeError } from "@/lib/admin/errors";
import { CATEGORY_ERRORS, useTags, type Tag } from "@/lib/admin/taxonomy";
import { useDebounced } from "@/lib/admin/use-debounced";
import { api } from "@/lib/api";

const tagError = (e: unknown) =>
  describeError(e, {
    SLUG_TAKEN: CATEGORY_ERRORS.SLUG_TAKEN,
    INVALID_SLUG: CATEGORY_ERRORS.INVALID_SLUG,
    TAG_NOT_FOUND: "This tag no longer exists. Reload the list.",
  });

function TagDialog({ tag, onClose }: { tag: Tag | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [nameNe, setNameNe] = useState(tag?.name_ne ?? "");
  const [nameEn, setNameEn] = useState(tag?.name_en ?? "");
  const [slug, setSlug] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    const names = { name_ne: nameNe.trim(), name_en: nameEn.trim() };
    try {
      if (tag) await api.patch(`/api/tags/${tag.id}`, names);
      else await api.post("/api/tags", { ...names, slug: slug.trim() || undefined });
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
      toast.success(tag ? "Tag renamed" : "Tag created");
      onClose();
    } catch (err) {
      setError(tagError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent>
        <form onSubmit={(e) => void submit(e)} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{tag ? "Rename tag" : "New tag"}</DialogTitle>
            <DialogDescription>Tags group related stories across categories.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="tag-name-ne">Name (नेपाली)</Label>
            <Input
              id="tag-name-ne"
              lang="ne"
              required
              maxLength={120}
              value={nameNe}
              onChange={(e) => setNameNe(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tag-name-en">Name (English)</Label>
            <Input
              id="tag-name-en"
              lang="en"
              required
              maxLength={120}
              value={nameEn}
              onChange={(e) => setNameEn(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tag-slug">Address (slug)</Label>
            {tag ? (
              <>
                <Input id="tag-slug" readOnly value={tag.slug} />
                <p className="text-xs text-muted-foreground">
                  The address is fixed once a tag exists, because tag pages are linked by it.
                </p>
              </>
            ) : (
              <>
                <Input
                  id="tag-slug"
                  maxLength={80}
                  placeholder="Made from the English name when empty"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Lower-case letters, digits and hyphens. It cannot be changed later.
                </p>
              </>
            )}
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 aria-hidden className="animate-spin" />}
              {tag ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteTagDialog({ tag, onClose }: { tag: Tag; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/tags/${tag.id}`);
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
      toast.success("Tag deleted");
      onClose();
    } catch (e) {
      setError(tagError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete “{tag.name_en}”?</DialogTitle>
          <DialogDescription>
            The tag is removed from every story that uses it. The stories stay.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" disabled={busy} onClick={() => void remove()}>
            {busy && <Loader2 aria-hidden className="animate-spin" />}
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function TagsPage() {
  const [input, setInput] = useState("");
  const q = useDebounced(input.trim());
  const list = useTags(q);
  const [editing, setEditing] = useState<Tag | "new" | null>(null);
  const [deleting, setDeleting] = useState<Tag | null>(null);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tags</h1>
          <p className="mt-1 text-sm text-muted-foreground">Labels for grouping related stories.</p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus aria-hidden /> New tag
        </Button>
      </div>

      <div className="relative max-w-sm">
        <Search
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          type="search"
          aria-label="Search tags"
          placeholder="Search tags"
          maxLength={100}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="pl-8"
        />
      </div>

      {list.isPending ? (
        <div role="status" aria-label="Loading tags" className="space-y-2">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="h-10 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : list.isError ? (
        <div role="alert" className="flex flex-col items-center gap-3 py-14 text-center">
          <p className="font-medium">Could not load tags</p>
          <Button variant="outline" onClick={() => void list.refetch()}>
            Retry
          </Button>
        </div>
      ) : list.data.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-14 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <Tags aria-hidden className="size-6" />
          </span>
          <p className="font-medium">{q ? "No tags match your search" : "No tags yet"}</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>नेपाली</TableHead>
                <TableHead>English</TableHead>
                <TableHead>Address</TableHead>
                <TableHead className="w-24">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.data.map((t) => (
                <TableRow key={t.id}>
                  <TableCell lang="ne">{t.name_ne}</TableCell>
                  <TableCell lang="en">{t.name_en}</TableCell>
                  <TableCell className="text-muted-foreground">/{t.slug}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Rename ${t.name_en}`}
                        onClick={() => setEditing(t)}
                      >
                        <Pencil aria-hidden />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Delete ${t.name_en}`}
                        onClick={() => setDeleting(t)}
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {editing && (
        <TagDialog tag={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      )}
      {deleting && <DeleteTagDialog tag={deleting} onClose={() => setDeleting(null)} />}
    </div>
  );
}
