import type { components } from "@/lib/api";

export type Role = components["schemas"]["Role"];

export const ROLE_RANK: Record<Role, number> = { reporter: 1, editor: 2, admin: 3 };

/** True when `role` is at least `min` (reporter < editor < admin). */
export function roleAtLeast(role: Role | null | undefined, min: Role): boolean {
  return role ? ROLE_RANK[role] >= ROLE_RANK[min] : false;
}
