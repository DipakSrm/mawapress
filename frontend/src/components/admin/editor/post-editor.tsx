"use client";

import { useQueryClient } from "@tanstack/react-query";
import type { Editor, JSONContent } from "@tiptap/react";
import { AlertTriangle, CalendarClock, FileUp, Languages, Loader2 } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { ScheduleDialog } from "@/components/admin/posts/schedule-dialog";
import { RichEditor } from "@/components/editor/RichEditor";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { docStats, sameJson } from "@/lib/admin/editor/doc";
import { LOCALES } from "@/lib/admin/editor/draft";
import { checkReadability } from "@/lib/admin/editor/readability";
import { buildSeoPreview, EXCERPT_MAX, fromSeoAuto, type Locale } from "@/lib/admin/editor/seo";
import { usePostEditor } from "@/lib/admin/editor/use-post-editor";
import { formatDateTime } from "@/lib/admin/post-display";
import {
  allowedActions,
  useCategories,
  usePostActions,
  type ActionResult,
  type PostAction,
  type PostOut,
} from "@/lib/admin/posts";
import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { FeaturedImageField, type MediaPickRequest } from "./featured-image-field";
import { ImportDocxDialog } from "./import-docx-dialog";
import { LanguageTabs, PANEL_ID, type TabState } from "./language-tabs";
import { LeaveGuard } from "./leave-guard";
import type { PublishTarget } from "./publish-confirm-dialog";
import { ReadabilityCard } from "./readability-card";
import { RevisionsDrawer } from "./revisions-drawer";
import { SeoPanel } from "./seo-panel";
import { TagPicker } from "./tag-picker";
import { WorkflowBar } from "./workflow-bar";

const NAME: Record<Locale, string> = { ne: "Nepali", en: "English" };
const TITLE_PLACEHOLDER: Record<Locale, string> = { ne: "शीर्षक", en: "Headline" };

const Body = memo(RichEditor);

function Section({ title, children, id }: { title: string; children: ReactNode; id: string }) {
  return (
    <section
      aria-labelledby={id}
      className="space-y-3 rounded-xl bg-card p-4 text-card-foreground ring-1 ring-foreground/10"
    >
      <h2 id={id} className="text-sm font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Banner({
  tone = "warn",
  title,
  children,
  actions,
}: {
  tone?: "warn" | "info";
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div
      role={tone === "warn" ? "alert" : "status"}
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-sm",
        tone === "warn" ? "border-amber-500/40 bg-amber-500/10" : "border-sky-500/30 bg-sky-500/10",
      )}
    >
      <AlertTriangle aria-hidden className="size-4 shrink-0 text-amber-600" />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        {children && <p className="text-muted-foreground">{children}</p>}
      </div>
      <div className="flex gap-2">{actions}</div>
    </div>
  );
}

function absolute(url: string | null | undefined, origin: string): string | null {
  if (!url) return null;
  return url.startsWith("/") ? `${origin}${url}` : url;
}

export interface PostEditorProps {
  /** The post to edit, or null for a new one (created on the first save). */
  initial: PostOut | null;
  /** Task 6 passes the media library picker here; until then the field shows a placeholder. */
  onRequestMedia?: MediaPickRequest;
}

