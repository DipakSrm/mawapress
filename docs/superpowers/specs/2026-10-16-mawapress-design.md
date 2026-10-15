# MAWAPRESS — Design Spec

**Date:** 2026-10-16
**Status:** Approved (design), pending spec review
**Product:** MAWAPRESS — a bilingual (Nepali/English) news portal for Morang, Nepal

---

## 1. Purpose and success criteria

**Intended outcome.** A news portal that a small newsroom in Morang runs day to day without a developer. Editors write in a Word-like editor, pick from 5 templates and control the look of the site from an admin panel, much like WordPress. Every published article gets complete SEO on its own.

**Who it is for**
- *Readers:* local and diaspora Nepali readers, mostly on mobile and often on 3G/4G.
- *Newsroom:* Admin, Editors and Reporters.

**Success criteria**
| # | Criterion | Measure |
|---|-----------|---------|
| S1 | Handles 1M monthly readers with breaking-news spikes | k6: 500 req/s sustained on cached pages, p95 < 300 ms at origin for uncached API |
| S2 | Fast on mobile | Lighthouse mobile ≥ 90; LCP < 2.5 s on 4G |
| S3 | Zero manual SEO | Every published post has title, description, canonical, OG/Twitter, JSON-LD NewsArticle, sitemap entry, hreflang — verified by E2E test |
| S4 | Word-like authoring | Reporter can write, format (bold, colour, headings, spacing), add images and submit a post with no training; .docx upload produces a faithful draft |
| S5 | Template control without code | Admin can switch among 5 templates and change logo, colours, menus and homepage blocks; the live site updates within 60 s |
| S6 | Low running cost | Phase 1 infrastructure ≤ US $60/month |

**Stated by the user:** blog/news posting, a WordPress-like backend, Word-like editor, 5 templates, automatic SEO, a name and logo, 1M users, FastAPI + React + PostgreSQL.
**Decided in clarification:** a small newsroom with roles; Nepali + English; VPS + Cloudflare; web editor + .docx import; Next.js (React) with ISR for rendering.
**Assumptions (correctable):** "1M users" means monthly readers, not concurrent; reads outnumber writes by more than 1000:1; peak concurrency is about 5–10k readers during breaking news.

---

## 2. Architecture

```
                    ┌──────────────────────────────────────────┐
 Reader (mobile) ──►│ Cloudflare: DNS, CDN, WAF, image resize  │  ~95% cache hits
                    └───────────────┬──────────────────────────┘
                                    │ cache miss
                           ┌────────▼────────┐
                           │   Nginx (TLS)   │
                           └───┬─────────┬───┘
                    /*, /admin │         │ /api/*
                   ┌───────────▼──┐   ┌──▼──────────────────┐
                   │  Next.js 15  │──►│  FastAPI (uvicorn,  │
                   │ public (ISR) │   │  gunicorn workers)  │
                   │ + admin (CSR)│◄──│  stateless          │
                   └──────────────┘   └──┬───────┬───────┬──┘
                  revalidate webhook     │       │       │
                               ┌─────────▼┐ ┌────▼───┐ ┌─▼──────────────┐
                               │PgBouncer │ │ Redis  │ │ Cloudflare R2  │
                               │PostgreSQL│ │cache/  │ │ media + backups│
                               │(+replica)│ │queue   │ └────────────────┘
                               └──────────┘ └────┬───┘
                                            ┌────▼──────────────┐
                                            │ arq worker        │
                                            │ docx, images,     │
                                            │ sitemaps, revalid.│
                                            └───────────────────┘
```

### Technology choices

| Layer | Choice | Reason |
|-------|--------|--------|
| Public frontend | **Next.js 15 (App Router, React 19), ISR** | Pages are pre-rendered and cached at the CDN, which gives the best SEO and cost profile; the frontend stays React as requested |
| Admin frontend | Same Next.js app, `/admin` route group, client-side, **shadcn/ui + Tailwind** | One codebase and deploy; looks good with little custom UI work |
| Editor | **TipTap 2** (ProseMirror) | Word-like, extensible, outputs JSON and HTML |
| API | **FastAPI** (Python 3.13), Pydantic v2, SQLAlchemy 2 async, Alembic | Requested; async I/O; automatic OpenAPI docs |
| DB | **PostgreSQL 17** + PgBouncer | Requested; JSONB for settings; built-in full-text search |
| Cache / queue | **Redis 7** + **arq** | Response cache, rate limits, view counters, background jobs |
| Media | **Cloudflare R2** + Cloudflare Images/resizing (or `imgproxy` self-hosted) | No egress fees; WebP/AVIF variants |
| Search | Postgres `tsvector` + `pg_trgm` | Fast enough at this scale; avoids running Elasticsearch |
| Infra | Docker Compose on a **Hetzner** VPS (CPX41: 8 vCPU / 16 GB) + Cloudflare | About $30–40/mo; scale-out path in §8 |
| Observability | Sentry, Prometheus + Grafana, Uptime Kuma, structured JSON logs | Free or self-hosted |
| CI/CD | GitHub Actions → build images → SSH deploy (blue/green via Compose profiles) | Simple and repeatable |

