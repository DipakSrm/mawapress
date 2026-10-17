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
import { api, getAccessToken, onAuthExpired, setAccessToken, type components } from "@/lib/api";
import { readCsrfCookie } from "@/lib/api/session";
import { LOGIN_PATH, loginUrl } from "./next-path";
import { roleAtLeast, type Role } from "./roles";

export type SessionUser = components["schemas"]["MeOut"];
export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

interface SessionContextValue {
  status: SessionStatus;
  user: SessionUser | null;
  role: Role | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasRole: (min: Role) => boolean;
}

const SessionContext = createContext<SessionContextValue | null>(null);

async function fetchMe(): Promise<SessionUser> {
  return api.get<SessionUser>("/api/auth/me");
}

/** Restore a session from the refresh cookie (or the in-memory token when one exists). */
async function restore(): Promise<SessionUser | null> {
  try {
    if (!getAccessToken()) await api.refresh();
    return await fetchMe();
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [user, setUser] = useState<SessionUser | null>(null);
  const boot = useRef<Promise<SessionUser | null> | null>(null);

  const clear = useCallback(() => {
    setUser(null);
    setStatus("unauthenticated");
    queryClient.clear();
  }, [queryClient]);

  // Silent restore on mount. The ref keeps React strict-mode's double effect to one refresh.
  useEffect(() => {
    let active = true;
    boot.current ??= restore();
    void boot.current.then((me) => {
      if (!active) return;
      if (me) {
        setUser(me);
        setStatus("authenticated");
      } else {
        setUser(null);
        setStatus("unauthenticated");
      }
    });
    return () => {
      active = false;
    };
  }, []);

  // The API client emits this when a refresh fails; the redirect itself happens below.
  useEffect(() => onAuthExpired(clear), [clear]);

  useEffect(() => {
    if (status !== "unauthenticated" || pathname === LOGIN_PATH) return;
    const search = typeof window === "undefined" ? "" : window.location.search;
    router.replace(loginUrl(pathname + search));
  }, [status, pathname, router]);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await api.post<{ access_token: string }>(
      "/api/auth/login",
      { email, password },
      { auth: false },
    );
    setAccessToken(access_token);
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
      hasRole: (min) => roleAtLeast(user?.role, min),
    }),
    [status, user, login, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
