"use client";

import type { ReactNode } from "react";
import { useSession } from "@/lib/auth";
import { AdminShell } from "./admin-shell";

function ShellSkeleton() {
  return (
    <div className="min-h-screen bg-muted/30" role="status" aria-label="Loading admin">
      <div className="fixed inset-y-0 left-0 hidden w-60 border-r bg-sidebar p-4 lg:block">
        <div className="h-8 w-32 animate-pulse rounded bg-muted" />
        <div className="mt-8 space-y-3">
          {Array.from({ length: 7 }, (_, i) => (
            <div key={i} className="h-6 animate-pulse rounded bg-muted" />
          ))}
        </div>
      </div>
      <div className="lg:pl-60">
        <div className="h-14 border-b bg-background" />
        <div className="space-y-4 p-6 lg:p-8">
          <div className="h-8 w-48 animate-pulse rounded bg-muted" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="h-28 animate-pulse rounded-xl bg-muted" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Client-side gate: the API enforces authorization; this keeps signed-out users off the screens. */
export function AdminGuard({ children }: { children: ReactNode }) {
  const { status } = useSession();
  // Signed-out users see the skeleton while the provider redirects them to login.
  if (status !== "authenticated") return <ShellSkeleton />;
  return <AdminShell>{children}</AdminShell>;
}
