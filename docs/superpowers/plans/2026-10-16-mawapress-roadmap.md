# MAWAPRESS — Master Roadmap and Agent Strategy

> **For agentic workers:** This is the programme-level roadmap. Each milestone is executed from its **own detailed plan** in `docs/superpowers/plans/`. M1 is already written (`2026-10-16-m1-backend-content-core.md`). Write each later plan with `superpowers:writing-plans` when its milestone starts, so it reflects the code that actually exists by then.

**Goal:** Ship MAWAPRESS, a bilingual Morang news portal with a WordPress-style admin, a Word-like editor, 5 templates and automatic SEO, sized for 1M monthly readers on a budget of about $60/month.

**Spec:** `docs/superpowers/specs/2026-10-16-mawapress-design.md`

**Stack:** FastAPI (Python 3.13) · PostgreSQL 17 · Redis 7 + arq · Next.js 15 / React 19 (ISR) · TipTap 2 · Tailwind + shadcn/ui · Cloudflare (CDN, WAF, R2) · Docker Compose on Hetzner.

---

## 1. Milestones

| # | Milestone | Delivers (testable outcome) | Depends on | Est. effort* |
|---|-----------|-----------------------------|------------|--------------|
| **M0** | Foundations and brand | Spec, roadmap, logo, git repo, CI skeleton | — | 0.5 d (largely done) |
| **M1** | Backend content core | FastAPI app, DB models + migrations, auth (login/JWT/roles), Nepali slugs, SEO generator, safe HTML renderer, post workflow API with optimistic locking, cached public post endpoint | M0 | 4–5 d |
| **M2** | Backend completion | Refresh/logout cookies + CSRF, login rate limit, user admin, categories/tags CRUD, media (R2 presigned upload + WebP variants), revisions, redirects (auto-301 on slug change), search (`tsvector` + `pg_trgm`), sitemaps / Google News sitemap / RSS, scheduled publishing, view stats, **arq worker** for the outbox (Next.js `revalidateTag` + Cloudflare purge), .docx importer (mammoth) | M1 | 8–10 d |
| **M3** | Admin app and editor | Next.js `/admin`: login, dashboard, posts list/filter, **TipTap Word-like editor** (ribbon toolbar, fonts, colours, line spacing, tables, embeds), autosave with `If-Match`, ne/EN tabs, SEO preview (Google/Facebook card), readability checklist, media library, .docx upload UI, users and categories screens | M1 API contract (OpenAPI); M2 for media/import | 8–10 d |
| **M4** | Public site, 5 templates and theme system | Template registry (Classic News, Magazine Grid, Minimal Blog, Live/Breaking, Local Morang), zod `settingsSchema` → Appearance form with live preview, ne/en routing, ISR + `/api/revalidate`, OG image generation, JSON-LD and meta output, BS date + weather widget, homepage block ordering | M1 public API; M2 sitemaps | 8–10 d |
| **M5** | Infrastructure and DevOps | Production Compose (Nginx, Next.js, API ×N, worker, Postgres + PgBouncer, Redis), Cloudflare config, GitHub Actions CI/CD (test → build → deploy blue/green), backups (pg_dump + WAL to R2) with a restore drill, Sentry, Prometheus/Grafana, Uptime Kuma | M1 | 3–4 d |
| **M6** | Hardening and launch | Playwright E2E (write → publish → page + meta), Lighthouse CI (SEO 100, Perf ≥ 90 mobile), k6 (500 req/s cached), security review, seed categories (Morang areas), go-live checklist, DNS cut-over | M2–M5 | 3–4 d |

\*Estimates assume one developer driving agents. Sequential total ≈ 7–8 weeks; with the parallel lanes in §3, ≈ 4–5 weeks.

---

## 2. Agents and models: who does what

The aim is to put the expensive model only where a mistake costs a lot (architecture, security, final review) and use cheaper models for mechanical, pattern-following work.

