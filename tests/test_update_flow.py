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
from tests.conftest import DEMO_B

URL = "https" + "://releases.example.com/v0.2.0/Thimbleby-0.2.0-macos-arm64.dmg"
SHA = "a" * 64


@pytest.fixture
def ws(tmp_path):
    made = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    made.private_dir.mkdir(exist_ok=True)
    update_offer._write(
        made.private_dir,
        {
            "found": {
                "version": "0.2.0",
                "date": "2026-11-16",
                "notes": ["Faster start"],
                "page": "https" + "://releases.example.com/tag/v0.2.0",
                "download_url": URL,
                "sha256": SHA,
            }
        },
    )
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


def test_a_restore_that_cannot_be_done_is_said_in_the_details_and_the_screen_still_shows(ws, cfg):
    write_result(ws, status="failed", reason="no_answer", restore=True, **{"from": "0.1.0"})  # no copy was ever made
    shell = FakeShell(answers=["open"])
    assert update_flow.settle(ws, cfg, shell, current="0.1.0") is True
    assert any(c[0] == "failed" for c in shell.calls)


def test_the_new_version_tells_the_waiting_script_it_runs_only_when_a_hand_over_waits(ws, tmp_path):
    assert update_flow.started(ws, "0.2.0") is False
    app_update.hand_over(
        ws,
        MAC,
        tmp_path / "n",
        from_version="0.1.0",
        version="0.2.0",
        page=None,
        notes=[],
        settings=SimpleNamespace(close_wait_seconds=30, answer_wait_seconds=60, install_wait_seconds=60),
        spawn=lambda _a: None,
        pid=1,
    )
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
