"""What the person sees while the app updates itself, and what the next start does with what an update left (S-0625,
design 11.7): the steps show in the starting window, a failed step is the failed-update screen with its reason and the
choices, a rolled-back update puts the copy of the work back, and the new version tells the waiting script it runs."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import app_update, update_flow, update_offer, updating
from engine.app_update import Install, Steps, UpdateFailed
from engine.sides import words_sheet
from engine.workspace import init_workspace
from tests import release_signing
from tests.conftest import DEMO_B

URL = "https" + "://releases.example.com/v0.2.0/Thimbleby-0.2.0-macos-arm64.dmg"
SHA = "a" * 64


@pytest.fixture
def ws(tmp_path):
    made = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    made.private_dir.mkdir(exist_ok=True)
    release_signing.trust(made)  # the release kept below carries its list of files, signed with the test run's key
    found = {
        "version": "0.2.0",
        "date": "2026-11-16",
        "notes": ["Faster start"],
        "page": "https" + "://releases.example.com/tag/v0.2.0",
        "download_url": URL,
        "sha256": SHA,
    }
    update_offer._write(made.private_dir, {"found": release_signing.signed_found(found)})
    return made


@pytest.fixture
def cfg(ws):
    return ws.config(env={})


class FakeShell:
    """The window the update talks to: it records what it was told and answers the failed-update screen from a list."""

    def __init__(self, answers=()):
        self.words = {k: str(v) for k, v in words_sheet().items() if k.startswith("desktop.")}
        self.calls, self.answers = [], list(answers)
        self.quit_event = threading.Event()
        self.details = ""

    def show_update(self, version=""):
        self.calls.append(("show_update", version))

    def update_step(self, step, fraction=None, detail=""):
        self.calls.append(("step", step))

    def update_failed(self, version, reason, details):
        self.calls.append(("failed", version, reason))
        self.details = details
        return self.answers.pop(0) if self.answers else ""

    def restore_failed(self, version, reason, details):
        self.calls.append(("unrestored", version, reason))
        self.details = details
        answer = self.answers.pop(0) if self.answers else ""
        if callable(answer):  # something the person does before pressing Try again
            answer = answer()
        return "again" if answer == "again" else ""

    def resume_starting(self):
        self.calls.append(("resume",))

    def quit(self):
        self.quit_event.set()
        self.calls.append(("quit",))


MAC = Install("Darwin", Path("/Applications/Thimbleby.app"), Path("/x"))


def steps(*, fail=None, kind="download"):
    """Update steps whose outside work records itself; the named one raises."""
    log = []

    def make(name):
        def step(*_a, **_k):
            log.append(name)
            if fail == name:
                raise UpdateFailed(kind, f"{name} failed")
            return Path("/dl/file")

        return step

    def backup(*_a):
        log.append("backup")
        if fail == "backup":
            raise UpdateFailed(kind, "backup failed")

    return Steps(backup=backup, download=make("download"), stage=make("stage"), hand_over=make("hand_over")), log


def test_the_window_shows_the_update_and_the_hand_over_ends_the_flow_with_true(ws, cfg):
    shell, (recorded, log) = FakeShell(), steps()
    assert update_flow.install(ws, cfg, shell, "0.2.0", current="0.1.0", steps=recorded, install_at=MAC) is True
    assert shell.calls[0] == ("show_update", "0.1.0")
    assert [c[1] for c in shell.calls if c[0] == "step"] == ["copy", "download", "check", "install", "open"]
    assert log == ["backup", "download", "stage", "backup", "hand_over"]


@pytest.mark.parametrize(
    ("fail", "kind", "words"),
    [
        ("backup", "copy", "couldn't be copied"),
        ("download", "offline", "isn't connected"),
        ("stage", "unreadable", "couldn't be opened"),
        ("hand_over", "install", "couldn't be installed"),
    ],
)
def test_a_step_that_fails_shows_one_reason_in_words_and_going_on_leaves_the_version_they_have(
    ws, cfg, fail, kind, words
):
    shell, (recorded, _) = FakeShell(answers=["open"]), steps(fail=fail, kind=kind)
    assert update_flow.install(ws, cfg, shell, "0.2.0", current="0.1.0", steps=recorded, install_at=MAC) is False
    [failed] = [c for c in shell.calls if c[0] == "failed"]
    assert failed[1] == "0.1.0" and words in failed[2]
    assert f"{kind}:" in shell.details and "Update from 0.1.0 to 0.2.0" in shell.details  # what Copy details copies
    assert ("quit",) not in shell.calls


def test_try_again_runs_the_steps_again_and_a_second_failure_asks_again(ws, cfg):
    shell, (recorded, log) = FakeShell(answers=["again", "again"]), steps(fail="download", kind="download")
    assert update_flow.install(ws, cfg, shell, "0.2.0", current="0.1.0", steps=recorded, install_at=MAC) is False
    assert log.count("download") == 3 and len([c for c in shell.calls if c[0] == "failed"]) == 3


def test_a_version_that_is_no_longer_on_offer_is_a_failed_update_not_a_silent_return(ws, cfg):
    shell, (recorded, log) = FakeShell(answers=["open"]), steps()
    assert update_flow.install(ws, cfg, shell, "9.9.9", current="0.1.0", steps=recorded, install_at=MAC) is False
    assert log == [] and any(c[0] == "failed" for c in shell.calls)


def test_a_release_whose_signed_list_no_longer_checks_is_not_installed_and_no_step_runs(ws, cfg):
    """H5-28: the signature is checked again when the person clicks, with the keys trusted at that moment; a kept
    release it doesn't hold for is no offer, so nothing is copied, downloaded or handed over."""
    release_signing.trust(ws, release_signing.OTHER_PUBLIC)
    shell, (recorded, log) = FakeShell(answers=["open"]), steps()
    assert update_flow.install(ws, cfg, shell, "0.2.0", current="0.1.0", steps=recorded, install_at=MAC) is False
    assert log == [] and any(c[0] == "failed" for c in shell.calls)
    assert "isn't on offer any more" in shell.details
    release_signing.trust(ws)
    shell, (recorded, log) = FakeShell(), steps()
    assert update_flow.install(ws, cfg, shell, "0.2.0", current="0.1.0", steps=recorded, install_at=MAC) is True
    assert "hand_over" in log


