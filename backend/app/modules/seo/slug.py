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
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
}
INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ॐ": "om",
}
MATRAS = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o",
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
    for i, run in enumerate(re.split(r"([ऀ-ॣ०-ॿ]+)", text)):
        parts.append(_transliterate_word(run) if i % 2 else unidecode(run))
    return "".join(parts)


def make_slug(text: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", transliterate(text).lower()).strip("-")
    if len(slug) > max_len:
        cut = slug[:max_len]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else cut
    return slug or "post"
