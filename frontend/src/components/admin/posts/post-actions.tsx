"use client";

import {
  CalendarClock,
  CalendarX2,
  CircleCheck,
  CornerUpLeft,
  Globe,
  Link2,
  Loader2,
  MoreHorizontal,
  Pencil,
  Send,
  Undo2,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  allowedActions,
  publicPath,
  type ActionResult,
  type Category,
  type PostAction,
  type PostSummary,
} from "@/lib/admin/posts";
import { SendBackDialog } from "./send-back-dialog";
import { ScheduleDialog } from "./schedule-dialog";

interface Props {
  post: PostSummary;
  title: string;
  viewer: { id: string; isEditor: boolean };
  categories: Category[] | undefined;
  busy: boolean;
  onRun: (post: PostSummary, action: PostAction) => Promise<ActionResult>;
}

async function copyPublicLink(path: string) {
  const url = new URL(path, window.location.origin).toString();
  try {
    await navigator.clipboard.writeText(url);
    toast.success("Link copied");
  } catch {
    toast.error("Could not copy the link");
  }
}

export function PostActions({ post, title, viewer, categories, busy, onRun }: Props) {
  const [dialog, setDialog] = useState<"schedule" | "send-back" | null>(null);
  const can = allowedActions(post, viewer);
  const link = can.copyLink ? publicPath(post, categories) : null;
  const run = (action: PostAction) => void onRun(post, action);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button variant="ghost" size="icon-sm" disabled={busy} />}
          aria-label={`Actions for ${title}`}
        >
          {busy ? <Loader2 aria-hidden className="animate-spin" /> : <MoreHorizontal aria-hidden />}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem render={<Link href={`/admin/posts/${post.id}`} />}>
            <Pencil aria-hidden /> Edit
          </DropdownMenuItem>
          {(can.submit ||
            can.sendBack ||
            can.publish ||
            can.schedule ||
            can.unschedule ||
            can.unpublish ||
            can.unarchive ||
            link) && <DropdownMenuSeparator />}
          {can.submit && (
            <DropdownMenuItem onClick={() => run({ type: "submit" })}>
              <Send aria-hidden /> Submit for review
            </DropdownMenuItem>
          )}
          {can.sendBack && (
            <DropdownMenuItem onClick={() => setDialog("send-back")}>
              <CornerUpLeft aria-hidden /> Send back…
            </DropdownMenuItem>
          )}
          {can.publish && (
            <DropdownMenuItem onClick={() => run({ type: "publish" })}>
              <CircleCheck aria-hidden /> Publish now
            </DropdownMenuItem>
          )}
          {can.schedule && (
            <DropdownMenuItem onClick={() => setDialog("schedule")}>
              <CalendarClock aria-hidden />{" "}
              {post.status === "scheduled" ? "Reschedule…" : "Schedule…"}
            </DropdownMenuItem>
          )}
          {can.unschedule && (
            <DropdownMenuItem onClick={() => run({ type: "unschedule" })}>
              <CalendarX2 aria-hidden /> Unschedule
            </DropdownMenuItem>
          )}
          {can.unpublish && (
            <DropdownMenuItem onClick={() => run({ type: "unpublish" })}>
              <Globe aria-hidden /> Unpublish
            </DropdownMenuItem>
          )}
          {can.unarchive && (
            <DropdownMenuItem onClick={() => run({ type: "unarchive" })}>
              <Undo2 aria-hidden /> Unarchive
            </DropdownMenuItem>
          )}
          {link && (
            <DropdownMenuItem onClick={() => void copyPublicLink(link)}>
              <Link2 aria-hidden /> Copy public link
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {dialog === "send-back" && (
        <SendBackDialog
          onClose={() => setDialog(null)}
          onSendBack={(note) => onRun(post, { type: "send-back", note: note || undefined })}
        />
      )}
      {dialog === "schedule" && (
        <ScheduleDialog
          post={post}
          onClose={() => setDialog(null)}
          onSchedule={(scheduledAt) => onRun(post, { type: "schedule", scheduledAt })}
        />
      )}
    </>
  );
}
