# M1 — Backend Content Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Model routing (see roadmap §2):** implementer = Sonnet 5.5, per-task reviewer = Sonnet 5.5, final branch review = Opus 5.5. Tasks 2–4 are pure functions with no shared state and can run in parallel.

**Goal:** A tested FastAPI backend where reporters write bilingual posts, editors publish them, and every post gets a Nepali-aware slug, sanitised HTML and complete auto-generated SEO, served through a Redis-cached public endpoint.

**Architecture:** Modular FastAPI app (`app/modules/<name>/`). Each module talks to the others only through `service.py`. PostgreSQL via async SQLAlchemy 2, with Alembic migrations. The pure-logic units (slug, SEO, renderer) have no I/O and are unit-tested. API tests run against a real Postgres started by testcontainers, with each test rolled back.

**Tech Stack:** Python 3.13, uv, FastAPI, Pydantic v2, SQLAlchemy 2 (asyncpg), Alembic, argon2-cffi, PyJWT, nh3, Unidecode, redis-py (asyncio), pytest + pytest-asyncio, httpx, testcontainers, fakeredis.

**Spec:** `docs/superpowers/specs/2026-10-16-mawapress-design.md` (sections 3, 4, 5 "Sanitisation", 7, 8 "Caching layers", 9)

**Prerequisites:** Docker Desktop running (needed by testcontainers and `docker compose`), `uv` installed (`pip install uv`), Git.

## Global Constraints

- Python **3.13**; FastAPI ≥ 0.115; SQLAlchemy 2.x async; Pydantic v2.
- PostgreSQL **17**, Redis **7** (dev via `docker-compose.yml`).
- Locales are exactly `"ne"` and `"en"`.
- Slug: produced by `make_slug`, **≤ 80 chars**, `[a-z0-9-]`, unique per locale (`-2`, `-3` …); DB column `String(100)`.
- SEO title: `seo_title` override, else `truncate_words(title, 60) + " | MAWAPRESS"` (en) / `" | मावाप्रेस"` (ne). Description ≤ **155** chars.
- Roles rank: `reporter < editor < admin`.
- Error envelope for every handled error: `{"error": {"code": str, "message": str, "details": dict}}`.
- Public post cache TTL **60 s**; header `Cache-Control: public, s-maxage=60, stale-while-revalidate=86400`.
- All timestamps timezone-aware UTC (`datetime.now(UTC)`).
- Env vars prefixed `MAWA_` (e.g. `MAWA_DATABASE_URL`).
- Slugs are frozen once a post is published (redirect support arrives in M2).

## Review Focus

1. **Duplicate headlines** (two "बाढी समाचार" stories): the second must get `…-2`, never a 500. Tested in Task 7.
2. **Two editors saving the same post**: a stale `If-Match` must return 412 `VERSION_CONFLICT`, not silently overwrite. Tested in Task 7.
3. **Pasted hostile content** (`<script>`, `javascript:` links, CSS injection in colour attrs): it must render inert. Tested in Task 4.
4. **A reporter trying to publish or edit someone else's post** must get 403. Tested in Task 7.
5. **Headlines that transliterate to nothing** (emoji or symbols only) must still get a valid slug (`post`). Tested in Task 2.

---

## File Structure

```
mawapress/
├── .gitignore
├── docker-compose.yml                 # dev Postgres + Redis
└── backend/
    ├── pyproject.toml
    ├── alembic.ini
    ├── migrations/                    # alembic (async template)
    │   ├── env.py
    │   └── versions/<rev>_content_core.py
    ├── app/
    │   ├── __init__.py
    │   ├── main.py                    # create_app(), router wiring
    │   ├── core/
    │   │   ├── __init__.py
    │   │   ├── config.py              # Settings (pydantic-settings)
    │   │   ├── errors.py              # AppError + handler
    │   │   └── cache.py               # get_redis()
    │   ├── db/
    │   │   ├── __init__.py
    │   │   ├── base.py                # Base, utcnow
    │   │   ├── session.py             # engine, get_session
    │   │   ├── outbox.py              # OutboxEvent model
    │   │   └── models.py              # imports all models (metadata registry)
    │   └── modules/
    │       ├── __init__.py
    │       ├── users/{__init__,models}.py
    │       ├── taxonomy/{__init__,models}.py
    │       ├── auth/{__init__,security,deps,router}.py
    │       ├── seo/{__init__,slug,generator}.py
    │       ├── posts/{__init__,models,render,schemas,service,router}.py
    │       └── public/{__init__,router}.py
    └── tests/
        ├── __init__.py
        ├── conftest.py
        ├── factories.py
        ├── test_health.py
        ├── seo/{__init__,test_slug,test_generator}.py
        ├── posts/{__init__,test_render,test_posts_api}.py
        ├── db/{__init__,test_models,test_migrations}.py
        ├── auth/{__init__,test_auth}.py
        └── public/{__init__,test_public_api}.py
```

All `__init__.py` files are empty. All commands run from `backend/` unless stated.

---

### Task 1: Project scaffold, config, error envelope, health check

**Files:**
- Create: `.gitignore`, `docker-compose.yml`, `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/app/core/errors.py`, `backend/app/main.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.main.create_app() -> FastAPI`; `app.core.config.get_settings() -> Settings` (fields `env, database_url, redis_url, jwt_secret, jwt_access_minutes, site_url`); `app.core.errors.AppError(status: int, code: str, message: str, details: dict | None = None)`; `register_error_handlers(app)`.

- [ ] **Step 1: Init repo and dev services**

```bash
git init mawapress && cd mawapress
```

`.gitignore`:
```gitignore
__pycache__/
.venv/
.env
.pytest_cache/
.ruff_cache/
node_modules/
```

`docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: mawa
      POSTGRES_PASSWORD: mawa
      POSTGRES_DB: mawapress
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
volumes:
  pgdata: {}
```

`backend/pyproject.toml`:
```toml
[project]
name = "mawapress-backend"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic-settings>=2.6",
  "email-validator>=2.2",
  "sqlalchemy[asyncio]>=2.0.36",
  "asyncpg>=0.30",
  "alembic>=1.14",
  "argon2-cffi>=23.1",
  "pyjwt>=2.10",
  "nh3>=0.2.18",
  "unidecode>=1.3.8",
  "redis>=5.2",
]

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "httpx>=0.28",
  "testcontainers[postgres]>=4.8",
  "fakeredis>=2.26",
  "ruff>=0.8",
]

[tool.uv]
package = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
pythonpath = ["."]
testpaths = ["tests"]
```

Run: `cd backend && uv sync`
Expected: creates `.venv`, resolves all packages.

- [ ] **Step 2: Write the failing tests**

`backend/tests/conftest.py`:
```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


def pytest_collection_modifyitems(items):
    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if pytest_asyncio.is_async_test(item):
            item.add_marker(marker, append=False)


@pytest_asyncio.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

`backend/tests/test_health.py`:
```python
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError
from app.main import create_app


async def test_healthz(client):
    r = await client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_app_error_uses_envelope():
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise AppError(418, "TEAPOT", "short and stout", {"x": 1})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/boom")
    assert r.status_code == 418
    assert r.json() == {"error": {"code": "TEAPOT", "message": "short and stout", "details": {"x": 1}}}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 4: Implement**

`backend/app/core/config.py`:
```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MAWA_")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://mawa:mawa@localhost:5432/mawapress"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-only-change-me"
    jwt_access_minutes: int = 15
    site_url: str = "https://mawapress.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/app/core/errors.py`:
```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )
```

`backend/app/main.py`:
```python
from fastapi import FastAPI

from app.core.errors import register_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="MAWAPRESS API", version="0.1.0")
    register_error_handlers(app)

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

Create the empty `app/__init__.py`, `app/core/__init__.py` and `tests/__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_health.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(backend): scaffold FastAPI app with config, error envelope and health check"
```

---

### Task 2: Nepali-aware slug generator

**Files:**
- Create: `backend/app/modules/__init__.py`, `backend/app/modules/seo/__init__.py`, `backend/app/modules/seo/slug.py`
- Test: `backend/tests/seo/__init__.py`, `backend/tests/seo/test_slug.py`

**Interfaces:**
- Produces: `transliterate(text: str) -> str`; `make_slug(text: str, max_len: int = 80) -> str` (always non-empty, `[a-z0-9-]`, no leading or trailing hyphen).

- [ ] **Step 1: Write the failing tests**

`backend/tests/seo/test_slug.py`:
```python
import re

