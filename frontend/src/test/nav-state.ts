import { vi } from "vitest";

const listeners = new Set<() => void>();

/**
 * Shared fake navigation state. Kept free of app imports so the next/navigation mock can load it.
 * With `nav.live` set, `router.push/replace` update `nav` and re-render subscribers, so a page that
 * keeps its state in the URL can be driven end to end. Off by default: other tests only assert calls.
 */
export const nav = { pathname: "/admin", search: "", live: false };

export function subscribeNav(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function go(url: string) {
  if (!nav.live) return;
  const [path, query = ""] = url.split("?");
  nav.pathname = path;
  nav.search = query ? `?${query}` : "";
  listeners.forEach((l) => l());
}

export const router = { replace: vi.fn(go), push: vi.fn(go), refresh: vi.fn() };
