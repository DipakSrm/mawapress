"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { api, isApiError, type components } from "@/lib/api";

export type MediaOut = components["schemas"]["MediaOut"];
export type MediaList = components["schemas"]["MediaListOut"];

export const MEDIA_PAGE = 24;
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];
export const ACCEPT_ATTR = ACCEPTED_TYPES.join(",");

export function useMediaList(q: string, page: number) {
  return useQuery({
    queryKey: ["media", "list", q, page],
    queryFn: () =>
      api.get<MediaList>("/api/media", {
        query: { q: q || undefined, limit: MEDIA_PAGE, offset: (page - 1) * MEDIA_PAGE },
      }),
    placeholderData: keepPreviousData,
  });
}

/** Grid thumbnail: the small variant when the worker has made it, else the original. */
export function mediaThumb(media: MediaOut): string {
  return media.variants["320"] ?? media.variants["640"] ?? media.url;
}

/** The image to put in an article: the 1024 px variant when there is one, else the original. */
export function mediaArticleUrl(media: MediaOut): string {
  return media.variants["1024"] ?? media.url;
}

/** Alt text in the editor's language, falling back to the caption. */
export function mediaAlt(media: MediaOut, locale: "ne" | "en"): string {
  const own = locale === "ne" ? media.alt_ne : media.alt_en;
  return own || media.caption || "";
}

/** Short label for a grid cell and for screen readers. */
export function mediaLabel(media: MediaOut): string {
  return media.alt_ne || media.alt_en || media.caption || `Image ${media.width}×${media.height}`;
}

/** Client-side check before sending; returns a message, or null when the file is fine. */
export function validateFile(file: Pick<File, "type" | "size" | "name">): string | null {
  if (!ACCEPTED_TYPES.includes(file.type))
    return "Only JPEG, PNG, WebP and GIF images are accepted.";
  if (file.size > MAX_UPLOAD_BYTES) return "Files can be at most 10 MB.";
  return null;
}

const SERVER_MESSAGES: Record<string, string> = {
  FILE_TOO_LARGE: "Files can be at most 10 MB.",
  HTTP_413: "Files can be at most 10 MB.",
  UNSUPPORTED_MEDIA: "Only JPEG, PNG, WebP and GIF images are accepted.",
  HTTP_415: "Only JPEG, PNG, WebP and GIF images are accepted.",
  IMAGE_TOO_LARGE: "Images can be at most 40 megapixels.",
  NETWORK_ERROR: "Could not reach the server. Check your connection and try again.",
};

export function uploadErrorMessage(e: unknown): string {
  if (isApiError(e)) return SERVER_MESSAGES[e.code] ?? e.message;
  return "The upload failed.";
}

export interface UploadItem {
  id: number;
  name: string;
  status: "uploading" | "done" | "error";
  /** 0..1 */
  progress: number;
  error?: string;
  media?: MediaOut;
}

/** A queue of uploads with per-file progress. Files that fail validation never leave the browser. */
export function useMediaUpload(onUploaded?: (media: MediaOut) => void) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<UploadItem[]>([]);
  const nextId = useRef(1);
  const onUploadedRef = useRef(onUploaded);
  onUploadedRef.current = onUploaded;

  const patch = useCallback((id: number, change: Partial<UploadItem>) => {
    setItems((all) => all.map((it) => (it.id === id ? { ...it, ...change } : it)));
  }, []);

  const add = useCallback(
    (files: Iterable<File>) => {
      for (const file of files) {
        const id = nextId.current++;
        const problem = validateFile(file);
        if (problem) {
          setItems((all) => [
            ...all,
            { id, name: file.name, status: "error", progress: 0, error: problem },
          ]);
          continue;
        }
        setItems((all) => [...all, { id, name: file.name, status: "uploading", progress: 0 }]);
        const form = new FormData();
        form.append("file", file);
        api
          .upload<MediaOut>("/api/media", form, {
            onProgress: (progress) => patch(id, { progress }),
          })
          .then((media) => {
            patch(id, { status: "done", progress: 1, media });
            void queryClient.invalidateQueries({ queryKey: ["media"] });
            onUploadedRef.current?.(media);
          })
          .catch((e: unknown) => patch(id, { status: "error", error: uploadErrorMessage(e) }));
      }
    },
    [patch, queryClient],
  );

  const dismiss = useCallback((id: number) => {
    setItems((all) => all.filter((it) => it.id !== id));
  }, []);

  return { items, add, dismiss };
}
