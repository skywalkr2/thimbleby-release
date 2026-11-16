"""The starting window's page, and what each way of not starting says.

The page is one bundled file (`engine/defaults/starting.html`) filled from the wording sheet and the brand's mark; it
shows the steps as they finish and turns into one of the messages. A failure is classified here from its type and
error number, never from message text, and never shown raw: the details are only copied when the person asks."""

from __future__ import annotations

import errno
import html
import json
from collections.abc import Mapping
from pathlib import Path

from engine import brandmark

PAGE = Path(__file__).resolve().parent / "defaults" / "starting.html"
#: The steps the starting window lists, in order, by wording key.
STEPS = ("desktop.step.workspace", "desktop.step.app", "desktop.step.screens")
#: Error numbers that mean the disk has no room, and that something else holds the address the app needs.
_FULL = {errno.ENOSPC, errno.EDQUOT}
_HELD = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}


def classify(error: BaseException) -> str:
    """Which message a failure to start gets: disk_full, elsewhere, held or other."""
    from engine.handover import Refused

    if isinstance(error, Refused):
        return "elsewhere"
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    for item in chain:
        number = getattr(item, "errno", None) if isinstance(item, OSError) else None
        if number in _FULL:
            return "disk_full"
        if number in _HELD:
            return "held"
    return "other"


def message(words: Mapping[str, str], kind: str) -> tuple[str, str]:
    """The title and the text of a way of not starting."""
    return words[f"desktop.problem.{kind}.title"], words[f"desktop.problem.{kind}.text"]


def page(words: Mapping[str, str], version: str = "", brand: Path = brandmark.BRAND_FOLDER) -> str:
    """The starting window's page, in the person's words."""
    steps = "".join(f'<li><span class="m" aria-hidden="true"></span>{html.escape(words[k])}</li>' for k in STEPS)
    marks = {
        "mark_day": _inline(brand / "mark-day.svg", "d"),
        "mark_night": _inline(brand / "mark-night.svg", "n"),
    }
    values = {
        "title": html.escape(words["desktop.title"]),
        "heading": html.escape(words["desktop.starting.title"]),
        "subtitle": html.escape(words["desktop.starting.subtitle"]),
        "version": html.escape(words["desktop.starting.version"].format(version=version)) if version else "",
        "steps": steps,
        "step_count": str(len(STEPS)),
        "copy_details": html.escape(words["desktop.copy_details"]),
        "try_again": html.escape(words["desktop.try_again"]),
        "earlier_use": html.escape(words.get("desktop.earlier.use", "")),
        "earlier_fresh": html.escape(words.get("desktop.earlier.fresh", "")),
        **marks,
    }
    text = PAGE.read_text(encoding="utf-8")
    for name, value in values.items():
        text = text.replace("{{" + name + "}}", value)
    return text


def _inline(path: Path, prefix: str) -> str:
    """A brand SVG as inline markup, its ids made distinct so two marks on one page don't share a gradient."""
    text = path.read_text(encoding="utf-8")
    text = text.split("?>", 1)[-1] if text.lstrip().startswith("<?xml") else text
    for ident in ("ground", "brass", "dimple-pattern", "thimble-clip"):
        text = text.replace(f'id="{ident}"', f'id="{prefix}-{ident}"').replace(
            f"url(#{ident})", f"url(#{prefix}-{ident})"
        )
    return text.strip()


def script_tick(done: int) -> str:
    return f"tick({int(done)})"


def script_problem(title: str, text: str) -> str:
    return f"problem({json.dumps(title)}, {json.dumps(text)})"


def script_choice(title: str, found: str, facts: str, text: str) -> str:
    return f"choice({json.dumps(title)}, {json.dumps(found)}, {json.dumps(facts)}, {json.dumps(text)})"


def script_resume(title: str, sub: str) -> str:
    return f"resume({json.dumps(title)}, {json.dumps(sub)})"
