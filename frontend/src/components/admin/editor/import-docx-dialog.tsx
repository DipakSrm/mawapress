"use client";

import { FileUp, Loader2, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
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
import { NativeSelect } from "@/components/ui/native-select";
import type { Locale } from "@/lib/admin/editor/seo";
import { useCategories, type PostOut } from "@/lib/admin/posts";
import { api, isApiError, type ApiError, type components } from "@/lib/api";

type ImportOut = components["schemas"]["ImportOut"];

export const MAX_DOCX_BYTES = 15 * 1024 * 1024;

/** Friendly text for each import failure; the API codes are in docs/api-contract.md. */
export function importErrorMessage(e: ApiError): string {
  const code = e.status === 413 ? "DOCX_TOO_LARGE" : e.status === 415 ? "NOT_A_DOCX" : e.code;
  switch (code) {
    case "IMPORT_BUSY":
      return "Other Word files are being converted right now.";
    case "DOCX_TOO_LARGE":
      return "That file is over 15 MB. Remove large images or split the document and try again.";
    case "NOT_A_DOCX":
      return "That is not a Word (.docx) file. Save it as .docx in Word and try again.";
    case "DOCX_UNREADABLE":
      return "We could not read that file. It may be damaged or password protected.";
    case "IMPORT_TIMEOUT":
      return "Converting the file took too long. Try a shorter document.";
    case "CATEGORY_NOT_FOUND":
      return "That category no longer exists. Pick another one.";
    case "NETWORK_ERROR":
      return "Could not reach the server. Check your connection and try again.";
    default:
      return e.message;
  }
}

interface Props {
  onClose: () => void;
  defaultLocale?: Locale;
  /** Where to go with the new draft. Defaults to a plain router push; the editor routes it through its leave guard. */
  onOpen?: (path: string) => void;
}

/** Upload a .docx, show what the importer dropped, then open the new draft. */
export function ImportDocxDialog({ onClose, defaultLocale = "ne", onOpen }: Props) {
  const router = useRouter();
  const categories = useCategories();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [locale, setLocale] = useState<Locale>(defaultLocale);
  const [categoryId, setCategoryId] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wait, setWait] = useState(0);
  const [result, setResult] = useState<ImportOut | null>(null);

  const busy = progress !== null;

  // Counts down the Retry-After of IMPORT_BUSY.
  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  function open(post: PostOut) {
    const path = `/admin/posts/${post.id}`;
    if (onOpen) onOpen(path);
    else router.push(path);
  }

  function pick(next: File | null) {
    setError(null);
    setWait(0);
    if (next && !next.name.toLowerCase().endsWith(".docx")) {
      setFile(null);
      setError("Choose a Word file with the .docx extension.");
      return;
    }
    if (next && next.size > MAX_DOCX_BYTES) {
      setFile(null);
      setError("That file is over 15 MB. Remove large images or split the document.");
      return;
    }
    setFile(next);
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (busy || wait > 0) return;
    if (!file) {
      setError("Choose a .docx file first.");
      return;
    }
    if (!categoryId) {
      setError("Choose a category.");
      return;
    }
    setError(null);
    setProgress(0);
    const form = new FormData();
    form.append("file", file);
    form.append("locale", locale);
    form.append("category_id", categoryId);
    try {
      const out = await api.upload<ImportOut>("/api/import/docx", form, {
        onProgress: setProgress,
      });
      if (out.report.warnings.length === 0) {
        open(out.post);
        return;
      }
      setResult(out);
    } catch (err) {
      if (!isApiError(err)) {
        setError("The import failed. Try again.");
      } else {
        setError(importErrorMessage(err));
        if (err.code === "IMPORT_BUSY") setWait(err.retryAfter ?? 30);
      }
    } finally {
      setProgress(null);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="sm:max-w-md">
        {result ? (
          <>
            <DialogHeader>
              <DialogTitle>Imported as a draft</DialogTitle>
              <DialogDescription>
                {result.report.images} image{result.report.images === 1 ? "" : "s"} imported. Check
                these before publishing:
              </DialogDescription>
            </DialogHeader>
            <ul
              aria-label="Import warnings"
              className="max-h-56 space-y-1.5 overflow-auto rounded-lg border bg-muted/40 p-3 text-sm"
            >
              {result.report.warnings.map((w, i) => (
                <li key={i} className="flex items-start gap-2">
                  <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber-600" />
                  {w}
                </li>
              ))}
            </ul>
            <DialogFooter>
              <Button type="button" onClick={() => open(result.post)}>
                Open draft
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Import from Word</DialogTitle>
              <DialogDescription>
                Creates a new draft from a .docx file (up to 15 MB). Headings, lists, tables and
                images are kept.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-1.5">
              <Label htmlFor="import-file">Word file</Label>
              <input
                ref={fileRef}
                id="import-file"
                type="file"
                accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                disabled={busy}
                onChange={(e) => pick(e.target.files?.[0] ?? null)}
                className="block w-full cursor-pointer rounded-lg border border-input text-sm file:mr-3 file:cursor-pointer file:border-0 file:bg-muted file:px-3 file:py-2 file:text-sm file:font-medium"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="import-locale">Language</Label>
                <NativeSelect
                  id="import-locale"
                  value={locale}
                  disabled={busy}
                  onChange={(e) => setLocale(e.target.value as Locale)}
                >
                  <option value="ne">Nepali</option>
                  <option value="en">English</option>
                </NativeSelect>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="import-category">Category</Label>
                <NativeSelect
                  id="import-category"
                  value={categoryId}
                  disabled={busy}
                  onChange={(e) => setCategoryId(e.target.value)}
                >
                  <option value="">Choose…</option>
                  {categories.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {locale === "ne" ? c.name_ne : c.name_en}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            </div>

            {busy && (
              <div className="space-y-1">
                <div
                  role="progressbar"
                  aria-label="Upload progress"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round((progress ?? 0) * 100)}
                  className="h-2 overflow-hidden rounded-full bg-muted"
                >
                  <div
                    className="h-full bg-primary transition-[width]"
                    style={{ width: `${Math.round((progress ?? 0) * 100)}%` }}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  {(progress ?? 0) < 1 ? "Uploading…" : "Converting the document…"}
                </p>
              </div>
            )}

            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
                {wait > 0 && ` Try again in ${wait} second${wait === 1 ? "" : "s"}.`}
              </p>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy || wait > 0}>
                {busy ? <Loader2 aria-hidden className="animate-spin" /> : <FileUp aria-hidden />}
                {error && !busy ? "Try again" : "Import"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
