"""Sitemaps, Google News sitemap and RSS. Built with ElementTree so user text is always escaped."""

import re
from datetime import datetime, timedelta
from email.utils import format_datetime
from xml.etree import ElementTree as ET

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.modules.posts.models import Post, PostTranslation
from app.modules.public.feeds import PUBLISHED_AT, card_query, category_feed, to_card, visible
from app.modules.seo.generator import BRAND, article_url
from app.modules.taxonomy import service as taxonomy_service
from app.modules.taxonomy.models import Category

LOCALES = ("ne", "en")
MAX_SITEMAP_URLS = 50_000
MAX_NEWS_URLS = 1000
NEWS_WINDOW = timedelta(hours=48)
RSS_ITEMS = 50
MONTH_PATTERN = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML_NS = "http://www.w3.org/1999/xhtml"
NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
DC_NS = "http://purl.org/dc/elements/1.1/"
MEDIA_NS = "http://search.yahoo.com/mrss/"
RSS_DESCRIPTION = {"ne": "मावाप्रेसका ताजा समाचार", "en": "Latest news from MAWAPRESS"}

# Characters XML 1.0 cannot carry at all; an ElementTree dump with one of them would not parse.
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = _INVALID_XML.sub("", value)
    return el


def _dump(root: ET.Element) -> str:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _urlset(*extra_ns: tuple[str, str]) -> ET.Element:
    root = ET.Element("urlset", {"xmlns": SITEMAP_NS})
    for prefix, uri in extra_ns:
        root.set(f"xmlns:{prefix}", uri)
    return root


def _w3c(dt: datetime) -> str:
    return dt.isoformat()


def _absolute(site: str, url: str) -> str:
    return f"{site}{url}" if url.startswith("/") else url


def parse_month(value: str) -> tuple[datetime, datetime] | None:
    """[start, end) of a YYYY-MM month in UTC, or None when the value is not a real month."""
    m = MONTH_PATTERN.fullmatch(value)
    if m is None:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if year < 2000:
        return None
    start = datetime(year, month, 1, tzinfo=utcnow().tzinfo)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=start.tzinfo)
    return start, end


async def sitemap_index(session: AsyncSession, site: str) -> str:
    month = func.to_char(func.timezone("UTC", PUBLISHED_AT), "YYYY-MM")
    months = (await session.scalars(
        select(month).select_from(PostTranslation).join(Post, Post.id == PostTranslation.post_id)
        .where(*visible()).group_by(month).order_by(month)
    )).all()
    root = ET.Element("sitemapindex", {"xmlns": SITEMAP_NS})
    for label in months:
        _text(ET.SubElement(root, "sitemap"), "loc", f"{site}/sitemaps/posts-{label}.xml")
    _text(ET.SubElement(root, "sitemap"), "loc", f"{site}/sitemaps/categories.xml")
    return _dump(root)


async def month_sitemap(session: AsyncSession, site: str, start: datetime, end: datetime) -> str:
    rows = (await session.execute(
        select(
            PostTranslation.post_id, PostTranslation.locale, PostTranslation.slug,
            PostTranslation.updated_at, Category.slug.label("category_slug"),
        )
        .select_from(PostTranslation)
        .join(Post, Post.id == PostTranslation.post_id)
        .join(Category, Category.id == Post.category_id)
        .where(*visible(), PUBLISHED_AT >= start, PUBLISHED_AT < end)
        .order_by(PUBLISHED_AT, PostTranslation.id)
        .limit(MAX_SITEMAP_URLS)
    )).all()
    siblings: dict[object, dict[str, str]] = {}
    if rows:  # siblings may be published in another month, so they come from their own query
        for r in await session.execute(
            select(PostTranslation.post_id, PostTranslation.locale, PostTranslation.slug)
            .select_from(PostTranslation).join(Post, Post.id == PostTranslation.post_id)
            .where(*visible(), PostTranslation.post_id.in_({r.post_id for r in rows}))
        ):
            siblings.setdefault(r.post_id, {})[r.locale] = r.slug
    root = _urlset(("xhtml", XHTML_NS))
    for r in rows:
        url = ET.SubElement(root, "url")
        loc = article_url(site, r.locale, r.category_slug, r.slug)
        _text(url, "loc", loc)
        _text(url, "lastmod", _w3c(r.updated_at))
        alts = siblings.get(r.post_id, {})
        if len(alts) > 1:
            for locale in LOCALES:
                if locale in alts:
                    ET.SubElement(url, "xhtml:link", {
                        "rel": "alternate", "hreflang": locale,
                        "href": article_url(site, locale, r.category_slug, alts[locale]),
                    })
            default = "ne" if "ne" in alts else r.locale
            ET.SubElement(url, "xhtml:link", {
                "rel": "alternate", "hreflang": "x-default",
                "href": article_url(site, default, r.category_slug, alts[default]),
            })
    return _dump(root)


