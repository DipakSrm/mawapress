"use client";

import { ChevronLeft, ChevronRight, FilePlus2, FileText } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  filtersToSearch,
  hasActiveFilters,
  PAGE_SIZE,
  parseFilters,
  type PostFilters,
} from "@/lib/admin/post-filters";
import { useCategories, usePostActions, usePostList, type PostSummary } from "@/lib/admin/posts";
import { useSession } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { PostFiltersBar } from "./post-filters-bar";
import { PostsTable, PostsTableSkeleton } from "./posts-table";

function EmptyState({ filtered, onClear }: { filtered: boolean; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-16 text-center">
      <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <FileText aria-hidden className="size-6" />
      </span>
      {filtered ? (
        <>
          <p className="font-medium">No posts match these filters</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Try a different search or remove a filter.
          </p>
          <Button variant="outline" onClick={onClear}>
            Clear filters
          </Button>
        </>
      ) : (
        <>
          <p className="font-medium">No posts yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Stories you write will show up here, with their status and language.
          </p>
          <Link href="/admin/posts/new" className={buttonVariants()}>
            <FilePlus2 aria-hidden /> New post
          </Link>
        </>
      )}
    </div>
  );
}

export function PostsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { user, hasRole } = useSession();
  const isEditor = hasRole("editor");

  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);
  const list = usePostList(filters);
  const categories = useCategories();
  const { run, pendingIds } = usePostActions();
  const [authorNames, setAuthorNames] = useState<Record<string, string>>({});

  const update = useCallback(
    (patch: Partial<PostFilters>) => {
      const next = { ...filters, ...patch, page: patch.page ?? 1 };
      const qs = filtersToSearch(next);
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [filters, pathname, router],
  );

  const filterByAuthor = useCallback(
    (post: PostSummary) => {
      setAuthorNames((names) => ({ ...names, [post.author_id]: post.author_name }));
      update({ author: post.author_id });
    },
    [update],
  );

  if (!user) return null;
  const viewer = { id: user.id, isEditor };
  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const first = total === 0 ? 0 : (filters.page - 1) * PAGE_SIZE + 1;
  const last = Math.min(total, filters.page * PAGE_SIZE);
  const authorLabel =
    (filters.author &&
      (authorNames[filters.author] ??
        list.data?.items.find((p) => p.author_id === filters.author)?.author_name)) ||
    undefined;
  const clearAll = () =>
    update({ status: undefined, category: undefined, author: undefined, locale: undefined, q: "" });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Posts</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {isEditor ? "Every story in the newsroom." : "Your stories."}
          </p>
        </div>
        <Link href="/admin/posts/new" className={buttonVariants()}>
          <FilePlus2 aria-hidden /> New post
        </Link>
      </div>

      <PostFiltersBar
        filters={filters}
        categories={categories.data}
        canFilterAuthor={isEditor}
        authorLabel={authorLabel}
        onChange={update}
      />

      <Card className="gap-0 overflow-hidden p-0">
        {list.isPending ? (
          <PostsTableSkeleton />
        ) : list.isError ? (
          <div role="alert" className="flex flex-col items-center gap-3 px-4 py-14 text-center">
            <p className="font-medium">Could not load posts</p>
            <p className="text-sm text-muted-foreground">Check your connection and try again.</p>
            <Button variant="outline" onClick={() => void list.refetch()}>
              Retry
            </Button>
          </div>
        ) : list.data.items.length === 0 ? (
          filters.page > 1 && total > 0 ? (
            <div className="flex flex-col items-center gap-3 px-4 py-14 text-center">
              <p className="font-medium">That page is past the end</p>
              <Button variant="outline" onClick={() => update({ page: 1 })}>
                Back to the first page
              </Button>
            </div>
          ) : (
            <EmptyState filtered={hasActiveFilters(filters)} onClear={clearAll} />
          )
        ) : (
          <div
            className={cn("transition-opacity", list.isPlaceholderData && "opacity-60")}
            aria-busy={list.isPlaceholderData}
          >
            <PostsTable
              posts={list.data.items}
              categories={categories.data}
              viewer={viewer}
              pendingIds={pendingIds}
              onRun={run}
              onFilterAuthor={filterByAuthor}
            />
          </div>
        )}
      </Card>

      {list.data && list.data.items.length > 0 && (
        <nav
          aria-label="Pagination"
          className="flex flex-wrap items-center justify-between gap-3 text-sm"
        >
          <p className="text-muted-foreground" aria-live="polite">
            Showing {first}–{last} of {total}
          </p>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">
              Page {filters.page} of {pages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={filters.page <= 1}
              onClick={() => update({ page: filters.page - 1 })}
            >
              <ChevronLeft aria-hidden /> Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={filters.page >= pages}
              onClick={() => update({ page: filters.page + 1 })}
            >
              Next <ChevronRight aria-hidden />
            </Button>
          </div>
        </nav>
      )}
    </div>
  );
}