| Agent role | Model | Used for | Why this model |
|------------|-------|----------|----------------|
| **Architect / Planner** | **Opus 5.5** (`claude-opus-5-5`) | Writing each milestone's detailed plan, resolving design questions, API contract decisions (OpenAPI freeze before parallel lanes) | Rarely invoked (about 5% of tokens), but its decisions shape everything downstream |
| **Implementer** (one fresh subagent per task) | **Sonnet 5.5** (`claude-sonnet-5-5`) | All TDD tasks: FastAPI modules, Next.js pages, TipTap extensions, templates, Compose files | Strong coding at a much lower price than Opus; the plans already carry the design, so it doesn't need to re-derive it |
| **Task reviewer** (spec compliance + code quality, per task) | **Sonnet 5.5** | Gate after every task in subagent-driven development | Catches drift cheaply before it compounds |
| **Whole-branch reviewer** (end of each milestone) | **Opus 5.5** | Cross-task consistency, architecture violations, missed spec items | One expensive pass per milestone instead of per task |
| **Security reviewer** | **Opus 5.5** (`/security-review`) | End of M2 (auth, uploads, sanitiser, CSRF) and before launch | Security misses are the costliest class of bug |
| **Explorer / searcher** | **Haiku 5.5** (`claude-haiku-5-5`, `Explore` agent) | "Where is X defined?", file sweeps, log triage | Read-only, high volume; Haiku is fast and cheap |
| **Mechanical worker** | **Haiku 5.5** | Ne/en UI string files, seed data (Morang areas, categories), fixture JSON, boilerplate Pydantic schemas from a given model, docs/README, lint-fix passes | Clear patterns with nothing to design |
| **Design implementer** | **Sonnet 5.5** + `frontend-design` / `ui-ux-pro-max` skills | The 5 templates, admin look and feel, logo refinements | Needs taste plus code; Opus isn't worth the cost here |
| **Perf / load tuner** | **Sonnet 5.5** | Lighthouse fixes, k6 scripts, query/index tuning from `EXPLAIN` | Iterative and evidence-driven |

### Cost-minimising rules
1. **Plans are the context.** Implementers get only their task text plus the spec section, never the whole conversation. Small tasks keep fresh contexts cheap.
2. **Stable prefixes get cached.** Keep the spec and plan files unchanged during a milestone so prompt caching hits across subagents.
3. **Escalate, don't default.** Start a task on Sonnet. Move to Opus only if the reviewer rejects the same task twice.
4. **Haiku for anything with a template.** If a task can be described as "do X exactly like file Y", use Haiku.
5. **Tests decide, not model reasoning.** Agents run `pytest` / `vitest` / Playwright and report results instead of reasoning about whether code works.
6. **Parallelise only across frozen interfaces** (see §3). Parallel agents editing shared files waste tokens on merge fixes.

---

## 3. Parallel lanes

```
          M0 ──► M1 (backend core, sequential; establishes API contract)
                    │
                    ├── OpenAPI contract frozen (Opus checkpoint)
                    │
   ┌────────────────┼──────────────────┬─────────────────────┐
   ▼                ▼                  ▼                     ▼
 Lane A           Lane B             Lane C                Lane D
 M2 backend       M3 admin + editor  M4 public templates   M5 infra/CI
 (Sonnet,         (Sonnet, mocks     (Sonnet + design      (Sonnet,
  worktree A)      from OpenAPI,      skills, fixture       worktree D)
                   worktree B)        JSON, worktree C)
   └────────────────┴──────────────────┴─────────────────────┘
                    │  merge in order A → D → B → C
                    ▼
                 M6 hardening + launch (Opus whole-branch + security review)
```

- Each lane runs in its own git worktree (`superpowers:using-git-worktrees`) and its own Claude session.
- Lanes B and C use generated TypeScript types from the frozen OpenAPI (`openapi-typescript`), so they never import backend code.
- Contract changes go back through the Architect (Opus) and get a version bump. A lane never changes the contract on its own.

---

## 4. Definition of done (per milestone)

- All tasks in the milestone plan are checked off, with every test green in CI.
- Sonnet reviewer approved every task, and the Opus whole-branch review has no open "must fix" items.
- The spec success criteria touched by the milestone have been verified (see spec §1, S1–S6).
- Docs updated: README section and `.env.example` keys.

## 5. Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| Nepali transliteration produces odd slugs | Heuristic schwa deletion plus an editor override field. Slugs are frozen after publish; redirects arrive in M2 |
| ISR revalidation missed → stale pages | Transactional outbox + retries, plus a time-based ISR fallback (300 s) |
| Breaking-news spike overwhelms origin | Cloudflare `stale-while-revalidate`, Redis cache, Live template edge TTL of 15 s, k6 proven before launch |
| VPS single point of failure (Phase 1) | Cloudflare serves stale pages, nightly + WAL backups, documented 30-minute rebuild runbook; Phase 3 adds a second node |
| .docx fidelity complaints | Import report listing dropped elements; supported-formatting guide in the admin |
| Agent cost overrun | Rules in §2; check usage weekly (`/usage`), and push work down to Haiku where reviewers rarely reject it |
