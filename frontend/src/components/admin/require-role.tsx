"use client";

import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { buttonVariants } from "@/components/ui/button";
import { useSession, type Role } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function ForbiddenView() {
  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-center py-20 text-center">
      <ShieldAlert aria-hidden className="size-10 text-muted-foreground" />
      <h1 className="mt-4 text-xl font-semibold">403 · Not allowed</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Your role does not have access to this page. Ask an administrator if you need it.
      </p>
      <Link href="/admin" className={cn(buttonVariants({ variant: "outline" }), "mt-6")}>
        Back to dashboard
      </Link>
    </div>
  );
}

/** Wrap a page that needs a minimum role; lower roles get the 403 view. */
export function RequireRole({ min, children }: { min: Role; children: ReactNode }) {
  const { hasRole } = useSession();
  return hasRole(min) ? <>{children}</> : <ForbiddenView />;
}
