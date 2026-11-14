"""An update comes back if it fails (S-0301, design 11.7): a copy of each workspace's database is taken first, each
workspace is opened once with the new version, and a failing step puts the previous version and the copy back."""

import sqlite3
from pathlib import Path

import pytest

from engine import updating
from engine.cli import update_checkout
from engine.storage import Store
from engine.storage.lease import Lease
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_update_restore import FakeRunner


@pytest.fixture
def ws(tmp_path):
    return init_workspace(tmp_path / "ws", template=DEMO_B, git=False)


@pytest.fixture
def checkout(tmp_path) -> Path:
    (tmp_path / "src" / ".git").mkdir(parents=True)
    (tmp_path / "src" / "web").mkdir()
    return tmp_path / "src"


def marker(ws, value=None):
    """Read, or write, one value in the workspace's database, standing for the records an update carries forward."""
    conn = sqlite3.connect(ws.db_path)
    try:
        if value is not None:
            conn.execute("CREATE TABLE IF NOT EXISTS marker(v TEXT)")
            conn.execute("DELETE FROM marker")
            conn.execute("INSERT INTO marker VALUES(?)", (value,))
            conn.commit()
            return value
        return conn.execute("SELECT v FROM marker").fetchone()[0]
    finally:
        conn.close()


def run_update(checkout, runner, workspaces, npm="npm"):
    said: list[str] = []
    code = update_checkout(checkout, runner, which=lambda name: npm, say=said.append, workspaces=workspaces)
    return code, said


def test_the_copy_holds_the_records_as_they_were_and_names_the_version_it_came_from(ws):
    marker(ws, "before")
    updating.backup(ws, "abc1234")
    marker(ws, "after the migration")
    assert updating.note(ws)["version"] == "abc1234"
    assert updating.restore(ws) is True
    assert marker(ws) == "before"
    # What was there when it was put back is kept beside it, never deleted.
    kept = sqlite3.connect(ws.db_path.with_name(updating.KEPT))
    assert kept.execute("SELECT v FROM marker").fetchone()[0] == "after the migration"
    kept.close()


def test_with_no_copy_nothing_is_put_back_and_a_copy_that_cannot_be_made_stops_the_update(ws, tmp_path):
    marker(ws, "now")
    assert updating.restore(ws) is False and marker(ws) == "now"
    ws.private_dir.mkdir(parents=True, exist_ok=True)
    (ws.private_dir / updating.FOLDER).write_text("a file where the folder should be")
    with pytest.raises(updating.UpdateError, match="nothing was changed"):
        updating.backup(ws, "abc1234")


def test_an_update_takes_the_copy_first_opens_each_workspace_after_and_keeps_what_worked(checkout, ws):
    runner = FakeRunner()
    marker(ws, "v1")
    code, said = run_update(checkout, runner, [ws])
    assert code == 0 and "Updated from aaa1111 to bbb2222." in said
    assert updating.note(ws)["version"] == "aaa1111"
    steps = runner.steps()
    assert steps[0] == ["git", "pull", "--ff-only"] and steps[1] == ["uv", "sync", "--inexact", "--locked"]
    assert steps[-1] == ["uv", "run", "thimbleby", "update-step", "check", "-w", str(ws.root)]
    assert any("[5/5]" in line for line in said)
    assert marker(ws) == "v1"  # nothing was put back


def test_a_step_made_to_fail_goes_back_to_the_commit_it_started_from(checkout, ws):
    runner = FakeRunner(fail=("uv", "sync"))
    marker(ws, "v1")
    code, said = run_update(checkout, runner, [ws])
    assert code == 1
    steps = runner.steps()
    assert ["git", "reset", "--hard", "aaa1111"] in steps
    # The old version's own lock is installed again, and the screens built again, after going back.
    back = steps[steps.index(["git", "reset", "--hard", "aaa1111"]) + 1 :]
    assert back == [
        ["uv", "sync", "--inexact", "--locked"],
        ["npm", "--prefix", "web", "install"],
        ["npm", "--prefix", "web", "run", "build"],
    ]
    assert ["uv", "run", "thimbleby", "update-step", "check", "-w", str(ws.root)] not in steps
    assert any("exit code 3" in line for line in said) and "The update was not kept" in said[-1]
    assert marker(ws) == "v1" and not ws.db_path.with_name(updating.KEPT).exists()  # no migration ran, so no copy back


def test_a_workspace_the_new_version_cannot_open_puts_the_copy_back(checkout, ws):
    runner = FakeRunner(fail=("uv", "run"))
    marker(ws, "v1")
    original = update_checkout

    def migrate_then_fail(command, cwd, capture):
        if command[:2] == ["uv", "run"]:
            marker(ws, "half migrated")  # what the new version did to the records before it failed
        return runner(command, cwd, capture)

    said: list[str] = []
    code = original(checkout, migrate_then_fail, which=lambda name: "npm", say=said.append, workspaces=[ws])
    assert code == 1
    assert ["git", "reset", "--hard", "aaa1111"] in runner.steps()
    assert marker(ws) == "v1"
    assert any("Put back the copy" in line for line in said) and "The update was not kept" in said[-1]


def test_a_failing_pull_changes_nothing_and_a_running_app_stops_the_update_before_any_step(checkout, ws):
    runner = FakeRunner(fail=("git", "pull"), heads=("aaa1111", "aaa1111"))
    code, said = run_update(checkout, runner, [ws])
    assert code == 1 and ["git", "reset", "--hard", "aaa1111"] not in runner.steps()

    store = Store(ws.db_path)
    lease = Lease(store)
    lease.acquire()
    try:
        runner = FakeRunner()
        code, said = run_update(checkout, runner, [ws])
        assert code == 1 and runner.steps() == []
        assert "The app is open" in said[0]
    finally:
        lease.release()
        store.close()


def test_the_steps_an_installer_runs_are_one_command(ws, capsys):
    from engine.cli import main

    marker(ws, "v1")
    assert main(["update-step", "backup", "--version", "0.9.0", "-w", str(ws.root)]) == 0
    marker(ws, "v2")
    assert main(["update-step", "check", "-w", str(ws.root)]) == 0
    assert main(["update-step", "restore", "-w", str(ws.root)]) == 0 and marker(ws) == "v1"
    updating_folder = ws.private_dir / updating.FOLDER
    for leftover in updating_folder.glob("*"):
        leftover.unlink()
    assert main(["update-step", "restore", "-w", str(ws.root)]) == 1
    assert "no copy to put back" in capsys.readouterr().err
