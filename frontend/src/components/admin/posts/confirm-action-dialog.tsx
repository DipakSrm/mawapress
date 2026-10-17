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
import type { ActionResult } from "@/lib/admin/posts";

interface Props {
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  onClose: () => void;
  onConfirm: () => Promise<ActionResult>;
}

/** A short "are you sure" for a workflow action. Stays open, with the error, when the action fails. */
export function ConfirmActionDialog({
  title,
  description,
  confirmLabel,
  destructive,
  onClose,
  onConfirm,
}: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
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
          <Button
            type="button"
            variant={destructive ? "destructive" : "default"}
            onClick={() => void confirm()}
            disabled={pending}
          >
            {pending && <Loader2 aria-hidden className="animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
