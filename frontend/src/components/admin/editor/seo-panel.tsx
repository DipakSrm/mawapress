"use client";

import { ChevronDown, ImageIcon, Lock } from "lucide-react";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  SEO_DESCRIPTION_MAX,
  SEO_TITLE_MAX,
  SLUG_PATTERN,
  type Locale,
  type SeoPreview,
} from "@/lib/admin/editor/seo";
import { cn } from "@/lib/utils";

export type SlugState = "new" | "draft" | "published";

interface Props {
  locale: Locale;
  preview: SeoPreview;
  /** True when the preview is the API's `seo_auto`, false when it is computed here from unsaved edits. */
  fromServer: boolean;
  seoTitle: string;
  seoDescription: string;
  slug: string;
  slugState: SlugState;
  canEditSlug: boolean;
  disabled?: boolean;
  onChange: (patch: { seoTitle?: string; seoDescription?: string; slug?: string }) => void;
}

function Counter({ value, max }: { value: number; max: number }) {
  return (
    <span
      className={cn(
        "text-xs text-muted-foreground tabular-nums",
        value > max && "text-destructive",
      )}
    >
      {value}/{max}
    </span>
  );
}

function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

function breadcrumb(url: string): string {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname.replace(/\/$/, "").split("/").join(" › ")}`;
  } catch {
    return url;
  }
}

export function SeoPanel({
  locale,
  preview,
  fromServer,
  seoTitle,
  seoDescription,
  slug,
  slugState,
  canEditSlug,
  disabled,
  onChange,
}: Props) {
  const [editing, setEditing] = useState(false);
  const slugEditable = slugState === "published" && canEditSlug && !disabled;
  const slugInvalid = slugEditable && slug !== "" && !SLUG_PATTERN.test(slug);
  const slugReason =
    slugState === "new"
      ? "The address is made from the title when this version is first saved."
      : slugState === "draft"
        ? "The address follows the title until this version is published. After that you can edit it here."
        : !canEditSlug
          ? "Only editors can change the address of a published article."
          : "Changing the address of a live article adds a redirect from the old one.";

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        {fromServer ? "As generated after the last save." : "Preview of your unsaved edits."}
      </p>

      <section aria-label="Google result preview" className="space-y-1">
        <h3 className="text-xs font-medium text-muted-foreground">Google</h3>
        <div className="rounded-lg border bg-background p-3" lang={locale}>
          <p className="truncate text-xs text-muted-foreground">{breadcrumb(preview.url)}</p>
          <p
            data-testid="serp-title"
            className="mt-0.5 text-base leading-snug text-[#1a0dab] dark:text-[#8ab4f8]"
          >
            {preview.title}
          </p>
          <p data-testid="serp-description" className="mt-0.5 text-sm text-muted-foreground">
            {preview.description}
          </p>
        </div>
        <p className="text-right text-xs text-muted-foreground tabular-nums">
          Title {preview.title.length} characters
        </p>
      </section>

      <section aria-label="Facebook card preview" className="space-y-1">
        <h3 className="text-xs font-medium text-muted-foreground">Facebook</h3>
        <div className="overflow-hidden rounded-lg border bg-background" lang={locale}>
          {preview.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview.image} alt="" className="aspect-[1200/630] w-full object-cover" />
          ) : (
            <div className="flex aspect-[1200/630] w-full items-center justify-center bg-muted text-muted-foreground">
              <ImageIcon aria-hidden className="size-6" />
            </div>
          )}
          <div className="space-y-0.5 border-t bg-muted/40 p-2.5">
            <p className="text-[11px] tracking-wide text-muted-foreground uppercase">
              {host(preview.url)}
            </p>
            <p className="line-clamp-2 text-sm font-semibold">{preview.title}</p>
            <p className="line-clamp-2 text-xs text-muted-foreground">{preview.description}</p>
          </div>
        </div>
      </section>

      <button
        type="button"
        aria-expanded={editing}
        aria-controls="seo-fields"
        onClick={() => setEditing((v) => !v)}
        className="flex w-full items-center justify-between rounded-lg border px-3 py-2 text-sm font-medium outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        Edit SEO
        <ChevronDown
          aria-hidden
          className={cn("size-4 transition-transform", editing && "rotate-180")}
        />
      </button>

      {editing && (
        <div id="seo-fields" className="space-y-4">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="seo-title">SEO title</Label>
              <Counter value={seoTitle.length} max={SEO_TITLE_MAX} />
            </div>
            <Input
              id="seo-title"
              lang={locale}
              value={seoTitle}
              maxLength={SEO_TITLE_MAX}
              disabled={disabled}
              placeholder="Leave empty to use the title"
              onChange={(e) => onChange({ seoTitle: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="seo-description">SEO description</Label>
              <Counter value={seoDescription.length} max={SEO_DESCRIPTION_MAX} />
            </div>
            <Textarea
              id="seo-description"
              lang={locale}
              rows={3}
              value={seoDescription}
              maxLength={SEO_DESCRIPTION_MAX}
              disabled={disabled}
              placeholder="Leave empty to use the start of the article"
              onChange={(e) => onChange({ seoDescription: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="seo-slug">
              Slug {!slugEditable && <Lock aria-hidden className="size-3 text-muted-foreground" />}
            </Label>
            <Input
              id="seo-slug"
              value={slug}
              disabled={!slugEditable}
              aria-invalid={slugInvalid || undefined}
              aria-describedby="seo-slug-help"
              placeholder="Created on first save"
              onChange={(e) => onChange({ slug: e.target.value })}
            />
            <p
              id="seo-slug-help"
              className={cn("text-xs text-muted-foreground", slugInvalid && "text-destructive")}
            >
              {slugInvalid
                ? "Use lowercase letters, numbers and single hyphens, up to 80 characters."
                : slugReason}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
