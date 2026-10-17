"use client";

import { AlertCircle, Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { isApiError } from "@/lib/api";
import { safeNextPath, useSession } from "@/lib/auth";
import { BrandLogo } from "./brand-logo";

export function formatWait(seconds: number): string {
  const s = Math.max(1, Math.ceil(seconds));
  if (s < 60) return `${s} second${s === 1 ? "" : "s"}`;
  const m = Math.ceil(s / 60);
  return `${m} minute${m === 1 ? "" : "s"}`;
}

export function loginErrorMessage(e: unknown): string {
  if (isApiError(e)) {
    if (e.code === "INVALID_CREDENTIALS") return "Incorrect email or password.";
    if (e.code === "RATE_LIMITED" || e.status === 429) {
      return e.retryAfter !== undefined
        ? `Too many sign-in attempts. Try again in ${formatWait(e.retryAfter)}.`
        : "Too many sign-in attempts. Please wait a moment and try again.";
    }
    if (e.code === "NETWORK_ERROR") return "Could not reach the server. Check your connection.";
  }
  return "Sign-in failed. Please try again.";
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const { status, login } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Already signed in (restored from the refresh cookie, or just logged in): leave the login page.
  useEffect(() => {
    if (status === "authenticated") router.replace(next);
  }, [status, next, router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setError(null);
    setPending(true);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(loginErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/30 px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <BrandLogo width={220} priority />
          <p lang="ne" className="text-sm text-muted-foreground">
            मोरङको आवाज
          </p>
        </div>
        <div className="rounded-xl border bg-card p-6 shadow-sm">
          <h1 className="text-lg font-semibold">Sign in to the newsroom</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Use your MAWAPRESS staff account to continue.
          </p>
          <form onSubmit={onSubmit} className="mt-5 space-y-4" noValidate>
            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="username"
                autoFocus
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-invalid={error ? true : undefined}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={error ? true : undefined}
              />
            </div>
            <Button type="submit" className="w-full" disabled={pending || !email || !password}>
              {pending && <Loader2 aria-hidden className="animate-spin" />}
              {pending ? "Signing in" : "Sign in"}
            </Button>
          </form>
        </div>
      </div>
    </main>
  );
}
