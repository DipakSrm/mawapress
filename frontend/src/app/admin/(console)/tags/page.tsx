import type { Metadata } from "next";
import { RequireRole } from "@/components/admin/require-role";
import { TagsPage } from "@/components/admin/taxonomy/tags-page";

export const metadata: Metadata = { title: "Tags" };

export default function TagsRoute() {
  return (
    <RequireRole min="editor">
      <TagsPage />
    </RequireRole>
  );
}
