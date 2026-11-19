"""Make and sign a release's list of files (the app checks it before it offers or installs an update).

The list is a small JSON file: the release's version and, for each installer, its name, size and SHA-256, taken from
the `SHA256SUMS` files the builds wrote and the installers themselves. Its signature is a detached Ed25519 signature
over the list's exact bytes, written as base64 text in a file beside it. The private key is read from the environment
variable `RELEASE_SIGNING_KEY` (the raw 32-byte key as base64 text), which the release workflow fills from a secret
of the repository; it is never written anywhere by this script except by `keygen`, into the file it is told.

  make    --version V --dir FOLDER --out FILE     write the list for the installers found under FOLDER
  sign    --manifest FILE --out FILE [--public KEY]
                                                  sign it; with --public, refuse a key that isn't that one's pair
  verify  --manifest FILE --signature FILE --public KEY
  keygen  --private-out FILE                      a new key pair: the private key into FILE, the public key printed

Needs only the standard library and `cryptography`."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path

MANIFEST_NAME = "RELEASE-MANIFEST.json"
SIGNATURE_NAME = MANIFEST_NAME + ".sig"
FORMAT = 1
KEY_VARIABLE = "RELEASE_SIGNING_KEY"


def build(version: str, folder: Path) -> bytes:
    """The list's bytes for every installer a `SHA256SUMS*.txt` under `folder` names. Each installer must be there, and
    its SHA-256 is taken again from the file itself: a line that doesn't match its file stops the release."""
    found: dict[str, dict[str, object]] = {}
    sums = sorted(folder.rglob("SHA256SUMS*.txt"))
    if not sums:
        raise SystemExit(f"no SHA256SUMS file under {folder}")
    files = {path.name: path for path in folder.rglob("*") if path.is_file()}
    for listing in sums:
        for line in listing.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (\S.*)", line.strip())
            if not match:
                continue
            digest, name = match.groups()
            path = files.get(name)
            if path is None:
                raise SystemExit(f"{listing.name} names {name}, which is not among the files")
            with path.open("rb") as payload:
                actual = hashlib.file_digest(payload, "sha256").hexdigest()
            if actual != digest:
                raise SystemExit(f"{name} is not the file {listing.name} lists")
            if name in found and found[name]["sha256"] != digest:
                raise SystemExit(f"{name} is listed twice with different checksums")
            found[name] = {"name": name, "size": path.stat().st_size, "sha256": digest}
    if not found:
        raise SystemExit("the SHA256SUMS files name no installer")
    body = {"format": FORMAT, "version": version, "files": [found[name] for name in sorted(found)]}
    return (json.dumps(body, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def _private(text: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        raw = base64.b64decode("".join(text.split()), validate=True)
    except ValueError:
        raw = b""
    if len(raw) != 32:
        raise SystemExit(f"{KEY_VARIABLE} is not a raw 32-byte Ed25519 private key written as base64 text")
    return Ed25519PrivateKey.from_private_bytes(raw)


def public_text(key) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def sign(content: bytes, private_key: str, public: str = "") -> str:
    """The signature text for the list's bytes. With `public`, the key must be that public key's pair: a release
    signed with a key the app doesn't carry would never be offered."""
    key = _private(private_key)
    if public.strip() and public_text(key) != "".join(public.split()):
        raise SystemExit("the signing key is not the pair of the public key the app carries (release_key)")
    return base64.b64encode(key.sign(content)).decode("ascii")


def verify(content: bytes, signature: str, public: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode("".join(public.split()), validate=True))
        key.verify(base64.b64decode("".join(signature.split()), validate=True), content)
    except (InvalidSignature, ValueError):
        return False
    return True


def keygen(private_out: Path) -> str:
    """A new key pair: the private key (base64 text) into a file only its owner can read, the public key returned."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    descriptor = os.open(private_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as out:
        out.write(base64.b64encode(raw).decode("ascii") + "\n")
    return public_text(key)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("step", choices=("make", "sign", "verify", "keygen"))
    parser.add_argument("--version")
    parser.add_argument("--dir")
    parser.add_argument("--out")
    parser.add_argument("--manifest")
    parser.add_argument("--signature")
    parser.add_argument("--public", default="")
    parser.add_argument("--private-out")
    args = parser.parse_args(argv)
    if args.step == "make":
        if not (args.version and args.dir and args.out):
            parser.error("make needs --version, --dir and --out")
        Path(args.out).write_bytes(build(args.version.lstrip("vV"), Path(args.dir)))
    elif args.step == "sign":
        if not (args.manifest and args.out):
            parser.error("sign needs --manifest and --out")
        private = os.environ.get(KEY_VARIABLE, "")
        if not private.strip():
            raise SystemExit(f"{KEY_VARIABLE} is not set, so the list can't be signed")
        content = Path(args.manifest).read_bytes()
        signature = sign(content, private, args.public)
        Path(args.out).write_text(signature + "\n", encoding="ascii")
    elif args.step == "verify":
        if not (args.manifest and args.signature and args.public):
            parser.error("verify needs --manifest, --signature and --public")
        signature = Path(args.signature).read_text(encoding="ascii")
        if not verify(Path(args.manifest).read_bytes(), signature, args.public):
            raise SystemExit("the signature does not verify")
        print("the signature verifies")
    else:
        if not args.private_out:
            parser.error("keygen needs --private-out")
        print(keygen(Path(args.private_out)))


if __name__ == "__main__":
    main(sys.argv[1:])
