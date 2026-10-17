"use client";

import type { JSONContent } from "@tiptap/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PostOut } from "@/lib/admin/posts";
import { api, ifMatch, isApiError } from "@/lib/api";
import {
  acknowledge,
  clearStoredDraft,
  draftFromPost,
  emptyDraft,
  emptyLocaleDraft,
  LOCALES,
  planSave,
  readStoredDraft,
  sameLocaleDraft,
  sameShared,
  writeStoredDraft,
  type LocaleDraft,
  type PostDraft,
  type SharedDraft,
  type StoredDraft,
} from "./draft";
import type { Locale } from "./seo";

export const AUTOSAVE_MS = 10_000;
const LOCAL_WRITE_MS = 800;
const DERIVE_MS = 400;
const RETRY_BASE_MS = 2_000;
const RETRY_MAX_MS = 60_000;

export type SaveStatus =
  | { kind: "idle" }
  | { kind: "dirty" }
  | { kind: "saving" }
  | { kind: "saved"; at: number }
  | { kind: "retrying" }
  | { kind: "offline" }
  | { kind: "blocked"; reason: "title" | "category" }
  | { kind: "error"; message: string }
  | { kind: "conflict" };

export interface ConflictState {
  currentUpdatedAt: string | null;
}

export interface RestoreOffer {
  records: StoredDraft[];
}

interface Options {
  initial: PostOut | null;
  initialLocale: Locale;
  canBreak: boolean;
  autosaveMs?: number;
  /** Called after the first save of a new post created it on the server. */
  onCreated?: (post: PostOut) => void;
}

function publishedMap(post: PostOut | null): Partial<Record<Locale, boolean>> {
  const map: Partial<Record<Locale, boolean>> = {};
  for (const t of post?.translations ?? []) {
    if (t.locale === "ne" || t.locale === "en") map[t.locale] = t.status === "published";
  }
  return map;
}

/**
 * Owns the working copy of a post and keeps it saved.
 *
 * The working copy lives in refs, not state: typing in the body must not re-render the screen. Only
 * metadata edits bump `version`, and body edits bump `contentTick` after a pause, for the panels that
 * read the text (SEO preview, readability). Saves send only what changed since the last acknowledged
 * save, with If-Match set to the `updated_at` of the last response.
 */
