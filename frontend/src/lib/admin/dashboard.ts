"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type components } from "@/lib/api";

export type PostSummary = components["schemas"]["PostSummary"];
export type PostList = components["schemas"]["PostListOut"];
type PostStatus = components["schemas"]["PostStatus"];

interface PostsQuery {
  status?: PostStatus;
  author_id?: string;
  limit?: number;
}

export function fetchPosts(query: PostsQuery): Promise<PostList> {
  return api.get<PostList>("/api/posts", { query: { ...query } });
}

export const DAY_MS = 24 * 60 * 60 * 1000;
export const PUBLISHED_SAMPLE = 100; // API page-size ceiling

/** Posts published in the last 24 h, counted from the most recently updated published posts. */
export function countRecentlyPublished(items: PostSummary[], now: number = Date.now()): number {
  return items.filter((p) => p.published_at && now - Date.parse(p.published_at) <= DAY_MS).length;
}

export function usePostCount(key: string, query: PostsQuery, enabled = true) {
  return useQuery({
    queryKey: ["posts", "count", key, query],
    queryFn: () => fetchPosts({ ...query, limit: 1 }).then((r) => r.total),
    enabled,
  });
}

export function usePublishedLast24h() {
  return useQuery({
    queryKey: ["posts", "published-24h"],
    queryFn: async () => {
      const res = await fetchPosts({ status: "published", limit: PUBLISHED_SAMPLE });
      const count = countRecentlyPublished(res.items);
      return { count, capped: res.items.length === PUBLISHED_SAMPLE && count === PUBLISHED_SAMPLE };
    },
  });
}

export function useRecentPosts() {
  return useQuery({
    queryKey: ["posts", "recent"],
    queryFn: () => fetchPosts({ limit: 10 }),
  });
}
