"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type components } from "@/lib/api";
import { describeError } from "./errors";

export type Category = components["schemas"]["CategoryOut"];
export type Tag = components["schemas"]["TagOut"];

export const MAX_DEPTH = 3;

export interface CategoryNode {
  category: Category;
  depth: number;
  children: CategoryNode[];
}

const bySort = (a: Category, b: Category) => a.sort - b.sort || a.id - b.id;

/** Flat list from the API into a forest, siblings ordered by `sort`. Orphans (unknown parent) become roots. */
export function buildTree(categories: Category[]): CategoryNode[] {
  const ids = new Set(categories.map((c) => c.id));
  const children = new Map<number | null, Category[]>();
  for (const c of categories) {
    const key = c.parent_id !== null && ids.has(c.parent_id) ? c.parent_id : null;
    children.set(key, [...(children.get(key) ?? []), c]);
  }
  const make = (c: Category, depth: number, seen: Set<number>): CategoryNode => ({
    category: c,
    depth,
    children: seen.has(c.id)
      ? []
      : (children.get(c.id) ?? [])
          .sort(bySort)
          .map((k) => make(k, depth + 1, new Set(seen).add(c.id))),
  });
  return (children.get(null) ?? []).sort(bySort).map((c) => make(c, 1, new Set()));
}

export function flattenTree(nodes: CategoryNode[]): CategoryNode[] {
  return nodes.flatMap((n) => [n, ...flattenTree(n.children)]);
}

/** Ids of `id` and everything below it. */
export function subtreeIds(categories: Category[], id: number): Set<number> {
  const out = new Set<number>([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const c of categories) {
      if (c.parent_id !== null && out.has(c.parent_id) && !out.has(c.id)) {
        out.add(c.id);
        grew = true;
      }
    }
  }
  return out;
}

export const CATEGORY_ERRORS = {
  CATEGORY_CYCLE: "A category cannot be moved under itself or one of its own subcategories.",
  CATEGORY_TOO_DEEP: `Categories can nest at most ${MAX_DEPTH} levels deep.`,
  CATEGORY_IN_USE: (d: Record<string, unknown>) => {
    const posts = Number(d.posts ?? 0);
    const children = Number(d.children ?? 0);
    const parts = [
      posts ? `${posts} ${posts === 1 ? "post" : "posts"}` : "",
      children ? `${children} ${children === 1 ? "subcategory" : "subcategories"}` : "",
    ].filter(Boolean);
    return `This category still has ${parts.join(" and ")}. Move ${posts ? "the posts to another category" : ""}${posts && children ? " and " : ""}${children ? "the subcategories elsewhere or delete them" : ""} first.`;
  },
  SLUG_TAKEN: "That address is already used by another item.",
  INVALID_SLUG:
    "The address can use lower-case letters, digits and single hyphens, up to 80 characters.",
} as const;

export const categoryError = (e: unknown) => describeError(e, CATEGORY_ERRORS);

export function useTags(q: string) {
  return useQuery({
    queryKey: ["tags", q],
    queryFn: () => api.get<Tag[]>("/api/tags", { query: { q: q || undefined } }),
  });
}