---

## 3. Backend modules (FastAPI)

Each module is a package under `backend/app/modules/<name>/` containing `router.py`, `schemas.py`, `models.py`, `service.py` and `tests/`. Modules talk to each other only through `service.py` functions.

| Module | Responsibility | Key endpoints |
|--------|----------------|---------------|
| `auth` | Login, JWT access token (15 min) + refresh token (httpOnly cookie, 14 d), password reset, roles | `POST /auth/login`, `/auth/refresh`, `/auth/logout` |
| `users` | User CRUD (Admin only), profile and author bio | `/users` |
| `posts` | Post lifecycle, translations, revisions, scheduling | `/posts`, `/posts/{id}/submit`, `/publish`, `/revisions` |
| `taxonomy` | Categories (tree), tags | `/categories`, `/tags` |
| `media` | Presigned upload to R2, metadata, alt text, variant generation | `/media/presign`, `/media` |
| `themes` | Active template, settings, menus, homepage blocks | `/settings/site`, `/settings/theme` |
| `seo` | Meta generation, slugs, sitemaps, RSS, redirects, OG image | `/sitemap.xml`, `/news-sitemap.xml`, `/rss.xml`, `/redirects` |
| `importer` | .docx → TipTap JSON draft | `POST /import/docx` |
| `stats` | View counts (Redis INCR → batch flush every 60 s), trending | `POST /stats/view`, `/posts/trending` |
| `public` | Read-only, cache-friendly endpoints used by Next.js | `/public/home`, `/public/posts/{slug}`, `/public/category/{slug}` |

### Roles and permissions
| Action | Reporter | Editor | Admin |
|--------|:-------:|:-----:|:----:|
| Create/edit own drafts | ✔ | ✔ | ✔ |
| Submit for review | ✔ | ✔ | ✔ |
| Edit others' posts, publish, schedule, unpublish | | ✔ | ✔ |
| Manage categories/tags/media library | | ✔ | ✔ |
| Templates, theme, menus, site settings | | | ✔ |
| Users and roles | | | ✔ |

### Post workflow
`draft → in_review → scheduled | published → archived`. Every save of a published post creates a `post_revisions` row. When a post is published, the backend writes a transactional outbox row. The worker reads it, calls the Next.js `revalidateTag` webhook (tags: `post:{id}`, `home`, `category:{slug}`) and purges the matching URLs from Cloudflare.

---

## 4. Data model (PostgreSQL)

```
users(id uuid pk, email citext unique, password_hash, name, name_ne, role enum,
      bio, avatar_media_id, is_active, created_at)

posts(id uuid pk, author_id fk, status enum, category_id fk, featured_media_id fk,
      template_override text null, published_at, scheduled_at, updated_at,
      is_breaking bool, view_count bigint)
      idx: (status, published_at desc), (category_id, published_at desc)

post_translations(id pk, post_id fk, locale enum('ne','en'),
      title, slug, excerpt, content_json jsonb, content_html text,
      seo_title null, seo_description null, og_media_id null,   -- manual overrides
      seo_auto jsonb,                                            -- generated values
      search_vector tsvector GENERATED,
      unique(locale, slug), unique(post_id, locale))
      idx: GIN(search_vector), GIN(title gin_trgm_ops)

post_revisions(id, post_id, locale, content_json, editor_id, created_at)
categories(id, parent_id, slug unique, name_ne, name_en, sort, seo_description)
tags(id, slug unique, name_ne, name_en);  post_tags(post_id, tag_id)
media(id, r2_key, mime, width, height, bytes, alt_ne, alt_en, caption, uploader_id, variants jsonb)
site_settings(key text pk, value jsonb, updated_at)   -- theme, colours, logo, menus, home blocks
redirects(from_path pk, to_path, code smallint, created_at)
outbox(id, topic, payload jsonb, processed_at null)
```

Read-heavy queries go to the replica from Phase 2 onward, using a SQLAlchemy session router (writes go to the primary, `public/*` reads go to the replica).

---

## 5. Editor (Word-like authoring)

**TipTap extensions:** StarterKit, Underline, TextStyle, Color, Highlight, FontFamily, custom FontSize, custom LineHeight (paragraph spacing 1.0/1.15/1.5/2.0), TextAlign, Link, Image (with caption node), Table, Youtube, custom `Embed` (Facebook/X/TikTok via oEmbed), Placeholder, CharacterCount.

