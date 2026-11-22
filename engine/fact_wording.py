"""Whether a fact is written as a sentence or is a raw run of its source (design 6.7, "A fact reads as a sentence").

A fact says what is true in one plain sentence; the exact words that show it are its evidence, kept beside it. A fact
whose text is a stretch of the source copied as it stood (most of its words one unbroken run of the source, line breaks
kept, a label in capital letters, or a string of "label: value" pairs) reads as raw on a card. A plain function: it
takes text and the settings and reads no records.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WORD = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)
_LABEL = re.compile(r"(?<![\w:])[A-Za-z][A-Za-z #/]{1,24}:(?=\s*\S)")
_CAPS = re.compile(r"[A-Z][A-Z0-9&/'’-]{2,}")


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def raw_run(
    text: str, source: str, *, min_words: int, copied_share: float, caps_run: int, label_run: int = 0
) -> str | None:
    """Why `text` is a raw run of `source` (the quote and the input's words), in plain words, or None. A line break
    inside the fact, or `caps_run` capitalized words in a row, is the shape of a copied block; a text of `min_words`
    words or more whose longest unbroken stretch found in the source is `copied_share` of its words is a copy."""
    if "\n" in text.strip() or "\r" in text.strip():
        return "it holds line breaks, as the source does"
    run = 0
    for word in text.split():
        run = run + 1 if _CAPS.fullmatch(word.strip(".,:;()\"'")) else 0
        if run >= caps_run > 0:
            return "it holds a label in capital letters, as the source does"
    if label_run > 0 and len(_LABEL.findall(text)) >= label_run:
        return "it holds several labels with their values, as the source does"
    mine = _words(text)
    if len(mine) < min_words or not source.strip():
        return None
    theirs = _words(source)
    match = SequenceMatcher(None, mine, theirs, autojunk=False).find_longest_match(0, len(mine), 0, len(theirs))
    if match.size >= copied_share * len(mine):
        return "most of it is the source's own words, copied as they stand"
    return None
