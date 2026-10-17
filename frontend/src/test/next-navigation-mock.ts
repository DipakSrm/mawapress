import { nav, router } from "./nav-state";

/** vi.mock factory for next/navigation, backed by the shared `router` and `nav` state. */
export function navigationMock() {
  return {
    useRouter: () => router,
    usePathname: () => nav.pathname,
    useSearchParams: () => new URLSearchParams(nav.search),
  };
}