def test_a_copy_that_is_not_the_installed_app_says_so_in_words(ws, cfg):
    shell, (recorded, log) = FakeShell(answers=["open"]), steps()
    assert update_flow.install(ws, cfg, shell, "0.2.0", current="0.1.0", steps=recorded, install_at=None) is False
    [failed] = [c for c in shell.calls if c[0] == "failed"]
    assert "isn't the installed app" in failed[2] and log == []


def test_every_way_an_update_can_fail_has_words_and_an_unknown_one_still_has_some(ws):
    shell = FakeShell()
    for kind in app_update.KINDS:
        assert update_flow.reason(shell.words, kind) and not update_flow.reason(shell.words, kind).startswith(
            "desktop."
        )
    assert update_flow.reason(shell.words, "something new") == shell.words["desktop.update.reason.other"]


# ---- the next start --------------------------------------------------------------------------------------------------


def write_result(ws, **body):
    (ws.private_dir / app_update.RESULT_FILE).write_text(json.dumps(body))


def marker(ws, value=None):
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


def test_a_start_with_nothing_left_by_an_update_goes_straight_on(ws, cfg):
    shell = FakeShell()
    assert update_flow.settle(ws, cfg, shell, current="0.1.0") is True and shell.calls == []


def test_a_rolled_back_update_puts_the_copy_of_the_work_back_and_shows_why_once(ws, cfg):
    marker(ws, "before")
    app_update.copy_work(ws, "0.1.0")
    marker(ws, "after the new version ran")
    write_result(ws, status="failed", reason="no_answer", restore=True, **{"from": "0.1.0"})
    shell = FakeShell(answers=["open"])
    assert update_flow.settle(ws, cfg, shell, current="0.1.0") is True
    assert marker(ws) == "before"
    [failed] = [c for c in shell.calls if c[0] == "failed"]
    assert failed[1] == "0.1.0" and "old one was put back" in failed[2]
    assert "copy of the work made before updating was put back" in shell.details
    assert ("resume",) in shell.calls
    assert app_update.read_result(ws) is None  # shown once


def test_a_failure_before_anything_changed_does_not_touch_the_database(ws, cfg):
    marker(ws, "now")
    app_update.copy_work(ws, "0.1.0")
    marker(ws, "later")
    write_result(ws, status="failed", reason="close", restore=False, **{"from": "0.1.0"})
    assert update_flow.settle(ws, cfg, FakeShell(answers=["open"]), current="0.1.0") is True
    assert marker(ws) == "later"


def test_try_again_on_the_failed_screen_runs_the_update_before_the_workspace_opens(ws, cfg):
    write_result(ws, status="failed", reason="install", restore=False, **{"from": "0.1.0"})
    shell, (recorded, log) = FakeShell(answers=["again"]), steps()
    assert update_flow.settle(ws, cfg, shell, current="0.1.0", steps=recorded, install_at=MAC) is False
    assert "hand_over" in log and ("quit",) in shell.calls


