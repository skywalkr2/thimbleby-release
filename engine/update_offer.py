"""The app notices a newer version of itself and offers it on Today (S-0152, the check; the install is separate).

Once a day (`updates.check_every_hours`), and when the person asks from the menu, the app reads the release feed named
in the settings (`updates.feed_address`) or else in the build's facts (`release_feed`). The request is the address and
an Accept header: it carries no identifier, no version and nothing about the person or their work; the versions are
compared here. The newest eligible release is kept
in the private folder with the moment of the look. Today shows one row for a release newer than the one running, until
the person chooses Later, which hides that version and no newer one. A look that fails, or a feed that doesn't read,
keeps the offer already found and shows no message on screen; the first failure of a run of them goes in the log once.

A release is kept and offered only with its signed list of files (`engine.release_manifest`): the look fetches the list
and its signature, and every read of the offer checks the signature again against the keys the app trusts (the build's
own, and any the settings add) and takes the installer's checksum from the list. A release with no list, a signature
that doesn't verify or a list without the installer is no offer, said once in the log and never on screen.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import platform
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from engine import release_manifest
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
    #: The installer for this system, with the SHA-256 and size the release's signed list states for it.
    download_url: str | None = None
    sha256: str | None = None
    size: int | None = None


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


def trusted_keys(settings: Any = None, facts: dict[str, Any] | None = None) -> list[str]:
    """The public keys a release's list may be signed with: the one this build ships (`release_key` in its facts) and
    the ones the settings add (`updates.trusted_keys`). With none, no release is ever offered."""
    if facts is None:
        from engine.shipped import product

        facts = product()
    shipped = facts.get("release_key")
    keys = [shipped.strip()] if isinstance(shipped, str) and shipped.strip() else []
    return [*keys, *(k for k in getattr(settings, "trusted_keys", None) or [] if k not in keys)]


def keys_now(ws: Any, cfg: Any) -> list[str]:
    """The trusted keys with the settings as the files hold them now; `cfg` stands in when the files can't be read."""
    from engine.config import ConfigError
    from engine.config.current import load_config_now

    try:
        return trusted_keys(load_config_now(ws.config_dir, env=dict(os.environ)).updates)
    except ConfigError:
        return trusted_keys(cfg.updates)


def installer_file(url: str) -> str:
    """The installer's file name, as its address ends: the name a release's list states it by."""
    return unquote(urlsplit(url).path).rsplit("/", 1)[-1]


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


