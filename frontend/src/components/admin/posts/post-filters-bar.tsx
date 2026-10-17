"use client";

import { Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { STATUS_LABEL } from "@/lib/admin/post-display";
import {
  hasActiveFilters,
  LOCALES,
  STATUSES,
  type Locale,
  type PostFilters,
} from "@/lib/admin/post-filters";
import type { Category } from "@/lib/admin/posts";
import { api } from "@/lib/api";
import type { components } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

export const SEARCH_DEBOUNCE_MS = 300;
const LOCALE_LABEL: Record<Locale, string> = { ne: "Nepali", en: "English" };

type StaffUser = components["schemas"]["UserOut"];

/** Only admins may list users; editors filter by author from the post rows instead. */
function useAuthors(enabled: boolean) {
  return useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<StaffUser[]>("/api/users"),
    enabled,
    staleTime: 5 * 60_000,
  });
}

interface Props {
  filters: PostFilters;
  categories: Category[] | undefined;
  canFilterAuthor: boolean;
  isAdmin: boolean;
  authorLabel: string | undefined;
  onChange: (patch: Partial<PostFilters>) => void;
}

function categoryLabel(c: Category, all: Category[]): string {
  return c.parent_id && all.some((p) => p.id === c.parent_id) ? `— ${c.name_en}` : c.name_en;
}

export function PostFiltersBar({
  filters,
  categories,
  canFilterAuthor,
  isAdmin,
  authorLabel,
  onChange,
}: Props) {
  const [q, setQ] = useState(filters.q);
  const pushed = useRef(filters.q);
  const authors = useAuthors(isAdmin);

  // Debounce typing into the URL.
  useEffect(() => {
    const next = q.trim();
    if (next === pushed.current) return;
    const timer = setTimeout(() => {
      pushed.current = next;
      onChange({ q: next });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [q, onChange]);

  // Follow the URL when it changes elsewhere (clear filters, back button).
  useEffect(() => {
    if (filters.q !== pushed.current) {
      pushed.current = filters.q;
      setQ(filters.q);
    }
  }, [filters.q]);

  const active = hasActiveFilters(filters);

  return (
    <form
      role="search"
      aria-label="Filter posts"
      onSubmit={(e) => e.preventDefault()}
      className="flex flex-wrap items-end gap-3"
    >
      <div className="min-w-48 flex-1 basis-64 space-y-1.5">
        <label htmlFor="post-search" className="text-xs font-medium text-muted-foreground">
          Search titles
        </label>
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            id="post-search"
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by title"
            maxLength={200}
            className="pl-8"
          />
        </div>
      </div>

      <Field label="Status" id="filter-status">
        <NativeSelect
          id="filter-status"
          value={filters.status ?? ""}
          onChange={(e) => onChange({ status: STATUSES.find((s) => s === e.target.value) })}
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </NativeSelect>
      </Field>

      <Field label="Category" id="filter-category">
        <NativeSelect
          id="filter-category"
          value={filters.category ?? ""}
          onChange={(e) => onChange({ category: Number(e.target.value) || undefined })}
        >
          <option value="">All categories</option>
          {categories?.map((c) => (
            <option key={c.id} value={c.id}>
              {categoryLabel(c, categories)}
            </option>
          ))}
        </NativeSelect>
      </Field>

      <Field label="Language" id="filter-language">
        <NativeSelect
          id="filter-language"
          value={filters.locale ?? ""}
          onChange={(e) => onChange({ locale: LOCALES.find((l) => l === e.target.value) })}
        >
          <option value="">Any language</option>
          {LOCALES.map((l) => (
            <option key={l} value={l}>
              {LOCALE_LABEL[l]}
            </option>
          ))}
        </NativeSelect>
      </Field>

      {isAdmin && (
        <Field label="Author" id="filter-author">
          <NativeSelect
            id="filter-author"
            value={filters.author ?? ""}
            onChange={(e) => onChange({ author: e.target.value || undefined })}
          >
            <option value="">All authors</option>
            {filters.author && !authors.data?.some((u) => u.id === filters.author) && (
              <option value={filters.author}>{authorLabel ?? "Selected author"}</option>
            )}
            {authors.data?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
      )}

      {canFilterAuthor && !isAdmin && filters.author && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => onChange({ author: undefined })}
          aria-label={`Remove author filter: ${authorLabel ?? "selected author"}`}
        >
          Author: {authorLabel ?? "selected"} <X aria-hidden />
        </Button>
      )}

      {active && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            pushed.current = "";
            setQ("");
            onChange({
              status: undefined,
              category: undefined,
              author: undefined,
              locale: undefined,
              q: "",
            });
          }}
        >
          Clear filters
        </Button>
      )}
    </form>
  );
}

function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className="w-40 space-y-1.5">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}
