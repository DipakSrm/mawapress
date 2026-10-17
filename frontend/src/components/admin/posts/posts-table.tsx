"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { timeAgo } from "@/lib/admin/post-display";
import type { ActionResult, Category, PostAction, PostSummary } from "@/lib/admin/posts";
import { cn } from "@/lib/utils";
import { PostActions } from "./post-actions";
import { PostStatusBadge } from "./status-badge";

const LOCALE_NAME: Record<string, string> = { ne: "Nepali", en: "English" };

function orderedTranslations(post: PostSummary) {
  return [...post.translations].sort((a, b) =>
    a.locale === "ne" ? -1 : b.locale === "ne" ? 1 : 0,
  );
}

export function primaryTitle(post: PostSummary): string {
  return orderedTranslations(post)[0]?.title || "Untitled";
}

function LanguageChip({ locale, status }: { locale: string; status: "draft" | "published" }) {
  return (
    <span
      title={`${LOCALE_NAME[locale] ?? locale}: ${status}`}
      aria-label={`${LOCALE_NAME[locale] ?? locale}, ${status}`}
      className={cn(
        "inline-flex h-4.5 shrink-0 items-center rounded px-1.5 text-[10px] font-semibold tracking-wide uppercase",
        status === "published"
          ? "bg-emerald-600/15 text-emerald-700 dark:text-emerald-400"
          : "bg-muted text-muted-foreground",
      )}
    >
      {locale}
    </span>
  );
}

export function TitleCell({ post }: { post: PostSummary }) {
  const translations = orderedTranslations(post);
  return (
    <ul className="space-y-1">
      {translations.map((t, i) => (
        <li key={t.locale} className="flex min-w-0 items-center gap-2">
          <LanguageChip locale={t.locale} status={t.status} />
          {i === 0 ? (
            <Link
              href={`/admin/posts/${post.id}`}
              lang={t.locale}
              className="truncate font-medium outline-none hover:underline focus-visible:underline"
            >
              {t.title || "Untitled"}
            </Link>
          ) : (
            <span lang={t.locale} className="truncate text-sm text-muted-foreground">
              {t.title || "Untitled"}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

export function PostsTableSkeleton() {
  return (
    <div role="status" aria-label="Loading posts" className="divide-y">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-4">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
            <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
          </div>
          <div className="hidden h-4 w-20 animate-pulse rounded bg-muted md:block" />
          <div className="h-5 w-16 animate-pulse rounded-full bg-muted" />
          <div className="size-7 animate-pulse rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}

interface Props {
  posts: PostSummary[];
  categories: Category[] | undefined;
  viewer: { id: string; isEditor: boolean };
  pendingId: string | null;
  onRun: (post: PostSummary, action: PostAction) => Promise<ActionResult>;
  onFilterAuthor: (post: PostSummary) => void;
}

export function PostsTable({ posts, categories, viewer, pendingId, onRun, onFilterAuthor }: Props) {
  return (
    <Table>
      <caption className="sr-only">Posts</caption>
      <TableHeader>
        <TableRow>
          <TableHead className="pl-4">Title</TableHead>
          <TableHead className="hidden md:table-cell">Category</TableHead>
          <TableHead className="hidden lg:table-cell">Author</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="hidden sm:table-cell">Updated</TableHead>
          <TableHead className="hidden text-right xl:table-cell">Views</TableHead>
          <TableHead className="w-12 pr-4">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {posts.map((post) => {
          const category = categories?.find((c) => c.id === post.category_id);
          return (
            <TableRow key={post.id}>
              <TableCell className="max-w-0 min-w-56 pl-4 sm:max-w-md">
                <TitleCell post={post} />
              </TableCell>
              <TableCell className="hidden text-sm md:table-cell">
                {category ? (
                  category.name_en
                ) : (
                  <span className="text-muted-foreground">{categories ? "Unknown" : "…"}</span>
                )}
              </TableCell>
              <TableCell className="hidden text-sm lg:table-cell">
                {viewer.isEditor ? (
                  <Button
                    type="button"
                    variant="link"
                    size="xs"
                    className="h-auto p-0 text-foreground"
                    onClick={() => onFilterAuthor(post)}
                    aria-label={`Show posts by ${post.author_name}`}
                  >
                    {post.author_name}
                  </Button>
                ) : (
                  post.author_name
                )}
              </TableCell>
              <TableCell>
                <PostStatusBadge post={post} />
              </TableCell>
              <TableCell className="hidden text-sm text-muted-foreground sm:table-cell">
                <time dateTime={post.updated_at} title={new Date(post.updated_at).toLocaleString()}>
                  {timeAgo(post.updated_at)}
                </time>
              </TableCell>
              <TableCell className="hidden text-right text-sm tabular-nums xl:table-cell">
                {post.view_count.toLocaleString("en")}
              </TableCell>
              <TableCell className="pr-4 text-right">
                <PostActions
                  post={post}
                  title={primaryTitle(post)}
                  viewer={viewer}
                  categories={categories}
                  busy={pendingId === post.id}
                  onRun={onRun}
                />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
