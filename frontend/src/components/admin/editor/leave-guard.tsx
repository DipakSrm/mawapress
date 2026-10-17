"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** The in-app link a click was about to follow, or null for anything the guard should leave alone. */
export function internalTarget(e: MouseEvent, from: Location): string | null {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
    return null;
  }
  const anchor = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
  if (!anchor || (anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) {
    return null;
  }
  const url = new URL(anchor.href, from.href);
  if (url.origin !== from.origin) return null;
  if (url.pathname === from.pathname && url.search === from.search) return null; // same page or a #hash
  return `${url.pathname}${url.search}${url.hash}`;
}

interface Props {
  /** True while there are changes the server does not have. */
  dirty: boolean;
  /** Save now; resolves true when nothing is left unsaved. */
  flush: () => Promise<boolean>;
  /** A navigation requested from code (not a link click): goes through the same check. */
  request?: string | null;
  onRequestHandled?: () => void;
}

/**
 * Blocks leaving with unsaved changes. A reload or tab close gets the browser's own prompt. A click on an
 * in-app link is held and asks first, because the App Router has no hook to cancel a navigation.
 * (The browser back button is covered by autosave and the local copy, not by a prompt.)
 */
export function LeaveGuard({ dirty, flush, request, onRequestHandled }: Props) {
  const router = useRouter();
  const [target, setTarget] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const dirtyRef = useRef(dirty);

  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  useEffect(() => {
    if (!request) return;
    onRequestHandled?.();
    if (dirtyRef.current) {
      setFailed(false);
      setTarget(request);
    } else {
      router.push(request);
    }
  }, [request, onRequestHandled, router]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const onClick = (e: MouseEvent) => {
      if (!dirtyRef.current) return;
      const next = internalTarget(e, window.location);
      if (!next) return;
      e.preventDefault();
      e.stopPropagation();
      setFailed(false);
      setTarget(next);
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);

  async function saveAndLeave() {
    if (!target) return;
    setSaving(true);
    const ok = await flush();
    setSaving(false);
    if (ok) {
      router.push(target);
      setTarget(null);
    } else {
      setFailed(true);
    }
  }

  if (!target) return null;
  return (
    <Dialog open onOpenChange={(open) => !open && !saving && setTarget(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Leave with unsaved changes?</DialogTitle>
          <DialogDescription>
            {failed
              ? "Saving did not work. A copy is kept in this browser, and you will be offered it the next time you open this post."
              : "Some changes have not reached the server yet. Save them first, or leave and keep a copy in this browser."}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={saving} onClick={() => setTarget(null)}>
            Stay
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={saving}
            onClick={() => {
              router.push(target);
              setTarget(null);
            }}
          >
            Leave anyway
          </Button>
          <Button type="button" disabled={saving} onClick={() => void saveAndLeave()}>
            {saving && <Loader2 aria-hidden className="animate-spin" />}
            Save and leave
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
