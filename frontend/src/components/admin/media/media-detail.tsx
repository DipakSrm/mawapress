"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
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
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import type { MediaOut } from "@/lib/admin/media";
import { siteUrl } from "@/lib/admin/site-url";
import { api, isApiError } from "@/lib/api";

type Field = "alt_ne" | "alt_en" | "caption";
const FIELDS: Field[] = ["alt_ne", "alt_en", "caption"];

interface Props {
  media: MediaOut;
  canDelete: boolean;
  onChange: (media: MediaOut) => void;
  onDeleted: () => void;
  onClose: () => void;
}

/** Side panel for one image: alt text and caption (saved when a field loses focus), URL, delete. */
export function MediaDetail({ media, canDelete, onChange, onDeleted, onClose }: Props) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState({
    alt_ne: media.alt_ne ?? "",
    alt_en: media.alt_en ?? "",
    caption: media.caption ?? "",
  });
  const saved = useRef({ ...values });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const inflight = useRef<Promise<boolean>>(Promise.resolve(true));
  const valuesRef = useRef(values);
  valuesRef.current = values;

  /** Saves every changed field in one PATCH. Resolves false when the save failed. */
  function flush(): Promise<boolean> {
    const run = inflight.current.then(async () => {
      const changes: Partial<Record<Field, string | null>> = {};
      const trimmed: Partial<Record<Field, string>> = {};
      for (const f of FIELDS) {
        const v = valuesRef.current[f].trim();
        if (v !== saved.current[f]) {
          changes[f] = v || null;
          trimmed[f] = v;
        }
      }
      if (Object.keys(changes).length === 0) return true;
      setSaving(true);
      setError(null);
      try {
        const out = await api.patch<MediaOut>(`/api/media/${media.id}`, changes);
        saved.current = { ...saved.current, ...trimmed };
        onChange(out);
        void queryClient.invalidateQueries({ queryKey: ["media"] });
        return true;
      } catch (e) {
        setError(isApiError(e) ? e.message : "Could not save. Try again.");
        return false;
      } finally {
        setSaving(false);
      }
    });
    inflight.current = run;
    return run;
  }

  /** Every close path (Escape, X, overlay) saves first and closes once the save has gone through. */
  async function close() {
    if (await flush()) onClose();
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(siteUrl(media.url));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy. Select the address and copy it by hand.");
    }
  }

  async function remove() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.delete(`/api/media/${media.id}`);
      void queryClient.invalidateQueries({ queryKey: ["media"] });
      toast.success("Image deleted");
      setConfirming(false);
      onDeleted();
    } catch (e) {
      if (isApiError(e) && e.code === "MEDIA_IN_USE") {
        setDeleteError(
          "This image is the featured image of a post. Change that post's image first.",
        );
      } else {
        setDeleteError(isApiError(e) ? e.message : "Could not delete the image.");
      }
    } finally {
      setDeleting(false);
    }
  }

  const bind = (field: Field) => ({
    value: values[field],
    onChange: (e: { target: { value: string } }) =>
      setValues((v) => ({ ...v, [field]: e.target.value })),
    onBlur: () => void flush(),
  });

  return (
    <>
      <Sheet open onOpenChange={(open) => !open && void close()}>
        <SheetContent side="right" className="w-full gap-0 sm:max-w-md">
          <div className="border-b p-4 pr-12">
            <SheetTitle>Image details</SheetTitle>
            <SheetDescription>
              {media.width}×{media.height} px. Changes save when you leave a field.
            </SheetDescription>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
            <div className="overflow-hidden rounded-lg bg-muted">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={media.variants["640"] ?? media.url}
                alt={media.alt_en || media.alt_ne || media.caption || "Selected image"}
                className="max-h-72 w-full object-contain"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="media-alt-ne">Alt text (नेपाली)</Label>
              <Input id="media-alt-ne" lang="ne" maxLength={300} {...bind("alt_ne")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="media-alt-en">Alt text (English)</Label>
              <Input id="media-alt-en" lang="en" maxLength={300} {...bind("alt_en")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="media-caption">Caption</Label>
              <Textarea id="media-caption" rows={3} maxLength={2000} {...bind("caption")} />
            </div>
            <p aria-live="polite" className="h-4 text-xs text-muted-foreground">
              {saving ? "Saving…" : ""}
            </p>
            {error && (
              <div className="space-y-2">
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
                {/* Closing normally retries the save; when it keeps failing this is the way out. */}
                <Button type="button" variant="outline" size="sm" onClick={onClose}>
                  Close without saving
                </Button>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="media-url">Address</Label>
              <div className="flex gap-2">
                <Input
                  id="media-url"
                  readOnly
                  value={media.url}
                  onFocus={(e) => e.target.select()}
                />
                <Button type="button" variant="outline" onClick={() => void copy()}>
                  {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>
          </div>
          {canDelete && (
            <div className="border-t p-4">
              <Button type="button" variant="destructive" onClick={() => setConfirming(true)}>
                <Trash2 aria-hidden /> Delete image
              </Button>
            </div>
          )}
        </SheetContent>
      </Sheet>

      {confirming && (
        <Dialog open onOpenChange={(open) => !open && !deleting && setConfirming(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete this image?</DialogTitle>
              <DialogDescription>
                The file and its smaller versions are removed for good. Stories that use it inline
                will show a broken image.
              </DialogDescription>
            </DialogHeader>
            {deleteError && (
              <p role="alert" className="text-sm text-destructive">
                {deleteError}
              </p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={deleting}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={deleting}
                onClick={() => void remove()}
              >
                {deleting && <Loader2 aria-hidden className="animate-spin" />}
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
