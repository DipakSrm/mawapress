"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X } from "lucide-react";
import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import type { TagOut } from "@/lib/admin/editor/draft";
import type { Locale } from "@/lib/admin/editor/seo";
import { api, isApiError } from "@/lib/api";

const MAX_TAGS = 20;

const tagName = (tag: TagOut, locale: Locale) =>
  (locale === "ne" ? tag.name_ne : tag.name_en) || tag.name_en || tag.name_ne;

interface Props {
  value: TagOut[];
  onChange: (tags: TagOut[]) => void;
  /** Language of the open tab: tags are shown in it. */
  locale: Locale;
  /** Editors can create tags on the fly; reporters pick from the existing ones. */
  canCreate: boolean;
  disabled?: boolean;
  id?: string;
}

/** Multi-select of tags with search, and "Create" for editors. */
export function TagPicker({ value, onChange, locale, canCreate, disabled, id }: Props) {
  const queryClient = useQueryClient();
  const listId = useId();
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setQuery(input.trim()), 200);
    return () => clearTimeout(t);
  }, [input]);

  const results = useQuery({
    queryKey: ["tags", query],
    queryFn: () => api.get<TagOut[]>("/api/tags", { query: { q: query || undefined } }),
    enabled: open,
    staleTime: 30_000,
  });

  const chosen = new Set(value.map((t) => t.id));
  const options = (results.data ?? []).filter((t) => !chosen.has(t.id)).slice(0, 8);
  const typed = input.trim();
  const exists = (results.data ?? []).some(
    (t) =>
      t.name_en.toLowerCase() === typed.toLowerCase() ||
      t.name_ne.toLowerCase() === typed.toLowerCase(),
  );
  const canAdd = canCreate && typed.length > 0 && !exists;
  const total = options.length + (canAdd ? 1 : 0);
  const full = value.length >= MAX_TAGS;

  function add(tag: TagOut) {
    if (full || chosen.has(tag.id)) return;
    onChange([...value, tag]);
    setInput("");
    setActive(0);
  }

  async function create() {
    if (!canAdd || creating || full) return;
    setCreating(true);
    try {
      const tag = await api.post<TagOut>("/api/tags", { name_ne: typed, name_en: typed });
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
      add(tag);
    } catch (e) {
      toast.error(isApiError(e) ? e.message : "Could not create the tag");
    } finally {
      setCreating(false);
    }
  }

  function choose(index: number) {
    if (index < options.length) add(options[index]);
    else void create();
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && total) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % total);
    } else if (e.key === "ArrowUp" && total) {
      e.preventDefault();
      setActive((i) => (i - 1 + total) % total);
    } else if (e.key === "Enter") {
      if (open && total) {
        e.preventDefault();
        choose(Math.min(active, total - 1));
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    } else if (e.key === "Backspace" && !input && value.length) {
      onChange(value.slice(0, -1));
    }
  }

  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Selected tags">
          {value.map((tag) => (
            <li
              key={tag.id}
              className="inline-flex items-center gap-1 rounded-full bg-secondary py-0.5 pr-1 pl-2.5 text-xs font-medium"
            >
              <span lang={locale}>{tagName(tag, locale)}</span>
              <button
                type="button"
                disabled={disabled}
                aria-label={`Remove tag ${tagName(tag, locale)}`}
                onClick={() => onChange(value.filter((t) => t.id !== tag.id))}
                className="rounded-full p-0.5 text-muted-foreground outline-none hover:bg-background hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X aria-hidden className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="relative">
        <Input
          id={id}
          role="combobox"
          aria-expanded={open && total > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            open && total ? `${listId}-${Math.min(active, total - 1)}` : undefined
          }
          autoComplete="off"
          disabled={disabled || full}
          placeholder={
            full ? "Tag limit reached" : canCreate ? "Search or create a tag" : "Search tags"
          }
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
        {open && total > 0 && (
          <ul
            id={listId}
            role="listbox"
            aria-label="Tag suggestions"
            className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border bg-popover p-1 text-sm shadow-md"
          >
            {options.map((tag, i) => (
              <li
                key={tag.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                // Mouse down, not click: the input must not blur (and close the list) first.
                onMouseDown={(e) => {
                  e.preventDefault();
                  add(tag);
                }}
                className="cursor-pointer rounded-md px-2 py-1.5 aria-selected:bg-muted"
              >
                <span lang={locale}>{tagName(tag, locale)}</span>
              </li>
            ))}
            {canAdd && (
              <li
                id={`${listId}-${options.length}`}
                role="option"
                aria-selected={active === options.length}
                onMouseDown={(e) => {
                  e.preventDefault();
                  void create();
                }}
                className="flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 aria-selected:bg-muted"
              >
                {creating ? (
                  <Loader2 aria-hidden className="size-3.5 animate-spin" />
                ) : (
                  <Plus aria-hidden className="size-3.5" />
                )}
                Create “{typed}”
              </li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
}
