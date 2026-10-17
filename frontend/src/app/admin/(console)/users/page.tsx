import type { Metadata } from "next";
import { RequireRole } from "@/components/admin/require-role";
import { UsersPage } from "@/components/admin/users/users-page";

export const metadata: Metadata = { title: "Users" };

export default function UsersRoute() {
  return (
    <RequireRole min="admin">
      <UsersPage />
    </RequireRole>
  );
}
