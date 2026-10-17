/**
 * In-memory access-token store. The token is never persisted: a page reload starts without
 * one, and the first authenticated call recovers it through the refresh cookie.
 */
export const AUTH_EXPIRED_EVENT = "auth:expired";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Drop the session and tell the UI to go to the login screen. */
export function expireSession(): void {
  accessToken = null;
  if (typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

export function onAuthExpired(handler: () => void): () => void {
  window.addEventListener(AUTH_EXPIRED_EVENT, handler);
  return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handler);
}

export const CSRF_COOKIE = "mawa_csrf";

export function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const i = part.indexOf("=");
    if (i === -1) continue;
    if (part.slice(0, i).trim() === CSRF_COOKIE) {
      return decodeURIComponent(part.slice(i + 1).trim());
    }
  }
  return null;
}
