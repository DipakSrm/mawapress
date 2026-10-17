import {
  FilePlus2,
  FileText,
  FolderTree,
  Image as ImageIcon,
  LayoutDashboard,
  ListChecks,
  Tags,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { Role } from "@/lib/auth/roles";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Minimum role that sees this item; omitted means every signed-in user. */
  minRole?: Role;
  /** Match only this exact path (otherwise prefix match). */
  exact?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Newsroom",
    items: [
      { href: "/admin", label: "Dashboard", icon: LayoutDashboard, exact: true },
      { href: "/admin/posts", label: "Posts", icon: FileText, exact: true },
      { href: "/admin/posts/new", label: "New post", icon: FilePlus2 },
      { href: "/admin/media", label: "Media", icon: ImageIcon },
    ],
  },
  {
    label: "Organise",
    items: [
      { href: "/admin/categories", label: "Categories", icon: FolderTree },
      { href: "/admin/tags", label: "Tags", icon: Tags },
    ],
  },
  {
    label: "Administration",
    items: [
      { href: "/admin/users", label: "Users", icon: Users, minRole: "admin" },
      { href: "/admin/jobs", label: "Jobs", icon: ListChecks, minRole: "admin" },
    ],
  },
  {
    label: "Account",
    items: [{ href: "/admin/profile", label: "Profile", icon: UserCog }],
  },
];

export function isActive(item: NavItem, pathname: string): boolean {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}
