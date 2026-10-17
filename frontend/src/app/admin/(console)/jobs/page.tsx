import type { Metadata } from "next";
import { JobsPage } from "@/components/admin/jobs/jobs-page";
import { RequireRole } from "@/components/admin/require-role";

export const metadata: Metadata = { title: "Jobs" };

export default function JobsRoute() {
  return (
    <RequireRole min="admin">
      <JobsPage />
    </RequireRole>
  );
}
