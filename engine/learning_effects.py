"""What a piece of learning does: it describes, or it grants power (design 6.22).

A learning that describes (what a word means, what a sender is, how the person files things, a fact such as "this
payment is automatic") can be active without anyone's Keep: from the person's own words at once, from incoming messages
once enough of them agree. A learning that grants power never becomes active from an input, however many messages say
it: it names who something is sent or forwarded to, marks someone trusted or gives them a role over the person, touches
money or spending, deletes or archives, or closes or drops the person's work on its own.

One plain function, with no AI, reads the kind and the wording. It is deliberately wide: anything that touches one of
those areas, or that it cannot read, counts as power, because the cost of asking once is small and the cost of an input
steering what is sent, trusted or spent is not.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

DESCRIBES, POWER = "describes", "power"

#: The kinds whose every entry grants power: a standing rule constrains, pauses or enforces; a routing entry names who
#: is asked or who answers, which is where questions and forwards go.
ALWAYS_POWER = ("rule", "routing_entry")

#: The text fields of each kind that are read. An entry of a kind not listed here, or with a field not listed, is read
#: through every string in it.
_READ = {
    "lesson": ("text", "guard"),
    "glossary_entry": ("text", "term", "meaning"),
    "style_note": ("text", "audience", "observation"),
}

#: Words that touch an area that grants power, by stem. A stem matches the start of a word (`approv` is approve,
#: approved, approval). The lists are wide on purpose.
_STEMS = (
    # who something is sent, forwarded or copied to
    "forward",
    "send",
    "cc",
    "bcc",
    "recipient",
    "redirect",
    "route to",
    "goes to",
    "go to",
    "assign",
    "hand to",
    "hand off",
    "handed to",
    "belongs to",
    "notify",
    "share",
    "publish",
    "invit",
    "deliver",
    "reply to",
    "respond to",
    "copy ",
    # trust, roles and standing over the person
    "trust",
    "allow",
    "whitelist",
    "allowlist",
    "approv",
    "authori",
    "permit",
    "permission",
    "grant",
    "role",
    "admin",
    "manager",
    "boss",
    "delegat",
    "behalf",
    "supervis",
    # money and spending (what is spent or moved; a plain fact about a payment is not listed)
    "pay",
    "spend",
    "spent",
    "purchas",
    "buy",
    "bought",
    "wire",
    "transfer",
    "refund",
    "reimburs",
    "charge",
    "donat",
    "subscribe",
    "account number",
    # deleting and archiving
    "delet",
    "remov",
    "trash",
    "bin",
    "archiv",
    "purge",
    "erase",
    "wipe",
    "discard",
    "destroy",
    "drop",
    # closing, dropping or ignoring the person's work
    "close",
    "resolv",
    "complete",
    "done",
    "cancel",
    "dismiss",
    "ignor",
    "skip",
    "mute",
    "silenc",
    "snooze",
    "stop",
    "disregard",
    "without ask",
    "no need to",
    "do not need",
    "don't need",
    # wording that talks to the assistant or lays down a rule
    "instruct",
    "overrid",
    "assistant",
    "reginald",
    "must",
    "should",
    "always",
    "never",
    "from now on",
    "policy",
)

#: Shapes that name a destination or a secret, whatever the words around them: a mail address, a web address, a phone
#: number, a long number (an account or card), a handle.
_SHAPES = (
    re.compile(r"\S+@\S+"),
    re.compile(r"https?://|www\.", re.IGNORECASE),
    re.compile(r"\b[\w-]+\.(?:com|org|net|io|app|co|edu|gov|biz|info|ru|cn)\b", re.IGNORECASE),
    re.compile(r"\+?\d[\d\s().-]{7,}\d"),
    re.compile(r"(?<!\w)@\w{2,}"),
)
_WORDS = re.compile(r"[a-z]+(?:'[a-z]+)?")
_STEM_PHRASES = tuple(s for s in _STEMS if " " in s or "'" in s)
_STEM_WORDS = tuple(s for s in _STEMS if " " not in s and "'" not in s)
#: Stems short enough to match words they don't mean ("bin" in "binder", "pay" in "payment", which is a plain fact) are
#: matched against the whole word and its plain endings only.
_WHOLE_ONLY = frozenset({"cc", "bcc", "bin", "pay", "buy", "role", "send", "wire", "done", "stop", "mute", "skip"})
_ENDINGS = ("", "s", "es", "ed", "ing", "d")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [t for v in value.values() for t in _strings(v)]
    if isinstance(value, list | tuple):
        return [t for v in value for t in _strings(v)]
    return []


def _wording(kind: str, data: Mapping[str, Any]) -> str:
    names = _READ.get(kind)
    if names is None:
        return " ".join(_strings({k: v for k, v in data.items() if k not in ("evidence", "more_evidence")}))
    return " ".join(_strings([data.get(n) for n in names]))


def _touches(text: str) -> bool:
    low = text.lower().replace("’", "'")
    if any(shape.search(text) for shape in _SHAPES):
        return True
    if any(phrase in low for phrase in _STEM_PHRASES):
        return True
    for word in _WORDS.findall(low):
        for stem in _STEM_WORDS:
            if stem in _WHOLE_ONLY:
                if any(word == stem + end for end in _ENDINGS):
                    return True
            elif word.startswith(stem):
                return True
    return False


def effect(kind: str, data: Mapping[str, Any]) -> str:
    """`describes` or `power` for a piece of learning of this kind with this content. A kind that is not one of the
    describing kinds, content that touches an area that grants power and content that cannot be read are all `power`."""
    if kind in ALWAYS_POWER or kind not in _READ:
        return POWER
    text = _wording(kind, data)
    if not text.strip() or _touches(text):
        return POWER
    return DESCRIBES


def grants_power(kind: str, data: Mapping[str, Any]) -> bool:
    """Whether a piece of learning of this kind grants power, so that no input may make it active."""
    return effect(kind, data) == POWER
