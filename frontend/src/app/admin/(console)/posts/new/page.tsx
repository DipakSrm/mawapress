import type { Metadata } from "next";
import { NewPostForm } from "@/components/admin/posts/new-post-form";

export const metadata: Metadata = { title: "New post" };

export default function NewPostRoute() {
  return <NewPostForm />;
}
