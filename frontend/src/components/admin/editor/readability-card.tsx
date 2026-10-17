import { CheckCircle2, TriangleAlert } from "lucide-react";
import type { ReadabilityItem } from "@/lib/admin/editor/readability";
import { cn } from "@/lib/utils";

/** Advisory list: warnings never block saving or publishing. */
export function ReadabilityCard({ items }: { items: ReadabilityItem[] }) {
  return (
    <ul className="space-y-2 text-sm" aria-label="Readability checks">
      {items.map((item) => (
        <li
          key={item.id}
          data-ok={item.ok}
          className={cn("flex items-start gap-2", !item.ok && "text-foreground")}
        >
          {item.ok ? (
            <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-emerald-600" />
          ) : (
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber-600" />
          )}
          <span className={cn(item.ok && "text-muted-foreground")}>
            <span className="sr-only">{item.ok ? "Good: " : "Warning: "}</span>
            {item.label}
          </span>
        </li>
      ))}
    </ul>
  );
}
