"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "sonner";
import { api, ifMatch, isApiError, type ApiError, type components } from "@/lib/api";
import { formatDateTime } from "./post-display";
import { filtersToApiQuery, type PostFilters } from "./post-filters";

export type PostSummary = components["schemas"]["PostSummary"];
export type PostList = components["schemas"]["PostListOut"];
export type PostOut = components["schemas"]["PostOut"];
export type PostStatus = components["schemas"]["PostStatus"];
export type Category = components["schemas"]["CategoryOut"];

export function usePostList(filters: PostFilters) {
  return useQuery({
    queryKey: ["posts", "list", filters],
    queryFn: () => api.get<PostList>("/api/posts", { query: filtersToApiQuery(filters) }),
    placeholderData: keepPreviousData,
  });
}

export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<Category[]>("/api/categories"),
    staleTime: 5 * 60_000,
  });
}

// ---- who can do what -------------------------------------------------------------------------

export interface AllowedActions {
  edit: boolean;
  submit: boolean;
  sendBack: boolean;
  publish: boolean;
  schedule: boolean;
  unschedule: boolean;
  unpublish: boolean;
  unarchive: boolean;
  copyLink: boolean;
}

/** Mirrors the backend rules so the menu only offers what the API will accept. */
export function allowedActions(
  post: Pick<PostSummary, "status" | "author_id">,
  viewer: { id: string; isEditor: boolean },
): AllowedActions {
  const { status } = post;
  const { isEditor } = viewer;
  const preLive = status === "draft" || status === "in_review" || status === "scheduled";
  return {
    edit: true,
    submit: status === "draft" && post.author_id === viewer.id,
    sendBack: isEditor && status === "in_review",
    publish: isEditor && preLive,
    schedule: isEditor && preLive,
    unschedule: isEditor && status === "scheduled",
    unpublish: isEditor && status === "published",
    unarchive: isEditor && status === "archived",
    copyLink: status === "published",
  };
}

// ---- public link -----------------------------------------------------------------------------

/** `/{locale}/{category}/{slug}` of the best published translation (Nepali first), or null. */
export function publicPath(
  post: {
    category_id: number;
    translations: { locale: string; slug: string; status: string }[];
  },
  categories: Category[] | undefined,
): string | null {
  const category = categories?.find((c) => c.id === post.category_id);
  const tr =
    post.translations.find((t) => t.locale === "ne" && t.status === "published") ??
    post.translations.find((t) => t.status === "published");
  return category && tr ? `/${tr.locale}/${category.slug}/${tr.slug}` : null;
}

// ---- schedule time ---------------------------------------------------------------------------

const pad = (n: number) => String(n).padStart(2, "0");

