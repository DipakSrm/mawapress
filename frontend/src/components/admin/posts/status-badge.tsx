import { CalendarClock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatDateTime, STATUS_LABEL, STATUS_VARIANT } from "@/lib/admin/post-display";
import type { PostSummary } from "@/lib/admin/posts";
import { cn } from "@/lib/utils";

const STATUS_TONE: Partial<Record<PostSummary["status"], string>> = {
  in_review: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  scheduled: "border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-400",
  published:
    "border-transparent bg-emerald-600 text-white dark:bg-emerald-500/20 dark:text-emerald-400",
};

export function PostStatusBadge({ post }: { post: Pick<PostSummary, "status" | "scheduled_at"> }) {
  const when = post.status === "scheduled" && post.scheduled_at;
  return (
    <div className="flex flex-col items-start gap-1">
      <Badge variant={STATUS_VARIANT[post.status]} className={cn(STATUS_TONE[post.status])}>
        {STATUS_LABEL[post.status]}
      </Badge>
      {when && (
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <CalendarClock aria-hidden className="size-3" />
          <time dateTime={post.scheduled_at ?? undefined}>{formatDateTime(when)}</time>
        </span>
      )}
    </div>
  );
}