import pytest

from app.modules.seo.slug import make_slug, transliterate


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("विराटनगर", "biratnagar"),
        ("मोरङ समाचार", "morang-samachar"),
        ("बाढी २०८२", "badhi-2082"),
        ("Hello World!", "hello-world"),
        ("Café Nepal", "cafe-nepal"),
    ],
)
def test_make_slug_examples(text, expected):
    assert make_slug(text) == expected


def test_symbol_only_title_falls_back_to_post():
    assert make_slug("!!! 🎉🎉 ???") == "post"


def test_long_title_is_cut_at_word_boundary():
    slug = make_slug("Morang district " * 20)
    assert len(slug) <= 80
    assert not slug.endswith("-")
    assert re.fullmatch(r"[a-z0-9-]+", slug)


def test_halant_joins_consonants():
    # क्ष = क + ् + ष  → "ksh"
    assert transliterate("क्षेत्र").startswith("kshe")


def test_single_consonant_word_keeps_vowel():
    assert transliterate("र") == "ra"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/seo/test_slug.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.seo'`.

- [ ] **Step 3: Implement**

`backend/app/modules/seo/slug.py`:
```python
"""Devanagari → Latin transliteration and URL slugs.

Each consonant carries an inherent 'a'. Matras replace it and a halant removes it.
A simplified schwa-deletion pass then drops the inherent 'a' (1) at the end of a
multi-letter word and (2) in a V C_C V context, scanning left to right, so that
"विराटनगर" becomes "biratnagar" rather than "biratanagara".
"""

import re
from dataclasses import dataclass

from unidecode import unidecode

CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "b", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h",
}
INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
MATRAS = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}
SIGNS = {"ं": "n", "ँ": "n", "ः": "h"}
HALANT = "्"
NUKTA = "़"
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


@dataclass
class _Unit:
    cons: str
    vowel: str
    inherent: bool
    suffix: str = ""


def _is_devanagari(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def _transliterate_word(word: str) -> str:
    units: list[_Unit] = []
    for ch in word:
        if ch in CONSONANTS:
            units.append(_Unit(CONSONANTS[ch], "a", True))
        elif ch in MATRAS and units:
            units[-1].vowel, units[-1].inherent = MATRAS[ch], False
        elif ch == HALANT and units:
            units[-1].vowel, units[-1].inherent = "", False
        elif ch in INDEPENDENT_VOWELS:
            units.append(_Unit("", INDEPENDENT_VOWELS[ch], False))
        elif ch in SIGNS and units:
            units[-1].suffix += SIGNS[ch]
        elif ch == NUKTA:
            continue
        else:
            units.append(_Unit(ch, "", False))

    last = units[-1] if units else None
    if last and len(units) > 1 and last.inherent and not last.suffix:
        last.vowel = ""
    for i in range(1, len(units) - 1):
        prev, cur, nxt = units[i - 1], units[i], units[i + 1]
        if cur.inherent and prev.vowel and nxt.cons and nxt.vowel:
            cur.vowel = ""
    return "".join(u.cons + u.vowel + u.suffix for u in units)


def transliterate(text: str) -> str:
    text = text.translate(DIGITS)
    parts = []
    for token in re.split(r"(\s+)", text):
        if any(_is_devanagari(c) for c in token):
            parts.append(_transliterate_word(token))
        else:
            parts.append(unidecode(token))
    return "".join(parts)


def make_slug(text: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", transliterate(text).lower()).strip("-")
    if len(slug) > max_len:
        cut = slug[:max_len]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else cut
    return slug or "post"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/seo/test_slug.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(seo): Nepali-aware transliteration and slug generator"
```

---

### Task 3: SEO metadata generator

**Files:**
- Create: `backend/app/modules/seo/generator.py`
- Test: `backend/tests/seo/test_generator.py`

**Interfaces:**
- Produces:
  - `plain_text(html: str) -> str`
  - `truncate_words(text: str, limit: int) -> str` (result ≤ `limit` chars)
  - `@dataclass(frozen=True) SeoInput(locale, title, html, slug, category_slug, category_name, author_name, published_at: datetime | None, modified_at: datetime, image_url: str | None = None, seo_title: str | None = None, seo_description: str | None = None, alternate_slugs: dict[str, str] = {})`
  - `@dataclass(frozen=True) SeoMeta(title, description, canonical, og_image, hreflang: dict[str, str], json_ld: list[dict])` with `.to_dict() -> dict` (JSON-serialisable)
  - `build_seo(inp: SeoInput, site_url: str) -> SeoMeta`
  - `article_url(site_url, locale, category_slug, slug) -> str`

- [ ] **Step 1: Write the failing tests**

`backend/tests/seo/test_generator.py`:
```python
import json
from datetime import UTC, datetime

from app.modules.seo.generator import SeoInput, build_seo, plain_text, truncate_words

SITE = "https://mawapress.com"
T0 = datetime(2026, 10, 16, 6, 30, tzinfo=UTC)


def make_input(**overrides) -> SeoInput:
    base = dict(
        locale="ne",
        title="विराटनगरमा भारी वर्षा",
        html="<p>विराटनगरमा आज बिहानदेखि भारी वर्षा भइरहेको छ।</p>",
        slug="biratnagarma-bhari-barsha",
        category_slug="morang",
        category_name="मोरङ",
        author_name="Sita Rai",
        published_at=T0,
        modified_at=T0,
    )
    base.update(overrides)
    return SeoInput(**base)


def test_plain_text_drops_tags_and_captions():
    html = "<p>Hello <strong>world</strong></p><figure><img src='x'><figcaption>Photo: AP</figcaption></figure><p>Next</p>"
    assert plain_text(html) == "Hello world Next"


def test_truncate_words_respects_limit_and_word_boundary():
    out = truncate_words("one two three four five", 12)
    assert len(out) <= 12
    assert out == "one two…"
    assert truncate_words("short", 12) == "short"


def test_title_gets_brand_suffix_per_locale():
    assert build_seo(make_input(), SITE).title == "विराटनगरमा भारी वर्षा | मावाप्रेस"
    en = build_seo(make_input(locale="en", title="Heavy rain in Biratnagar"), SITE)
    assert en.title == "Heavy rain in Biratnagar | MAWAPRESS"


def test_long_title_is_truncated_before_suffix():
    meta = build_seo(make_input(locale="en", title="word " * 40), SITE)
    headline_part = meta.title.removesuffix(" | MAWAPRESS")
    assert len(headline_part) <= 60


def test_manual_overrides_win():
    meta = build_seo(make_input(seo_title="Custom", seo_description="Desc"), SITE)
    assert meta.title == "Custom"
    assert meta.description == "Desc"


def test_description_from_body_max_155_and_falls_back_to_title():
    long_html = "<p>" + "शब्द " * 100 + "</p>"
    assert len(build_seo(make_input(html=long_html), SITE).description) <= 155
    assert build_seo(make_input(html=""), SITE).description == "विराटनगरमा भारी वर्षा"


def test_canonical_og_fallback_and_no_hreflang_without_alternates():
    meta = build_seo(make_input(), SITE)
    assert meta.canonical == f"{SITE}/ne/morang/biratnagarma-bhari-barsha"
    assert meta.og_image == f"{SITE}/ne/og/biratnagarma-bhari-barsha.png"
    assert meta.hreflang == {}


def test_hreflang_when_translation_exists():
    meta = build_seo(make_input(alternate_slugs={"en": "heavy-rain-in-biratnagar"}), SITE)
    assert meta.hreflang == {
        "ne": f"{SITE}/ne/morang/biratnagarma-bhari-barsha",
        "en": f"{SITE}/en/morang/heavy-rain-in-biratnagar",
        "x-default": f"{SITE}/ne/morang/biratnagarma-bhari-barsha",
    }


def test_json_ld_news_article_and_breadcrumb():
    meta = build_seo(make_input(image_url="https://cdn.mawapress.com/a.webp"), SITE)
    article, crumbs = meta.json_ld
    assert article["@type"] == "NewsArticle"
    assert article["headline"] == "विराटनगरमा भारी वर्षा"
    assert article["datePublished"] == T0.isoformat()
    assert article["inLanguage"] == "ne-NP"
    assert article["image"] == ["https://cdn.mawapress.com/a.webp"]
    assert crumbs["@type"] == "BreadcrumbList"
    assert len(crumbs["itemListElement"]) == 3
    json.dumps(meta.to_dict())  # must be JSON-serialisable
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/seo/test_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.seo.generator'`.

