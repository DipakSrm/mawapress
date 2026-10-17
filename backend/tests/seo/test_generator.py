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


def test_missing_published_at_falls_back_to_modified_at():
    later = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    article = build_seo(make_input(published_at=None, modified_at=later), SITE).json_ld[0]
    assert article["datePublished"] == later.isoformat()
    assert article["dateModified"] == later.isoformat()


def test_english_primary_hreflang_keeps_x_default_on_nepali():
    meta = build_seo(
        make_input(locale="en", title="Heavy rain in Biratnagar", slug="heavy-rain-in-biratnagar",
                   category_name="Morang", alternate_slugs={"ne": "biratnagarma-bhari-barsha"}),
        SITE,
    )
    assert meta.canonical == f"{SITE}/en/morang/heavy-rain-in-biratnagar"
    assert meta.hreflang == {
        "en": f"{SITE}/en/morang/heavy-rain-in-biratnagar",
        "ne": f"{SITE}/ne/morang/biratnagarma-bhari-barsha",
        "x-default": f"{SITE}/ne/morang/biratnagarma-bhari-barsha",
    }
    assert meta.json_ld[0]["inLanguage"] == "en"


def test_seo_title_passes_through_verbatim():
    custom = "Election results 2082: every Morang constituency, live and updated through the night"
    meta = build_seo(make_input(locale="en", seo_title=custom), SITE)
    assert meta.title == custom  # no truncation and no brand suffix
