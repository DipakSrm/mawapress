"use client";

import { Plus } from "lucide-react";
import { useRef, type KeyboardEvent } from "react";
import { Badge } from "@/components/ui/badge";
import type { Locale } from "@/lib/admin/editor/seo";
import { cn } from "@/lib/utils";

export type TabState = "draft" | "published" | "missing";

const LOCALES: { locale: Locale; short: string; name: string; lang: string }[] = [
  { locale: "ne", short: "ने", name: "Nepali", lang: "ne" },
  { locale: "en", short: "EN", name: "English", lang: "en" },
];

export const PANEL_ID = "editor-language-panel";

interface Props {
  active: Locale;
  onChange: (locale: Locale) => void;
  states: Record<Locale, TabState>;
}

/** ने / EN switch. A language with no translation yet is marked "Not added"; opening it offers to add it. */
export function LanguageTabs({ active, onChange, states }: Props) {
  const refs = useRef<Partial<Record<Locale, HTMLButtonElement | null>>>({});

  function onKeyDown(e: KeyboardEvent, index: number) {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = LOCALES[(index + delta + LOCALES.length) % LOCALES.length];
    onChange(next.locale);
    refs.current[next.locale]?.focus();
  }

  return (
    <div role="tablist" aria-label="Language" className="flex gap-1 border-b">
      {LOCALES.map((l, i) => {
        const selected = l.locale === active;
        const state = states[l.locale];
        return (
          <button
            key={l.locale}
            ref={(el) => {
              refs.current[l.locale] = el;
            }}
            type="button"
            role="tab"
            id={`editor-tab-${l.locale}`}
            aria-selected={selected}
            aria-controls={PANEL_ID}
            aria-label={`${l.name}${state === "missing" ? ", not added" : `, ${state}`}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(l.locale)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              "-mb-px flex items-center gap-2 rounded-t-md border-b-2 px-3 py-2 text-sm font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              selected
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <span lang={l.lang} aria-hidden className="text-base">
              {l.short}
            </span>
            {state === "missing" ? (
              <Badge variant="outline" className="gap-1 text-muted-foreground" aria-hidden>
                <Plus className="size-3" /> Not added
              </Badge>
            ) : (
              <Badge
                aria-hidden
                variant={state === "published" ? "default" : "secondary"}
                className={cn(
                  state === "published" &&
                    "border-transparent bg-emerald-600 text-white dark:bg-emerald-500/20 dark:text-emerald-400",
                )}
              >
                {state === "published" ? "Published" : "Draft"}
              </Badge>
            )}
          </button>
        );
      })}
    </div>
  );
}
