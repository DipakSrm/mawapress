"use client";

import { CalendarClock, FilePen, Globe, Inbox, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSession } from "@/lib/auth";
import {
  usePostCount,
  usePublishedLast24h,
  useRecentPosts,
  type PostSummary,
} from "@/lib/admin/dashboard";
import { cn } from "@/lib/utils";

function StatCard({
  label,
  icon: Icon,
  value,
  loading,
  failed,
  hint,
  href,
  tone,
}: {
  label: string;
  icon: LucideIcon;
  value: number | undefined;
  loading: boolean;
  failed: boolean;
  hint?: string;
  href?: string;
  tone: string;
}) {
  const body = (
    <Card className="h-full transition-shadow group-hover:shadow-md" size="sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
          <span className={cn("flex size-8 items-center justify-center rounded-lg", tone)}>
            <Icon aria-hidden className="size-4" />
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div
            role="status"
            aria-label={`Loading ${label}`}
            className="h-9 w-16 animate-pulse rounded bg-muted"
          />
        ) : failed ? (
          <p className="text-sm text-muted-foreground">Could not load</p>
        ) : (
          <p
            className="text-3xl font-semibold tracking-tight tabular-nums"
            data-testid={`stat-${label}`}
          >
            {value}
          </p>
        )}
        {hint && !loading && !failed && (
          <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
        )}
      </CardContent>
    </Card>
  );
  return href ? (
    <Link
      href={href}
      className="group rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {body}
    </Link>
  ) : (
    <div className="group">{body}</div>
  );
}

const STATUS_LABEL: Record<PostSummary["status"], string> = {
  draft: "Draft",
  in_review: "In review",
  scheduled: "Scheduled",
  published: "Published",
  archived: "Archived",
};

const STATUS_VARIANT: Record<PostSummary["status"], "default" | "secondary" | "outline"> = {
  draft: "secondary",
  in_review: "outline",
  scheduled: "outline",
  published: "default",
  archived: "secondary",
};

export function postTitle(post: PostSummary): { title: string; locale: string } {
  const t = post.translations.find((x) => x.locale === "ne") ?? post.translations[0];
  return t
    ? { title: t.title || "Untitled", locale: t.locale }
    : { title: "Untitled", locale: "en" };
}

function timeAgo(iso: string, now = Date.now()): string {
  const diff = Date.parse(iso) - now;
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const mins = Math.round(diff / 60_000);
  if (Math.abs(mins) < 60) return rtf.format(mins, "minute");
  const hours = Math.round(mins / 60);
  if (Math.abs(hours) < 24) return rtf.format(hours, "hour");
  return rtf.format(Math.round(hours / 24), "day");
}

function RecentActivity() {
  const { data, isPending, isError } = useRecentPosts();
  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle className="text-base">Recent activity</CardTitle>
      </CardHeader>
      <CardContent className="px-0">
        {isPending ? (
          <ul role="status" aria-label="Loading recent activity" className="divide-y">
            {Array.from({ length: 5 }, (_, i) => (
              <li key={i} className="px-4 py-3">
                <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
                <div className="mt-2 h-3 w-1/3 animate-pulse rounded bg-muted" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">Could not load recent posts.</p>
        ) : data.items.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            No posts yet. Start with{" "}
            <Link href="/admin/posts/new" className="font-medium text-foreground underline">
              a new post
            </Link>
            .
          </p>
        ) : (
          <ul className="divide-y">
            {data.items.map((post) => {
              const { title, locale } = postTitle(post);
              return (
                <li key={post.id}>
                  <Link
                    href={`/admin/posts/${post.id}`}
                    className="flex items-center gap-3 px-4 py-3 outline-none hover:bg-muted/50 focus-visible:bg-muted/50"
                  >
                    <div className="min-w-0 flex-1">
                      <p lang={locale} className="truncate text-sm font-medium">
                        {title}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {post.author_name} · updated {timeAgo(post.updated_at)}
                      </p>
                    </div>
                    <Badge variant={STATUS_VARIANT[post.status]}>{STATUS_LABEL[post.status]}</Badge>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function Dashboard() {
  const { user, hasRole } = useSession();
  const isEditor = hasRole("editor");
  const drafts = usePostCount("drafts", { status: "draft", author_id: user?.id }, Boolean(user));
  const review = usePostCount("review", { status: "in_review" }, isEditor);
  const scheduled = usePostCount("scheduled", { status: "scheduled" });
  const published = usePublishedLast24h();
  const firstName = user?.name.trim().split(/\s+/)[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Welcome back{firstName ? `, ${firstName}` : ""}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {isEditor ? "Here is where the newsroom stands." : "Here is where your stories stand."}
        </p>
      </div>

      <section aria-label="Overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="My drafts"
          icon={FilePen}
          tone="bg-brand-blue/10 text-brand-blue"
          value={drafts.data}
          loading={drafts.isPending}
          failed={drafts.isError}
          href="/admin/posts?status=draft"
        />
        {isEditor && (
          <StatCard
            label="In review"
            icon={Inbox}
            tone="bg-amber-500/15 text-amber-600 dark:text-amber-400"
            value={review.data}
            loading={review.isPending}
            failed={review.isError}
            hint="Waiting for an editor"
            href="/admin/posts?status=in_review"
          />
        )}
        <StatCard
          label="Scheduled"
          icon={CalendarClock}
          tone="bg-violet-500/15 text-violet-600 dark:text-violet-400"
          value={scheduled.data}
          loading={scheduled.isPending}
          failed={scheduled.isError}
          href="/admin/posts?status=scheduled"
        />
        <StatCard
          label="Published (24 h)"
          icon={Globe}
          tone="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
          value={published.data?.count}
          loading={published.isPending}
          failed={published.isError}
          hint={published.data?.capped ? "At least this many" : "In the last 24 hours"}
          href="/admin/posts?status=published"
        />
      </section>

      <RecentActivity />
    </div>
  );
}
