"use client";

import { AlertCircle, Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ActionResult } from "@/lib/admin/posts";

interface Props {
  onClose: () => void;
  onSendBack: (note: string) => Promise<ActionResult>;
}

export function SendBackDialog({ onClose, onSendBack }: Props) {
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    const result = await onSendBack(note.trim());
    if (result.ok) {
      onClose();
      return;
    }
    // Stay open with the note intact, so a dropped connection costs the editor nothing.
    setError(result.error.message);
    setPending(false);
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Send back to the reporter</DialogTitle>
            <DialogDescription>
              The post returns to draft so the reporter can edit it again.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="send-back-note">Note (optional)</Label>
            <Textarea
              id="send-back-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              rows={4}
              placeholder="What should change?"
              aria-describedby={error ? "send-back-error" : undefined}
            />
            {error && (
              <p
                id="send-back-error"
                role="alert"
                className="flex items-start gap-1.5 text-sm text-destructive"
              >
                <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
                <span>{error}</span>
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={pending}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 aria-hidden className="animate-spin" />}
              Send back
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
