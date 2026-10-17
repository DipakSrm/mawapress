import type { Metadata } from "next";
import { PostEditorLoader } from "@/components/admin/editor/post-editor-loader";

export const metadata: Metadata = { title: "Edit post" };

export default async function EditPostRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PostEditorLoader id={id} />;
}
