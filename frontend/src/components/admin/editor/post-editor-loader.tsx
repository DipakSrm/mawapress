"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import type { PostOut } from "@/lib/admin/posts";
import { api, isApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PostEditor } from "./post-editor";

/** Loads one post for the editor. The editor owns the copy afterwards, so nothing refetches under it. */
export function PostEditorLoader({ id }: { id: string }) {
  const query = useQuery({
    queryKey: ["post", id],
    queryFn: () => api.get<PostOut>(`/api/posts/${id}`),
    gcTime: 0,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: (count, error) => !isApiError(error) || (error.status >= 500 && count < 2),
  });

  if (query.isPending) {
    return (
      <div role="status" aria-label="Loading post" className="animate-pulse space-y-4">
        <div className="h-10 rounded-lg bg-muted" />
        <div className="h-12 w-2/3 rounded-lg bg-muted" />
        <div className="h-96 rounded-xl bg-muted" />
      </div>
    );
  }
  if (query.isError) {
    const status = isApiError(query.error) ? query.error.status : 0;
    return (
      <div
        role="alert"
        className="mx-auto flex max-w-md flex-col items-center gap-3 py-20 text-center"
      >
        <h1 className="text-xl font-semibold">
          {status === 404
            ? "Post not found"
            : status === 403
              ? "You cannot open this post"
              : "Could not load the post"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {status === 404
            ? "It may have been deleted, or the link is wrong."
            : status === 403
              ? "Reporters can open only their own posts."
              : "Check your connection and try again."}
        </p>
        <div className="flex gap-2">
          {status !== 404 && status !== 403 && (
            <Button variant="outline" onClick={() => void query.refetch()}>
              Try again
            </Button>
          )}
          <Link
            href="/admin/posts"
            className={cn(buttonVariants({ variant: status ? "default" : "outline" }))}
          >
            Back to posts
          </Link>
        </div>
      </div>
    );
  }
  return <PostEditor key={query.data.id} initial={query.data} />;
}
