"""Which build this is, and which of two copies is newer (S-0662): the stamp the installer build writes, the rule that
decides a take-over, the same stamp on the runtime config, and the build step that writes it."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.build_info import Build, current, from_published, is_newer, stamp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "desktop" / "build_support"))
import release_tools  # noqa: E402


def test_a_stamped_build_reads_its_number_and_commit_and_a_source_run_says_it_has_none(tmp_path):
    assert stamp(tmp_path) == (None, "")
    (tmp_path / "build.yaml").write_text("number: 52\ncommit: 630a595abcdef\n")
    assert stamp(tmp_path) == (52, "630a595abcde")
    (tmp_path / "build.yaml").write_text("number: banana\ncommit: 5\n")
    assert stamp(tmp_path) == (None, "")
    (tmp_path / "build.yaml").write_text("{ not: [valid")
    assert stamp(tmp_path) == (None, "")
    assert current(tmp_path).number is None


@pytest.mark.parametrize(
    ("new", "running", "newer"),
    [
        (Build("0.1.0", 52), Build("0.1.0", 51), True),
        (Build("0.1.0", 52), Build("0.1.0", 52), False),
        (Build("0.1.0", 51), Build("0.1.0", 52), False),
        (Build("0.2.0", 1), Build("0.1.0", 90), True),
        (Build("0.1.0", 90), Build("0.2.0", 1), False),
        (Build("0.1.0", 52), None, True),  # the running copy predates the stamp
        (Build("0.1.0"), None, False),  # a source run takes over from nothing
        (Build("0.1.0"), Build("0.1.0", 51), False),
        (Build("0.1.0", 52), Build("0.1.0"), False),
        (Build("not a version", 5), Build("0.1.0", 1), False),
    ],
)
def test_the_newer_copy_is_the_higher_version_then_the_higher_numbered_build(new, running, newer):
    assert is_newer(new, running) is newer


def test_a_published_identity_is_read_back_and_nothing_published_is_none():
    assert from_published({"version": "0.1.0", "build": 51, "commit": "abc"}) == Build("0.1.0", 51, "abc")
    assert from_published({"version": "0.1.0", "build": None}) == Build("0.1.0")
    assert from_published(None) is None and from_published({}) is None and from_published({"build": 3}) is None


def test_the_runtime_config_names_the_build_from_its_stamp(tmp_path, monkeypatch, demo):
    from api.app import create_app
    from engine import build_info
    from engine.config import load_config
    from engine.workspace import init_workspace

    monkeypatch.setattr(build_info, "current", lambda catalog=None: Build("0.1.0", 52, "630a595"))
    ws = init_workspace(tmp_path / "ws", template=demo, git=False)
    client = TestClient(create_app(ws, load_config(ws.config_dir, env={}, flags={}), "tok"))
    body = client.get("/api/runtime-config", headers={"Authorization": "Bearer tok"}).json()
    assert (body["build_number"], body["build_commit"]) == (52, "630a595")
    monkeypatch.setattr(build_info, "current", lambda catalog=None: Build("0.1.0"))
    body = client.get("/api/runtime-config", headers={"Authorization": "Bearer tok"}).json()
    assert (body["build_number"], body["build_commit"]) == (None, None)


def test_the_release_build_stamps_its_run_number_and_commit_and_a_build_by_hand_stays_unstamped(tmp_path):
    path = tmp_path / "build.yaml"
    assert release_tools.write_build_stamp(path, {"GITHUB_RUN_NUMBER": "52", "GITHUB_SHA": "630a595" + "0" * 33})
    assert stamp(tmp_path) == (52, "630a595")
    path.unlink()
    for env in ({}, {"GITHUB_RUN_NUMBER": "52"}, {"GITHUB_RUN_NUMBER": "x", "GITHUB_SHA": "630a595"}):
        assert not release_tools.write_build_stamp(path, env) and not path.exists()
