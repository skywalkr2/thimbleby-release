"""The app notices a newer version of itself and offers it on Today (S-0152, the check; the install is separate).

Once a day (`updates.check_every_hours`), and when the person asks from the menu, the app reads the release feed named
in the settings (`updates.feed_address`) or else in the build's facts (`release_feed`). The request is the address and
an Accept header: it carries no identifier, no version and nothing about the person or their work; the versions are
compared here. The newest eligible release is kept
in the private folder with the moment of the look. Today shows one row for a release newer than the one running, until
the person chooses Later, which hides that version and no newer one. A look that fails, or a feed that doesn't read,
keeps the offer already found and shows no message on screen; the first failure of a run of them goes in the log once.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from engine.release_check import LOOPBACK, Release, newer_release
from engine.state_file import changing, write_whole

log = logging.getLogger(__name__)

STATE_FILE = "update-offer.json"
#: The most lines of what changed the row shows.
NOTE_LINES = 5
#: The most characters of one of those lines.
NOTE_LINE_CHARS = 200
#: What the request asks for; it names no one.
ACCEPT = "application/json"
#: The kinds of installer each system's app is updated from.
INSTALLER_SUFFIXES = {"Windows": (".exe", ".msi"), "Darwin": (".dmg", ".pkg")}


@dataclass(frozen=True)
class Offer:
    version: str
    date: str
    notes: list[str]
    page: str | None
    #: The installer for this system and its SHA-256, as the feed gives them; the install checks both again.
    download_url: str | None = None
    sha256: str | None = None


def _system() -> str:
    return platform.system()


def current_version() -> str:
    from engine import __version__

    return __version__


def feed_address(facts: dict[str, Any] | None = None, chosen: str = "") -> str | None:
    """The release feed's address: the one the settings name (`updates.feed_address`), else the build's facts. None
    when there is none, or it is neither https nor on this computer."""
    if facts is None:
        from engine.shipped import product

        facts = product()
    address = chosen.strip() or facts.get("release_feed")
    if not isinstance(address, str):
        return None
    parts = urlsplit(address)
    if parts.hostname and (parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK)):
        return address
    return None


def _path(private_dir: Path) -> Path:
    return Path(private_dir) / STATE_FILE


def _read(private_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads(_path(private_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(private_dir: Path, data: dict[str, Any]) -> None:
    write_whole(_path(private_dir), json.dumps(data))


def _entries(feed: Any, system: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The feed as the entries `newer_release` reads, and each version's page. A feed already in that shape is used as
    it is; the release host's list is turned into it: a release's tag is its version, and its installer for this system
    gives the address and the checksum the host states for it. Drafts and releases with no installer are left out."""
    if not isinstance(feed, list):
        raise ValueError("The release feed must be a list")
    entries: list[dict[str, Any]] = []
    pages: dict[str, str] = {}
    suffixes = INSTALLER_SUFFIXES.get(system, ())
    for item in feed:
        if not isinstance(item, dict):
            continue
        if "tag_name" not in item:
            entries.append(item)
            if isinstance(item.get("version"), str) and isinstance(item.get("page"), str):
                pages[item["version"]] = item["page"]
            continue
        tag = item.get("tag_name")
        if item.get("draft") is True or not isinstance(tag, str):
            continue
        version = tag[1:] if tag[:1] in ("v", "V") else tag
        for asset in item.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            name, digest = asset.get("name"), asset.get("digest")
            if not (isinstance(name, str) and name.lower().endswith(suffixes) and suffixes):
                continue
            if not (isinstance(digest, str) and digest.lower().startswith("sha256:")):
                continue
            entries.append(
                {
                    "version": version,
                    "date": item.get("published_at") or item.get("created_at"),
                    "notes": item.get("body") or "",
                    "download_url": asset.get("browser_download_url"),
                    "sha256": digest.split(":", 1)[1],
                }
            )
            html = item.get("html_url")
            if isinstance(html, str) and html.startswith("https://"):
                pages[version] = html
            break
    return entries, pages


def _lines(notes: str) -> list[str]:
    """What changed as up to five short plain lines: the release's own words with list marks, headings and emphasis
    taken off, empty lines dropped."""
    found: list[str] = []
    for raw in notes.splitlines():
        line = raw.strip().lstrip("#>*-+ ").strip().replace("**", "").replace("`", "")
        if not line or line.startswith(("<", "![", "---")):
            continue
        found.append(line[: NOTE_LINE_CHARS - 1] + "…" if len(line) > NOTE_LINE_CHARS else line)
        if len(found) == NOTE_LINES:
            break
    return found


def choose(
    feed_text: str | bytes, current: str, include_prereleases: bool, system: str | None = None
) -> tuple[Release, str | None] | None:
    """The release to offer from the feed's text, with its page: none when nothing newer is listed. A feed that doesn't
    read raises ValueError."""
    try:
        data = json.loads(feed_text)
    except (ValueError, UnicodeError) as err:
        raise ValueError("The release feed is not JSON") from err
    entries, pages = _entries(data, system or _system())
    if not include_prereleases and isinstance(data, list):
        entries = [e for e in entries if not _is_pre(data, e)]
    release = newer_release(current, entries, include_prereleases)
    return None if release is None else (release, pages.get(release.version))


