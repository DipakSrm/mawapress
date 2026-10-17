"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  getAccessToken,
  isApiError,
  onAuthExpired,
  setAccessToken,
  type components,
} from "@/lib/api";
import { readCsrfCookie } from "@/lib/api/session";
import { LOGIN_PATH, loginUrl } from "./next-path";
import { roleAtLeast, type Role } from "./roles";

export type SessionUser = components["schemas"]["MeOut"];
/** `error`: the session could not be checked (network down or server error); the user may retry. */
export type SessionStatus = "loading" | "authenticated" | "unauthenticated" | "error";

interface SessionContextValue {
  status: SessionStatus;
  user: SessionUser | null;
  role: Role | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Re-run the session restore after a status of `error`. */
  retry: () => void;
  hasRole: (min: Role) => boolean;
}

const SessionContext = createContext<SessionContextValue | null>(null);

async function fetchMe(): Promise<SessionUser> {
  return api.get<SessionUser>("/api/auth/me");
}

type RestoreResult = { kind: "ok"; user: SessionUser } | { kind: "signed-out" } | { kind: "error" };

/** A failure that says nothing about whether the session is valid. */
function isTransient(e: unknown): boolean {
  return !isApiError(e) || e.status === 0 || e.status >= 500;
}

/** Restore a session from the refresh cookie (or the in-memory token when one exists). */
async function restore(): Promise<RestoreResult> {
  try {
    if (!getAccessToken()) await api.refresh();
    return { kind: "ok", user: await fetchMe() };
  } catch (e) {
    return isTransient(e) ? { kind: "error" } : { kind: "signed-out" };
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [user, setUser] = useState<SessionUser | null>(null);
  const boot = useRef<Promise<RestoreResult> | null>(null);
  const mounted = useRef(false);
  const explicitLogout = useRef(false);

  const clear = useCallback(() => {
    setUser(null);
    setStatus("unauthenticated");
    queryClient.clear();
  }, [queryClient]);

  const apply = useCallback((pending: Promise<RestoreResult>) => {
    void pending.then((result) => {
      if (!mounted.current) return;
      if (result.kind === "ok") {
        setUser(result.user);
        setStatus("authenticated");
      } else {
        setUser(null);
        setStatus(result.kind === "error" ? "error" : "unauthenticated");
      }
    });
  }, []);

  // Silent restore on mount. The ref keeps React strict-mode's double effect to one refresh.
  useEffect(() => {
    mounted.current = true;
    boot.current ??= restore();
    apply(boot.current);
    return () => {
      mounted.current = false;
    };
  }, [apply]);

  const retry = useCallback(() => {
    setStatus("loading");
    boot.current = restore();
    apply(boot.current);
  }, [apply]);

  // The API client emits this when a refresh fails; the redirect itself happens below.
  useEffect(() => onAuthExpired(clear), [clear]);

  useEffect(() => {
    if (status !== "unauthenticated" || pathname === LOGIN_PATH) return;
    const search = typeof window === "undefined" ? "" : window.location.search;
    // An explicit log-out lands on the plain login page; an expiry remembers where the user was.
    router.replace(explicitLogout.current ? LOGIN_PATH : loginUrl(pathname + search));
  }, [status, pathname, router]);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await api.post<{ access_token: string }>(
      "/api/auth/login",
      { email, password },
      { auth: false },
    );
    setAccessToken(access_token);
    explicitLogout.current = false;
    try {
      const me = await fetchMe();
      setUser(me);
      setStatus("authenticated");
    } catch (e) {
      setAccessToken(null);
      throw e;
    }
  }, []);

  const logout = useCallback(async () => {
    explicitLogout.current = true;
    try {
      const csrf = readCsrfCookie();
      await api.post(
        "/api/auth/logout",
        undefined,
        csrf ? { headers: { "X-CSRF-Token": csrf } } : {},
      );
    } catch {
      // The server session may already be gone; the local session ends either way.
    } finally {
      setAccessToken(null);
      clear();
    }
  }, [clear]);

  const value = useMemo<SessionContextValue>(
    () => ({
      status,
      user,
      role: user?.role ?? null,
      login,
      logout,
      retry,
      hasRole: (min) => roleAtLeast(user?.role, min),
    }),
    [status, user, login, logout, retry],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
