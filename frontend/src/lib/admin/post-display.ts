import type { components } from "@/lib/api";

type PostStatus = components["schemas"]["PostStatus"];
type Variant = "default" | "secondary" | "outline";

export const STATUS_LABEL: Record<PostStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  scheduled: "Scheduled",
  published: "Published",
  archived: "Archived",
};

export const STATUS_VARIANT: Record<PostStatus, Variant> = {
  draft: "secondary",
  in_review: "outline",
  scheduled: "outline",
  published: "default",
  archived: "secondary",
};

export function timeAgo(iso: string, now = Date.now()): string {
  const diff = Date.parse(iso) - now;
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const mins = Math.round(diff / 60_000);
  if (Math.abs(mins) < 60) return rtf.format(mins, "minute");
  const hours = Math.round(mins / 60);
  if (Math.abs(hours) < 24) return rtf.format(hours, "hour");
  return rtf.format(Math.round(hours / 24), "day");
}

/** Short local date and time, for example "20 Oct, 14:30". */
export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}