export function usePostEditor({
  initial,
  initialLocale,
  canBreak,
  autosaveMs = AUTOSAVE_MS,
  onCreated,
}: Options) {
  const baseRef = useRef<PostDraft>(initial ? draftFromPost(initial) : emptyDraft(initialLocale));
  const curRef = useRef<PostDraft>(initial ? draftFromPost(initial) : emptyDraft(initialLocale));
  const idRef = useRef<string | null>(initial?.id ?? null);
  const etagRef = useRef<string | null>(initial?.updated_at ?? null);
  const postRef = useRef<PostOut | null>(initial);
  const localeRef = useRef<Locale>(initialLocale);
  const dirtyRef = useRef(false);
  const conflictRef = useRef<ConflictState | null>(null);
  const queueRef = useRef<Promise<boolean>>(Promise.resolve(true));
  const attemptRef = useRef(0);
  const timers = useRef<{
    save?: ReturnType<typeof setTimeout>;
    retry?: ReturnType<typeof setTimeout>;
    local?: ReturnType<typeof setTimeout>;
    derive?: ReturnType<typeof setTimeout>;
  }>({});
  const canBreakRef = useRef(canBreak);
  const onCreatedRef = useRef(onCreated);

  const [post, setPostState] = useState<PostOut | null>(initial);
  const [activeLocale, setActiveLocaleState] = useState<Locale>(initialLocale);
  const [version, setVersion] = useState(0);
  const [epoch, setEpoch] = useState(0);
  const [contentTick, setContentTick] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [conflict, setConflictState] = useState<ConflictState | null>(null);
  const [restoreOffer, setRestoreOffer] = useState<RestoreOffer | null>(null);

  useEffect(() => {
    canBreakRef.current = canBreak;
    onCreatedRef.current = onCreated;
  });

  const setPost = useCallback((p: PostOut | null) => {
    postRef.current = p;
    setPostState(p);
  }, []);
  const setConflict = useCallback((c: ConflictState | null) => {
    conflictRef.current = c;
    setConflictState(c);
  }, []);
  const bump = useCallback(() => setVersion((v) => v + 1), []);

  // ---- local copy of unsaved work -----------------------------------------------------------

  const writeLocal = useCallback(() => {
    clearTimeout(timers.current.local);
    timers.current.local = undefined;
    const id = idRef.current;
    const { base, cur } = { base: baseRef.current, cur: curRef.current };
    const sharedChanged = !sameShared(base.shared, cur.shared);
    let wrote = false;
    for (const locale of LOCALES) {
      const fields = cur.locales[locale];
      if (!fields) continue;
      const baseFields = base.locales[locale];
      const differs = baseFields ? !sameLocaleDraft(baseFields, fields) : hasAnyField(fields);
      if (differs || (sharedChanged && !wrote && locale === localeRef.current)) {
        writeStoredDraft(id, { savedAt: Date.now(), locale, fields, shared: cur.shared });
        wrote = true;
      } else {
        clearStoredDraft(id, locale);
      }
    }
  }, []);

  // ---- saving -------------------------------------------------------------------------------

  const clearRetry = () => {
    clearTimeout(timers.current.retry);
    timers.current.retry = undefined;
  };

  const syncSlugs = useCallback((out: PostOut) => {
    const base = baseRef.current;
    const cur = curRef.current;
    for (const t of out.translations) {
      if (t.locale !== "ne" && t.locale !== "en") continue;
      const b = base.locales[t.locale];
      if (!b) continue;
      const c = cur.locales[t.locale];
      if (c && c.slug === b.slug && c.slug !== t.slug) {
        curRef.current = {
          ...curRef.current,
          locales: { ...curRef.current.locales, [t.locale]: { ...c, slug: t.slug } },
        };
      }
      baseRef.current = {
        ...baseRef.current,
        locales: { ...baseRef.current.locales, [t.locale]: { ...b, slug: t.slug } },
      };
    }
  }, []);

  const acceptPost = useCallback(
    (out: PostOut) => {
      etagRef.current = out.updated_at;
      setPost(out);
      syncSlugs(out);
      bump();
    },
    [bump, setPost, syncSlugs],
  );

  const scheduleSave = useCallback(
    (run: () => void) => {
      if (timers.current.save || conflictRef.current) return;
      timers.current.save = setTimeout(() => {
        timers.current.save = undefined;
        run();
      }, autosaveMs);
    },
    [autosaveMs],
  );

  const runSave = useCallback(
    async (flushAgain: () => Promise<boolean>): Promise<boolean> => {
      if (conflictRef.current) return false;
      clearRetry();
      const plan = planSave({
        postId: idRef.current,
        base: baseRef.current,
        cur: curRef.current,
        activeLocale: localeRef.current,
        published: publishedMap(postRef.current),
        canBreak: canBreakRef.current,
      });
      if (plan.kind === "none") {
        if (dirtyRef.current) {
          dirtyRef.current = false;
          setDirty(false);
          clearStoredDraft(idRef.current);
        }
        setStatus((s) =>
          s.kind === "idle" || s.kind === "saved" ? s : { kind: "saved", at: Date.now() },
        );
        return true;
      }
      if (plan.kind === "blocked") {
        setStatus({ kind: "blocked", reason: plan.reason });
        return false;
      }
      setStatus({ kind: "saving" });
      const snapshot = curRef.current;
      try {
        if (plan.kind === "create") {
          const out = await api.post<PostOut>("/api/posts", plan.body);
          const sent = snapshot.locales[plan.locale]!;
          const created: LocaleDraft = {
            ...emptyLocaleDraft(),
            title: plan.body.title,
            content: sent.content,
          };
          clearStoredDraft(null);
          idRef.current = out.id;
          etagRef.current = out.updated_at;
          baseRef.current = {
            locales: { [plan.locale]: created },
            shared: {
              categoryId: snapshot.shared.categoryId,
              tags: snapshot.shared.tags,
              featuredMedia: snapshot.shared.featuredMedia,
              isBreaking: false,
            },
          };
          setPost(out);
          syncSlugs(out);
          onCreatedRef.current?.(out);
        } else {
          for (const { locale, body } of plan.requests) {
            const out = await api.patch<PostOut>(`/api/posts/${idRef.current}`, body, {
              headers: ifMatch(etagRef.current ?? ""),
            });
            etagRef.current = out.updated_at;
            baseRef.current = acknowledge(baseRef.current, snapshot, locale, body);
            setPost(out);
            syncSlugs(out);
          }
        }
      } catch (e) {
        if (isApiError(e) && e.status === 412) {
          const current = e.details.current_updated_at;
          setConflict({ currentUpdatedAt: typeof current === "string" ? current : null });
          setStatus({ kind: "conflict" });
          writeLocal();
          return false;
        }
        const transient = !isApiError(e) || e.status === 0 || e.status === 429 || e.status >= 500;
        if (transient) {
          attemptRef.current += 1;
          if (typeof navigator !== "undefined" && navigator.onLine === false) {
            setStatus({ kind: "offline" });
          } else {
            setStatus({ kind: "retrying" });
            const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** (attemptRef.current - 1));
            timers.current.retry = setTimeout(() => void flushAgain(), delay);
          }
        } else {
          setStatus({ kind: "error", message: e.message });
        }
        writeLocal();
        return false;
      }
      attemptRef.current = 0;
      // Edits made while the request was in flight still need saving.
      const next = planSave({
        postId: idRef.current,
        base: baseRef.current,
        cur: curRef.current,
        activeLocale: localeRef.current,
        published: publishedMap(postRef.current),
        canBreak: canBreakRef.current,
      });
      if (next.kind === "patch" || next.kind === "create") {
        setStatus({ kind: "dirty" });
        scheduleSave(() => void flushAgain());
        writeLocal();
      } else {
        dirtyRef.current = false;
        setDirty(false);
        clearStoredDraft(idRef.current);
        setStatus({ kind: "saved", at: Date.now() });
      }
      bump();
      return true;
    },
    [bump, scheduleSave, setConflict, setPost, syncSlugs, writeLocal],
  );

  /** Save now (after any save already running). Resolves true when nothing is left unsaved. */
  const flush = useCallback((): Promise<boolean> => {
    clearTimeout(timers.current.save);
    timers.current.save = undefined;
    const run = (): Promise<boolean> => {
      const result = queueRef.current.then(
        () => runSave(run),
        () => runSave(run),
      );
      queueRef.current = result;
      return result;
    };
    return run();
  }, [runSave]);

  // ---- editing ------------------------------------------------------------------------------

  const changed = useCallback(
    (render: boolean, content: boolean) => {
      dirtyRef.current = true;
      setDirty(true);
      setStatus((s) =>
        s.kind === "saved" || s.kind === "idle" || s.kind === "blocked" ? { kind: "dirty" } : s,
      );
      scheduleSave(() => void flush());
      if (!timers.current.local) {
        timers.current.local = setTimeout(writeLocal, LOCAL_WRITE_MS);
      }
      if (content) {
        clearTimeout(timers.current.derive);
        timers.current.derive = setTimeout(() => setContentTick((t) => t + 1), DERIVE_MS);
      }
      if (render) bump();
    },
    [bump, flush, scheduleSave, writeLocal],
  );

  const updateLocale = useCallback(
    (locale: Locale, patch: Partial<LocaleDraft>) => {
      const cur = curRef.current;
      curRef.current = {
        ...cur,
        locales: {
          ...cur.locales,
          [locale]: { ...(cur.locales[locale] ?? emptyLocaleDraft()), ...patch },
        },
      };
      changed(true, false);
    },
    [changed],
  );

  const setContent = useCallback(
    (locale: Locale, content: JSONContent) => {
      const cur = curRef.current;
      curRef.current = {
        ...cur,
        locales: {
          ...cur.locales,
          [locale]: { ...(cur.locales[locale] ?? emptyLocaleDraft()), content },
        },
      };
      changed(false, true);
    },
    [changed],
  );

  const updateShared = useCallback(
    (patch: Partial<SharedDraft>) => {
      curRef.current = { ...curRef.current, shared: { ...curRef.current.shared, ...patch } };
      changed(true, false);
    },
    [changed],
  );

  const addLocale = useCallback(
    (locale: Locale) => {
      if (curRef.current.locales[locale]) return;
      curRef.current = {
        ...curRef.current,
        locales: { ...curRef.current.locales, [locale]: emptyLocaleDraft() },
      };
      bump();
    },
    [bump],
  );

  const setActiveLocale = useCallback((locale: Locale) => {
    localeRef.current = locale;
    setActiveLocaleState(locale);
    setContentTick((t) => t + 1);
  }, []);

  // ---- replacing the working copy -----------------------------------------------------------

  const resetFromPost = useCallback(
    (out: PostOut, opts: { keepStored?: boolean } = {}) => {
      baseRef.current = draftFromPost(out);
      curRef.current = draftFromPost(out);
      etagRef.current = out.updated_at;
      idRef.current = out.id;
      dirtyRef.current = false;
      attemptRef.current = 0;
      clearTimeout(timers.current.save);
      timers.current.save = undefined;
      clearRetry();
      if (!opts.keepStored) clearStoredDraft(out.id);
      setPost(out);
      setDirty(false);
      setConflict(null);
      setStatus({ kind: "idle" });
      setRestoreOffer(null);
      setEpoch((n) => n + 1);
      setContentTick((t) => t + 1);
      bump();
    },
    [bump, setConflict, setPost],
  );

  /** True when the server holds exactly what the editor shows for this language. */
  const isLocaleSaved = useCallback((locale: Locale): boolean => {
    const base = baseRef.current.locales[locale];
    const cur = curRef.current.locales[locale];
    return Boolean(
      base &&
      cur &&
      sameLocaleDraft(base, cur) &&
      sameShared(baseRef.current.shared, curRef.current.shared),
    );
  }, []);

  const findRestoreOffer = useCallback((): RestoreOffer | null => {
    const id = idRef.current;
    const serverTime = postRef.current ? Date.parse(postRef.current.updated_at) : 0;
    const base = baseRef.current;
    const records: StoredDraft[] = [];
    for (const locale of LOCALES) {
      const rec = readStoredDraft(id, locale);
      if (!rec || rec.savedAt <= serverTime) continue;
      const baseFields = base.locales[locale];
      const differs =
        (baseFields ? !sameLocaleDraft(baseFields, rec.fields) : hasAnyField(rec.fields)) ||
        !sameShared(base.shared, rec.shared);
      if (differs) records.push(rec);
    }
    return records.length ? { records } : null;
  }, []);

  /** Pull the stored copy back into the editor (as unsaved changes). */
  const restoreLocal = useCallback(() => {
    if (!restoreOffer) return;
    const records = restoreOffer.records;
    const newest = records.reduce((a, b) => (b.savedAt > a.savedAt ? b : a));
    const locales = { ...curRef.current.locales };
    for (const rec of records) locales[rec.locale] = rec.fields;
    curRef.current = { locales, shared: newest.shared };
    localeRef.current = newest.locale;
    setActiveLocaleState(newest.locale);
    setRestoreOffer(null);
    setEpoch((n) => n + 1);
    changed(true, true);
  }, [changed, restoreOffer]);

  const dismissRestore = useCallback(() => {
    setRestoreOffer(null);
    clearStoredDraft(idRef.current);
  }, []);

  useEffect(() => {
    // Read after mount: localStorage does not exist on the server.
    setRestoreOffer(findRestoreOffer());
  }, [findRestoreOffer]);

  /** The conflict banner's "Load their version": fetch, keep my copy in localStorage, offer to restore it. */
  const loadTheirs = useCallback(async () => {
    writeLocal();
    const id = idRef.current;
    if (!id) return;
    const out = await api.get<PostOut>(`/api/posts/${id}`);
    resetFromPost(out, { keepStored: true });
    setRestoreOffer(findRestoreOffer());
  }, [findRestoreOffer, resetFromPost, writeLocal]);

  /** The conflict banner's "Overwrite": adopt their `updated_at` and send my changes again. */
  const overwrite = useCallback(async () => {
    const id = idRef.current;
    let updatedAt = conflictRef.current?.currentUpdatedAt ?? null;
    if (!updatedAt && id) updatedAt = (await api.get<PostOut>(`/api/posts/${id}`)).updated_at;
    if (updatedAt) etagRef.current = updatedAt;
    setConflict(null);
    return flush();
  }, [flush, setConflict]);

  /** A workflow action elsewhere hit a 412: show the same banner. */
  const reportConflict = useCallback(
    (currentUpdatedAt: string | null) => {
      setConflict({ currentUpdatedAt });
      setStatus({ kind: "conflict" });
      writeLocal();
    },
    [setConflict, writeLocal],
  );

  // ---- browser events -----------------------------------------------------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void flush();
      }
    };
    const onOnline = () => {
      if (dirtyRef.current) void flush();
    };
    const onOffline = () => {
      if (dirtyRef.current) setStatus({ kind: "offline" });
    };
    const onHide = () => {
      if (dirtyRef.current) writeLocal();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("pagehide", onHide);
    const t = timers.current;
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("pagehide", onHide);
      for (const key of ["save", "retry", "local", "derive"] as const) clearTimeout(t[key]);
    };
  }, [flush, writeLocal]);

  return useMemo(
    () => ({
      post,
      postId: idRef.current,
      /** The working copy. Read it during render; it changes whenever `version` does. */
      draft: curRef.current,
      version,
      epoch,
      contentTick,
      dirty,
      status,
      conflict,
      restoreOffer,
      activeLocale,
      getUpdatedAt: () => etagRef.current,
      getDraft: () => curRef.current,
      isLocaleSaved,
      setActiveLocale,
      updateLocale,
      setContent,
      updateShared,
      addLocale,
      flush,
      acceptPost,
      resetFromPost,
      restoreLocal,
      dismissRestore,
      loadTheirs,
      overwrite,
      reportConflict,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [post, version, epoch, contentTick, dirty, status, conflict, restoreOffer, activeLocale],
  );
}

function hasAnyField(d: LocaleDraft): boolean {
  return Boolean(d.title.trim() || d.excerpt || d.seoTitle || d.seoDescription) || hasBody(d);
}

function hasBody(d: LocaleDraft): boolean {
  const walk = (n: JSONContent): boolean =>
    n.type === "text"
      ? Boolean(n.text?.trim())
      : n.type === "image" || Boolean(n.content?.some(walk));
  return walk(d.content);
}
