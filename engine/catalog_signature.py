"""Checking a catalog feed's signature (design 3.11, "A signed catalog").

A feed is accepted only with a detached Ed25519 signature over its exact bytes, made with a key the app trusts. Keys and
signatures are written as base64 text (the raw 32-byte public key, the raw 64-byte signature), so one can be pasted.
"""

from __future__ import annotations

import base64
import binascii

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _raw(text: str, size: int) -> bytes | None:
    try:
        raw = base64.b64decode("".join(str(text).split()), validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == size else None


def is_public_key(text: str) -> bool:
    """Whether the text is an Ed25519 public key as base64 text."""
    return _raw(text, 32) is not None


def verify(content: bytes, signature: str, keys: list[str]) -> bool:
    """Whether the signature text is valid over the content for any of the keys. An unreadable signature or key never
    verifies; nothing here raises on bad input."""
    sig = _raw(signature, 64)
    if sig is None:
        return False
    for key in keys:
        raw = _raw(key, 32)
        if raw is None:
            continue
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(sig, content)
            return True
        except (InvalidSignature, ValueError):
            continue
    return False
