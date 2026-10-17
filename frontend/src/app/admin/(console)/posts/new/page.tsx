import type { Metadata } from "next";
import { PostEditor } from "@/components/admin/editor/post-editor";

export const metadata: Metadata = { title: "New post" };

export default function NewPostRoute() {
  return <PostEditor initial={null} />;
}
