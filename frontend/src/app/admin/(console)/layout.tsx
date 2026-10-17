import { AdminGuard } from "@/components/admin/admin-guard";

export default function ConsoleLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AdminGuard>{children}</AdminGuard>;
}