def test_quitting_from_the_failed_screen_does_not_start_the_app(ws, cfg):
    write_result(ws, status="failed", reason="install", restore=False, **{"from": "0.1.0"})
    shell = FakeShell(answers=[""])
    shell.quit_event.set()
    assert update_flow.settle(ws, cfg, shell, current="0.1.0") is False


def test_a_finished_update_is_left_for_today_to_say_and_never_shows_the_failed_screen(ws, cfg):
    write_result(ws, status="ok", version="0.2.0", **{"from": "0.1.0"})
    shell = FakeShell()
    assert update_flow.settle(ws, cfg, shell, current="0.2.0") is True and shell.calls == []
    assert app_update.read_result(ws)["status"] == "ok"


def test_with_no_copy_to_put_back_the_failed_screen_still_shows_and_nothing_is_left_waiting(ws, cfg):
    write_result(ws, status="failed", reason="no_answer", restore=True, **{"from": "0.1.0"})  # no copy was ever made
    shell = FakeShell(answers=["open"])
    assert update_flow.settle(ws, cfg, shell, current="0.1.0") is True
    assert any(c[0] == "failed" for c in shell.calls) and not any(c[0] == "unrestored" for c in shell.calls)
    assert app_update.restore_needed(ws) is None


# ---- a failed restore is never forgotten (H5-28, H2) -----------------------------------------------------------------


def rolled_back(ws):
    """A rolled-back update whose copy of the work has to be put back, and a disk that refuses it."""
    marker(ws, "before")
    app_update.copy_work(ws, "0.1.0")
    marker(ws, "after the new version ran")
    write_result(ws, status="failed", reason="no_answer", restore=True, **{"from": "0.1.0"})


def refuse_restores(monkeypatch):
    """The copy can't be put back (as a full disk refuses it); returns the switch that lets it through again."""
    real, refusing = updating.restore, [True]

    def restore(ws):
        if refusing[0]:
            raise updating.UpdateError("The copy made before updating couldn't be put back (OSError).")
        return real(ws)

    monkeypatch.setattr(updating, "restore", restore)
    return lambda: refusing.clear() or refusing.append(False)


def test_a_restore_that_fails_keeps_the_app_closed_and_is_tried_again_at_every_start_until_it_works(
    ws, cfg, monkeypatch
):
    """The review's sequence: the update is rolled back, putting the work back fails, the person quits. Before, the
    plan and result were cleared and the next start opened the workspace on the new version's database."""
    rolled_back(ws)
    allow = refuse_restores(monkeypatch)
    shell = FakeShell(answers=[""])  # Quit
    assert update_flow.settle(ws, cfg, shell, current="0.1.0") is False  # the workspace is not opened
    [shown] = [c for c in shell.calls if c[0] == "unrestored"]
    assert shown[1] == "0.1.0" and "couldn't be put back" in shown[2] and "nothing has been deleted" in shown[2]
    assert ("quit",) in shell.calls and ("resume",) not in shell.calls
    assert not any(c[0] == "failed" for c in shell.calls)  # no way on to the app from here
    assert "couldn't be put back (OSError)" in shell.details
    assert app_update.restore_needed(ws)["from"] == "0.1.0"
    assert marker(ws) == "after the new version ran"  # untouched, and still not opened

    # The next start, and the one after: still refused, still closed, even with the update's result gone.
    app_update.clear(ws)
    for _ in range(2):
        again = FakeShell(answers=[""])
        assert update_flow.settle(ws, cfg, again, current="0.1.0") is False
        assert [c[0] for c in again.calls] == ["unrestored", "quit"]
        assert app_update.restore_needed(ws) is not None

    # Once it can be put back, it is, before the app goes on.
    allow()
    last = FakeShell()
    assert update_flow.settle(ws, cfg, last, current="0.1.0") is True
    assert marker(ws) == "before" and app_update.restore_needed(ws) is None
    assert not any(c[0] == "unrestored" for c in last.calls)


def test_try_again_on_that_screen_puts_the_work_back_and_then_shows_why_the_update_failed(ws, cfg, monkeypatch):
    rolled_back(ws)
    allow = refuse_restores(monkeypatch)
    shell = FakeShell(answers=["again", lambda: allow() or "again", "open"])
    assert update_flow.settle(ws, cfg, shell, current="0.1.0") is True
    assert [c[0] for c in shell.calls] == ["unrestored", "unrestored", "failed", "resume"]
    assert marker(ws) == "before" and app_update.restore_needed(ws) is None
    assert "copy of the work made before updating was put back" in shell.details
    assert app_update.read_result(ws) is None  # the failed update itself is shown once


