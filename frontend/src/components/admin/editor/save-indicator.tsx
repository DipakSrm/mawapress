import { AlertCircle, CheckCircle2, CloudOff, Loader2, PenLine, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import type { SaveStatus } from "@/lib/admin/editor/use-post-editor";
import { cn } from "@/lib/utils";

const time = (at: number) =>
  new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" }).format(new Date(at));

function describe(status: SaveStatus): { text: string; icon: ReactNode; tone: string } | null {
  switch (status.kind) {
    case "idle":
      return null;
    case "dirty":
      return {
        text: "Unsaved changes",
        icon: <PenLine aria-hidden />,
        tone: "text-muted-foreground",
      };
    case "saving":
      return { text: "Saving…", icon: <Loader2 aria-hidden className="animate-spin" />, tone: "" };
    case "saved":
      return {
        text: `Saved · ${time(status.at)}`,
        icon: <CheckCircle2 aria-hidden />,
        tone: "text-emerald-700 dark:text-emerald-400",
      };
    case "retrying":
      return {
        text: "Not saved — retrying",
        icon: <RefreshCw aria-hidden />,
        tone: "text-amber-700 dark:text-amber-400",
      };
    case "offline":
      return {
        text: "Offline",
        icon: <CloudOff aria-hidden />,
        tone: "text-amber-700 dark:text-amber-400",
      };
    case "blocked":
      return {
        text:
          status.reason === "category"
            ? "Choose a category to start saving"
            : status.locale
              ? `Add a title to save the ${status.locale === "ne" ? "Nepali" : "English"} version`
              : "Add a title to start saving",
        icon: <PenLine aria-hidden />,
        tone: "text-muted-foreground",
      };
    case "error":
      return {
        text: `Not saved — ${status.message}`,
        icon: <AlertCircle aria-hidden />,
        tone: "text-destructive",
      };
    case "conflict":
      return {
        text: "Not saved — edited elsewhere",
        icon: <AlertCircle aria-hidden />,
        tone: "text-destructive",
      };
  }
}

/** Polite live region: screen readers hear each change of save state once. */
export function SaveIndicator({ status, className }: { status: SaveStatus; className?: string }) {
  const info = describe(status);
  return (
    <div role="status" aria-live="polite" className={cn("min-h-5 text-xs", className)}>
      {info && (
        <span className={cn("inline-flex items-center gap-1.5 [&_svg]:size-3.5", info.tone)}>
          {info.icon}
          {info.text}
        </span>
      )}
    </div>
  );
}
