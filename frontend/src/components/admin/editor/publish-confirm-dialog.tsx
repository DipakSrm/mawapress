"use client";

import { AlertCircle, Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Locale } from "@/lib/admin/editor/seo";
import type { ActionResult } from "@/lib/admin/posts";

export interface PublishTarget {
  locale: Locale;
  title: string;
  /** Already live translations stay live; they are listed so the editor sees the whole post. */
  live: boolean;
}

const NAME: Record<Locale, string> = { ne: "Nepali", en: "English" };

interface Props {
  targets: PublishTarget[];
  /** One translation of a post that is already live. */
  single?: boolean;
  onClose: () => void;
  onConfirm: () => Promise<ActionResult>;
}

/** Says exactly which versions go public, before the click that makes them public. */
export function PublishConfirmDialog({ targets, single, onClose, onConfirm }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const goingLive = targets.filter((t) => !t.live);

  async function confirm() {
    if (pending) return;
    setPending(true);
    setError(null);
    const result = await onConfirm();
    if (result.ok) {
      onClose();
      return;
    }
    setError(result.error.message);
    setPending(false);
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{single ? "Publish this version?" : "Publish this post?"}</DialogTitle>
          <DialogDescription>
            {goingLive.length === 0
              ? "Nothing new will go public."
              : "These versions become visible to readers now:"}
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-2" aria-label="Versions going live">
          {targets.map((t) => (
            <li key={t.locale} className="rounded-lg border px-3 py-2">
              <p className="text-xs font-medium text-muted-foreground">
                {NAME[t.locale]}
                {t.live ? " · already live" : " · goes live"}
              </p>
              <p lang={t.locale} className="truncate text-sm font-medium">
                {t.title.trim() || "(no title yet)"}
              </p>
            </li>
          ))}
        </ul>
        {error && (
          <p role="alert" className="flex items-start gap-1.5 text-sm text-destructive">
            <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void confirm()} disabled={pending}>
            {pending && <Loader2 aria-hidden className="animate-spin" />}
            Publish
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
