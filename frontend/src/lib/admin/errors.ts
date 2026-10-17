import { isApiError } from "@/lib/api";

/** Plain-language message for an API error: a known code's text first, then the server's, then a fallback. */
export function describeError(
  e: unknown,
  known: Record<string, string | ((details: Record<string, unknown>) => string)> = {},
  fallback = "Something went wrong. Try again.",
): string {
  if (!isApiError(e)) return fallback;
  const text = known[e.code];
  if (typeof text === "function") return text(e.details);
  if (text) return text;
  if (e.code === "NETWORK_ERROR") return "Could not reach the server. Check your connection.";
  return e.message || fallback;
}
