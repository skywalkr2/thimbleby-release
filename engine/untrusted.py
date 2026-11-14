"""Outside text made safe to put inside the markers that fence it in a prompt (design 6.6).

Outside text (a mail, a page, a saved input, a to-do made from them) is shown to the assistant between marker tags
and is material to read, never instructions. Text that carried a closing marker would end its own block and pass what
follows for the app's own words, so every closing form of a marker tag inside outside text is written out as plain
text instead: any capitals, any spaces between its parts."""

from __future__ import annotations

import re
import unicodedata

#: The tags that fence a part of a prompt whose words came from outside, or hold such a part.
MARKER_TAGS = ("untrusted", "note", "reference", "material", "app_data", "owed", "may_answer")

_CLOSING = re.compile(r"<(?=\s*/\s*(?:" + "|".join(MARKER_TAGS) + r")(?![\w-]))", re.IGNORECASE)


#: Slash and angle look-alikes that NFKC leaves as they are.
_LOOKALIKES = str.maketrans({"\u2044": "/", "\u2215": "/", "\u29f8": "/", "\u2039": "<", "\u276c": "<"})


def _folded(text: str) -> tuple[str, list[int]]:
    """The text in compatibility-normal form, with the index in `text` each folded character came from."""
    out: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        folded = unicodedata.normalize("NFKC", char).translate(_LOOKALIKES)
        out.append(folded)
        origin.extend([index] * len(folded))
    return "".join(out), origin


def neutralize(text: str) -> str:
    """The text with the `<` of every closing marker tag written as `&lt;`, so it reads as the words it is and can't
    end the block it sits in. Fullwidth and other look-alike forms of the characters are caught too. Other text is
    left as it is."""
    folded, origin = _folded(text)
    starts = {origin[m.start()] for m in _CLOSING.finditer(folded)}
    if not starts:
        return text
    return "".join("&lt;" if index in starts else char for index, char in enumerate(text))