**Toolbar layout (Word-like ribbon):** Undo/Redo · Style dropdown (Paragraph, H1–H4, Quote) · Font (Mukta / Noto Sans Devanagari / Inter) · Size · **B** *I* U · Text colour · Highlight · Align · Line spacing · Bullets/Numbers · Link · Image · Table · Embed · Clear formatting.

**Writing screen:** editor on the left. The right sidebar holds Language tab (ने / EN), Category, Tags, Featured image, Template override, Schedule, an SEO preview (Google snippet + Facebook card, both read-only by default with an "Edit SEO" toggle) and a readability checklist.

**Autosave and conflicts:** autosave every 10 s to `PATCH /posts/{id}` with an `If-Match: <updated_at>` header. If someone else saved in the meantime (412), a "someone else edited" banner offers to reload or overwrite.

**Sanitisation:** the server renders `content_json` → HTML with a whitelist renderer (Python port of the schema), then runs it through `nh3`. Raw client HTML is never trusted.

**.docx import:** upload → worker → `mammoth` (docx → semantic HTML, custom style map that keeps colour and highlight) → HTML → TipTap JSON (server-side via `prosemirror-py` schema, or the client converts with `generateJSON`) → embedded images extracted to R2 → new draft. Unsupported elements (text boxes, SmartArt) are flagged in an import report.

---

## 6. The five templates

Templates live in `frontend/src/templates/<name>/` and each exports `HomeLayout`, `ArticleLayout`, `CategoryLayout` and a `settingsSchema` (zod). The admin's **Appearance** page renders a settings form generated from that schema, with a live preview iframe.

| # | Template | Home | Article | Best for |
|---|----------|------|---------|----------|
| 1 | **Classic News** | Breaking ticker, lead story + 4 secondary, category rows | Standard with sidebar (trending, related) | Default daily news |
| 2 | **Magazine Grid** | Masonry image cards, featured hero | Wide hero image, pull quotes | Features, culture |
| 3 | **Minimal Blog** | Single-column list | 680 px reading column, large type | Opinion, columns |
| 4 | **Live / Breaking** | Live-updates timeline, auto-refresh every 30 s (SWR, cached at edge for 15 s) | Timestamped update blocks | Elections, disasters |
| 5 | **Local Morang** | Area tabs (Biratnagar, Urlabari, Belbari, Pathari, Rangeli, Sundarharaicha…), Nepali date (BS) + weather widget, notices | Classic plus area badge | Hyper-local identity |

**Global theme settings:** logo (light/dark), primary/accent colours (CSS variables), fonts, header menu, footer menu, social links, homepage block order (drag-and-drop list of `{type, category, count}`), ad slots (HTML snippet, sanitised). Settings are stored in `site_settings`, read by Next.js with tag `settings`, and revalidated on save.

**Per-post override:** a post can pick a different `ArticleLayout`, for example Live for an election post.

---

## 7. Automatic SEO

Generated in `seo.service.generate(post_translation)` on every save. Manual override fields win when set.

| Item | Rule |
|------|------|
| `<title>` | `seo_title` or `truncate(title, 60) + " | MAWAPRESS"` (Nepali: "| मावाप्रेस") |
| Meta description | `seo_description` or the first 155 characters of plain text, cut at a word boundary, ignoring captions |
| Slug | Nepali → Latin transliteration (custom Devanagari table + `unidecode` fallback), kebab-case, ≤ 80 characters, unique per locale (`-2`, `-3`…) |
| Canonical | `https://mawapress.com/{locale}/{category}/{slug}` |
| hreflang | `ne`, `en`, `x-default` when both translations exist |
| Open Graph / Twitter | title, description, `og:image` = featured image (1200×630 crop) or **auto-generated card** (Next.js `ImageResponse`: headline + logo + category colour) |
| JSON-LD | `NewsArticle` (headline, datePublished, dateModified, author, publisher logo, image, articleSection, inLanguage), `BreadcrumbList`, sitewide `NewsMediaOrganization` + `WebSite` with `SearchAction` |
| Sitemaps | `sitemap.xml` index → per-month sitemaps; `news-sitemap.xml` (last 48 h, Google News); regenerated by the worker on publish |
| Feeds | `/rss.xml`, `/{locale}/category/{slug}/rss.xml` |
| Robots | `robots.txt`; `noindex` on search, tag pages with fewer than 3 posts, drafts and previews |
| Redirects | Slug change → automatic 301 in `redirects`; Next.js middleware checks a Redis-cached map |
| Images | Required alt text (falls back to the caption, then the title, with a warning); `width`/`height` always set; lazy loading below the fold |
| Readability checklist (advisory) | Missing featured image, missing alt, < 150 words, no subheadings in > 600 words, title > 70 characters |

---

## 8. Scalability and performance

**Traffic model.** 1M monthly readers × about 4 pages ≈ 4M page views/month ≈ 1.5/s average, ~30–50/s at daily peak, and possibly 500/s during a breaking-news spike.