def test_the_need_to_put_the_work_back_is_noted_before_the_restore_is_tried(ws, cfg, monkeypatch):
    """A start that stops in the middle of the restore (the power goes) leaves the note, not a cleared result."""
    rolled_back(ws)

    def stopped(_ws):
        assert app_update.restore_needed(ws) is not None
        raise KeyboardInterrupt

    monkeypatch.setattr(updating, "restore", stopped)
    with pytest.raises(KeyboardInterrupt):
        update_flow.settle(ws, cfg, FakeShell(), current="0.1.0")
    assert app_update.restore_needed(ws) is not None and app_update.read_result(ws) is not None


def test_a_restore_never_leaves_the_live_database_missing_and_can_be_run_again(ws, monkeypatch):
    """`updating.restore` used to move the live database aside first: a failure after that left none at all."""
    marker(ws, "before")
    app_update.copy_work(ws, "0.1.0")
    marker(ws, "after")
    real_replace, seen = updating.os.replace, []

    def replace(source, target):
        if Path(target) == ws.db_path:
            seen.append(ws.db_path.is_file())  # the live database is there at the moment it is replaced
            raise OSError(28, "No space left on device")
        return real_replace(source, target)

    monkeypatch.setattr(updating.os, "replace", replace)
    with pytest.raises(updating.UpdateError):
        updating.restore(ws)
    assert seen == [True] and marker(ws) == "after"  # still the database it was, whole
    assert not list(ws.db_path.parent.glob(".*.restoring"))
    monkeypatch.setattr(updating.os, "replace", real_replace)
    assert updating.restore(ws) is True and marker(ws) == "before"
    kept = sqlite3.connect(ws.db_path.with_name(updating.KEPT))
    try:
        assert kept.execute("SELECT v FROM marker").fetchone()[0] == "after"  # what the new version left is kept
    finally:
        kept.close()
    assert updating.restore(ws) is True  # run once more: nothing to do, and the kept database is not overwritten
    kept = sqlite3.connect(ws.db_path.with_name(updating.KEPT))
    try:
        assert kept.execute("SELECT v FROM marker").fetchone()[0] == "after"
    finally:
        kept.close()


def test_the_database_kept_aside_holds_what_was_still_in_its_journal(ws):
    marker(ws, "before")
    app_update.copy_work(ws, "0.1.0")
    conn = sqlite3.connect(ws.db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("UPDATE marker SET v = 'written to the journal only'")
    conn.commit()
    import shutil

    # The database as a stopped program leaves it: its last writes still in the journal file beside it.
    for extra in ("", "-wal"):
        shutil.copy(f"{ws.db_path}{extra}", f"{ws.db_path}.crashed{extra}")
    conn.close()
    for extra in ("", "-wal"):
        shutil.move(f"{ws.db_path}.crashed{extra}", f"{ws.db_path}{extra}")
    assert updating.restore(ws) is True and marker(ws) == "before"
    kept = sqlite3.connect(ws.db_path.with_name(updating.KEPT))
    try:
        assert kept.execute("SELECT v FROM marker").fetchone()[0] == "written to the journal only"
    finally:
        kept.close()


def test_the_new_version_tells_the_waiting_script_it_runs_only_when_a_hand_over_waits(ws, tmp_path):
    assert update_flow.started(ws, "0.2.0") is False
    app_update.hand_over(
        ws,
        Install("Windows", tmp_path / "Thimbleby", tmp_path / "Thimbleby" / "Thimbleby.exe"),
        tmp_path / "setup.exe",
        from_version="0.1.0",
        version="0.2.0",
        page=None,
        notes=[],
        settings=SimpleNamespace(close_wait_seconds=30, answer_wait_seconds=60, install_wait_seconds=60),
        spawn=lambda _a: None,
        pid=1,
        sha256=SHA,
    )
    # The version that was updated from, opened again while the script waits, is not the update's success (H5-28, H3).
    assert update_flow.started(ws, "0.1.0") is False
    assert app_update.read_result(ws)["status"] == "wrong" and app_update.read_plan(ws) is not None
    assert update_flow.started(ws, "0.2.0") is True
    assert app_update.read_result(ws)["status"] == "ok"


def test_the_failed_screen_rolls_a_database_back_only_through_the_one_restore(ws, cfg):
    """The put-back is the same function the command line's update uses, so the copy, its note and the kept database
    beside it behave as they do there."""
    marker(ws, "a")
    app_update.copy_work(ws, "0.1.0")
    marker(ws, "b")
    write_result(ws, status="failed", reason="no_answer", restore=True, **{"from": "0.1.0"})
    update_flow.settle(ws, cfg, FakeShell(answers=["open"]), current="0.1.0")
    assert (ws.db_path.with_name(updating.KEPT)).is_file()