/** Value for an `<input type="datetime-local">`, in the browser local time. */
export function toLocalInputValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Local wall-clock value from a datetime-local input, as ISO 8601 with the local UTC offset. */
export function toOffsetIso(local: string): string | null {
  const date = new Date(local);
  if (Number.isNaN(date.getTime())) return null;
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  return `${toLocalInputValue(date)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

/** The backend rejects times under a minute away or beyond a year; checked here for instant feedback. */
export const SCHEDULE_MIN_LEAD_MS = 60_000;
export const SCHEDULE_MAX_AHEAD_MS = 365 * 24 * 3_600_000;

export function validateScheduleTime(local: string, now = Date.now()): string | null {
  const when = new Date(local).getTime();
  if (!local || Number.isNaN(when)) return "Choose a date and time.";
  if (when < now + SCHEDULE_MIN_LEAD_MS) return "Choose a time at least a minute from now.";
  if (when > now + SCHEDULE_MAX_AHEAD_MS) return "Choose a time within the next year.";
  return null;
}

// ---- workflow actions ------------------------------------------------------------------------

export type PostAction =
  | { type: "submit" }
  | { type: "send-back"; note?: string }
  | { type: "publish" }
  | { type: "schedule"; scheduledAt: string }
  | { type: "unschedule" }
  | { type: "unpublish" }
  | { type: "unarchive" }
  | { type: "publish-translation"; locale: "ne" | "en" };

export const CONFLICT_MESSAGE = "This post changed — refresh";

function requestFor(action: PostAction): { path: string; body?: unknown } {
  switch (action.type) {
    case "send-back":
      return { path: "send-back", body: action.note ? { note: action.note } : undefined };
    case "schedule":
      return { path: "schedule", body: { scheduled_at: action.scheduledAt } };
    case "publish-translation":
      return { path: `translations/${action.locale}/publish` };
    default:
      return { path: action.type };
  }
}

function successMessage(action: PostAction, out: PostOut): string {
  switch (action.type) {
    case "submit":
      return "Submitted for review";
    case "send-back":
      return "Sent back to the reporter";
    case "publish":
      return "Published";
    case "schedule":
      return out.scheduled_at ? `Scheduled for ${formatDateTime(out.scheduled_at)}` : "Scheduled";
    case "unschedule":
      return "Unscheduled, back to draft";
    case "unpublish":
      return "Unpublished";
    case "unarchive":
      return "Restored from the archive";
    case "publish-translation":
      return action.locale === "ne" ? "Nepali version published" : "English version published";
  }
}

function isPostList(data: unknown): data is PostList {
  return Boolean(data && typeof data === "object" && Array.isArray((data as PostList).items));
}

/** Copy what a state change returns onto the matching list row, so the next action has a fresh If-Match. */
function patchRow(list: PostList, out: PostOut): PostList {
  return {
    ...list,
    items: list.items.map((row) =>
      row.id === out.id
        ? {
            ...row,
            status: out.status,
            updated_at: out.updated_at,
            published_at: out.published_at,
            scheduled_at: out.scheduled_at,
            translations: out.translations.map((t) => ({
              locale: t.locale,
              title: t.title,
              slug: t.slug,
              status: t.status,
            })),
          }
        : row,
    ),
  };
}

export type ActionResult = { ok: true; post: PostOut } | { ok: false; error: ApiError };

/**
 * Runs a workflow action for a list row.
 *
 * Every call sends `If-Match` with the row `updated_at`, so an action only applies to the version
 * the user was looking at. On 412 the list is refetched and the user is told to review the change;
 * the action is not silently retried against newer content. On success the cache is patched with the
 * response and the lists are invalidated so filters and counts stay right.
 */
export function usePostActions() {
  const queryClient = useQueryClient();
  const [pendingId, setPendingId] = useState<string | null>(null);

  const run = useCallback(
    async (
      post: Pick<PostSummary, "id" | "updated_at">,
      action: PostAction,
    ): Promise<ActionResult> => {
      const { path, body } = requestFor(action);
      setPendingId(post.id);
      try {
        const out = await api.post<PostOut>(`/api/posts/${post.id}/${path}`, body, {
          headers: ifMatch(post.updated_at),
        });
        queryClient.setQueriesData({ queryKey: ["posts"] }, (old: unknown) =>
          isPostList(old) ? patchRow(old, out) : old,
        );
        void queryClient.invalidateQueries({ queryKey: ["posts"] });
        toast.success(successMessage(action, out));
        return { ok: true, post: out };
      } catch (e) {
        if (!isApiError(e)) throw e;
        if (e.status === 412) {
          toast.error(CONFLICT_MESSAGE);
          void queryClient.invalidateQueries({ queryKey: ["posts"] });
        } else if (action.type === "schedule" && e.status === 422) {
          // Shown inside the schedule dialog, next to the field.
        } else {
          toast.error(e.message);
          if (e.status === 409) void queryClient.invalidateQueries({ queryKey: ["posts"] });
        }
        return { ok: false, error: e };
      } finally {
        setPendingId(null);
      }
    },
    [queryClient],
  );

  return { run, pendingId };
}