**Caching layers**
1. **Cloudflare edge:** HTML from ISR is served with `s-maxage=60, stale-while-revalidate=86400`. Images are cached for a year (immutable keys). Target hit ratio ≥ 95%.
2. **Next.js ISR:** pages are regenerated on demand through `revalidateTag` when content is published.
3. **Redis:** `public/*` API responses are cached for 60 s and the keys are cleared on publish. Rate limiting uses `slowapi` + Redis.
4. **Postgres:** the right indexes, connection pooling through PgBouncer (transaction mode), and `statement_timeout`.

**Scale path**
| Phase | Trigger | Setup | ~Cost/mo |
|-------|---------|-------|----------|
| 1 | Launch to ~300k MAU | 1 × CPX41 VPS (all services), Cloudflare Free/Pro, R2 | $40–60 |
| 2 | ~300k–1M MAU or DB CPU > 60% | + dedicated DB VPS + streaming read replica, Redis on its own box | $90–130 |
| 3 | > 1M MAU / high availability required | 2+ app nodes behind a Hetzner LB, managed Postgres optional, worker autoscale | $200–350 |

**Resilience:** `stale-while-revalidate` lets Cloudflare keep serving cached pages if the origin goes down. Database backups run as a nightly `pg_dump` plus WAL archiving to R2 (point-in-time recovery, 14-day retention), with a monthly restore drill. Health checks are `/healthz` (liveness) and `/readyz` (DB + Redis).

**Security:** Cloudflare WAF and bot protection; argon2 password hashing; refresh cookies with CSRF protection (SameSite=Lax + double-submit token on admin mutations); rate limits on login; admin optionally behind Cloudflare Access; dependency scanning in CI; uploads limited to an allowlist of MIME types with a size cap; HTML sanitised with `nh3`.

---

## 9. Error handling

- **API errors:** errors use a single envelope, `{error: {code, message, details}}`, with codes such as `POST_NOT_FOUND`, `SLUG_TAKEN`, `VERSION_CONFLICT` and `FORBIDDEN_ROLE`.
- **Background jobs:** worker jobs retry up to 5 times with backoff, after which they go to a dead-letter list shown in an admin "Jobs" page.
- **Revalidation failures:** if revalidation fails, the outbox row stays unprocessed and is retried. ISR's time-based fallback (300 s) caps how stale a page can get.
- **Editor saves:** autosave failures show a persistent "Not saved — retrying" indicator, and the draft is also kept in `localStorage`.
- **Public pages:** custom 404 (with search) and 500 pages. 404s for missing slugs check `redirects` first.

---

## 10. Testing strategy

| Level | Tooling | Scope |
|-------|---------|-------|
| Unit | pytest | SEO generator (Nepali transliteration, truncation), sanitiser, permission matrix, docx mapper |
| API / integration | pytest + httpx + testcontainers (Postgres, Redis) | Every endpoint, workflow transitions, cache invalidation |
| Frontend unit | Vitest + Testing Library | Editor toolbar actions, template settings forms |
| E2E | Playwright | Login → write → format → upload image → publish → public page renders → meta/JSON-LD present; template switch; .docx import |
| SEO checks | Playwright + Lighthouse CI | Lighthouse SEO = 100, Performance ≥ 90 mobile on 3 key pages |
| Load | k6 | 500 req/s cached, 50 req/s uncached API mix, p95 thresholds |

TDD applies to backend services and the SEO generator.

---

## 11. Brand

- **Name:** MAWAPRESS (Nepali: मावाप्रेस). Proposed reading: **MA**ro **WA**r-pa (our surroundings), keeping "Morang" in the visual identity.
- **Logo concept:** a Devanagari-inspired "M" formed from the peaks of the Himalaya, rising over the flat Terai plain (a horizon line) of Morang. A small rising sun or dot suggests "news breaking". Colours: **Gurans red** `#C8102E` (rhododendron, Nepal's national flower and the flag crimson), **flag blue** `#003893`, ink `#111827`. Wordmark: bold condensed sans with the tagline "मोरङको आवाज · Voice of Morang".
- Files: `brand/mawapress-logo.svg` (horizontal) and `brand/mawapress-icon.svg` (square favicon/app icon).

---

## 12. Out of scope (YAGNI for v1)

Reader accounts and comments (social embeds or Facebook comments can come later), paywall or subscriptions, a native mobile app, a page builder beyond homepage blocks, multi-site, an ad server (only plain ad-slot HTML), and AI writing features. All can be added later without changing the architecture.

## 13. Open questions (non-blocking)

- Domain name (assumed `mawapress.com`; `.com.np` is free for registered Nepali entities).
- Whether to use Google AdSense in v1 (affects CSP and ad slots).
- A weather API for the Local Morang template (Open-Meteo, free, is the default).
