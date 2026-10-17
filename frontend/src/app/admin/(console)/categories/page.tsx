import type { Metadata } from "next";
import { RequireRole } from "@/components/admin/require-role";
import { CategoriesPage } from "@/components/admin/taxonomy/categories-page";

export const metadata: Metadata = { title: "Categories" };

export default function CategoriesRoute() {
  return (
    <RequireRole min="editor">
      <CategoriesPage />
    </RequireRole>
  );
}
