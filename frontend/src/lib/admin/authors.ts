import { useQuery } from "@tanstack/react-query";
import { api, type components } from "@/lib/api";

export type Author = components["schemas"]["AuthorOut"];

/** Names of active staff, for author filters and revision history. Editors and admins only. */
export function useAuthors(enabled: boolean) {
  return useQuery({
    queryKey: ["authors"],
    queryFn: () => api.get<Author[]>("/api/users/authors"),
    enabled,
    staleTime: 5 * 60_000,
  });
}
