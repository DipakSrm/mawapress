"use client";

import type { JSONContent } from "@tiptap/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PostOut } from "@/lib/admin/posts";
import { toast } from "sonner";
import { api, ifMatch, isApiError } from "@/lib/api";
import {
  acknowledge,
  applyStored,
  clearStoredDraft,
  draftFromPost,
  mergeDrafts,
  mergeStored,
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
const MAX_PASSES = 3;

export type SaveStatus =
  | { kind: "idle" }
  | { kind: "dirty" }
  | { kind: "saving" }
  | { kind: "saved"; at: number }
  | { kind: "retrying" }
  | { kind: "offline" }
  | { kind: "blocked"; reason: "title" | "category"; locale?: Locale }
  | { kind: "error"; message: string }
  | { kind: "conflict" };

export interface ConflictState {
  currentUpdatedAt: string | null;
}

export interface RestoreOffer {
  records: StoredDraft[];
  /** Some copy was saved before the newest server version: restoring merges instead of replacing. */
  stale: boolean;
  /** The post id the copies are stored under (null = the new-post slot), kept even after a create. */
  keyId: string | null;
}

interface Options {
  initial: PostOut | null;
  initialLocale: Locale;
  canBreak: boolean;
  /** The signed-in user, to recognise a post this user just created (see `findRecentDuplicate`). */
  userId?: string;
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
  userId,
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
  const userIdRef = useRef(userId);
  /** Title of a create POST whose outcome is unknown (timeout, dropped connection, 5xx). */
  const createUncertain = useRef<string | null>(null);

  const [post, setPostState] = useState<PostOut | null>(initial);
  const [activeLocale, setActiveLocaleState] = useState<Locale>(initialLocale);
  const [version, setVersion] = useState(0);
  const [epoch, setEpoch] = useState(0);
  const [contentTick, setContentTick] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [conflict, setConflictState] = useState<ConflictState | null>(null);
  const [restoreOffer, setRestoreOffer] = useState<RestoreOffer | null>(null);
  const restoreOfferRef = useRef<RestoreOffer | null>(null);
  useEffect(() => {
    restoreOfferRef.current = restoreOffer;
  }, [restoreOffer]);

  useEffect(() => {
    canBreakRef.current = canBreak;
    onCreatedRef.current = onCreated;
    userIdRef.current = userId;
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
  const findRestoreOfferRef = useRef<() => RestoreOffer | null>(() => null);

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
        writeStoredDraft(userIdRef.current, id, {
          savedAt: Date.now(),
          locale,
          fields,
          shared: cur.shared,
          base: baseFields,
          baseShared: base.shared,
        });
        wrote = true;
      } else {
        clearStoredDraft(userIdRef.current, id, locale);
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

  /**
   * A create POST that failed in a way that may still have reached the server must not simply be repeated:
   * that would make a second post. Before the next attempt we look for posts this user created in the
   * last two minutes (by `created_at`) with the same title (the API has no idempotency key). Exactly one
   * match is adopted; several matches are ambiguous and nothing is adopted or created.
   */
  const findRecentDuplicate = useCallback(
    async (
      title: string,
    ): Promise<{ kind: "none" } | { kind: "one"; post: PostOut } | { kind: "ambiguous" }> => {
      const author = userIdRef.current;
      if (!author) return { kind: "none" };
      const list = await api.get<{
        items: { id: string; created_at: string; translations: { title: string }[] }[];
      }>("/api/posts", { query: { q: title, author_id: author, limit: 10 } });
      const recent = Date.now() - 120_000;
      const hits = list.items.filter(
        (p) => Date.parse(p.created_at) >= recent && p.translations.some((t) => t.title === title),
      );
      if (hits.length === 0) return { kind: "none" };
      if (hits.length > 1) return { kind: "ambiguous" };
      return { kind: "one", post: await api.get<PostOut>(`/api/posts/${hits[0].id}`) };
    },
    [],
  );

  const runSave = useCallback(
    async (flushAgain: () => Promise<boolean>): Promise<boolean> => {
      if (conflictRef.current) return false;
      clearRetry();
      // Several passes: edits that arrive while a request is in flight are sent straight after it, so a
      // resolved flush means nothing is left behind (callers such as "Save and leave" rely on that).
      for (let pass = 0; pass < MAX_PASSES; pass++) {
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
            clearStoredDraft(userIdRef.current, idRef.current);
          }
          setStatus((s) =>
            s.kind === "idle" || s.kind === "saved" ? s : { kind: "saved", at: Date.now() },
          );
          bump();
          return true;
        }
        if (plan.kind === "blocked") {
          // Still unsaved: stay dirty (leave guard) and keep the stored copy.
          setStatus({ kind: "blocked", reason: plan.reason, locale: plan.locale });
          writeLocal();
          return false;
        }
        setStatus({ kind: "saving" });
        const snapshot = curRef.current;
        try {
          if (plan.kind === "create") {
            let out: PostOut | null = null;
            let adopted = false;
            if (createUncertain.current === plan.body.title) {
              const found = await findRecentDuplicate(plan.body.title);
              if (found.kind === "ambiguous") {
                setStatus({
                  kind: "error",
                  message:
                    "Could not tell whether this post was already created. Check the posts list, then save again.",
                });
                writeLocal();
                return false;
              }
              if (found.kind === "one") {
                out = found.post;
                adopted = true;
              }
            }
            out ??= await api.post<PostOut>("/api/posts", plan.body);
            createUncertain.current = null;
            const sent = snapshot.locales[plan.locale]!;
            const created: LocaleDraft = {
              ...emptyLocaleDraft(),
              title: plan.body.title,
              content: sent.content,
            };
            clearStoredDraft(userIdRef.current, null);
            // A kept copy still on offer stays until the user restores or discards it.
            if (!restoreOfferRef.current) {
              clearStoredDraft(userIdRef.current, null, undefined, "kept");
            }
            idRef.current = out.id;
            etagRef.current = out.updated_at;
            baseRef.current = adopted
              ? draftFromPost(out)
              : {
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
          attemptRef.current = 0;
        } catch (e) {
          if (isApiError(e) && e.status === 412) {
            const current = e.details.current_updated_at;
            setConflict({ currentUpdatedAt: typeof current === "string" ? current : null });
            setStatus({ kind: "conflict" });
            writeLocal();
            return false;
          }
          const transient = !isApiError(e) || e.status === 0 || e.status === 429 || e.status >= 500;
          if (plan.kind === "create" && transient) createUncertain.current = plan.body.title;
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
            setStatus({ kind: "error", message: (e as Error).message });
          }
          writeLocal();
          return false;
        }
      }
      // Still changing faster than we can save: leave it to the next autosave and say so.
      setStatus({ kind: "dirty" });
      scheduleSave(() => void flushAgain());
      writeLocal();
      bump();
      return false;
    },
    [bump, findRecentDuplicate, scheduleSave, setConflict, setPost, syncSlugs, writeLocal],
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
      if (!opts.keepStored) clearStoredDraft(userIdRef.current, out.id);
      setPost(out);
      setDirty(false);
      setConflict(null);
      setStatus({ kind: "idle" });
      setEpoch((n) => n + 1);
      setContentTick((t) => t + 1);
      bump();
      setRestoreOffer(findRestoreOfferRef.current());
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

  useEffect(() => {
    findRestoreOfferRef.current = findRestoreOffer;
  });

  /**
   * Unsaved copies worth offering. A copy is moved to a separate `kept` key the moment it is offered, so
   * nothing the editor does afterwards (autosave, clean-up, new edits) can overwrite or delete it. Only
   * Restore and Discard remove it. A kept copy that already matches the server is dropped.
   *
   * Every copy that differs from the server is offered, even one older than the server version: it is
   * labelled as such and restoring merges it over the server values. When a kept copy and a newer live
   * copy both exist for a language they are merged (the newer copy's edits win), so neither is lost.
   */
  function findRestoreOffer(): RestoreOffer | null {
    const id = idRef.current;
    const user = userIdRef.current;
    const serverTime = postRef.current ? Date.parse(postRef.current.updated_at) : 0;
    const base = baseRef.current;
    const differs = (rec: StoredDraft) => {
      const baseFields = base.locales[rec.locale];
      return (
        (baseFields ? !sameLocaleDraft(baseFields, rec.fields) : hasAnyField(rec.fields)) ||
        !sameShared(base.shared, rec.shared)
      );
    };
    const records: StoredDraft[] = [];
    for (const locale of LOCALES) {
      let kept = readStoredDraft(user, id, locale, "kept");
      if (kept && !differs(kept)) {
        clearStoredDraft(user, id, locale, "kept");
        kept = null;
      }
      const liveRaw = readStoredDraft(user, id, locale);
      const live = liveRaw && differs(liveRaw) ? liveRaw : null;
      if (!kept && !live) continue;
      const record =
        kept && live
          ? kept.savedAt <= live.savedAt
            ? mergeStored(kept, live, base)
            : mergeStored(live, kept, base)
          : (kept ?? live)!;
      if (live) {
        // Write the kept copy first; only then is the live key released.
        writeStoredDraft(user, id, record, "kept");
        clearStoredDraft(user, id, locale);
      }
      records.push(record);
    }
    if (!records.length) return null;
    return { records, stale: records.some((r) => r.savedAt < serverTime), keyId: id };
  }

  /** Pull the stored copy back into the editor (as unsaved changes). */
  const restoreLocal = useCallback(() => {
    if (!restoreOffer) return;
    const records = restoreOffer.records;
    const newest = records.reduce((a, b) => (b.savedAt > a.savedAt ? b : a));
    // The user's own edits win; fields they never touched keep what the editor holds now (the server's values).
    let next = curRef.current;
    for (const rec of records) next = applyStored(rec, next, baseRef.current);
    curRef.current = next;
    localeRef.current = newest.locale;
    setActiveLocaleState(newest.locale);
    setRestoreOffer(null);
    setEpoch((n) => n + 1);
    changed(true, true);
    writeLocal(); // the live copy is back in place before the kept one goes
    for (const rec of records) {
      clearStoredDraft(userIdRef.current, restoreOffer.keyId, rec.locale, "kept");
    }
  }, [changed, restoreOffer, writeLocal]);

  /** Delete the kept copy. The UI asks for confirmation first. */
  const dismissRestore = useCallback(() => {
    const keyId = restoreOfferRef.current ? restoreOfferRef.current.keyId : idRef.current;
    setRestoreOffer(null);
    clearStoredDraft(userIdRef.current, keyId, undefined, "kept");
  }, []);

  useEffect(() => {
    // Read after mount (localStorage does not exist on the server) and once the user is known, because
    // copies are scoped to the signed-in user.
    if (userId) setRestoreOffer(findRestoreOfferRef.current());
  }, [userId]);

  /** The conflict banner's "Load their version": fetch, keep my copy aside, offer to restore it. */
  const loadTheirs = useCallback(async () => {
    const id = idRef.current;
    if (!id) return;
    writeLocal();
    const out = await api.get<PostOut>(`/api/posts/${id}`);
    resetFromPost(out, { keepStored: true });
  }, [resetFromPost, writeLocal]);

  /**
   * The conflict banner's "Overwrite": fetch the current post, take its values for every field I did not
   * touch, keep my edits on top, adopt its `updated_at` and save. A failed fetch leaves the banner up.
   */
  const overwrite = useCallback(async (): Promise<boolean> => {
    const id = idRef.current;
    if (!id) return false;
    let out: PostOut;
    try {
      out = await api.get<PostOut>(`/api/posts/${id}`);
    } catch {
      toast.error("Could not load the current version. Try again.");
      return false;
    }
    const server = draftFromPost(out);
    curRef.current = mergeDrafts(baseRef.current, curRef.current, server);
    baseRef.current = server;
    etagRef.current = out.updated_at;
    setPost(out);
    setConflict(null);
    setEpoch((n) => n + 1);
    setContentTick((t) => t + 1);
    bump();
    return flush();
  }, [bump, flush, setConflict, setPost]);

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
      // Leaving the screen inside the debounce window must not lose the last edits.
      if (t.local) writeLocal();
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
