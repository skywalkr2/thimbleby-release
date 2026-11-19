"""A release's signed list of files for tests: a key made here for the run and kept nowhere, the list in the format
the release build writes, and its signature. Tests that need an offer give the feed a list signed with this key and
trust its public half, as a person adding their own key does; the check itself is never turned off."""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from engine import release_manifest


def new_key() -> tuple[Ed25519PrivateKey, str]:
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(raw).decode("ascii")


#: A fictional signing key for this test run, and its public half as the app's settings take it.
KEY, PUBLIC = new_key()
#: Another key, which nothing trusts.
OTHER_KEY, OTHER_PUBLIC = new_key()


def manifest(version: str, files: dict[str, tuple[int, str]]) -> bytes:
    """The list's bytes: each file's name with its size and SHA-256."""
    listed = [{"name": name, "size": size, "sha256": sha} for name, (size, sha) in sorted(files.items())]
    body = {"format": release_manifest.FORMAT, "version": version, "files": listed}
    return (json.dumps(body, indent=2) + "\n").encode("ascii")


def sign(content: bytes, key: Ed25519PrivateKey = KEY) -> str:
    return base64.b64encode(key.sign(content)).decode("ascii")


def signed_found(found: dict, *, size: int = 0, key: Ed25519PrivateKey = KEY) -> dict:
    """A kept release (the offer's state) with the signed list that names its installer, as a look keeps it."""
    name = found["download_url"].rsplit("/", 1)[-1]
    content = manifest(found["version"], {name: (size, found["sha256"])})
    return {**found, "manifest": base64.b64encode(content).decode("ascii"), "signature": sign(content, key)}


def trust(ws, *keys: str) -> None:
    """Add the keys to the workspace's own settings (`updates.trusted_keys`)."""
    path = ws.config_dir / "updates.yaml"
    text = path.read_text() if path.exists() else "version: 1\n"
    lines = [line for line in text.splitlines() if not line.startswith("trusted_keys:")]
    path.write_text("\n".join([*lines, f"trusted_keys: {json.dumps(list(keys or (PUBLIC,)))}"]) + "\n")
