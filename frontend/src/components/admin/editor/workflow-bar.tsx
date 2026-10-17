"use client";

import {
  ArrowLeft,
  CalendarClock,
  CalendarX2,
  CircleCheck,
  CornerUpLeft,
  ExternalLink,
  Globe,
  History,
  Loader2,
  Save,
  Send,
  Undo2,
} from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { PostStatusBadge } from "@/components/admin/posts/status-badge";
import { SendBackDialog } from "@/components/admin/posts/send-back-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import type { Locale } from "@/lib/admin/editor/seo";
import type { SaveStatus } from "@/lib/admin/editor/use-post-editor";
import {
  allowedActions,
  publicPath,
  type ActionResult,
  type Category,
  type PostAction,
  type PostOut,
} from "@/lib/admin/posts";
import { cn } from "@/lib/utils";
import { ConfirmActionDialog } from "@/components/admin/posts/confirm-action-dialog";
import { PublishConfirmDialog, type PublishTarget } from "./publish-confirm-dialog";
import { SaveIndicator } from "./save-indicator";

interface Props {
  post: PostOut | null;
  viewer: { id: string; isEditor: boolean };
  /** Language of the open tab, for "Publish translation". */
  locale: Locale;
  /** Titles as the editor shows them (unsaved edits included), for the publish confirmation. */
  targets: PublishTarget[];
  categories: Category[] | undefined;
  status: SaveStatus;
  busy: boolean;
  canEdit: boolean;
  onSave: () => void;
  onRun: (action: PostAction) => Promise<ActionResult>;
  onRevisions: () => void;
  /** Saves before the publish confirmation opens; resolves false when it could not. */
  onPrepare: () => Promise<boolean>;
  onOpenSchedule: () => void;
  /** Extra controls, e.g. "Import from Word" on a new post. */
  extra?: ReactNode;
}

type Dialog = "send-back" | "publish" | "publish-translation" | "unpublish" | null;

export function WorkflowBar({
  post,
  viewer,
  locale,
  targets,
  categories,
  status,
  busy,
  canEdit,
  onSave,
  onRun,
  onRevisions,
  onPrepare,
  onOpenSchedule,
  extra,
}: Props) {
  const [dialog, setDialog] = useState<Dialog>(null);
  const can = post ? allowedActions(post, viewer) : null;
  const translation = post?.translations.find((t) => t.locale === locale);
  const canPublishTranslation =
    Boolean(post && viewer.isEditor && post.status === "published") &&
    translation?.status === "draft";
  const live = post && post.status === "published" ? publicPath(post, categories) : null;
  const run = (action: PostAction) => void onRun(action);
  const open = async (which: "publish" | "publish-translation") => {
    if (await onPrepare()) setDialog(which);
  };
  const spinner = busy && <Loader2 aria-hidden className="animate-spin" />;

  return (
    <div
      role="toolbar"
      aria-label="Post actions"
      className="sticky top-14 z-10 -mx-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-background/90 px-4 py-2 backdrop-blur supports-backdrop-filter:bg-background/75 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
    >
      <Link
        href="/admin/posts"
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2")}
      >
        <ArrowLeft aria-hidden /> Posts
      </Link>
      {post ? (
        <PostStatusBadge post={post} />
      ) : (
        <span className="text-sm font-medium text-muted-foreground">New post</span>
      )}
      <SaveIndicator status={status} />

      <div className="ml-auto flex flex-wrap items-center gap-2">
        {extra}
        {post && (
          <Button type="button" variant="ghost" size="sm" onClick={onRevisions}>
            <History aria-hidden /> Revisions
          </Button>
        )}
        {live && (
          <Link
            href={live}
            target="_blank"
            rel="noopener"
            className={buttonVariants({ variant: "ghost", size: "sm" })}
          >
            <ExternalLink aria-hidden /> View live
          </Link>
        )}
        {canEdit && (
          <Button type="button" variant="outline" size="sm" onClick={onSave} disabled={busy}>
            <Save aria-hidden /> Save
          </Button>
        )}
        {can?.submit && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => run({ type: "submit" })}
          >
            {spinner || <Send aria-hidden />} Submit for review
          </Button>
        )}
        {can?.sendBack && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => setDialog("send-back")}
          >
            <CornerUpLeft aria-hidden /> Send back
          </Button>
        )}
        {can?.unschedule && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => run({ type: "unschedule" })}
          >
            <CalendarX2 aria-hidden /> Unschedule
          </Button>
        )}
        {can?.schedule && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={onOpenSchedule}
          >
            <CalendarClock aria-hidden /> {post?.status === "scheduled" ? "Reschedule" : "Schedule"}
          </Button>
        )}
        {can?.unpublish && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => setDialog("unpublish")}
          >
            <Globe aria-hidden /> Unpublish
          </Button>
        )}
        {can?.unarchive && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => run({ type: "unarchive" })}
          >
            <Undo2 aria-hidden /> Unarchive
          </Button>
        )}
        {canPublishTranslation && (
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => void open("publish-translation")}
          >
            <CircleCheck aria-hidden /> Publish translation
          </Button>
        )}
        {can?.publish && (
          <Button type="button" size="sm" disabled={busy} onClick={() => void open("publish")}>
            {spinner || <CircleCheck aria-hidden />} Publish
          </Button>
        )}
      </div>

      {dialog === "send-back" && (
        <SendBackDialog
          onClose={() => setDialog(null)}
          onSendBack={(note) => onRun({ type: "send-back", note: note || undefined })}
        />
      )}
      {dialog === "unpublish" && (
        <ConfirmActionDialog
          title="Unpublish this post?"
          description="Every language leaves the public site now and the post moves to the archive. Unarchive brings it back."
          confirmLabel="Unpublish"
          destructive
          onClose={() => setDialog(null)}
          onConfirm={() => onRun({ type: "unpublish" })}
        />
      )}
      {dialog === "publish" && (
        <PublishConfirmDialog
          targets={targets}
          onClose={() => setDialog(null)}
          onConfirm={() => onRun({ type: "publish" })}
        />
      )}
      {dialog === "publish-translation" && (
        <PublishConfirmDialog
          targets={targets.filter((t) => t.locale === locale)}
          single
          onClose={() => setDialog(null)}
          onConfirm={() => onRun({ type: "publish-translation", locale })}
        />
      )}
    </div>
  );
}