- [ ] **Step 3: Implement**

`backend/app/modules/seo/generator.py`:
```python
import html as html_lib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

import nh3

BRAND = {"ne": "मावाप्रेस", "en": "MAWAPRESS"}
LANG_TAG = {"ne": "ne-NP", "en": "en"}
HOME_LABEL = {"ne": "गृहपृष्ठ", "en": "Home"}

_FIGCAPTION = re.compile(r"<figcaption\b.*?</figcaption>", re.S | re.I)
_BLOCK_END = re.compile(r"</(?:p|h[1-6]|li|blockquote|figure|td|th)>|<br\s*/?>", re.I)
_WS = re.compile(r"\s+")


def plain_text(html: str) -> str:
    text = _FIGCAPTION.sub(" ", html)
    text = _BLOCK_END.sub(" ", text)
    text = nh3.clean(text, tags=set())
    return _WS.sub(" ", html_lib.unescape(text)).strip()


def truncate_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:–—।") + "…"


def article_url(site_url: str, locale: str, category_slug: str, slug: str) -> str:
    return f"{site_url}/{locale}/{category_slug}/{slug}"


@dataclass(frozen=True)
class SeoInput:
    locale: str
    title: str
    html: str
    slug: str
    category_slug: str
    category_name: str
    author_name: str
    published_at: datetime | None
    modified_at: datetime
    image_url: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    alternate_slugs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SeoMeta:
    title: str
    description: str
    canonical: str
    og_image: str
    hreflang: dict[str, str]
    json_ld: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def build_seo(inp: SeoInput, site_url: str) -> SeoMeta:
    title = inp.seo_title or f"{truncate_words(inp.title, 60)} | {BRAND[inp.locale]}"
    description = inp.seo_description or truncate_words(plain_text(inp.html), 155) or inp.title
    canonical = article_url(site_url, inp.locale, inp.category_slug, inp.slug)
    og_image = inp.image_url or f"{site_url}/{inp.locale}/og/{inp.slug}.png"

    hreflang: dict[str, str] = {}
    if inp.alternate_slugs:
        hreflang[inp.locale] = canonical
        for locale, slug in inp.alternate_slugs.items():
            hreflang[locale] = article_url(site_url, locale, inp.category_slug, slug)
        hreflang["x-default"] = hreflang.get("ne", canonical)

    published = inp.published_at or inp.modified_at
    article = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": truncate_words(inp.title, 110),
        "description": description,
        "image": [og_image],
        "datePublished": published.isoformat(),
        "dateModified": inp.modified_at.isoformat(),
        "inLanguage": LANG_TAG[inp.locale],
        "articleSection": inp.category_name,
        "mainEntityOfPage": canonical,
        "author": [{"@type": "Person", "name": inp.author_name}],
        "publisher": {
            "@type": "NewsMediaOrganization",
            "name": "MAWAPRESS",
            "logo": {"@type": "ImageObject", "url": f"{site_url}/brand/mawapress-icon.png"},
        },
    }
    breadcrumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": HOME_LABEL[inp.locale], "item": f"{site_url}/{inp.locale}"},
            {"@type": "ListItem", "position": 2, "name": inp.category_name,
             "item": f"{site_url}/{inp.locale}/{inp.category_slug}"},
            {"@type": "ListItem", "position": 3, "name": inp.title, "item": canonical},
        ],
    }
    return SeoMeta(title, description, canonical, og_image, hreflang, [article, breadcrumbs])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/seo/test_generator.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(seo): automatic title, description, canonical, hreflang and JSON-LD generation"
```

---

### Task 4: Safe TipTap JSON → HTML renderer

**Files:**
- Create: `backend/app/modules/posts/__init__.py`, `backend/app/modules/posts/render.py`
- Test: `backend/tests/posts/__init__.py`, `backend/tests/posts/test_render.py`

**Interfaces:**
- Produces: `render_html(doc: dict) -> str`. This renders a TipTap/ProseMirror JSON document to sanitised HTML. Unknown nodes keep their text and lose the wrapper, and invalid attributes are dropped.

- [ ] **Step 1: Write the failing tests**

`backend/tests/posts/test_render.py`:
```python
from app.modules.posts.render import render_html


def doc(*blocks):
    return {"type": "doc", "content": list(blocks)}


def para(*inlines, **attrs):
    return {"type": "paragraph", "attrs": attrs, "content": list(inlines)}


def text(value, *marks):
    return {"type": "text", "text": value, "marks": list(marks)}


def test_bold_italic_and_colour():
    out = render_html(doc(para(
        text("Breaking", {"type": "bold"}),
        text(" red", {"type": "textStyle", "attrs": {"color": "#C8102E", "fontSize": "18px"}}),
    )))
    assert "<strong>Breaking</strong>" in out
    assert "#C8102E" in out and "18px" in out


def test_heading_level_is_clamped():
    out = render_html(doc({"type": "heading", "attrs": {"level": 9}, "content": [text("Title")]}))
    assert out == "<h2>Title</h2>"


def test_line_height_and_alignment():
    out = render_html(doc(para(text("x"), textAlign="center", lineHeight="1.5")))
    assert "text-align" in out and "center" in out and "line-height" in out


def test_script_in_text_is_escaped():
    out = render_html(doc(para(text("<script>alert(1)</script>"))))
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_javascript_link_is_dropped_but_text_kept():
    out = render_html(doc(para(text("click", {"type": "link", "attrs": {"href": "javascript:alert(1)"}}))))
    assert "javascript" not in out
    assert "click" in out


def test_safe_link_gets_rel():
    out = render_html(doc(para(text("site", {"type": "link", "attrs": {"href": "https://mawapress.com"}}))))
    assert 'href="https://mawapress.com"' in out
    assert "noopener" in out


def test_css_injection_in_colour_is_ignored():
    out = render_html(doc(para(text("x", {"type": "textStyle", "attrs": {"color": "red;background:url(evil)"}}))))
    assert "evil" not in out
    assert "<span" not in out


def test_image_with_caption_and_bad_src():
    good = render_html(doc({"type": "image", "attrs": {"src": "https://cdn.mawapress.com/a.webp", "alt": "बाढी", "caption": "Photo"}}))
    assert '<img src="https://cdn.mawapress.com/a.webp"' in good and "<figcaption>Photo</figcaption>" in good
    bad = render_html(doc({"type": "image", "attrs": {"src": "javascript:x"}}))
    assert bad == ""


def test_unknown_node_keeps_text():
    out = render_html(doc({"type": "mysteryWidget", "content": [para(text("still here"))]}))
    assert out == "<p>still here</p>"


def test_lists_and_blockquote():
    out = render_html(doc(
        {"type": "bulletList", "content": [{"type": "listItem", "content": [para(text("a"))]}]},
        {"type": "blockquote", "content": [para(text("q"))]},
    ))
    assert out == "<ul><li><p>a</p></li></ul><blockquote><p>q</p></blockquote>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/posts/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.posts'`.

- [ ] **Step 3: Implement**

