export const LOGIN_PATH = "/admin/login";

/** Only same-origin admin paths are valid redirect targets (blocks open redirects). */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/admin") || next.startsWith("//") || next.includes("\\")) {
    return "/admin";
  }
  if (next === LOGIN_PATH || next.startsWith(`${LOGIN_PATH}?`)) return "/admin";
  return next;
}

export function loginUrl(next: string): string {
  const safe = safeNextPath(next);
  return safe === "/admin" ? LOGIN_PATH : `${LOGIN_PATH}?next=${encodeURIComponent(safe)}`;
}
