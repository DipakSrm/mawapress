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
