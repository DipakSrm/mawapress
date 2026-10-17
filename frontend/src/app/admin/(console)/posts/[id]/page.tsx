import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Edit post" };

/** Placeholder until the editor lands (M3 task 5), which replaces this page. */
export default function EditPostRoute() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">Post editor</h1>
      <p className="text-sm text-muted-foreground">The editor is coming in a later step.</p>
      <Link href="/admin/posts" className="text-sm font-medium underline">
        Back to posts
      </Link>
    </div>
  );
}
