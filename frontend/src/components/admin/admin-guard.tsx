"use client";

import { CloudOff } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
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

function SessionError({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/30 px-4">
      <div role="alert" className="max-w-sm rounded-xl border bg-card p-6 text-center shadow-sm">
        <CloudOff aria-hidden className="mx-auto size-8 text-muted-foreground" />
        <h1 className="mt-3 text-lg font-semibold">Could not check your session</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The server is not responding. Your sign-in is not affected; try again in a moment.
        </p>
        <Button className="mt-4" onClick={onRetry}>
          Retry
        </Button>
      </div>
    </main>
  );
}

/** Client-side gate: the API enforces authorization; this keeps signed-out users off the screens. */
export function AdminGuard({ children }: { children: ReactNode }) {
  const { status, retry } = useSession();
  if (status === "error") return <SessionError onRetry={retry} />;
  // Signed-out users see the skeleton while the provider redirects them to login.
  if (status !== "authenticated") return <ShellSkeleton />;
  return <AdminShell>{children}</AdminShell>;
}
