"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_GROUPS, isActive } from "@/lib/admin/nav";
import { useSession } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { BrandLogo } from "./brand-logo";

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { hasRole } = useSession();
  const groups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => !i.minRole || hasRole(i.minRole)),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center border-b border-sidebar-border px-4">
        <Link href="/admin" onClick={onNavigate} aria-label="MAWAPRESS admin home">
          <BrandLogo width={132} priority />
        </Link>
      </div>
      <nav aria-label="Admin" className="flex-1 overflow-y-auto px-3 py-4">
        {groups.map((group) => (
          <div key={group.label} className="mb-5 last:mb-0">
            <p className="px-2 pb-1.5 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
              {group.label}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActive(item, pathname);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "relative flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm font-medium text-sidebar-foreground/80 transition-colors outline-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring",
                        active && "bg-sidebar-accent text-sidebar-accent-foreground",
                      )}
                    >
                      {active && (
                        <span
                          aria-hidden
                          className="absolute inset-y-1.5 -left-3 w-1 rounded-r bg-brand-red"
                        />
                      )}
                      <item.icon
                        aria-hidden
                        className={cn(
                          "size-4 shrink-0",
                          active ? "text-brand-red" : "text-muted-foreground",
                        )}
                      />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  );
}
