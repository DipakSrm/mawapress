/**
 * Origin of the public site, without a trailing slash. `NEXT_PUBLIC_SITE_URL` when set (the admin may be
 * served from a different host than the public site), else the origin the admin is open on.
 */
export function siteOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL?.trim().replace(/\/+$/, "");
  if (configured) return configured;
  return typeof window === "undefined" ? "" : window.location.origin;
}

/** Absolute URL for a site-relative path; absolute URLs pass through unchanged. */
export function siteUrl(pathOrUrl: string, origin: string = siteOrigin()): string {
  return pathOrUrl.startsWith("/") ? `${origin}${pathOrUrl}` : pathOrUrl;
}
