"use client";

import { AlertCircle } from "lucide-react";
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
import {
  parseMediaUrl,
  validateImageUrl,
  validateLinkUrl,
  type MediaTarget,
} from "@/lib/editor/url";

function FieldError({ id, message }: { id: string; message: string | null }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="flex items-start gap-1.5 text-sm text-destructive">
      <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>{message}</span>
    </p>
  );
}

interface LinkDialogProps {
  initialUrl: string;
  hasLink: boolean;
  onClose: () => void;
  onApply: (url: string) => void;
  onRemove: () => void;
}

/** Mounted only while open, so each opening starts from the link under the cursor. */
export function LinkDialog({ initialUrl, hasLink, onClose, onApply, onRemove }: LinkDialogProps) {
  const [value, setValue] = useState(initialUrl);
  const [error, setError] = useState<string | null>(null);
  function submit(e: FormEvent) {
    e.preventDefault();
    const result = validateLinkUrl(value);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onApply(result.url);
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{hasLink ? "Edit link" : "Insert link"}</DialogTitle>
            <DialogDescription>Links can go to http, https or mailto addresses.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="editor-link-url">Web address</Label>
            <Input
              id="editor-link-url"
              value={value}
              autoFocus
              placeholder="https://example.com"
              onChange={(e) => {
                setValue(e.target.value);
                setError(null);
              }}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "editor-link-error" : undefined}
            />
            <FieldError id="editor-link-error" message={error} />
          </div>
          <DialogFooter>
            {hasLink && (
              <Button type="button" variant="outline" onClick={onRemove} className="sm:mr-auto">
                Remove link
              </Button>
            )}
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">Apply</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export interface ImageInput {
  src: string;
  alt: string;
  caption: string;
}

/** Fallback image prompt, used when no media picker is wired in. */
export function ImageDialog({
  onClose,
  onInsert,
}: {
  onClose: () => void;
  onInsert: (image: ImageInput) => void;
}) {
  const [src, setSrc] = useState("");
  const [alt, setAlt] = useState("");
  const [caption, setCaption] = useState("");
  const [error, setError] = useState<string | null>(null);
  function submit(e: FormEvent) {
    e.preventDefault();
    const result = validateImageUrl(src);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onInsert({ src: result.url, alt: alt.trim(), caption: caption.trim() });
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Insert image</DialogTitle>
            <DialogDescription>
              Paste the address of an image from the media library.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="editor-image-url">Image address</Label>
            <Input
              id="editor-image-url"
              value={src}
              autoFocus
              placeholder="https://"
              onChange={(e) => {
                setSrc(e.target.value);
                setError(null);
              }}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "editor-image-error" : undefined}
            />
            <FieldError id="editor-image-error" message={error} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="editor-image-alt">Alt text</Label>
            <Input id="editor-image-alt" value={alt} onChange={(e) => setAlt(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="editor-image-caption">Caption</Label>
            <Input
              id="editor-image-caption"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">Insert</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** YouTube videos and Facebook / X / TikTok posts, detected from the address. */
export function MediaDialog({
  onClose,
  onInsert,
}: {
  onClose: () => void;
  onInsert: (target: MediaTarget) => void;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  function submit(e: FormEvent) {
    e.preventDefault();
    const result = parseMediaUrl(value);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onInsert(result.target);
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Embed video or post</DialogTitle>
            <DialogDescription>
              Paste a YouTube video, or a Facebook, X or TikTok post address.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="editor-media-url">Address</Label>
            <Input
              id="editor-media-url"
              value={value}
              autoFocus
              placeholder="https://www.youtube.com/watch?v=..."
              onChange={(e) => {
                setValue(e.target.value);
                setError(null);
              }}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "editor-media-error" : undefined}
            />
            <FieldError id="editor-media-error" message={error} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">Embed</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