`backend/app/modules/posts/render.py`:
```python
"""Whitelist renderer for TipTap JSON. Raw client HTML is never trusted."""

import html
import re

import nh3

_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\))$")
_FONT_SIZE = re.compile(r"^\d{1,2}(px|pt)$")
FONTS = {"Mukta", "Noto Sans Devanagari", "Inter"}
LINE_HEIGHTS = {"1", "1.15", "1.5", "2"}
ALIGNS = {"center", "right", "justify"}
LINK_SCHEMES = ("http://", "https://", "mailto:")

_STYLED = {"p", "h1", "h2", "h3", "h4", "span", "mark"}
ALLOWED_TAGS = _STYLED | {
    "strong", "em", "u", "s", "a", "ul", "ol", "li", "blockquote", "br", "hr", "figure", "img", "figcaption",
}
ALLOWED_ATTRS = {tag: {"style"} for tag in _STYLED} | {
    "a": {"href", "target"},
    "img": {"src", "alt", "loading"},
}
STYLE_PROPS = {"color", "background-color", "font-size", "font-family", "text-align", "line-height"}


def _valid(value: str | None, pattern: re.Pattern) -> str | None:
    return value if value and pattern.match(value) else None


def _style(pairs: dict[str, str | None]) -> str:
    parts = [f"{k}: {v}" for k, v in pairs.items() if v]
    return f' style="{html.escape("; ".join(parts))}"' if parts else ""


def _block_style(attrs: dict) -> str:
    align = attrs.get("textAlign")
    line_height = attrs.get("lineHeight")
    return _style({
        "text-align": align if align in ALIGNS else None,
        "line-height": line_height if line_height in LINE_HEIGHTS else None,
    })


def _render_text(node: dict) -> str:
    out = html.escape(node.get("text", ""))
    for mark in node.get("marks") or []:
        kind = mark.get("type")
        attrs = mark.get("attrs") or {}
        if kind == "bold":
            out = f"<strong>{out}</strong>"
        elif kind == "italic":
            out = f"<em>{out}</em>"
        elif kind == "underline":
            out = f"<u>{out}</u>"
        elif kind == "strike":
            out = f"<s>{out}</s>"
        elif kind == "highlight":
            out = f"<mark{_style({'background-color': _valid(attrs.get('color'), _COLOR)})}>{out}</mark>"
        elif kind == "textStyle":
            style = _style({
                "color": _valid(attrs.get("color"), _COLOR),
                "font-size": _valid(attrs.get("fontSize"), _FONT_SIZE),
                "font-family": attrs.get("fontFamily") if attrs.get("fontFamily") in FONTS else None,
            })
            if style:
                out = f"<span{style}>{out}</span>"
        elif kind == "link":
            href = attrs.get("href") or ""
            if href.startswith(LINK_SCHEMES):
                out = f'<a href="{html.escape(href)}" target="_blank">{out}</a>'
    return out


def _children(node: dict) -> str:
    return "".join(_render(child) for child in node.get("content") or [])


def _render(node: dict) -> str:
    attrs = node.get("attrs") or {}
    match node.get("type"):
        case "text":
            return _render_text(node)
        case "paragraph":
            return f"<p{_block_style(attrs)}>{_children(node)}</p>"
        case "heading":
            level = attrs.get("level") if attrs.get("level") in (1, 2, 3, 4) else 2
            return f"<h{level}{_block_style(attrs)}>{_children(node)}</h{level}>"
        case "bulletList":
            return f"<ul>{_children(node)}</ul>"
        case "orderedList":
            return f"<ol>{_children(node)}</ol>"
        case "listItem":
            return f"<li>{_children(node)}</li>"
        case "blockquote":
            return f"<blockquote>{_children(node)}</blockquote>"
        case "hardBreak":
            return "<br>"
        case "horizontalRule":
            return "<hr>"
        case "image":
            src = attrs.get("src") or ""
            if not (src.startswith("https://") or (src.startswith("/") and not src.startswith("//"))):
                return ""
            img = f'<img src="{html.escape(src)}" alt="{html.escape(attrs.get("alt") or "")}" loading="lazy">'
            caption = attrs.get("caption")
            return f"<figure>{img}<figcaption>{html.escape(caption)}</figcaption></figure>" if caption else f"<figure>{img}</figure>"
        case _:
            return _children(node)


def render_html(doc: dict) -> str:
    return nh3.clean(
        _render(doc),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        filter_style_properties=STYLE_PROPS,
        link_rel="noopener nofollow",
        url_schemes={"http", "https", "mailto"},
    )
```

