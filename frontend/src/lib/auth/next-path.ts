export const LOGIN_PATH = "/admin/login";

/** True when `path` is `base` itself, or `base` followed by a path, query or hash boundary. */
function isUnder(path: string, base: string): boolean {
  if (!path.startsWith(base)) return false;
  const next = path.charAt(base.length);
  return next === "" || next === "/" || next === "?" || next === "#";
}

/**
 * Only same-origin admin paths are valid redirect targets (blocks open redirects, `/administrator`,
 * protocol-relative and backslash tricks). The login page itself is never a target.
 */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !isUnder(next, "/admin") || next.startsWith("//") || next.includes("\\")) {
    return "/admin";
  }
  if (isUnder(next, LOGIN_PATH)) return "/admin";
  return next;
}

export function loginUrl(next: string): string {
  const safe = safeNextPath(next);
  return safe === "/admin" ? LOGIN_PATH : `${LOGIN_PATH}?next=${encodeURIComponent(safe)}`;
}
