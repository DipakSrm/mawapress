import type { Metadata } from "next";
import { Suspense } from "react";
import { PostsPage } from "@/components/admin/posts/posts-page";

export const metadata: Metadata = { title: "Posts" };

export default function PostsRoute() {
  return (
    <Suspense>
      <PostsPage />
    </Suspense>
  );
}
