"""Report a problem (design 7, Help): the person's own words, the app's version and system, and the masked recent
problem lines go to the maintainers' web form, once, when the person presses Send on the exact content shown.

The request is one JSON body with `words`, `reply_to` (the person's address, when they gave one), `version`, `system`
and `problems` (the lines the person was shown), and nothing else: no workspace, folder, host name, account or record
text. It goes through the core's web client, limited to the one host of the configured address. The address is the
setting `ui.report_to`, else the build's fact `report_to`; with neither, the report is not offered.
"""

from __future__ import annotations

import platform
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from engine.net import LOCAL, WebClient
from engine.shipped import product

#: The most characters of each part, as the form accepts them.
LIMITS = {"words": 5000, "problems": 20000, "version": 100, "system": 100, "reply_to": 200}

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


def send(
    to: str,
    *,
    words: str,
    reply_to: str,
    version: str,
    problems: str,
    web_for: Callable[[str], Any] | None = None,
) -> Outcome:
    """Post the report. Never raises: the outcome says why it did not go, as a kind the screen puts in words."""
    from engine.connectors import ConnectorError

    body = {"words": words, "reply_to": reply_to, "version": version, "system": system_text(), "problems": problems}
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
