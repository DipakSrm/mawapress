"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type components } from "@/lib/api";
import type { PostList } from "./posts";

export type { PostSummary, PostList } from "./posts";
type PostStatus = components["schemas"]["PostStatus"];

interface PostsQuery {
  status?: PostStatus;
  author_id?: string;
  published_after?: string;
  limit?: number;
}

export function fetchPosts(query: PostsQuery): Promise<PostList> {
  return api.get<PostList>("/api/posts", { query: { ...query } });
}

export const DAY_MS = 24 * 60 * 60 * 1000;

export function usePostCount(key: string, query: PostsQuery, enabled = true) {
  return useQuery({
    queryKey: ["posts", "count", key, query],
    queryFn: () => fetchPosts({ ...query, limit: 1 }).then((r) => r.total),
    enabled,
  });
}

/** Exact count of posts published in the last 24 h (server-side `published_after` filter). */
export function usePublishedLast24h() {
  return useQuery({
    queryKey: ["posts", "published-24h"],
    queryFn: () =>
      fetchPosts({
        status: "published",
        published_after: new Date(Date.now() - DAY_MS).toISOString(),
        limit: 1,
      }).then((r) => r.total),
  });
}

export function useRecentPosts() {
  return useQuery({
    queryKey: ["posts", "recent"],
    queryFn: () => fetchPosts({ limit: 10 }),
  });
}
