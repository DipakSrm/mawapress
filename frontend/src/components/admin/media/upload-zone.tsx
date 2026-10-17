"use client";

import { AlertCircle, CheckCircle2, Loader2, UploadCloud, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { Button } from "@/components/ui/button";
import { ACCEPT_ATTR, type UploadItem } from "@/lib/admin/media";
import { cn } from "@/lib/utils";

interface Props {
  items: UploadItem[];
  onFiles: (files: File[]) => void;
  onDismiss: (id: number) => void;
  compact?: boolean;
}

/** Drag-and-drop target, file picker and the per-file progress list. */
export function UploadZone({ items, onFiles, onDismiss, compact }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  function drop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    if (e.dataTransfer.files.length) onFiles(Array.from(e.dataTransfer.files));
  }

  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn(
          "flex flex-wrap items-center justify-center gap-3 rounded-xl border border-dashed bg-card px-4 text-sm text-muted-foreground transition-colors",
          compact ? "py-3" : "py-8",
          over && "border-ring bg-accent/50 text-foreground",
        )}
      >
        <UploadCloud aria-hidden className="size-5" />
        <span>Drop images here, or</span>
        <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()}>
          Choose files
        </Button>
        <span className="text-xs">JPEG, PNG, WebP or GIF, up to 10 MB each</span>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          aria-label="Upload images"
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            if (e.target.files?.length) onFiles(Array.from(e.target.files));
            e.target.value = "";
          }}
        />
      </div>
      {items.length > 0 && (
        <ul aria-label="Uploads" className="space-y-1.5">
          {items.map((it) => (
            <li
              key={it.id}
              className="flex items-center gap-3 rounded-lg bg-card px-3 py-2 text-sm ring-1 ring-foreground/10"
            >
              {it.status === "uploading" ? (
                <Loader2 aria-hidden className="size-4 shrink-0 animate-spin" />
              ) : it.status === "done" ? (
                <CheckCircle2 aria-hidden className="size-4 shrink-0 text-emerald-600" />
              ) : (
                <AlertCircle aria-hidden className="size-4 shrink-0 text-destructive" />
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{it.name}</p>
                {it.status === "uploading" && (
                  <div
                    role="progressbar"
                    aria-label={`Uploading ${it.name}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(it.progress * 100)}
                    className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"
                  >
                    <div
                      className="h-full bg-primary transition-[width]"
                      style={{ width: `${Math.round(it.progress * 100)}%` }}
                    />
                  </div>
                )}
                {it.status === "error" && (
                  <p role="alert" className="text-xs text-destructive">
                    {it.error}
                  </p>
                )}
                {it.status === "done" && <p className="text-xs text-muted-foreground">Uploaded</p>}
              </div>
              {it.status !== "uploading" && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Dismiss ${it.name}`}
                  onClick={() => onDismiss(it.id)}
                >
                  <X aria-hidden />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