def _is_pre(data: list[Any], entry: dict[str, Any]) -> bool:
    """Whether the release host marks this entry's release as a test release (its version may not say so)."""
    for item in data:
        if isinstance(item, dict) and item.get("prerelease") is True:
            tag = item.get("tag_name")
            if isinstance(tag, str) and tag.lstrip("vV") == entry.get("version"):
                return True
    return False


def look(
    private_dir: Path,
    address: str | None,
    *,
    include_prereleases: bool = True,
    current: str | None = None,
    web_for: Callable[[str], Any] | None = None,
    now: datetime | None = None,
    system: str | None = None,
) -> Offer | None:
    """Read the feed now and keep what it says. Returns the offer kept (none when there is nothing newer). Nothing here
    raises: a failed look keeps the offer already found, and its first failure in a row is logged once."""
    from engine.connectors import ConnectorError
    from engine.net import WebClient

    now = now or datetime.now(UTC)
    running = current or current_version()
    found: dict[str, Any] | None = None
    failed = address is None
    if address is not None:
        client = web_for(address) if web_for else WebClient([urlsplit(address).hostname or ""])
        try:
            response = client.get(address, headers={"Accept": ACCEPT})
            chosen = choose(response.content, running, include_prereleases, system)
            if chosen is not None:
                release, page = chosen
                found = {
                    "version": release.version,
                    "date": release.date,
                    "notes": _lines(release.notes),
                    "page": page,
                    "download_url": release.download_url,
                    "sha256": release.sha256,
                }
        except (ConnectorError, ValueError, TypeError, AttributeError) as err:
            failed = True
            reason = err.kind if isinstance(err, ConnectorError) else "unreadable"
        finally:
            if web_for is None:
                client.close()
    with changing(_path(private_dir)):
        state = _read(private_dir)
        if failed and address is not None:
            if not state.get("failing"):
                log.warning("the look at the release feed failed (%s); it is tried again at the next look", reason)
            state["failing"] = True
        else:
            state["failing"] = False
            state["found"] = found
        if address is None:
            state["found"] = None  # no feed is named any more, so nothing is on offer
        # A look that failed keeps the release already found: the row stays until a good look says otherwise.
        state["checked_at"] = now.isoformat()
        _write(private_dir, state)
    return offer(private_dir, running)


def due(private_dir: Path, now: datetime, every_hours: int) -> bool:
    """Whether the last look was at least `every_hours` ago (or there was none)."""
    try:
        last = datetime.fromisoformat(str(_read(private_dir).get("checked_at")))
    except ValueError:
        return True
    return (now - last).total_seconds() >= every_hours * 3600


def offer(private_dir: Path, current: str | None = None) -> Offer | None:
    """The kept release when it is newer than the running version and the person hasn't put that version off."""
    from packaging.version import InvalidVersion, Version

    state = _read(private_dir)
    found = state.get("found")
    if not isinstance(found, dict) or not isinstance(found.get("version"), str):
        return None
    try:
        if Version(found["version"]) <= Version(current or current_version()):
            return None
    except InvalidVersion:
        return None
    if state.get("later") == found["version"]:
        return None
    notes = [n for n in found.get("notes") or [] if isinstance(n, str)][:NOTE_LINES]
    page = found.get("page")
    url, sha = found.get("download_url"), found.get("sha256")
    return Offer(
        found["version"],
        str(found.get("date") or ""),
        notes,
        page if isinstance(page, str) and page.startswith("https://") else None,
        url if isinstance(url, str) else None,
        sha if isinstance(sha, str) else None,
    )


def later(private_dir: Path, version: str, on: bool = True) -> None:
    """Hide the offer of this version (and no newer one); with `on` false, show it again."""
    with changing(_path(private_dir)):
        state = _read(private_dir)
        if on:
            state["later"] = version
        elif state.get("later") == version:
            state.pop("later")
        _write(private_dir, state)


def checking(ws: Any, cfg: Any) -> bool:
    """Whether the look for a newer version is on, read from the settings as the files hold them now (like the look
    itself), so turning it off or on applies at once; `cfg` stands in when the files can't be read."""
    from engine.config import ConfigError
    from engine.config.current import load_config_now

    try:
        return bool(load_config_now(ws.config_dir, env=dict(os.environ)).updates.check)
    except ConfigError:
        return bool(cfg.updates.check)


def check_now(ws: Any, cfg: Any, **more: Any) -> Offer | None:
    """The look the menu asks for, whatever the hour: the build's feed, this workspace's settings."""
    address = feed_address(None, cfg.updates.feed_address)
    return look(ws.private_dir, address, include_prereleases=cfg.updates.include_prereleases, **more)
