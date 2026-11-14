"""Backups prune only their own workspace's copies, and a copy that didn't finish is never counted, offered or kept
(design 5.0, backups). Two workspaces may share one backup folder, and one's name may start with the other's."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from engine import backup
from engine.backup import overview, run_backup, state
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "thimbleby", template=DEMO_B, git=False)
    target = tmp_path / "offsite"
    target.mkdir()
    cfg = ws.config(env={}, flags={"storage.backups.targets": [{"path": str(target)}], "storage.backups.keep": 2})
    store = Store(ws.db_path)
    yield ws, cfg, store, target
    store.close()


def made(target: Path, name: str) -> Path:
    folder = target / name
    folder.mkdir()
    (folder / "thimbleby.db").write_bytes(b"x")
    return folder


def test_a_workspace_never_prunes_the_copies_of_one_whose_name_starts_with_its_own(env):
    ws, cfg, _, target = env
    others = [made(target, f"thimbleby-work-2026010{n}-000000") for n in range(1, 5)]
    for hours in range(3):
        run_backup(ws, cfg, NOW + timedelta(hours=hours))
    assert all(folder.is_dir() for folder in others)
    mine = [p.name for p in target.iterdir() if p.name.startswith("thimbleby-2026")]
    assert len(mine) == 2  # its own kept to the limit


def test_the_copies_listed_for_restore_are_only_this_workspaces(env):
    ws, cfg, _, target = env
    made(target, "thimbleby-work-20260101-000000")
    made(target, "thimbleby-20260102-000000")
    made(target, "thimbleby-20260102-000000-2")
    listed = [c.name for c in overview(ws, cfg, NOW, limit=10).copies]
    assert sorted(listed) == ["thimbleby-20260102-000000", "thimbleby-20260102-000000-2"]


def test_a_copy_that_fails_midway_is_removed_and_never_counted_or_offered(env, monkeypatch):
    ws, cfg, _, target = env
    run_backup(ws, cfg, NOW)
    run_backup(ws, cfg, NOW + timedelta(hours=1))
    real = backup._copy

    def broken(workspace, dest):
        real(workspace, dest)
        (dest / "half").write_text("x")
        raise OSError("the drive went away")

    monkeypatch.setattr(backup, "_copy", broken)
    status = run_backup(ws, cfg, NOW + timedelta(hours=2))
    assert "drive went away" in status[str(target)]["last_error"]
    monkeypatch.undo()
    names = sorted(p.name for p in target.iterdir())
    assert len(names) == 2 and all(n.startswith("thimbleby-2026") and not n.endswith(".part") for n in names)
    assert [c.name for c in overview(ws, cfg, NOW, limit=10).copies] == sorted(names, reverse=True)
    assert state(ws, cfg, NOW + timedelta(hours=2)).last_error  # and the failure still says so


def test_a_copy_an_earlier_run_left_unfinished_is_removed_and_never_offered(env):
    ws, cfg, _, target = env
    left = made(target, ".thimbleby-20260101-000000.part")
    other = made(target, ".thimbleby-work-20260101-000000.part")  # another workspace's, maybe still being made
    assert [c.name for c in overview(ws, cfg, NOW, limit=10).copies] == []
    run_backup(ws, cfg, NOW)
    assert not left.exists() and other.exists()
    assert len([c for c in overview(ws, cfg, NOW, limit=10).copies]) == 1


def test_two_backups_in_one_second_both_finish_and_neither_is_taken_for_unfinished(env):
    ws, cfg, _, target = env
    run_backup(ws, cfg, NOW)
    run_backup(ws, cfg, NOW)
    assert sorted(p.name for p in target.iterdir()) == ["thimbleby-20261009-140000", "thimbleby-20261009-140000-2"]
    assert all((p / "thimbleby.db").is_file() for p in target.iterdir())
