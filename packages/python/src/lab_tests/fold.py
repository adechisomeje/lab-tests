"""Accent- and case-insensitive folding for search.

The mapping must match the dataset's ID generation exactly, including
``ß`` -> ``beta``: in this corpus "ß2 Microglobulin" uses ß as a beta glyph and
the generated id is ``beta2-microglobulin``. The conformance suite pins this.
"""

from __future__ import annotations

import unicodedata

_MULTI = (
    ("ß", "beta"),
    ("æ", "ae"),
    ("œ", "oe"),
    ("þ", "th"),
    ("ð", "d"),
    ("–", "-"),
    ("—", "-"),
    ("‐", "-"),
    ("’", "'"),
    ("°", ""),
)


def fold(text: str | None) -> str:
    """Lowercase, expand multi-character glyphs and strip combining accents."""
    s = (text or "").lower().strip()
    for src, dst in _MULTI:
        s = s.replace(src, dst)
    decomposed = unicodedata.normalize("NFD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", stripped)
