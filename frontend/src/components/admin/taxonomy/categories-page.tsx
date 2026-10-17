"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderTree, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
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
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import {
  buildTree,
  categoryError,
  flattenTree,
  subtreeIds,
  type Category,
} from "@/lib/admin/taxonomy";
import { api } from "@/lib/api";

function useCategoryList() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<Category[]>("/api/categories"),
  });
}

interface FormProps {
  /** The category being edited, or null to create one. */
  category: Category | null;
  all: Category[];
  onClose: () => void;
}

function CategoryDialog({ category, all, onClose }: FormProps) {
  const queryClient = useQueryClient();
  const [nameNe, setNameNe] = useState(category?.name_ne ?? "");
  const [nameEn, setNameEn] = useState(category?.name_en ?? "");
  const [slug, setSlug] = useState("");
  const [seo, setSeo] = useState(category?.seo_description ?? "");
  const [sort, setSort] = useState(String(category?.sort ?? 0));
  const [parent, setParent] = useState(category?.parent_id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blocked = category ? subtreeIds(all, category.id) : new Set<number>();
  const parents = flattenTree(buildTree(all)).filter((n) => !blocked.has(n.category.id));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    const sortNum = Number.parseInt(sort, 10);
    const common = {
      name_ne: nameNe.trim(),
      name_en: nameEn.trim(),
      parent_id: parent,
      sort: Number.isFinite(sortNum) ? sortNum : 0,
      seo_description: seo.trim() || null,
    };
    try {
      if (category) await api.patch(`/api/categories/${category.id}`, common);
      else await api.post("/api/categories", { ...common, slug: slug.trim() || undefined });
      void queryClient.invalidateQueries({ queryKey: ["categories"] });
      toast.success(category ? "Category saved" : "Category created");
      onClose();
    } catch (err) {
      setError(categoryError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={(e) => void submit(e)} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{category ? "Edit category" : "New category"}</DialogTitle>
            <DialogDescription>Shown in the site menu and on story pages.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="cat-name-ne">Name (नेपाली)</Label>
              <Input
                id="cat-name-ne"
                lang="ne"
                required
                maxLength={120}
                value={nameNe}
                onChange={(e) => setNameNe(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cat-name-en">Name (English)</Label>
              <Input
                id="cat-name-en"
                lang="en"
                required
                maxLength={120}
                value={nameEn}
                onChange={(e) => setNameEn(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cat-slug">Address (slug)</Label>
            {category ? (
              <>
                <Input id="cat-slug" readOnly value={category.slug} />
                <p className="text-xs text-muted-foreground">
                  The address is fixed once a category exists: changing it would break the links to
                  every story in it.
                </p>
              </>
            ) : (
              <>
                <Input
                  id="cat-slug"
                  value={slug}
                  maxLength={80}
                  placeholder="Made from the English name when empty"
                  onChange={(e) => setSlug(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Lower-case letters, digits and hyphens. It cannot be changed later.
                </p>
              </>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-[1fr_7rem]">
            <div className="space-y-1.5">
              <Label htmlFor="cat-parent">Parent</Label>
              <NativeSelect
                id="cat-parent"
                value={parent ?? ""}
                onChange={(e) => setParent(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">None (top level)</option>
                {parents.map((n) => (
                  <option key={n.category.id} value={n.category.id}>
                    {"— ".repeat(n.depth - 1)}
                    {n.category.name_en}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cat-sort">Order</Label>
              <Input
                id="cat-sort"
                type="number"
                min={-10000}
                max={10000}
                value={sort}
                onChange={(e) => setSort(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cat-seo">Description for search engines</Label>
            <Textarea
              id="cat-seo"
              rows={2}
              maxLength={320}
              value={seo}
              onChange={(e) => setSeo(e.target.value)}
            />
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
              {category ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteDialog({ category, onClose }: { category: Category; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/categories/${category.id}`);
      void queryClient.invalidateQueries({ queryKey: ["categories"] });
      toast.success("Category deleted");
      onClose();
    } catch (e) {
      setError(categoryError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete “{category.name_en}”?</DialogTitle>
          <DialogDescription>
            Only an empty category can be deleted: no stories and no subcategories.
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

export function CategoriesPage() {
  const queryClient = useQueryClient();
  const list = useCategoryList();
  const [editing, setEditing] = useState<Category | "new" | null>(null);
  const [deleting, setDeleting] = useState<Category | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [moving, setMoving] = useState<number | null>(null);

  const all = useMemo(() => list.data ?? [], [list.data]);
  const rows = useMemo(() => flattenTree(buildTree(all)), [all]);

  async function move(category: Category, parentId: number | null) {
    setMoving(category.id);
    setMoveError(null);
    try {
      await api.patch(`/api/categories/${category.id}`, { parent_id: parentId });
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
    } catch (e) {
      setMoveError(`Could not move “${category.name_en}”. ${categoryError(e)}`);
    } finally {
      setMoving(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Categories</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Sections of the site. Up to three levels deep.
          </p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus aria-hidden /> New category
        </Button>
      </div>

      {moveError && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {moveError}
        </p>
      )}

      {list.isPending ? (
        <div role="status" aria-label="Loading categories" className="space-y-2">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : list.isError ? (
        <div role="alert" className="flex flex-col items-center gap-3 py-14 text-center">
          <p className="font-medium">Could not load categories</p>
          <Button variant="outline" onClick={() => void list.refetch()}>
            Retry
          </Button>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-14 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <FolderTree aria-hidden className="size-6" />
          </span>
          <p className="font-medium">No categories yet</p>
          <p className="text-sm text-muted-foreground">Every story needs one. Create the first.</p>
        </div>
      ) : (
        <ul
          aria-label="Categories"
          className="divide-y overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10"
        >
          {rows.map(({ category: c, depth }) => {
            const blocked = subtreeIds(all, c.id);
            const targets = rows.filter((r) => !blocked.has(r.category.id));
            return (
              <li
                key={c.id}
                className="flex flex-wrap items-center gap-3 px-3 py-2.5"
                style={{ paddingLeft: `${0.75 + (depth - 1) * 1.5}rem` }}
              >
                <div className="min-w-0 flex-1 basis-48">
                  <p className="truncate font-medium">
                    <span lang="ne">{c.name_ne}</span>
                    <span className="text-muted-foreground"> · </span>
                    <span lang="en">{c.name_en}</span>
                  </p>
                  <p className="truncate text-xs text-muted-foreground">/{c.slug}</p>
                </div>
                <div className="flex items-center gap-1.5">
                  <label htmlFor={`parent-${c.id}`} className="sr-only">
                    Parent of {c.name_en}
                  </label>
                  <NativeSelect
                    id={`parent-${c.id}`}
                    className="w-44"
                    value={c.parent_id ?? ""}
                    disabled={moving === c.id}
                    onChange={(e) => void move(c, e.target.value ? Number(e.target.value) : null)}
                  >
                    <option value="">Top level</option>
                    {targets.map((t) => (
                      <option key={t.category.id} value={t.category.id}>
                        {"— ".repeat(t.depth - 1)}
                        {t.category.name_en}
                      </option>
                    ))}
                  </NativeSelect>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Edit ${c.name_en}`}
                    onClick={() => setEditing(c)}
                  >
                    <Pencil aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Delete ${c.name_en}`}
                    onClick={() => setDeleting(c)}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {editing && (
        <CategoryDialog
          category={editing === "new" ? null : editing}
          all={all}
          onClose={() => setEditing(null)}
        />
      )}
      {deleting && <DeleteDialog category={deleting} onClose={() => setDeleting(null)} />}
    </div>
  );
}