def _entries(
    feed: Any, system: str, lists: dict[str, tuple[str, str]] | None = None
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The feed as the entries `newer_release` reads, and each version's page. A feed already in that shape is used as
    it is; the release host's list is turned into it: a release's tag is its version, and its installer for this system
    gives the address and the checksum the host states for it. Drafts and releases with no installer are left out.
    `lists` is filled with where each version's signed list and its signature are (`manifest_url` and `signature_url`
    of an entry; the release's files of those names)."""
    if not isinstance(feed, list):
        raise ValueError("The release feed must be a list")
    entries: list[dict[str, Any]] = []
    pages: dict[str, str] = {}
    lists = {} if lists is None else lists
    suffixes = INSTALLER_SUFFIXES.get(system, ())
    for item in feed:
        if not isinstance(item, dict):
            continue
        if "tag_name" not in item:
            entries.append(item)
            if isinstance(item.get("version"), str) and isinstance(item.get("page"), str):
                pages[item["version"]] = item["page"]
            signed = item.get("manifest_url"), item.get("signature_url")
            if isinstance(item.get("version"), str) and all(isinstance(a, str) for a in signed):
                lists[item["version"]] = (str(signed[0]), str(signed[1]))
            continue
        tag = item.get("tag_name")
        if item.get("draft") is True or not isinstance(tag, str):
            continue
        version = tag[1:] if tag[:1] in ("v", "V") else tag
        named = {
            asset.get("name"): asset.get("browser_download_url")
            for asset in item.get("assets") or []
            if isinstance(asset, dict)
        }
        signed = named.get(release_manifest.MANIFEST_NAME), named.get(release_manifest.SIGNATURE_NAME)
        if all(isinstance(a, str) for a in signed):
            lists[version] = (str(signed[0]), str(signed[1]))
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
    feed_text: str | bytes,
    current: str,
    include_prereleases: bool,
    system: str | None = None,
    lists: dict[str, tuple[str, str]] | None = None,
) -> tuple[Release, str | None] | None:
    """The release to offer from the feed's text, with its page: none when nothing newer is listed. A feed that doesn't
    read raises ValueError. `lists` is filled with where each version's signed list and signature are."""
    try:
        data = json.loads(feed_text)
    except (ValueError, UnicodeError) as err:
        raise ValueError("The release feed is not JSON") from err
    entries, pages = _entries(data, system or _system(), lists)
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
    keys: Sequence[str] = (),
    fetch: Callable[[str], bytes] | None = None,
) -> Offer | None:
    """Read the feed now and keep what it says. Returns the offer kept (none when there is nothing newer). Nothing here
    raises: a failed look keeps the offer already found, and its first failure in a row is logged once. The newest
    release is kept only with its signed list, verified against `keys`; `fetch` reads the list and its signature."""
    import httpx

    from engine.connectors import ConnectorError
    from engine.net import WebClient

    now = now or datetime.now(UTC)
    running = current or current_version()
    found: dict[str, Any] | None = None
    unsigned: str | None = None
    failed = address is None
    if address is not None:
        client = web_for(address) if web_for else WebClient([urlsplit(address).hostname or ""])
        try:
            response = client.get(address, headers={"Accept": ACCEPT})
            lists: dict[str, tuple[str, str]] = {}
            chosen = choose(response.content, running, include_prereleases, system, lists)
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
                where = lists.get(release.version)
                if where is not None:
                    get = fetch or release_manifest.fetch
                    content, signature = get(where[0]), get(where[1]).decode("ascii", "replace").strip()
                    found["manifest"] = base64.b64encode(content).decode("ascii")
                    found["signature"] = signature
                if _verified(found, keys) is None:
                    # No list, a signature no trusted key made, or a list without this installer: never an offer.
                    unsigned, found = release.version, None
        except httpx.HTTPError:
            failed, reason = True, "offline"
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
            if unsigned is not None and state.get("unsigned") != unsigned:
                log.warning(
                    "version %s is listed without a list of its files signed by a trusted key; it is not offered",
                    unsigned,
                )
            state["unsigned"] = unsigned
        if address is None:
            state["found"] = None  # no feed is named any more, so nothing is on offer
        # A look that failed keeps the release already found: the row stays until a good look says otherwise.
        state["checked_at"] = now.isoformat()
        _write(private_dir, state)
    return offer(private_dir, running, keys)


def _verified(found: dict[str, Any], keys: Sequence[str]) -> release_manifest.Listed | None:
    """The installer of a kept release as its signed list states it, checked now: none when the list is missing, its
    signature doesn't verify against a trusted key, it is for another version, or it doesn't hold the installer with
    the checksum the feed gave."""
    url, sha, version = found.get("download_url"), found.get("sha256"), found.get("version")
    content, signature = found.get("manifest"), found.get("signature")
    if not all(isinstance(x, str) for x in (url, sha, version, content, signature)):
        return None
    try:
        raw = base64.b64decode(str(content), validate=True)
    except (binascii.Error, ValueError):
        return None
    return release_manifest.listed(raw, str(signature), keys, str(version), installer_file(str(url)), str(sha))


def due(private_dir: Path, now: datetime, every_hours: int) -> bool:
    """Whether the last look was at least `every_hours` ago (or there was none)."""
    try:
        last = datetime.fromisoformat(str(_read(private_dir).get("checked_at")))
    except ValueError:
        return True
    return (now - last).total_seconds() >= every_hours * 3600


def offer(private_dir: Path, current: str | None = None, keys: Sequence[str] = ()) -> Offer | None:
    """The kept release when it is newer than the running version, the person hasn't put that version off, and its
    list of files is signed by one of `keys` (checked on every read; with no key nothing is offered). The checksum and
    size it carries are the signed list's."""
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
    signed = _verified(found, keys)
    if signed is None:
        return None
    notes = [n for n in found.get("notes") or [] if isinstance(n, str)][:NOTE_LINES]
    page = found.get("page")
    return Offer(
        found["version"],
        str(found.get("date") or ""),
        notes,
        page if isinstance(page, str) and page.startswith("https://") else None,
        str(found["download_url"]),
        signed.sha256,
        signed.size,
    )


def offer_for(ws: Any, cfg: Any, current: str | None = None) -> Offer | None:
    """The offer for this workspace, checked against the keys its settings trust now."""
    return offer(ws.private_dir, current, keys_now(ws, cfg))


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
    more.setdefault("keys", trusted_keys(cfg.updates))
    return look(ws.private_dir, address, include_prereleases=cfg.updates.include_prereleases, **more)
