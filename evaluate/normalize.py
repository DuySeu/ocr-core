"""Text normalization for scoring: two ladders, both applied to both sides.

Strict is the reporting default. Tone-blind strips only the five Vietnamese tone
marks and keeps the vowel-quality marks (ă â ê ô ơ ư) and ``đ`` — those are
different letters, not tones, so folding them in would hide the very distinction
the second CER exists to expose.

Tone placement is canonicalized toward the traditional style (``hoà`` -> ``hòa``).
Both spellings are correct Vietnamese; scoring one against the other measures the
transcriber, not the OCR.
"""

from __future__ import annotations

import re
import unicodedata

# The five tone marks, as combining codepoints. Everything else survives NFD.
TONE_MARKS = frozenset(
    (
        "\u0300",  # huyen  (grave)
        "\u0301",  # sac    (acute)
        "\u0303",  # nga    (tilde)
        "\u0309",  # hoi    (hook above)
        "\u0323",  # nang   (dot below)
    )
)

# Modern placement (mark on the second vowel) -> traditional (on the first).
# Explicit pairs rather than a generated rule, so the table reads by eye.
TONE_PLACEMENT_PAIRS = (
    ("oà", "òa"),
    ("oá", "óa"),
    ("oả", "ỏa"),
    ("oã", "õa"),
    ("oạ", "ọa"),
    ("oè", "òe"),
    ("oé", "óe"),
    ("oẻ", "ỏe"),
    ("oẽ", "õe"),
    ("oẹ", "ọe"),
    ("uỳ", "ùy"),
    ("uý", "úy"),
    ("uỷ", "ủy"),
    ("uỹ", "ũy"),
    ("uỵ", "ụy"),
)

TONE_PLACEMENT = {
    form(src): form(dst)
    for src, dst in TONE_PLACEMENT_PAIRS
    for form in (str.lower, str.capitalize, str.upper)
}

# Two guards, both required to avoid corrupting correct spellings:
#   - in "qu" the u is a glide, so "quý" is already right and must not become "qúy"
#   - the variation only exists in open syllables; once a final consonant follows,
#     "khoản" / "hoạt" / "hoàng" have exactly one correct form and must be left alone
NOT_AFTER_Q = r"(?<![qQ])"
NOT_BEFORE_LETTER = r"(?![^\W\d_])"
TONE_PLACEMENT_RE = re.compile(
    "|".join(
        (NOT_AFTER_Q if src[0] in "uU" else "") + re.escape(src) + NOT_BEFORE_LETTER
        for src in TONE_PLACEMENT
    )
)

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Inline tags sit inside a word: m<sup>2</sup> is one token, so they vanish without
# a trace. Every other tag separates content and becomes a space, or <td>a</td><td>b</td>
# would run together into one word.
INLINE_TAGS = "sup|sub|b|i|u|em|strong|span|a|code|small|mark"
INLINE_TAG_RE = re.compile(rf"</?(?:{INLINE_TAGS})(?:\s[^>]*)?>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
# Images are dropped whole, alt text included. A caption an engine wrote for a
# figure is the engine describing the page, not transcribing it, and ground truth
# carries no counterpart — scoring it charges the model for text nobody asked for.
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
BULLET_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+\.)[ \t]+", re.MULTILINE)
EMPHASIS_RE = re.compile(r"[*_`]+")
WHITESPACE_RE = re.compile(r"\s+")


# Normalize text for the strict CER/WER ladder.
def strict(text: str) -> str:
    # Compose first so the tone-placement table matches precomposed characters
    out = unicodedata.normalize("NFC", text)

    # Drop markup: comments and images before links, since ![x](y) contains [x](y)
    out = HTML_COMMENT_RE.sub(" ", out)
    out = IMAGE_RE.sub(" ", out)
    out = LINK_RE.sub(r"\1", out)
    out = INLINE_TAG_RE.sub("", out)
    out = HTML_TAG_RE.sub(" ", out)
    out = HEADING_RE.sub("", out)
    out = BULLET_RE.sub("", out)
    out = EMPHASIS_RE.sub("", out)

    # Canonicalize tone placement, then flatten whitespace
    out = TONE_PLACEMENT_RE.sub(lambda m: TONE_PLACEMENT[m.group(0)], out)
    return WHITESPACE_RE.sub(" ", out).strip()


# Normalize text for the tone-blind CER ladder: strict, minus the five tone marks.
def tone_blind(text: str) -> str:
    # Decompose so tone marks stand alone, drop only those five, recompose
    decomposed = unicodedata.normalize("NFD", strict(text))
    return unicodedata.normalize("NFC", "".join(c for c in decomposed if c not in TONE_MARKS))
