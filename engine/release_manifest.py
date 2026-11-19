"""A release's signed list of files (design 11.7, "An update is checked against a signed list").

Each release carries a small JSON file naming its version and, for each file, its name, size and SHA-256, with a
detached Ed25519 signature beside it made by the release build (`engine.catalog_signature` checks it, as it does a
catalog feed's). The app offers or installs an update only when the signature verifies against a key it trusts, the
list is for that version, and the installer is in it; the checksum a download is held to is the list's. Nothing here
raises on a bad list: it reads as no list at all.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from engine.catalog_signature import verify
from engine.release_check import address_ok

#: The names of the list and its signature among a release's files.
MANIFEST_NAME = "RELEASE-MANIFEST.json"
SIGNATURE_NAME = MANIFEST_NAME + ".sig"
#: The format this app reads.
FORMAT = 1
#: The largest list, or signature, the app will fetch.
MAX_BYTES = 256 * 1024
ACCEPT = "application/octet-stream"


@dataclass(frozen=True)
class Listed:
    """One file of a release, as its signed list states it."""

    name: str
    size: int
    sha256: str


def read(content: bytes, signature: str, keys: Sequence[str]) -> tuple[str, dict[str, Listed]] | None:
    """The list's version and its files by name, or none when the signature doesn't verify against any of the keys or
    the content isn't a list in the format this app reads. The signature is checked first, over the exact bytes."""
    if not keys or not verify(content, signature, list(keys)):
        return None
    try:
        data = json.loads(content)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("version"), str):
        return None
    files: dict[str, Listed] = {}
    entries = data.get("files")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        name, size, digest = entry.get("name"), entry.get("size"), entry.get("sha256")
        if not (isinstance(name, str) and name and type(size) is int and size >= 0 and isinstance(digest, str)):
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or name in files:
            return None
        files[name] = Listed(name, size, digest)
    return data["version"], files


def listed(
    content: bytes, signature: str, keys: Sequence[str], version: str, name: str, sha256: str | None = None
) -> Listed | None:
    """The file `name` of release `version` as a verified list states it; none when the list doesn't verify, is for
    another version, doesn't hold the file, or states another checksum than the one given."""
    from packaging.version import InvalidVersion, Version

    found = read(content, signature, keys)
    if found is None:
        return None
    try:
        if Version(found[0]) != Version(version):
            return None
    except InvalidVersion:
        return None
    entry = found[1].get(name)
    if entry is None or (sha256 is not None and sha256.lower() != entry.sha256):
        return None
    return entry


def fetch(url: str, *, client: Any = None, limit: int = MAX_BYTES) -> bytes:
    """A small file of a release. The request is the address and an Accept header and nothing else. A redirect is
    followed only to another https address (or one on this computer). Raises `ValueError` for an address that may not
    be fetched, an answer that is refused or too large; a network that fails raises httpx's own error."""
    import httpx

    if not address_ok(url):
        raise ValueError("the release names a file at an address that may not be fetched")
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=False)
    try:
        address = url
        for _ in range(6):
            with client.stream("GET", address, headers={"Accept": ACCEPT}) as response:
                if response.is_redirect and response.headers.get("location"):
                    address = str(response.url.join(response.headers["location"]))
                    if not address_ok(address):
                        raise ValueError("the file was sent somewhere it may not go")
                    continue
                if response.status_code >= 400:
                    raise ValueError(f"the release host answered {response.status_code}")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise ValueError("the file is larger than a release's list may be")
                return bytes(body)
        raise ValueError("too many redirects")
    finally:
        if own:
            client.close()
