import { useMemo, useSyncExternalStore } from "react";
import { nav, router, subscribeNav } from "./nav-state";

/** vi.mock factory for next/navigation, backed by the shared `router` and `nav` state. */
export function navigationMock() {
  return {
    useRouter: () => router,
    usePathname: () =>
      useSyncExternalStore(
        subscribeNav,
        () => nav.pathname,
        () => nav.pathname,
      ),
    useSearchParams: () => {
      const search = useSyncExternalStore(
        subscribeNav,
        () => nav.search,
        () => nav.search,
      );
      return useMemo(() => new URLSearchParams(search), [search]);
    },
  };
}
