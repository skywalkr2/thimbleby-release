"""Report a problem (design 7, Help): the person's own words, the app's version and system, and the masked recent
problem lines go to the maintainers' web form, once, when the person presses Send on the exact content shown.

The request is one JSON body with `words`, `reply_to` (the person's address, when they gave one), `version`, `system`
and `problems` (the lines the person was shown), and, when the person left them in, `details` (the app's recent log
lines, scrubbed, as shown), and nothing else: no workspace, folder, host name, account or record text. No part is
longer than the form's limit (`defaults/report_limits.json`, a copy of the form's own); one that is over is never sent.
It goes through the core's web client, limited to the one host of the configured
address. The address is the setting `ui.report_to`, else the build's fact `report_to`; with neither, the report is
not offered.
"""

from __future__ import annotations

import json
import platform
import re
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from engine import problems as problems_mod
from engine.net import LOCAL, WebClient
from engine.shipped import product


def _limits() -> dict[str, int]:
    found = json.loads((Path(__file__).parent / "defaults" / "report_limits.json").read_text(encoding="utf-8"))
    return {key: value for key, value in found.items() if not key.startswith("_")}


#: The most characters of each part, as the form accepts them (a copy of the form's own file).
LIMITS = _limits()

#: The packages whose code places an exception's frames are kept for.
OWN_PACKAGES = ("engine/", "api/")
_ADDRESS = re.compile(r"[^\s@<>\"']+@[^\s@<>\"']+\.[A-Za-z]{2,}")

Why = Literal["offline", "busy", "refused", "unavailable"]
_WHY: dict[str, Why] = {"offline": "offline", "throttled": "busy", "auth": "refused", "no_access": "refused"}


@dataclass(frozen=True)
class Outcome:
    ok: bool
    why: Why | None = None


def address(chosen: str = "", facts: dict[str, Any] | None = None) -> str | None:
    """Where a report goes: the settings' address, else the build's. None when there is none, or it is neither https
    nor on this computer."""
    facts = product() if facts is None else facts
    found = chosen.strip() or facts.get("report_to")
    if not isinstance(found, str):
        return None
    parts = urlsplit(found)
    if parts.hostname and (parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOCAL)):
        return found
    return None


def system_text() -> str:
    """The operating system and its release, such as "Windows 11": no computer name and no user."""
    return f"{platform.system()} {platform.release()}".strip()[: LIMITS["system"]]


def exception_lines(error: BaseException) -> list[str]:
    """An exception as its type, its message and one line per frame inside the app's own packages, as
    `file:line in function`: never a variable's value and never the code's text."""
    from engine.app_log import short_path

    found = [f"{type(error).__name__}: {error}"]
    for frame in traceback.extract_tb(error.__traceback__):
        place = short_path(frame.filename)
        if place.startswith(OWN_PACKAGES):
            found.append(f"  {place}:{frame.lineno} in {frame.name}")
    return found


def scrub(
    text: str, *, masker: Callable[[str | None], str] | None = None, folders: dict[str, str] | None = None
) -> str:
    """The text with what must not leave replaced: secrets, hosts and the person's own names (the core's mask), then
    each folder of `folders` (the home folder as "~", the workspace as "<workspace>"), then any email address left."""
    hide = masker or problems_mod.mask
    text = hide(text)
    for folder, name in sorted((folders or {}).items(), key=lambda kv: -len(kv[0])):
        if folder:
            text = text.replace(folder, name).replace(folder.replace("\\", "/"), name)
    return _ADDRESS.sub(problems_mod.ADDRESS, text)


def units(text: str) -> int:
    """The length of `text` as the form counts it: in UTF-16 code units, so a character outside the basic plane (most
    emoji) counts twice."""
    return len(text.encode("utf-16-le")) // 2


def fit(text: str, limit: int) -> str:
    """The newest lines that fit in `limit` characters as the form counts them, the oldest dropped first; a newest line
    longer than the limit keeps its end."""
    if units(text) <= limit:
        return text
    kept: list[str] = []
    size = 0
    for line in reversed(text.split("\n")):
        cost = units(line) + (1 if kept else 0)
        if size + cost > limit:
            if not kept:
                end = line
                while end and units(end) > limit:
                    end = end[max(1, units(end) - limit) // 2 or 1 :]
                kept.append(end)
            break
        kept.append(line)
        size += cost
    return "\n".join(reversed(kept))


def details_text(
    log_text: str,
    *,
    error: BaseException | None = None,
    masker: Callable[[str | None], str] | None = None,
    folders: dict[str, str] | None = None,
    limit: int | None = None,
) -> str:
    """The technical details: the exception (when there is one) then the last lines of the app's log, scrubbed and
    trimmed to the form's limit with the oldest log lines dropped first. No AI: the same input gives the same text."""
    limit = LIMITS["details"] if limit is None else limit
    head = scrub("\n".join(exception_lines(error)), masker=masker, folders=folders) if error else ""
    tail = scrub(log_text.strip("\n"), masker=masker, folders=folders)
    room = max(0, limit - units(head) - (1 if head and tail else 0))
    return fit("\n".join(part for part in (head, fit(tail, room) if tail else "") if part), limit)


def details_for(ws: Any, store: Any, cfg: Any, *, error: BaseException | None = None) -> str:
    """The details for this workspace: the end of its own log file, scrubbed with the workspace's own names."""
    from engine.app_log import log_path

    path = log_path(ws)
    size = 0
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - LIMITS["details"] * 4))
            raw = handle.read().decode("utf-8", "replace")
    except OSError:
        raw = ""
    lines = raw.split("\n")
    if size > LIMITS["details"] * 4:
        lines = lines[1:]  # the first line may be cut in two
    try:
        hide = problems_mod.masker_for(ws, store, cfg)
    except Exception:  # the shape-based masking still applies
        hide = problems_mod.Masker()
    folders = {str(Path.home()): "~", str(ws.root): "<workspace>"}
    return details_text("\n".join(lines), error=error, masker=hide, folders=folders)


def send(
    to: str,
    *,
    words: str,
    reply_to: str,
    version: str,
    problems: str,
    details: str = "",
    web_for: Callable[[str], Any] | None = None,
) -> Outcome:
    """Post the report. Never raises: the outcome says why it did not go, as a kind the screen puts in words."""
    from engine.connectors import ConnectorError

    body = {"words": words, "reply_to": reply_to, "version": version, "system": system_text(), "problems": problems}
    if details:
        body["details"] = details
    if any(units(str(value)) > LIMITS[key] for key, value in body.items()):
        return Outcome(False, "refused")  # the form would refuse it: nothing is sent
    client = web_for(to) if web_for else WebClient([urlsplit(to).hostname or ""])
    try:
        response = client.post(to, json=body, headers={"Accept": "application/json"})
    except ConnectorError as err:
        return Outcome(False, _WHY.get(err.kind, "unavailable"))
    finally:
        if web_for is None:
            client.close()
    if 200 <= response.status < 300:
        return Outcome(True)
    if response.status == 429:
        return Outcome(False, "busy")
    return Outcome(False, "refused" if 400 <= response.status < 500 else "unavailable")
