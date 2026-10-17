"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type components } from "@/lib/api";
import { describeError } from "./errors";

export type StaffUser = components["schemas"]["UserOut"];
export type Role = components["schemas"]["Role"];

export const ROLES: Role[] = ["reporter", "editor", "admin"];
export const ROLE_LABEL: Record<Role, string> = {
  reporter: "Reporter",
  editor: "Editor",
  admin: "Admin",
};
export { ROLE_RANK as ROLE_RANK_OF } from "@/lib/auth/roles";
export const MIN_PASSWORD = 10;

export function useUsers() {
  return useQuery({ queryKey: ["users"], queryFn: () => api.get<StaffUser[]>("/api/users") });
}

export const userError = (e: unknown) =>
  describeError(e, {
    LAST_ADMIN: "At least one active admin must remain. Make someone else an admin first.",
    CANNOT_MODIFY_SELF: "You cannot deactivate or demote your own account. Ask another admin.",
    EMAIL_TAKEN: "Someone already uses that email address.",
    USER_NOT_FOUND: "This user no longer exists. Reload the list.",
  });