async def categories_sitemap(session: AsyncSession, site: str) -> str:
    cats = await taxonomy_service.all_categories(session)
    root = _urlset()
    for locale in LOCALES:
        for cat in cats.values():
            _text(ET.SubElement(root, "url"), "loc", f"{site}/{locale}/{cat.slug}")
    return _dump(root)


async def news_sitemap(session: AsyncSession, site: str) -> str:
    cutoff = utcnow() - NEWS_WINDOW
    items = []
    for locale in LOCALES:
        for r in await session.execute(
            card_query(locale).where(PUBLISHED_AT >= cutoff).order_by(PUBLISHED_AT.desc(), Post.id.desc())
            .limit(MAX_NEWS_URLS)
        ):
            items.append((locale, r))
    items.sort(key=lambda it: it[1].published_at, reverse=True)
    root = _urlset(("news", NEWS_NS))
    for locale, r in items[:MAX_NEWS_URLS]:
        url = ET.SubElement(root, "url")
        _text(url, "loc", article_url(site, locale, r.category_slug, r.slug))
        news = ET.SubElement(url, "news:news")
        pub = ET.SubElement(news, "news:publication")
        _text(pub, "news:name", BRAND[locale])
        _text(pub, "news:language", locale)
        _text(news, "news:publication_date", _w3c(r.published_at))
        _text(news, "news:title", r.title)
    return _dump(root)


async def rss_feed(session: AsyncSession, site: str, locale: str, category_slug: str | None) -> str:
    if category_slug is None:
        cards = [to_card(r) for r in await session.execute(
            card_query(locale).order_by(PUBLISHED_AT.desc(), Post.id.desc()).limit(RSS_ITEMS)
        )]
        title, link = BRAND[locale], f"{site}/{locale}"
    else:  # raises the 404 for an unknown category; includes descendants
        feed = await category_feed(session, category_slug, locale, limit=RSS_ITEMS, offset=0)
        cards = feed.items
        title = f"{feed.category.name} | {BRAND[locale]}"
        link = f"{site}/{locale}/{category_slug}"
    root = ET.Element("rss", {"version": "2.0", "xmlns:dc": DC_NS, "xmlns:media": MEDIA_NS})
    channel = ET.SubElement(root, "channel")
    _text(channel, "title", title)
    _text(channel, "link", link)
    _text(channel, "description", RSS_DESCRIPTION[locale])
    _text(channel, "language", locale)
    for card in cards:
        item = ET.SubElement(channel, "item")
        url = article_url(site, locale, card.category_slug, card.slug)
        _text(item, "title", card.title)
        _text(item, "link", url)
        guid = _text(item, "guid", url)
        guid.set("isPermaLink", "true")
        if card.published_at is not None:
            _text(item, "pubDate", format_datetime(card.published_at.astimezone(utcnow().tzinfo), usegmt=False))
        _text(item, "description", card.excerpt)
        _text(item, "dc:creator", card.author_name)
        if card.image is not None:
            ET.SubElement(item, "media:content", {"url": _absolute(site, card.image.url), "medium": "image"})
    return _dump(root)
