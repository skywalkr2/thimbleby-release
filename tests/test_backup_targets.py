"""Each backup place is judged on its own, each copy is opened and checked after it is written, and a copy much
smaller than the last is flagged (design 6.14). One place that fails every night is never hidden by one that works."""

from datetime import UTC, datetime, timedelta

import pytest

from engine import backup
from engine.backup import run_backup, state
from engine.config.schema import BackupSettings
from engine.storage import Store
from engine.today_queue import queue
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "thimbleby", template=DEMO_B, git=False)
    local, remote = tmp_path / "local", tmp_path / "remote"
    local.mkdir()
    remote.mkdir()
    cfg = ws.config(
        env={},
        flags={
            "storage.backups.targets": [
                {"path": str(local), "label": "this computer"},
                {"path": str(remote), "label": "the drive"},
            ],
            "storage.backups.automatic": False,
            "storage.backups.every_hours": 24,
        },
    )
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store, local, remote
    store.close()


def test_a_place_failing_for_36_hours_is_shown_while_the_other_is_fine(env):
    ws, cfg, store, local, remote = env
    run_backup(ws, cfg, NOW)
    remote.rename(remote.with_name("unplugged"))  # the off-machine place stops answering; the local one goes on
    for hours in (12, 24, 36):
        run_backup(ws, cfg, NOW + timedelta(hours=hours))
    kept = state(ws, cfg, NOW + timedelta(hours=36))
    # The folder isn't there at all: one state for it everywhere, not "failed" (a copy kept here is still fine).
    assert kept.needs_attention and kept.place == "the drive" and kept.problem == "folder_missing"
    assert kept.last_error and "Backup folder missing: 'the drive' not found" in kept.message
    lines = [x for x in queue(ws, store, cfg, NOW + timedelta(hours=36)) if x.kind == "backup"]
    assert len(lines) == 1 and lines[0].state == "folder_missing" and lines[0].subject == "the drive"


def test_both_places_working_is_no_line(env):
    ws, cfg, store, *_ = env
    run_backup(ws, cfg, NOW)
    kept = state(ws, cfg, NOW + timedelta(hours=20))
    assert not kept.needs_attention and kept.problem is None and kept.place is None


def test_a_place_with_no_copy_in_over_two_days_is_overdue_even_though_the_other_is_recent(env):
    ws, cfg, store, local, remote = env
    run_backup(ws, cfg, NOW)
    remote.rename(remote.with_name("unplugged"))
    run_backup(ws, cfg, NOW + timedelta(hours=60))
    kept = state(ws, cfg, NOW + timedelta(hours=60))
    assert kept.problem == "overdue" and kept.place == "the drive" and "overdue" in kept.message


def test_a_copy_that_cannot_be_opened_is_not_kept_and_the_place_says_why(env, monkeypatch):
    ws, cfg, store, local, remote = env
    real = backup._copy

    def damaged(w, dest):
        real(w, dest)
        (dest / "thimbleby.db").write_bytes(b"this is not a database at all" * 100)

    monkeypatch.setattr(backup, "_copy", damaged)
    status = run_backup(ws, cfg, NOW)
    assert all(
        entry["last_success"] is None and "doesn't check out" in entry["last_error"] for entry in status.values()
    )
    assert not [p for p in local.iterdir()], "a copy that fails its check leaves nothing behind, not even a partial"


def test_an_encrypted_copy_is_opened_with_its_key_before_it_counts(env, monkeypatch, tmp_path):
    ws, cfg, store, local, remote = env
    key = tmp_path / "key"
    key.write_text("a long enough passphrase for the test")
    cfg = ws.config(
        env={},
        flags={
            "storage.backups.targets": [{"path": str(local)}],
            "storage.backups.encrypt": f"file:{key}",
        },
    )
    status = run_backup(ws, cfg, NOW)
    assert status[str(local)]["last_success"] and status[str(local)]["last_error"] is None
    from engine import backup_crypto

    def broken(*_a, **_k):
        raise backup_crypto.BackupDamaged("a sealed file doesn't match")

    monkeypatch.setattr(backup_crypto, "open_tree", broken)
    later = run_backup(ws, cfg, NOW + timedelta(hours=1))
    assert "doesn't check out" in later[str(local)]["last_error"]


def test_a_copy_much_smaller_than_the_last_is_flagged(env):
    ws, cfg, store, local, remote = env
    run_backup(ws, cfg, NOW)
    files = ws.root / "files"
    files.mkdir(exist_ok=True)
    (files / "big.bin").write_bytes(b"x" * 400_000)
    run_backup(ws, cfg, NOW + timedelta(hours=1))
    (files / "big.bin").unlink()
    run_backup(ws, cfg, NOW + timedelta(hours=2))
    kept = state(ws, cfg, NOW + timedelta(hours=3))
    assert kept.needs_attention and kept.problem == "smaller" and "much smaller" in kept.message
    # The next copy, as big as the one before it, clears the flag.
    run_backup(ws, cfg, NOW + timedelta(hours=4))
    assert not state(ws, cfg, NOW + timedelta(hours=5)).needs_attention


def test_the_shrink_limit_is_a_setting_with_a_default():
    assert BackupSettings.model_fields["shrink_percent"].default == 50
    assert BackupSettings.model_fields["shrink_percent"].description
