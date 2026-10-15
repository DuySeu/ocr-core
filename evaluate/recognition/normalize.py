"""Text normalization for the Recognition tier, applied identically to both sides.

Three functions, one per stage of the ladder in evaluate/README.md:

- ``mark_images`` (GT only, WER only) turns each ``<!-- image -->`` marker into a
  placeholder word that survives every later step, so WER can treat it as a wildcard.
- ``strip_figures`` (steps 1-4) drops what describes a figure rather than transcribes
  the page. TEDS runs only this on cell text.
- ``strict`` (steps 1-12) is what WER compares.

Tone placement is canonicalized toward the traditional style (``hoà`` -> ``hòa``).
Both spellings are correct Vietnamese; scoring one against the other measures the
transcriber, not the OCR.
"""

from __future__ import annotations

import html
import re
import unicodedata

# A private-use codepoint: no step below touches it, and no real text contains it.
IMAGE_PLACEHOLDER = ""

IMAGE_MARKER_RE = re.compile(r"<!--\s*image\s*-->", re.IGNORECASE)

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
# Images are dropped whole, alt text included. A caption an engine wrote for a
# figure is the engine describing the page, not transcribing it.
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
FIGURE_DESCRIPTION_RE = re.compile(r"\[hình:[^\]]*\]", re.IGNORECASE)

# Inline tags sit inside a word: m<sup>2</sup> is one token, so they vanish without
# a trace. Every other tag separates content and becomes a space, or <td>a</td><td>b</td>
# would run together into one word.
INLINE_TAGS = "sup|sub|b|i|u|em|strong|span|a|code|small|mark"
INLINE_TAG_RE = re.compile(rf"</?(?:{INLINE_TAGS})(?:\s[^>]*)?>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
BULLET_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+\.)[ \t]+", re.MULTILINE)
EMPHASIS_RE = re.compile(r"[*_`]+")
WHITESPACE_RE = re.compile(r"\s+")


# Step 0: turn each image marker into a standalone placeholder word.
def mark_images(text: str) -> str:
    return IMAGE_MARKER_RE.sub(f" {IMAGE_PLACEHOLDER} ", text)


# Steps 1-4: compose, then drop comments, images and figure descriptions.
def strip_figures(text: str) -> str:
    out = unicodedata.normalize("NFC", text)

    # Comments and images before anything else, since ![x](y) contains [x](y)
    out = HTML_COMMENT_RE.sub(" ", out)
    out = IMAGE_RE.sub(" ", out)
    return FIGURE_DESCRIPTION_RE.sub(" ", out)


# Steps 1-12: the text WER compares.
def strict(text: str) -> str:
    out = strip_figures(text)

    # Drop markup, keeping link text and closing up inline tags
    out = LINK_RE.sub(r"\1", out)
    out = INLINE_TAG_RE.sub("", out)
    out = HTML_TAG_RE.sub(" ", out)

    # Entities after tags, so a decoded &lt; is never read as markup
    out = html.unescape(out)
    out = HEADING_RE.sub("", out)
    out = BULLET_RE.sub("", out)
    out = EMPHASIS_RE.sub("", out)

    # Canonicalize tone placement, then flatten whitespace
    out = TONE_PLACEMENT_RE.sub(lambda m: TONE_PLACEMENT[m.group(0)], out)
    return WHITESPACE_RE.sub(" ", out).strip()
