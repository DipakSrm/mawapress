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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ActionResult, PostSummary } from "@/lib/admin/posts";
import { toLocalInputValue, toOffsetIso, validateScheduleTime } from "@/lib/admin/posts";

interface Props {
  post: Pick<PostSummary, "status" | "scheduled_at">;
  onClose: () => void;
  onSchedule: (scheduledAt: string) => Promise<ActionResult>;
}

/** Mounted only while open, so every opening starts from the post current schedule. */
export function ScheduleDialog({ post, onClose, onSchedule }: Props) {
  const [value, setValue] = useState(() =>
    post.scheduled_at ? toLocalInputValue(new Date(post.scheduled_at)) : "",
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const rescheduling = post.status === "scheduled";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    const problem = validateScheduleTime(value);
    const iso = problem ? null : toOffsetIso(value);
    if (problem || !iso) {
      setError(problem ?? "Choose a date and time.");
      return;
    }
    setError(null);
    setPending(true);
    const result = await onSchedule(iso);
    if (result.ok) {
      onClose();
      return;
    }
    // Any failure (validation, a conflict, a dropped connection) keeps the dialog and the chosen time.
    setError(result.error.message);
    setPending(false);
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent>
        <form onSubmit={onSubmit} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{rescheduling ? "Reschedule post" : "Schedule post"}</DialogTitle>
            <DialogDescription>
              The post goes live at this time. Times are in your local time ({zone}).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="schedule-at">Publish at</Label>
            <Input
              id="schedule-at"
              type="datetime-local"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              min={toLocalInputValue(new Date(Date.now() + 60_000))}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "schedule-error" : undefined}
            />
            {error && (
              <p
                id="schedule-error"
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
              {rescheduling ? "Reschedule" : "Schedule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
