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