/** The writing screen: language tabs, title and body, the side panels, autosave and the workflow bar. */
export function PostEditor({ initial, onRequestMedia }: PostEditorProps) {
  const queryClient = useQueryClient();
  const { user, hasRole } = useSession();
  const isEditor = hasRole("editor");
  const viewer = useMemo(() => ({ id: user?.id ?? "", isEditor }), [user?.id, isEditor]);
  const categories = useCategories();
  const actions = usePostActions();
  const editorRef = useRef<Editor | null>(null);
  const [origin, setOrigin] = useState("");
  const [revisionsOpen, setRevisionsOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const initialLocale: Locale = initial
    ? initial.translations.some((t) => t.locale === "ne")
      ? "ne"
      : ((initial.translations[0]?.locale as Locale | undefined) ?? "ne")
    : "ne";

  const ed = usePostEditor({
    initial,
    initialLocale,
    canBreak: isEditor,
    userId: user?.id,
    // The App Router syncs a direct replaceState, so the page keeps its state (and the caret).
    onCreated: (out) => window.history.replaceState(null, "", `/admin/posts/${out.id}`),
  });
  const { post, draft, activeLocale: locale } = ed;
  const local = draft.locales[locale];
  const canEdit = !post || isEditor || (post.author_id === viewer.id && post.status === "draft");
  const serverTr = post?.translations.find((t) => t.locale === locale);

  useEffect(() => setOrigin(window.location.origin), []);

  // Keep the posts list fresh after each save.
  const savedAt = ed.status.kind === "saved" ? ed.status.at : null;
  useEffect(() => {
    if (savedAt) void queryClient.invalidateQueries({ queryKey: ["posts"] });
  }, [savedAt, queryClient]);

  // On load the editor re-emits the document with its defaults filled in (null attributes). That is not an
  // edit: ignore emissions equal to what we hold until the first real change.
  const touched = useRef(false);
  useEffect(() => {
    touched.current = false;
  }, [locale, ed.epoch]);
  const { setContent, getDraft } = ed;
  const onBody = useCallback(
    (json: JSONContent) => {
      if (!touched.current) {
        if (sameJson(json, getDraft().locales[locale]?.content)) return;
        touched.current = true;
      }
      setContent(locale, json);
    },
    [setContent, getDraft, locale],
  );
  const onEditorReady = useCallback((e: Editor) => {
    editorRef.current = e;
  }, []);

  // ---- derived panels (recomputed after a pause in typing, not on every key) ----------------

  const stats = useMemo(() => docStats(local?.content), [local?.content]);
  const readability = useMemo(
    () =>
      checkReadability({
        title: local?.title ?? "",
        stats,
        hasFeaturedImage: Boolean(draft.shared.featuredMedia),
      }),
    [local?.title, stats, draft.shared.featuredMedia],
  );
  const category = categories.data?.find((c) => c.id === draft.shared.categoryId);
  const saved = useMemo(() => ed.isLocaleSaved(locale), [ed, locale]);
  const seo = useMemo(() => {
    const auto = saved ? fromSeoAuto(serverTr?.seo_auto) : null;
    if (auto) return { preview: auto, fromServer: true };
    const media = draft.shared.featuredMedia;
    return {
      fromServer: false,
      preview: buildSeoPreview({
        locale,
        title: local?.title ?? "",
        bodyText: stats.text,
        seoTitle: local?.seoTitle,
        seoDescription: local?.seoDescription,
        slug: local?.slug,
        categorySlug: category?.slug,
        origin,
        imageUrl: absolute(media?.variants.og ?? media?.url, origin),
      }),
    };
  }, [
    saved,
    serverTr?.seo_auto,
    draft.shared.featuredMedia,
    locale,
    local,
    stats.text,
    category?.slug,
    origin,
  ]);

  const tabStates = Object.fromEntries(
    LOCALES.map((l): [Locale, TabState] => {
      const tr = post?.translations.find((t) => t.locale === l);
      return [l, tr ? tr.status : draft.locales[l] ? "draft" : "missing"];
    }),
  ) as Record<Locale, TabState>;

  // What the publish confirmation lists: the server's translations, read after the flush that precedes it.
  const targets: PublishTarget[] = LOCALES.flatMap((l) => {
    const tr = post?.translations.find((t) => t.locale === l);
    return tr ? [{ locale: l, title: tr.title, live: tr.status === "published" }] : [];
  });

  // ---- workflow -----------------------------------------------------------------------------

  // Covers the flush before an action as well as the request, so a double click cannot run two actions.
  const acting = useRef(false);
  const [actingNow, setActingNow] = useState(false);

  async function runAction(action: PostAction): Promise<ActionResult> {
    if (!post) throw new Error("Save the post before changing its state");
    if (acting.current) {
      return {
        ok: false,
        error: new ApiError(0, "ACTION_IN_PROGRESS", "Another action is running"),
      };
    }
    acting.current = true;
    setActingNow(true);
    try {
      if (!(await ed.flush())) {
        toast.error("Your latest changes could not be saved. Fix that, then try again.");
        return { ok: false, error: new ApiError(0, "NOT_SAVED", "Unsaved changes") };
      }
      const result = await actions.run(
        { id: post.id, updated_at: ed.getUpdatedAt() ?? post.updated_at },
        action,
      );
      if (result.ok) ed.acceptPost(result.post);
      else if (result.error.status === 412) {
        const current = result.error.details.current_updated_at;
        ed.reportConflict(typeof current === "string" ? current : null);
      }
      return result;
    } finally {
      acting.current = false;
      setActingNow(false);
    }
  }

  /** Before the publish confirmation: save, so the dialog lists what the server really holds. */
  async function prepareToPublish(): Promise<boolean> {
    const ok = await ed.flush();
    if (!ok) toast.error("Your latest changes could not be saved. Fix that, then try again.");
    return ok;
  }

  const [discardOpen, setDiscardOpen] = useState(false);
  const [leaveTo, setLeaveTo] = useState<string | null>(null);

  async function reload(action: () => Promise<unknown>) {
    setRestoring(true);
    try {
      await action();
    } catch {
      toast.error("Could not load their version. Try again.");
    } finally {
      setRestoring(false);
    }
  }

  const can = post ? allowedActions(post, viewer) : null;

  return (
    <div
      className="space-y-4"
      onBlur={(e) => {
        // Leaving the editing area (not just moving between its controls) saves.
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) void ed.flush();
      }}
    >
      <WorkflowBar
        post={post}
        viewer={viewer}
        locale={locale}
        targets={targets}
        categories={categories.data}
        status={ed.status}
        busy={actions.pendingId !== null || actingNow}
        onPrepare={prepareToPublish}
        canEdit={canEdit}
        onSave={() => void ed.flush()}
        onRun={runAction}
        onRevisions={() => setRevisionsOpen(true)}
        onOpenSchedule={() => setScheduleOpen(true)}
        extra={
          !post && (
            <Button type="button" variant="outline" size="sm" onClick={() => setImportOpen(true)}>
              <FileUp aria-hidden /> Import from Word
            </Button>
          )
        }
      />

      {ed.conflict && (
        <Banner
          title="Someone else edited this post"
          actions={
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={restoring}
                onClick={() => void reload(ed.loadTheirs)}
              >
                {restoring && <Loader2 aria-hidden className="animate-spin" />}
                Load their version
              </Button>
              <Button size="sm" disabled={restoring} onClick={() => void reload(ed.overwrite)}>
                Overwrite
              </Button>
            </>
          }
        >
          Loading theirs keeps a copy of your changes in this browser. Overwriting saves your
          changes over theirs.
        </Banner>
      )}
      {ed.restoreOffer && !ed.conflict && (
        <Banner
          tone="info"
          title="Unsaved changes found"
          actions={
            <>
              <Button size="sm" onClick={ed.restoreLocal}>
                Restore unsaved changes
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDiscardOpen(true)}>
                Discard
              </Button>
            </>
          }
        >
          This browser has edits from{" "}
          {formatDateTime(
            new Date(Math.max(...ed.restoreOffer.records.map((r) => r.savedAt))).toISOString(),
          )}{" "}
          that never reached the server.
        </Banner>
      )}
      {!canEdit && (
        <Banner tone="info" title="Read only">
          {post?.status === "draft"
            ? "Only the author or an editor can change this draft."
            : "Reporters can edit their own drafts. Ask an editor to change this post."}
        </Banner>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="min-w-0 space-y-4">
          <LanguageTabs active={locale} onChange={ed.setActiveLocale} states={tabStates} />
          <div
            role="tabpanel"
            id={PANEL_ID}
            aria-labelledby={`editor-tab-${locale}`}
            className="space-y-4"
          >
            {local ? (
              <>
                <input
                  aria-label="Title"
                  lang={locale}
                  value={local.title}
                  maxLength={300}
                  readOnly={!canEdit}
                  autoFocus={!post}
                  placeholder={TITLE_PLACEHOLDER[locale]}
                  onChange={(e) => ed.updateLocale(locale, { title: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      editorRef.current?.commands.focus("start");
                    }
                  }}
                  className="w-full rounded-lg bg-transparent px-1 py-2 text-3xl leading-tight font-semibold tracking-tight outline-none placeholder:text-muted-foreground/60 focus-visible:ring-3 focus-visible:ring-ring/40 sm:text-4xl"
                />
                <Body
                  key={`${locale}-${ed.epoch}`}
                  value={local.content}
                  onChange={onBody}
                  locale={locale}
                  readOnly={!canEdit}
                  onEditorReady={onEditorReady}
                  aria-label={`${NAME[locale]} article body`}
                />
              </>
            ) : (
              <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-16 text-center">
                <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
                  <Languages aria-hidden className="size-6" />
                </span>
                <p className="font-medium">There is no {NAME[locale]} version yet</p>
                <p className="max-w-sm text-sm text-muted-foreground">
                  It is saved as its own draft, with its own title, address and SEO. The other
                  language is not affected.
                </p>
                {canEdit && (
                  <Button type="button" onClick={() => ed.addLocale(locale)}>
                    Add {NAME[locale]} version
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>

        <aside aria-label="Post settings" className="min-w-0 space-y-4">
          <Section id="sec-organise" title="Organise">
            <div className="space-y-1.5">
              <Label htmlFor="post-category">Category</Label>
              <NativeSelect
                id="post-category"
                value={draft.shared.categoryId ?? ""}
                disabled={!canEdit}
                onChange={(e) =>
                  ed.updateShared({ categoryId: e.target.value ? Number(e.target.value) : null })
                }
              >
                <option value="">Choose a category…</option>
                {categories.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {locale === "ne" ? c.name_ne : c.name_en}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="post-tags">Tags</Label>
              <TagPicker
                id="post-tags"
                value={draft.shared.tags}
                onChange={(tags) => ed.updateShared({ tags })}
                locale={locale}
                canCreate={isEditor}
                disabled={!canEdit}
              />
            </div>
          </Section>

          <Section id="sec-image" title="Featured image">
            <FeaturedImageField
              media={draft.shared.featuredMedia}
              onChange={(featuredMedia) => ed.updateShared({ featuredMedia })}
              onRequestPick={onRequestMedia}
              disabled={!canEdit}
            />
          </Section>

          <Section id="sec-excerpt" title={`Excerpt (${NAME[locale]})`}>
            <div className="space-y-1.5">
              <Label htmlFor="post-excerpt" className="sr-only">
                Excerpt
              </Label>
              <Textarea
                id="post-excerpt"
                lang={locale}
                rows={3}
                maxLength={EXCERPT_MAX}
                value={local?.excerpt ?? ""}
                disabled={!canEdit || !local}
                placeholder="Optional short summary for cards and feeds"
                onChange={(e) => ed.updateLocale(locale, { excerpt: e.target.value })}
              />
              <p className="text-right text-xs text-muted-foreground tabular-nums">
                {(local?.excerpt ?? "").length}/{EXCERPT_MAX}
              </p>
            </div>
          </Section>

          <Section id="sec-publishing" title="Publishing">
            {isEditor && (
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="post-breaking" className="flex-col items-start gap-1">
                  Breaking news
                  <span className="text-xs font-normal text-muted-foreground">
                    Pinned to the breaking strip on the site.
                  </span>
                </Label>
                <Switch
                  id="post-breaking"
                  checked={draft.shared.isBreaking}
                  disabled={!canEdit}
                  onCheckedChange={(isBreaking) => ed.updateShared({ isBreaking })}
                />
              </div>
            )}
            <div className="space-y-1.5">
              <p className="text-sm font-medium">Schedule</p>
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <CalendarClock aria-hidden className="size-4" />
                {post?.scheduled_at ? formatDateTime(post.scheduled_at) : "Not scheduled"}
              </p>
              {can?.schedule && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setScheduleOpen(true)}
                >
                  {post?.status === "scheduled" ? "Reschedule…" : "Schedule…"}
                </Button>
              )}
              {post?.schedule_last_error && (
                <p role="alert" className="text-xs text-destructive">
                  The last attempt failed: {post.schedule_last_error}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="post-template">Template</Label>
              <NativeSelect id="post-template" disabled value="">
                <option value="">Default for the category</option>
              </NativeSelect>
              <p className="text-xs text-muted-foreground">Coming in Appearance.</p>
            </div>
          </Section>

          <Section id="sec-seo" title="Search and social">
            <SeoPanel
              locale={locale}
              preview={seo.preview}
              fromServer={seo.fromServer}
              seoTitle={local?.seoTitle ?? ""}
              seoDescription={local?.seoDescription ?? ""}
              slug={local?.slug ?? ""}
              slugState={
                !serverTr ? "new" : serverTr.status === "published" ? "published" : "draft"
              }
              canEditSlug={isEditor}
              disabled={!canEdit || !local}
              onChange={(patch) =>
                ed.updateLocale(locale, {
                  ...(patch.seoTitle !== undefined && { seoTitle: patch.seoTitle }),
                  ...(patch.seoDescription !== undefined && {
                    seoDescription: patch.seoDescription,
                  }),
                  ...(patch.slug !== undefined && { slug: patch.slug }),
                })
              }
            />
          </Section>

          <Section id="sec-readability" title="Readability">
            <ReadabilityCard items={readability} />
          </Section>
        </aside>
      </div>

      {scheduleOpen && post && (
        <ScheduleDialog
          post={post}
          onClose={() => setScheduleOpen(false)}
          onSchedule={(scheduledAt) => runAction({ type: "schedule", scheduledAt })}
        />
      )}
      {importOpen && (
        <ImportDocxDialog
          onClose={() => setImportOpen(false)}
          defaultLocale={locale}
          onOpen={(path) => {
            setImportOpen(false);
            setLeaveTo(path); // the leave guard decides: straight through when saved, a prompt when not
          }}
        />
      )}
      {revisionsOpen && post && (
        <RevisionsDrawer
          postId={post.id}
          locale={locale}
          viewerId={viewer.id}
          canRestore={isEditor}
          prepare={ed.flush}
          getUpdatedAt={ed.getUpdatedAt}
          onRestored={ed.resetFromPost}
          onConflict={ed.reportConflict}
          onClose={() => setRevisionsOpen(false)}
        />
      )}
      <LeaveGuard
        dirty={ed.dirty}
        flush={ed.flush}
        request={leaveTo}
        onRequestHandled={() => setLeaveTo(null)}
      />
      {discardOpen && (
        <Dialog open onOpenChange={(open) => !open && setDiscardOpen(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Discard the unsaved copy?</DialogTitle>
              <DialogDescription>
                The edits kept in this browser are deleted for good. They cannot be recovered.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDiscardOpen(false)}>
                Keep it
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => {
                  ed.dismissRestore();
                  setDiscardOpen(false);
                }}
              >
                Discard
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