> Note: if the installed `nh3` reformats `style` values (for example `color:#C8102E` without a space), the tests still pass because they assert on substrings. Do not loosen the tests if they fail for any other reason.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/posts/test_render.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(posts): whitelist TipTap JSON to sanitised HTML renderer"
```

---

### Task 5: Database models, session, Alembic, test DB fixtures

**Files:**
- Create: `backend/app/db/__init__.py`, `backend/app/db/base.py`, `backend/app/db/session.py`, `backend/app/db/outbox.py`, `backend/app/db/models.py`, `backend/app/modules/users/__init__.py`, `backend/app/modules/users/models.py`, `backend/app/modules/taxonomy/__init__.py`, `backend/app/modules/taxonomy/models.py`, `backend/app/modules/posts/models.py`, `backend/alembic.ini`, `backend/migrations/**`
- Modify: `backend/tests/conftest.py` (replace whole file)
- Test: `backend/tests/db/__init__.py`, `backend/tests/db/test_models.py`, `backend/tests/db/test_migrations.py`

**Interfaces:**
- Produces:
  - `app.db.base.Base`, `utcnow() -> datetime`
  - `app.db.session.get_session() -> AsyncIterator[AsyncSession]` (FastAPI dependency)
  - `Role(StrEnum)`: `reporter`, `editor`, `admin`; `User(id: UUID, email, password_hash, name, role: Role, is_active: bool, created_at)`
  - `Category(id: int, slug, name_ne, name_en)`
  - `PostStatus(StrEnum)`: `draft`, `in_review`, `scheduled`, `published`, `archived`
  - `Post(id: UUID, author_id, category_id, status, published_at, created_at, updated_at, translations: list[PostTranslation])` (translations eager via `selectin`)
  - `PostTranslation(id: int, post_id, locale, title, slug, content_json: dict, content_html, seo_title, seo_description, seo_auto: dict, post)`; unique `(locale, slug)` and `(post_id, locale)`
  - `OutboxEvent(id, topic, payload: dict, created_at, processed_at)`
  - Test fixtures: `pg_url` (session), `engine` (session), `session` (per test, rolled back), `client` (app with `get_session` overridden)

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/conftest.py`:
```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.db.models import Base
from app.db.session import get_session
from app.main import create_app


def pytest_collection_modifyitems(items):
    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if pytest_asyncio.is_async_test(item):
            item.add_marker(marker, append=False)


@pytest.fixture(scope="session")
def pg_url():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest_asyncio.fixture(scope="session")
async def engine(pg_url):
    eng = create_async_engine(pg_url)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        yield s
        await s.close()
        await outer.rollback()


@pytest_asyncio.fixture
async def client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

`backend/tests/db/test_models.py`:
```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.posts.models import Post, PostStatus, PostTranslation
from app.modules.taxonomy.models import Category
from app.modules.users.models import Role, User

DOC = {"type": "doc", "content": []}


async def _author_and_category(session):
    user = User(email="a@mawapress.com", password_hash="x", name="A", role=Role.reporter)
    cat = Category(slug="morang", name_ne="मोरङ", name_en="Morang")
    session.add_all([user, cat])
    await session.flush()
    return user, cat


def _post(user, cat, locale, slug):
    post = Post(author_id=user.id, category_id=cat.id)
    post.translations.append(
        PostTranslation(locale=locale, title="t", slug=slug, content_json=DOC, content_html="")
    )
    return post


async def test_post_with_translation_roundtrip(session):
    user, cat = await _author_and_category(session)
    post = _post(user, cat, "ne", "shirshak")
    session.add(post)
    await session.flush()
    session.expunge_all()

    loaded = await session.get(Post, post.id)
    assert loaded.status == PostStatus.draft
    assert loaded.updated_at.tzinfo is not None
    assert [t.slug for t in loaded.translations] == ["shirshak"]


async def test_slug_unique_per_locale(session):
    user, cat = await _author_and_category(session)
    session.add_all([_post(user, cat, "ne", "same"), _post(user, cat, "ne", "same")])
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_same_slug_allowed_in_other_locale(session):
    user, cat = await _author_and_category(session)
    session.add_all([_post(user, cat, "ne", "same"), _post(user, cat, "en", "same")])
    await session.flush()
```

`backend/tests/db/test_migrations.py`:
```python
import os
import subprocess
import sys
from pathlib import Path

from testcontainers.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_head_on_empty_database():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        env = {**os.environ, "MAWA_DATABASE_URL": pg.get_connection_url()}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
        )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/db -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`.

- [ ] **Step 3: Implement models and session**

`backend/app/db/base.py`:
```python
from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)
```

`backend/app/db/session.py`:
```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

`backend/app/db/outbox.py`:
```python
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

`backend/app/modules/users/models.py`:
```python
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Role(StrEnum):
    reporter = "reporter"
    editor = "editor"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

`backend/app/modules/taxonomy/models.py`:
```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name_ne: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))
```

`backend/app/modules/posts/models.py`:
```python
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow


class PostStatus(StrEnum):
    draft = "draft"
    in_review = "in_review"
    scheduled = "scheduled"
    published = "published"
    archived = "archived"


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_status_published_at", "status", "published_at"),
        Index("ix_posts_category_published_at", "category_id", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    status: Mapped[PostStatus] = mapped_column(Enum(PostStatus, name="post_status"), default=PostStatus.draft)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    translations: Mapped[list["PostTranslation"]] = relationship(
        back_populates="post", lazy="selectin", cascade="all, delete-orphan", order_by="PostTranslation.id"
    )


class PostTranslation(Base):
    __tablename__ = "post_translations"
    __table_args__ = (
        UniqueConstraint("locale", "slug", name="uq_translation_locale_slug"),
        UniqueConstraint("post_id", "locale", name="uq_translation_post_locale"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(String(2))
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(100))
    content_json: Mapped[dict] = mapped_column(JSONB)
    content_html: Mapped[str] = mapped_column(Text)
    seo_title: Mapped[str | None] = mapped_column(String(120))
    seo_description: Mapped[str | None] = mapped_column(String(320))
    seo_auto: Mapped[dict] = mapped_column(JSONB, default=dict)

    post: Mapped[Post] = relationship(back_populates="translations")
```

`backend/app/db/models.py`:
```python
"""Import every model so Base.metadata is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.db.outbox import OutboxEvent
from app.modules.posts.models import Post, PostTranslation
from app.modules.taxonomy.models import Category
from app.modules.users.models import User

__all__ = ["Base", "Category", "OutboxEvent", "Post", "PostTranslation", "User"]
```

Create the empty `__init__.py` files for `app/db`, `app/modules/users`, `app/modules/taxonomy` and `tests/db`.

- [ ] **Step 4: Run model tests to verify they pass**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: 3 passed (the first run pulls the `postgres:17-alpine` image).

- [ ] **Step 5: Set up Alembic and generate the first migration**

```bash
uv run alembic init -t async migrations
```

In `backend/migrations/env.py`, replace the block from `config = context.config` through `target_metadata = None` with:
```python
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.core.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```

Then generate the migration against the empty dev database:
```bash
docker compose -f ../docker-compose.yml up -d postgres
uv run alembic revision --autogenerate -m "content core"
uv run alembic upgrade head
```
Expected: `migrations/versions/<rev>_content_core.py` creates `users`, `categories`, `posts`, `post_translations` and `outbox`, plus the `user_role` and `post_status` enums. Open the file and check that all 5 tables are present.

- [ ] **Step 6: Run all DB tests**

Run: `uv run pytest tests/db tests/test_health.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(db): content core models, async session, alembic migration and test fixtures"
```

---

### Task 6: Authentication and role guards

**Files:**
- Create: `backend/app/modules/auth/__init__.py`, `backend/app/modules/auth/security.py`, `backend/app/modules/auth/deps.py`, `backend/app/modules/auth/router.py`, `backend/tests/factories.py`
- Modify: `backend/app/main.py` (include auth router)
- Test: `backend/tests/auth/__init__.py`, `backend/tests/auth/test_auth.py`

**Interfaces:**
- Consumes: `User`, `Role`, `get_session`, `AppError`, `get_settings`, `utcnow`.
- Produces:
  - `hash_password(p: str) -> str`, `verify_password(p: str, h: str) -> bool`
  - `create_access_token(user_id: UUID, role: str) -> str`, `decode_access_token(token: str) -> dict`
  - `ROLE_RANK: dict[Role, int]`
  - `current_user` dependency → `User` (401 `NOT_AUTHENTICATED` / `INVALID_TOKEN`)
  - `require_role(min_role: Role)` → dependency returning `User` (403 `FORBIDDEN_ROLE`)
  - `POST /api/auth/login` `{email, password}` → `{access_token, token_type: "bearer"}` (401 `INVALID_CREDENTIALS`)
  - `GET /api/auth/me` → `{id, email, name, role}`
  - `tests.factories`: `make_user(session, *, role=Role.reporter, email=None, password="secret-pass-1", name="Test User", is_active=True) -> User`, `make_category(session, slug="morang", name_ne="मोरङ", name_en="Morang") -> Category`, `auth_header(user) -> dict`

- [ ] **Step 1: Write the factories and failing tests**

`backend/tests/factories.py`:
```python
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.security import create_access_token, hash_password
from app.modules.taxonomy.models import Category
from app.modules.users.models import Role, User


async def make_user(
    session: AsyncSession,
    *,
    role: Role = Role.reporter,
    email: str | None = None,
    password: str = "secret-pass-1",
    name: str = "Test User",
    is_active: bool = True,
) -> User:
    user = User(
        email=(email or f"{uuid.uuid4().hex[:10]}@mawapress.com").lower(),
        password_hash=hash_password(password),
        name=name,
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


async def make_category(session: AsyncSession, slug: str = "morang", name_ne: str = "मोरङ", name_en: str = "Morang") -> Category:
    cat = Category(slug=slug, name_ne=name_ne, name_en=name_en)
    session.add(cat)
    await session.flush()
    return cat


def auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.value)}"}
```

`backend/tests/auth/test_auth.py`:
```python
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.main import create_app
from app.modules.auth.deps import require_role
from app.modules.users.models import Role, User
from tests.factories import auth_header, make_user


async def test_login_returns_token_usable_on_me(client, session):
    await make_user(session, email="editor@mawapress.com", role=Role.editor, password="correct-horse-1")
    r = await client.post("/api/auth/login", json={"email": "Editor@Mawapress.com", "password": "correct-horse-1"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "editor@mawapress.com"
    assert me.json()["role"] == "editor"


async def test_wrong_password_unknown_email_and_inactive_all_401(client, session):
    await make_user(session, email="a@mawapress.com", password="right-pass-1")
    await make_user(session, email="off@mawapress.com", password="right-pass-1", is_active=False)
    for email, pw in [("a@mawapress.com", "nope"), ("ghost@mawapress.com", "x"), ("off@mawapress.com", "right-pass-1")]:
        r = await client.post("/api/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_me_requires_valid_token(client):
    assert (await client.get("/api/auth/me")).json()["error"]["code"] == "NOT_AUTHENTICATED"
    r = await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_require_role_blocks_lower_roles(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    @app.get("/editor-only")
    async def editor_only(user: User = Depends(require_role(Role.editor))):
        return {"ok": True}

    reporter = await make_user(session, role=Role.reporter)
    editor = await make_user(session, role=Role.editor)
    admin = await make_user(session, role=Role.admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        denied = await c.get("/editor-only", headers=auth_header(reporter))
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "FORBIDDEN_ROLE"
        assert (await c.get("/editor-only", headers=auth_header(editor))).status_code == 200
        assert (await c.get("/editor-only", headers=auth_header(admin))).status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/auth -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.auth'`.

- [ ] **Step 3: Implement**

`backend/app/modules/auth/security.py`:
```python
import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.db.base import utcnow

_hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = utcnow()
    claims = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(minutes=settings.jwt_access_minutes)}
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
```

`backend/app/modules/auth/deps.py`:
```python
import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.security import decode_access_token
from app.modules.users.models import Role, User

ROLE_RANK = {Role.reporter: 1, Role.editor: 2, Role.admin: 3}
_bearer = HTTPBearer(auto_error=False)


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None:
        raise AppError(401, "NOT_AUTHENTICATED", "Login required")
    try:
        claims = decode_access_token(creds.credentials)
        user = await session.get(User, uuid.UUID(claims["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if user is None or not user.is_active:
        raise AppError(401, "INVALID_TOKEN", "Token is invalid or expired")
    return user


def require_role(min_role: Role):
    async def dependency(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[min_role]:
            raise AppError(403, "FORBIDDEN_ROLE", f"Requires {min_role.value} role or higher")
        return user

    return dependency
```

`backend/app/modules/auth/router.py`:
```python
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.deps import current_user
from app.modules.auth.security import create_access_token, verify_password
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: Role


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
    return TokenOut(access_token=create_access_token(user.id, user.role.value))


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(current_user)) -> User:
    return user
```

Modify `backend/app/main.py`. Add the import, and include the router after `register_error_handlers(app)`:
```python
from app.modules.auth.router import router as auth_router
...
    register_error_handlers(app)
    app.include_router(auth_router)
```

Create the empty `app/modules/auth/__init__.py` and `tests/auth/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/auth -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(auth): argon2 login, JWT access tokens and role guards"
```

---

### Task 7: Posts API — create, edit with optimistic locking, submit, publish

**Files:**
- Create: `backend/app/modules/posts/schemas.py`, `backend/app/modules/posts/service.py`, `backend/app/modules/posts/router.py`
- Modify: `backend/app/main.py` (include posts router)
- Test: `backend/tests/posts/test_posts_api.py`

**Interfaces:**
- Consumes: `make_slug` (Task 2), `build_seo`, `SeoInput` (Task 3), `render_html` (Task 4), models (Task 5), `require_role`, `ROLE_RANK` (Task 6), `get_settings`, `AppError`, `utcnow`.
- Produces:
  - Schemas `PostCreate(locale, title, content_json, category_id)`, `PostUpdate(locale, title?, content_json?, seo_title?, seo_description?)`, `TranslationOut`, `PostOut(id, status, author_id, category_id, published_at, updated_at, translations)`
  - Service: `create_post(session, author, data) -> Post`, `get_post(session, post_id) -> Post`, `update_post(session, user, post_id, if_match, data) -> Post`, `submit_post(session, user, post_id) -> Post`, `publish_post(session, post_id) -> Post`, `unique_slug(session, locale, base, exclude_id=None) -> str`
  - Endpoints: `POST /api/posts` (201), `GET /api/posts/{id}`, `PATCH /api/posts/{id}` (header `If-Match: <updated_at>`), `POST /api/posts/{id}/submit`, `POST /api/posts/{id}/publish` (editor+)
  - On publish: one `OutboxEvent(topic="post.published", payload={"post_id", "category_id", "slugs": {locale: slug}})`
  - Error codes: `CATEGORY_NOT_FOUND` 422, `POST_NOT_FOUND` 404, `FORBIDDEN_ROLE` 403, `PRECONDITION_REQUIRED` 428, `VERSION_CONFLICT` 412, `TRANSLATION_INCOMPLETE` 422, `INVALID_TRANSITION` 409

- [ ] **Step 1: Write the failing tests**

`backend/tests/posts/test_posts_api.py`:
```python
from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.users.models import Role
from tests.factories import auth_header, make_category, make_user


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def create(client, user, category, title="बाढी समाचार", locale="ne", body="पानी परिरहेको छ"):
    return await client.post(
        "/api/posts",
        json={"locale": locale, "title": title, "content_json": doc(body), "category_id": category.id},
        headers=auth_header(user),
    )


async def test_reporter_creates_draft_with_slug_html_and_seo(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    r = await create(client, reporter, cat)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    tr = body["translations"][0]
    assert tr["slug"] == "badhi-samachar"
    assert tr["content_html"] == "<p>पानी परिरहेको छ</p>"
    assert tr["seo_auto"]["title"] == "बाढी समाचार | मावाप्रेस"
    assert tr["seo_auto"]["canonical"].endswith("/ne/morang/badhi-samachar")


async def test_duplicate_title_gets_numbered_slug(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    await create(client, reporter, cat)
    second = await create(client, reporter, cat)
    assert second.json()["translations"][0]["slug"] == "badhi-samachar-2"


async def test_unknown_category_is_422(client, session):
    reporter = await make_user(session)
    r = await client.post(
        "/api/posts",
        json={"locale": "ne", "title": "x", "content_json": doc("y"), "category_id": 999999},
        headers=auth_header(reporter),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CATEGORY_NOT_FOUND"


async def test_update_requires_current_if_match(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    url = f"/api/posts/{post['id']}"
    patch = {"locale": "ne", "title": "मोरङ समाचार"}

    missing = await client.patch(url, json=patch, headers=auth_header(reporter))
    assert missing.status_code == 428

    stale = await client.patch(url, json=patch, headers={**auth_header(reporter), "If-Match": "2020-01-01T00:00:00Z"})
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

    ok = await client.patch(url, json=patch, headers={**auth_header(reporter), "If-Match": post["updated_at"]})
    assert ok.status_code == 200
    assert ok.json()["translations"][0]["slug"] == "morang-samachar"
    assert ok.json()["updated_at"] != post["updated_at"]


async def test_adding_english_translation_links_hreflang(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": "Flood in Biratnagar", "content_json": doc("It is raining")},
        headers={**auth_header(reporter), "If-Match": post["updated_at"]},
    )
    assert r.status_code == 200
    ne, en = r.json()["translations"]
    assert en["slug"] == "flood-in-biratnagar"
    assert set(ne["seo_auto"]["hreflang"]) == {"ne", "en", "x-default"}
    assert en["seo_auto"]["hreflang"]["ne"].endswith("/ne/morang/badhi-samachar")


async def test_new_translation_needs_title_and_content(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": "Only title"},
        headers={**auth_header(reporter), "If-Match": post["updated_at"]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "TRANSLATION_INCOMPLETE"


async def test_reporter_cannot_edit_someone_elses_post(client, session):
    author = await make_user(session)
    other = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, author, cat)).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "ne", "title": "hack"},
        headers={**auth_header(other), "If-Match": post["updated_at"]},
    )
    assert r.status_code == 403


async def test_submit_then_editor_publishes_and_outbox_written(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()

    submitted = await client.post(f"/api/posts/{post['id']}/submit", headers=auth_header(reporter))
    assert submitted.json()["status"] == "in_review"
    again = await client.post(f"/api/posts/{post['id']}/submit", headers=auth_header(reporter))
    assert again.status_code == 409

    denied = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(reporter))
    assert denied.status_code == 403

    published = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None

    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.published"))).all()
    assert len(events) == 1
    assert events[0].payload["slugs"] == {"ne": "badhi-samachar"}


async def test_slug_is_frozen_after_publish(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    published = (await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers={**auth_header(editor), "If-Match": published["updated_at"]},
    )
    assert r.json()["translations"][0]["title"] == "नयाँ शीर्षक"
    assert r.json()["translations"][0]["slug"] == "badhi-samachar"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/posts/test_posts_api.py -v`
Expected: FAIL. Every request returns 404 because `/api/posts` is not routed yet.

- [ ] **Step 3: Implement schemas**

`backend/app/modules/posts/schemas.py`:
```python
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.posts.models import PostStatus

Locale = Literal["ne", "en"]


class PostCreate(BaseModel):
    locale: Locale
    title: str = Field(min_length=1, max_length=300)
    content_json: dict
    category_id: int


class PostUpdate(BaseModel):
    locale: Locale
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content_json: dict | None = None
    seo_title: str | None = Field(default=None, max_length=120)
    seo_description: str | None = Field(default=None, max_length=320)


class TranslationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    title: str
    slug: str
    content_json: dict
    content_html: str
    seo_title: str | None
    seo_description: str | None
    seo_auto: dict


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: PostStatus
    author_id: uuid.UUID
    category_id: int
    published_at: datetime | None
    updated_at: datetime
    translations: list[TranslationOut]
```

- [ ] **Step 4: Implement the service**

`backend/app/modules/posts/service.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.auth.deps import ROLE_RANK
from app.modules.posts.models import Post, PostStatus, PostTranslation
from app.modules.posts.render import render_html
from app.modules.posts.schemas import PostCreate, PostUpdate
from app.modules.seo.generator import SeoInput, build_seo
from app.modules.seo.slug import make_slug
from app.modules.taxonomy.models import Category
from app.modules.users.models import Role, User


def _is_editor(user: User) -> bool:
    return ROLE_RANK[user.role] >= ROLE_RANK[Role.editor]


async def unique_slug(session: AsyncSession, locale: str, base: str, exclude_id: int | None = None) -> str:
    stmt = select(PostTranslation.slug).where(
        PostTranslation.locale == locale,
        or_(PostTranslation.slug == base, PostTranslation.slug.like(f"{base}-%")),
    )
    if exclude_id is not None:
        stmt = stmt.where(PostTranslation.id != exclude_id)
    taken = set((await session.scalars(stmt)).all())
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def _refresh_all_seo(session: AsyncSession, post: Post) -> None:
    category = await session.get(Category, post.category_id)
    author = await session.get(User, post.author_id)
    site_url = get_settings().site_url
    for tr in post.translations:
        alternates = {t.locale: t.slug for t in post.translations if t.locale != tr.locale}
        meta = build_seo(
            SeoInput(
                locale=tr.locale,
                title=tr.title,
                html=tr.content_html,
                slug=tr.slug,
                category_slug=category.slug,
                category_name=category.name_ne if tr.locale == "ne" else category.name_en,
                author_name=author.name,
                published_at=post.published_at,
                modified_at=post.updated_at,
                seo_title=tr.seo_title,
                seo_description=tr.seo_description,
                alternate_slugs=alternates,
            ),
            site_url,
        )
        tr.seo_auto = meta.to_dict()


async def _save(session: AsyncSession, post: Post) -> Post:
    await session.flush()
    await _refresh_all_seo(session, post)
    await session.commit()
    return post


async def get_post(session: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await session.get(Post, post_id)
    if post is None:
        raise AppError(404, "POST_NOT_FOUND", "Post not found")
    return post


async def create_post(session: AsyncSession, author: User, data: PostCreate) -> Post:
    if await session.get(Category, data.category_id) is None:
        raise AppError(422, "CATEGORY_NOT_FOUND", "Category does not exist")
    post = Post(author_id=author.id, category_id=data.category_id, status=PostStatus.draft)
    session.add(post)
    post.translations.append(
        PostTranslation(
            locale=data.locale,
            title=data.title,
            slug=await unique_slug(session, data.locale, make_slug(data.title)),
            content_json=data.content_json,
            content_html=render_html(data.content_json),
        )
    )
    return await _save(session, post)


def _check_version(post: Post, if_match: str | None) -> None:
    if if_match is None:
        raise AppError(428, "PRECONDITION_REQUIRED", "If-Match header with updated_at is required")
    try:
        sent = datetime.fromisoformat(if_match.strip('"'))
    except ValueError:
        sent = None
    if sent != post.updated_at:
        raise AppError(412, "VERSION_CONFLICT", "Post was changed by someone else",
                       {"current_updated_at": post.updated_at.isoformat()})


async def update_post(session: AsyncSession, user: User, post_id: uuid.UUID, if_match: str | None, data: PostUpdate) -> Post:
    post = await get_post(session, post_id)
    own_draft = post.author_id == user.id and post.status == PostStatus.draft
    if not (_is_editor(user) or own_draft):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot edit this post")
    _check_version(post, if_match)

    tr = next((t for t in post.translations if t.locale == data.locale), None)
    if tr is None:
        if data.title is None or data.content_json is None:
            raise AppError(422, "TRANSLATION_INCOMPLETE", "A new translation needs title and content_json")
        tr = PostTranslation(
            locale=data.locale,
            title=data.title,
            slug=await unique_slug(session, data.locale, make_slug(data.title)),
            content_json=data.content_json,
            content_html=render_html(data.content_json),
        )
        post.translations.append(tr)
    else:
        if data.title is not None and data.title != tr.title:
            tr.title = data.title
            if post.status != PostStatus.published:
                tr.slug = await unique_slug(session, tr.locale, make_slug(data.title), exclude_id=tr.id)
        if data.content_json is not None:
            tr.content_json = data.content_json
            tr.content_html = render_html(data.content_json)
    if "seo_title" in data.model_fields_set:
        tr.seo_title = data.seo_title or None
    if "seo_description" in data.model_fields_set:
        tr.seo_description = data.seo_description or None

    post.updated_at = utcnow()
    return await _save(session, post)


async def submit_post(session: AsyncSession, user: User, post_id: uuid.UUID) -> Post:
    post = await get_post(session, post_id)
    if not (_is_editor(user) or post.author_id == user.id):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot submit this post")
    if post.status != PostStatus.draft:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot submit a post that is {post.status.value}")
    post.status = PostStatus.in_review
    post.updated_at = utcnow()
    return await _save(session, post)


async def publish_post(session: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await get_post(session, post_id)
    if post.status not in (PostStatus.draft, PostStatus.in_review):
        raise AppError(409, "INVALID_TRANSITION", f"Cannot publish a post that is {post.status.value}")
    now = utcnow()
    post.status = PostStatus.published
    post.published_at = post.published_at or now
    post.updated_at = now
    session.add(OutboxEvent(
        topic="post.published",
        payload={
            "post_id": str(post.id),
            "category_id": post.category_id,
            "slugs": {t.locale: t.slug for t in post.translations},
        },
    ))
    return await _save(session, post)
```

- [ ] **Step 5: Implement the router and wire it in**

`backend/app/modules/posts/router.py`:
```python
import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.deps import ROLE_RANK, require_role
from app.modules.posts import service
from app.modules.posts.models import Post
from app.modules.posts.schemas import PostCreate, PostOut, PostUpdate
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api/posts", tags=["posts"])
any_staff = require_role(Role.reporter)
editors = require_role(Role.editor)


@router.post("", response_model=PostOut, status_code=201)
async def create_post(body: PostCreate, user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)) -> Post:
    return await service.create_post(session, user, body)


@router.get("/{post_id}", response_model=PostOut)
async def get_post(post_id: uuid.UUID, user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)) -> Post:
    post = await service.get_post(session, post_id)
    if post.author_id != user.id and ROLE_RANK[user.role] < ROLE_RANK[Role.editor]:
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot view this post")
    return post


@router.patch("/{post_id}", response_model=PostOut)
async def update_post(
    post_id: uuid.UUID,
    body: PostUpdate,
    if_match: str | None = Header(default=None),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
) -> Post:
    return await service.update_post(session, user, post_id, if_match, body)


@router.post("/{post_id}/submit", response_model=PostOut)
async def submit_post(post_id: uuid.UUID, user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)) -> Post:
    return await service.submit_post(session, user, post_id)


@router.post("/{post_id}/publish", response_model=PostOut)
async def publish_post(post_id: uuid.UUID, user: User = Depends(editors), session: AsyncSession = Depends(get_session)) -> Post:
    return await service.publish_post(session, post_id)
```

Modify `backend/app/main.py`, adding the import and `app.include_router(posts_router)` after the auth router:
```python
from app.modules.posts.router import router as posts_router
...
    app.include_router(posts_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/posts -v`
Expected: 19 passed (10 render + 9 API).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(posts): post workflow API with auto slug, SEO, optimistic locking and outbox"
```

---

### Task 8: Cached public post endpoint with invalidation

**Files:**
- Create: `backend/app/core/cache.py`, `backend/app/modules/public/__init__.py`, `backend/app/modules/public/router.py`
- Modify: `backend/app/modules/posts/router.py` (invalidate cache on update/publish), `backend/app/main.py` (include public router), `backend/tests/conftest.py` (override Redis in `client`)
- Test: `backend/tests/public/__init__.py`, `backend/tests/public/test_public_api.py`

**Interfaces:**
- Consumes: `Post`, `PostTranslation`, `PostStatus`, `Category`, `User`, `get_session`, `AppError`.
- Produces:
  - `app.core.cache.get_redis() -> redis.asyncio.Redis` (FastAPI dependency; `decode_responses=True`)
  - `app.modules.public.router.post_cache_key(locale: str, slug: str) -> str` = `"public:post:{locale}:{slug}"`
  - `invalidate_post_cache(redis, post: Post) -> None`
  - `GET /api/public/posts/{locale}/{slug}` → `PublicPostOut(id, locale, title, slug, content_html, category_slug, author_name, published_at, updated_at, seo: dict, alternates: dict[str, str])`, headers `X-Cache: HIT|MISS` and `Cache-Control: public, s-maxage=60, stale-while-revalidate=86400`; 404 `POST_NOT_FOUND` unless published.

- [ ] **Step 1: Override Redis in test client and write failing tests**

In `backend/tests/conftest.py`, add these imports:
```python
from fakeredis import FakeAsyncRedis

from app.core.cache import get_redis
```
and replace the `client` fixture with:
```python
@pytest_asyncio.fixture
async def fake_redis():
    r = FakeAsyncRedis(decode_responses=True)
    yield r
    await r.flushall()
    await r.aclose()


@pytest_asyncio.fixture
async def client(session, fake_redis):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

`backend/tests/public/test_public_api.py`:
```python
from app.modules.users.models import Role
from tests.factories import auth_header, make_category, make_user


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def published_post(client, session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    cat = await make_category(session)
    post = (await client.post(
        "/api/posts",
        json={"locale": "ne", "title": "बाढी समाचार", "content_json": doc("पानी"), "category_id": cat.id},
        headers=auth_header(editor),
    )).json()
    published = (await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))).json()
    return editor, published


async def test_published_post_is_served_then_cached(client, session):
    await published_post(client, session)
    first = await client.get("/api/public/posts/ne/badhi-samachar")
    assert first.status_code == 200
    assert first.headers["x-cache"] == "MISS"
    assert first.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    body = first.json()
    assert body["title"] == "बाढी समाचार"
    assert body["author_name"] == "Sita Rai"
    assert body["category_slug"] == "morang"
    assert body["seo"]["json_ld"][0]["@type"] == "NewsArticle"

    second = await client.get("/api/public/posts/ne/badhi-samachar")
    assert second.headers["x-cache"] == "HIT"
    assert second.json() == body


async def test_draft_is_not_public(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    draft = (await client.post(
        "/api/posts",
        json={"locale": "ne", "title": "गोप्य मस्यौदा", "content_json": doc("x"), "category_id": cat.id},
        headers=auth_header(reporter),
    )).json()
    r = await client.get(f"/api/public/posts/ne/{draft['translations'][0]['slug']}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "POST_NOT_FOUND"


async def test_editing_published_post_invalidates_cache(client, session):
    editor, published = await published_post(client, session)
    await client.get("/api/public/posts/ne/badhi-samachar")  # warm cache

    await client.patch(
        f"/api/posts/{published['id']}",
        json={"locale": "ne", "title": "विराटनगरमा भीषण बाढी"},
        headers={**auth_header(editor), "If-Match": published["updated_at"]},
    )
    r = await client.get("/api/public/posts/ne/badhi-samachar")
    assert r.headers["x-cache"] == "MISS"
    assert r.json()["title"] == "विराटनगरमा भीषण बाढी"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/public -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.cache'`.

- [ ] **Step 3: Implement cache and public router**

`backend/app/core/cache.py`:
```python
from redis.asyncio import Redis

from app.core.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis
```

`backend/app/modules/public/router.py`:
```python
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.errors import AppError
from app.db.session import get_session
from app.modules.posts.models import Post, PostStatus, PostTranslation
from app.modules.taxonomy.models import Category
from app.modules.users.models import User

router = APIRouter(prefix="/api/public", tags=["public"])
CACHE_TTL_SECONDS = 60
CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=86400"


class PublicPostOut(BaseModel):
    id: uuid.UUID
    locale: str
    title: str
    slug: str
    content_html: str
    category_slug: str
    author_name: str
    published_at: datetime | None
    updated_at: datetime
    seo: dict
    alternates: dict[str, str]


def post_cache_key(locale: str, slug: str) -> str:
    return f"public:post:{locale}:{slug}"


async def invalidate_post_cache(redis: Redis, post: Post) -> None:
    keys = [post_cache_key(t.locale, t.slug) for t in post.translations]
    if keys:
        await redis.delete(*keys)


@router.get("/posts/{locale}/{slug}", response_model=PublicPostOut)
async def get_public_post(
    locale: Literal["ne", "en"],
    slug: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> PublicPostOut:
    response.headers["Cache-Control"] = CACHE_CONTROL
    key = post_cache_key(locale, slug)
    if cached := await redis.get(key):
        response.headers["X-Cache"] = "HIT"
        return PublicPostOut.model_validate_json(cached)

    row = (await session.execute(
        select(PostTranslation, Post)
        .join(Post, PostTranslation.post_id == Post.id)
        .where(PostTranslation.locale == locale, PostTranslation.slug == slug, Post.status == PostStatus.published)
    )).first()
    if row is None:
        raise AppError(404, "POST_NOT_FOUND", "Post not found")
    tr, post = row
    category = await session.get(Category, post.category_id)
    author = await session.get(User, post.author_id)

    out = PublicPostOut(
        id=post.id,
        locale=tr.locale,
        title=tr.title,
        slug=tr.slug,
        content_html=tr.content_html,
        category_slug=category.slug,
        author_name=author.name,
        published_at=post.published_at,
        updated_at=post.updated_at,
        seo=tr.seo_auto,
        alternates={t.locale: t.slug for t in post.translations if t.locale != tr.locale},
    )
    await redis.set(key, out.model_dump_json(), ex=CACHE_TTL_SECONDS)
    response.headers["X-Cache"] = "MISS"
    return out
```

- [ ] **Step 4: Invalidate on update and publish, wire router**

In `backend/app/modules/posts/router.py`, add these imports:
```python
from redis.asyncio import Redis

from app.core.cache import get_redis
from app.modules.public.router import invalidate_post_cache
```
and replace the `update_post` and `publish_post` endpoints with:
```python
@router.patch("/{post_id}", response_model=PostOut)
async def update_post(
    post_id: uuid.UUID,
    body: PostUpdate,
    if_match: str | None = Header(default=None),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.update_post(session, user, post_id, if_match, body)
    await invalidate_post_cache(redis, post)
    return post


@router.post("/{post_id}/publish", response_model=PostOut)
async def publish_post(
    post_id: uuid.UUID,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.publish_post(session, post_id)
    await invalidate_post_cache(redis, post)
    return post
```

In `backend/app/main.py`, add:
```python
from app.modules.public.router import router as public_router
...
    app.include_router(public_router)
```

Create the empty `app/modules/public/__init__.py` and `tests/public/__init__.py`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all tests pass (2 health + 9 slug + 9 SEO + 10 render + 3 models + 1 migration + 4 auth + 9 posts API + 3 public = 50 passed).

- [ ] **Step 6: Smoke-run the server**

```bash
docker compose -f ../docker-compose.yml up -d
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/docs`. The Swagger UI should list the auth, posts and public routes. Stop the server with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(public): Redis-cached public post endpoint with CDN headers and invalidation"
```

---

## After M1

- Export the OpenAPI schema (`curl http://127.0.0.1:8000/openapi.json > contracts/openapi-v1.json`), then run the **Opus contract checkpoint** described in roadmap §3. After that, lanes A–D can start in parallel.
- Next plans to write (with `superpowers:writing-plans`): `m2-backend-completion`, `m3-admin-editor`, `m4-public-templates`, `m5-infra`.
