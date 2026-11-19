"""A release's signed list of files (H5-28, signed releases): the list the release
build makes and signs is the one the app reads, a list that was changed or signed by another key reads as no list, and
the build's script never signs with a key that is not the pair of the one the app carries. Every key here is made for
the test run and kept nowhere."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

from engine import release_manifest
from tests import release_signing
from tests.release_signing import OTHER_PUBLIC, PUBLIC

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "deploy" / "desktop" / "build_support"))

import release_manifest as build_script  # noqa: E402

HOST = "https" + "://releases.example.com"
SHA = "a" * 64
FILES = {"Thimbleby-0.2.0-windows-x64-setup.exe": (1234, SHA), "Thimbleby-0.2.0-macos-arm64.dmg": (99, "b" * 64)}
SETUP = "Thimbleby-0.2.0-windows-x64-setup.exe"


def test_a_list_signed_by_a_trusted_key_gives_the_installers_checksum_and_size():
    content = release_signing.manifest("0.2.0", FILES)
    signature = release_signing.sign(content)
    assert release_manifest.listed(content, signature, [PUBLIC], "0.2.0", SETUP) == release_manifest.Listed(
        SETUP, 1234, SHA
    )
    assert release_manifest.listed(content, signature, [OTHER_PUBLIC, PUBLIC], "v0.2.0".lstrip("v"), SETUP, SHA)
    assert release_manifest.listed(content, signature + "\n", [PUBLIC], "0.2", SETUP)  # the same version, written short


def test_a_list_that_was_changed_or_signed_by_another_key_or_is_for_something_else_reads_as_no_list():
    content = release_signing.manifest("0.2.0", FILES)
    signature = release_signing.sign(content)
    changed = content.replace(SHA.encode(), b"c" * 64)
    cases = [
        (changed, signature, [PUBLIC], "0.2.0", SETUP, None),  # the list changed after it was signed
        (content, release_signing.sign(content, release_signing.OTHER_KEY), [PUBLIC], "0.2.0", SETUP, None),
        (content, signature, [], "0.2.0", SETUP, None),  # nothing is trusted
        (content, signature, ["not a key"], "0.2.0", SETUP, None),
        (content, "", [PUBLIC], "0.2.0", SETUP, None),
        (content, signature, [PUBLIC], "0.3.0", SETUP, None),  # another release's list
        (content, signature, [PUBLIC], "0.2.0", "Other-setup.exe", None),  # a file the list doesn't hold
        (content, signature, [PUBLIC], "0.2.0", SETUP, "c" * 64),  # another checksum than the list's
        (content, signature, [PUBLIC], "not a version", SETUP, None),
    ]
    for case in cases:
        assert release_manifest.listed(*case) is None, case


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        json.dumps({"format": 2, "version": "0.2.0", "files": []}).encode(),
        json.dumps({"format": 1, "version": 2, "files": []}).encode(),
        json.dumps({"format": 1, "version": "0.2.0", "files": {}}).encode(),
        json.dumps({"format": 1, "version": "0.2.0", "files": [{"name": SETUP, "size": "1", "sha256": SHA}]}).encode(),
        json.dumps({"format": 1, "version": "0.2.0", "files": [{"name": SETUP, "size": 1, "sha256": "abc"}]}).encode(),
        json.dumps(
            {"format": 1, "version": "0.2.0", "files": [{"name": SETUP, "size": 1, "sha256": SHA}] * 2}
        ).encode(),
    ],
)
def test_a_signed_file_that_is_not_a_list_in_this_format_reads_as_no_list(body):
    assert release_manifest.read(body, release_signing.sign(body), [PUBLIC]) is None


# ---- fetching the list: its address and an Accept header, nothing else -----------------------------------------------


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_the_list_is_fetched_by_its_address_alone_and_a_redirect_is_followed_only_to_a_secure_address():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v0.2.0/list":
            return httpx.Response(302, headers={"location": "https" + "://files.example.com/kept/list"})
        if request.url.host == "files.example.com":
            return httpx.Response(200, content=b"the list")
        if request.url.path == "/plain":
            return httpx.Response(302, headers={"location": "http" + "://files.example.com/kept/list"})
        if request.url.path == "/large":
            return httpx.Response(200, content=b"x" * (release_manifest.MAX_BYTES + 1))
        return httpx.Response(404)

    assert release_manifest.fetch(f"{HOST}/v0.2.0/list", client=client(handler)) == b"the list"
    first = seen[0]
    assert first.headers["accept"] == release_manifest.ACCEPT and not first.url.query and not first.content
    assert "authorization" not in first.headers and "cookie" not in first.headers
    for bad in ("/plain", "/large", "/missing"):
        with pytest.raises(ValueError):
            release_manifest.fetch(f"{HOST}{bad}", client=client(handler))
    with pytest.raises(ValueError):
        release_manifest.fetch("http" + "://releases.example.com/list", client=client(handler))


# ---- the release build's script ----------------------------------------------------------------------------------


@pytest.fixture
def built(tmp_path):
    """The installers and checksum files as the builds leave them for the release: a folder per target."""
    folder = tmp_path / "installers"
    for target, name, body in (
        ("Thimbleby-0.2.0-windows-x64-unsigned", SETUP, b"the setup" * 100),
        ("Thimbleby-0.2.0-macos-arm64-unsigned", "Thimbleby-0.2.0-macos-arm64.dmg", b"the image" * 50),
    ):
        (folder / target).mkdir(parents=True)
        (folder / target / name).write_bytes(body)
        (folder / target / "SHA256SUMS.txt").write_text(f"{hashlib.sha256(body).hexdigest()}  {name}\n")
    return folder


def private_text(key) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return base64.b64encode(raw).decode("ascii")


def test_the_list_the_build_makes_and_signs_is_the_one_the_app_reads(built, tmp_path, monkeypatch):
    out, sig = tmp_path / build_script.MANIFEST_NAME, tmp_path / build_script.SIGNATURE_NAME
    build_script.main(["make", "--version", "v0.2.0", "--dir", str(built), "--out", str(out)])
    monkeypatch.setenv(build_script.KEY_VARIABLE, private_text(release_signing.KEY))
    build_script.main(["sign", "--manifest", str(out), "--out", str(sig), "--public", PUBLIC])
    build_script.main(["verify", "--manifest", str(out), "--signature", str(sig), "--public", PUBLIC])
    # The names and the format are the ones the app looks for among a release's files.
    assert (build_script.MANIFEST_NAME, build_script.SIGNATURE_NAME, build_script.FORMAT) == (
        release_manifest.MANIFEST_NAME, release_manifest.SIGNATURE_NAME, release_manifest.FORMAT,
    )  # fmt: skip
    found = release_manifest.listed(out.read_bytes(), sig.read_text(), [PUBLIC], "0.2.0", SETUP)
    body = (built / "Thimbleby-0.2.0-windows-x64-unsigned" / SETUP).read_bytes()
    assert found == release_manifest.Listed(SETUP, len(body), hashlib.sha256(body).hexdigest())
    assert json.loads(out.read_bytes())["version"] == "0.2.0" and len(json.loads(out.read_bytes())["files"]) == 2
    assert private_text(release_signing.KEY) not in out.read_text() + sig.read_text()


def test_the_build_refuses_a_missing_key_a_key_that_is_not_the_apps_pair_and_a_checksum_that_is_not_the_files(
    built, tmp_path, monkeypatch
):
    out, sig = tmp_path / "list.json", tmp_path / "list.json.sig"
    build_script.main(["make", "--version", "0.2.0", "--dir", str(built), "--out", str(out)])
    monkeypatch.delenv(build_script.KEY_VARIABLE, raising=False)
    with pytest.raises(SystemExit, match="is not set"):
        build_script.main(["sign", "--manifest", str(out), "--out", str(sig)])
    monkeypatch.setenv(build_script.KEY_VARIABLE, "not a key")
    with pytest.raises(SystemExit, match="not a raw 32-byte"):
        build_script.main(["sign", "--manifest", str(out), "--out", str(sig)])
    monkeypatch.setenv(build_script.KEY_VARIABLE, private_text(release_signing.OTHER_KEY))
    with pytest.raises(SystemExit, match="not the pair"):
        build_script.main(["sign", "--manifest", str(out), "--out", str(sig), "--public", PUBLIC])
    assert not sig.exists()  # nothing was signed
    (built / "Thimbleby-0.2.0-windows-x64-unsigned" / SETUP).write_bytes(b"changed after its checksum was written")
    with pytest.raises(SystemExit, match="is not the file"):
        build_script.main(["make", "--version", "0.2.0", "--dir", str(built), "--out", str(out)])
    with pytest.raises(SystemExit):
        build_script.main(["make", "--version", "0.2.0", "--dir", str(tmp_path / "none"), "--out", str(out)])


def test_a_new_key_pair_keeps_the_private_half_in_a_file_only_its_owner_reads_and_prints_the_public_half(
    tmp_path, capsys, monkeypatch
):
    kept = tmp_path / "private.key"
    build_script.main(["keygen", "--private-out", str(kept)])
    public = capsys.readouterr().out.strip()
    assert release_manifest.verify(b"x", "", [public]) is False  # a key the app's reader takes
    from engine.catalog_signature import is_public_key

    assert is_public_key(public) and kept.read_text().strip() != public
    assert kept.stat().st_mode & 0o777 == 0o600 or os.name != "posix"
    monkeypatch.setenv(build_script.KEY_VARIABLE, kept.read_text())
    signature = build_script.sign(b"a list", kept.read_text(), public)
    assert release_manifest.verify(b"a list", signature, [public])
    with pytest.raises(FileExistsError):  # a key file is never written over
        build_script.main(["keygen", "--private-out", str(kept)])


def test_this_build_and_both_made_up_workspaces_carry_no_key_of_their_own():
    """No signing key, real or stand-in, is in the repository; the build's public half is the maintainers' to fill."""
    import yaml

    facts = yaml.safe_load((REPO / "catalog" / "product.yaml").read_text())
    assert "release_key" in facts
    for demo in ("demo-a", "demo-b"):
        settings = yaml.safe_load((REPO / "workspaces" / demo / "config" / "updates.yaml").read_text())
        assert settings["trusted_keys"] == []
