"use client";

import { AlertCircle, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import type { Locale } from "@/lib/admin/post-filters";
import { useCategories, type PostOut } from "@/lib/admin/posts";
import { api, isApiError } from "@/lib/api";

const EMPTY_DOC = { type: "doc", content: [{ type: "paragraph" }] };
const ERROR_ID = "new-post-error";

/** Minimal create form. The full editor (task 5) replaces the page this redirects to. */
export function NewPostForm() {
  const router = useRouter();
  const categories = useCategories();
  const [title, setTitle] = useState("");
  const [locale, setLocale] = useState<Locale>("ne");
  const [categoryId, setCategoryId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const categoryRef = useRef<HTMLSelectElement>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    if (!title.trim()) {
      setError("Enter a title.");
      titleRef.current?.focus();
      return;
    }
    if (!categoryId) {
      setError("Choose a category.");
      categoryRef.current?.focus();
      return;
    }
    setError(null);
    setPending(true);
    try {
      const post = await api.post<PostOut>("/api/posts", {
        locale,
        title: title.trim(),
        content_json: EMPTY_DOC,
        category_id: Number(categoryId),
      });
      router.push(`/admin/posts/${post.id}`);
    } catch (err) {
      setError(
        isApiError(err) && err.code !== "NETWORK_ERROR"
          ? err.message
          : "Could not create the post. Check your connection and try again.",
      );
      setPending(false);
    }
  }

  const invalid = error ? true : undefined;
  const describedBy = error ? ERROR_ID : undefined;

  return (
    <div className="mx-auto max-w-xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New post</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Start with a title, language and category. You can write the story next.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Basics</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} noValidate className="space-y-4">
            {error && (
              <div
                id={ERROR_ID}
                role="alert"
                className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="new-title">Title</Label>
              <Input
                id="new-title"
                ref={titleRef}
                lang={locale}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={300}
                autoFocus
                required
                aria-invalid={invalid}
                aria-describedby={describedBy}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="new-locale">Language</Label>
                <NativeSelect
                  id="new-locale"
                  value={locale}
                  onChange={(e) => setLocale(e.target.value === "en" ? "en" : "ne")}
                >
                  <option value="ne">Nepali</option>
                  <option value="en">English</option>
                </NativeSelect>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="new-category">Category</Label>
                <NativeSelect
                  id="new-category"
                  ref={categoryRef}
                  value={categoryId}
                  onChange={(e) => setCategoryId(e.target.value)}
                  required
                  disabled={categories.isPending}
                  aria-invalid={invalid}
                  aria-describedby={describedBy}
                >
                  <option value="">
                    {categories.isPending ? "Loading…" : "Choose a category"}
                  </option>
                  {categories.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name_en}
                    </option>
                  ))}
                </NativeSelect>
                {categories.isError && (
                  <p className="text-xs text-destructive">Could not load categories.</p>
                )}
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="submit" disabled={pending}>
                {pending && <Loader2 aria-hidden className="animate-spin" />}
                Create draft
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
