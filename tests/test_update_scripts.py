"""The hand-over script outside the app (design 11.7: an update is all or nothing). The Mac script is plain `sh`, so it
runs here for real, on folders standing for the two app bundles and stand-ins for the program that opens the app; the
Windows script is PowerShell, so its text is checked for its steps and its quoting (the release build runs it for
real on Windows)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.update_scripts import Hand, mac_script, windows_script


class Mac:
    """Folders for the installed app and the new one, each holding a marker, and a stand-in for `open`."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.app, self.new = tmp_path / "Thimbleby.app", tmp_path / ".Thimbleby.app.new"
        for folder, marker in ((self.app, "old"), (self.new, "new")):
            folder.mkdir()
            (folder / "marker").write_text(marker)
        self.old = tmp_path / ".Thimbleby.app.old"
        self.result, self.log, self.calls = tmp_path / "result.json", tmp_path / "hand-over.log", tmp_path / "calls"

    def opener(self, *, answers: bool) -> Path:
        """What opens the app: records which version it opened, and (when `answers`) the new version says it runs."""
        path = self.root / ("open-answers.sh" if answers else "open-silent.sh")
        reply = f'printf \'{{"status":"ok"}}\' > {self.result}' if answers else ":"
        path.write_text(
            f'#!/bin/sh\necho "$(cat {self.app}/marker)" >> {self.calls}\n'
            f'if [ "$(cat {self.app}/marker)" = new ]; then {reply}; fi\n'
        )
        return path

    def hand(self, *, answers=True, pid=None, close_wait=2, answer_wait=1, new=None) -> Hand:
        if pid is None:
            done = subprocess.Popen(["true"])
            done.wait()
            pid = done.pid
        return Hand(
            pid=pid,
            app=str(self.app),
            old=str(self.old),
            new=str(new or self.new),
            result=str(self.result),
            log=str(self.log),
            launch=["/bin/sh", str(self.opener(answers=answers))],
            from_version="0.1.0",
            close_wait=close_wait,
            answer_wait=answer_wait,
        )

    def run(self, hand: Hand) -> int:
        script = self.root / "hand-over.sh"
        script.write_text(mac_script(hand))
        return subprocess.run(["/bin/sh", str(script)], check=False, timeout=60).returncode

    def result_json(self):
        return json.loads(self.result.read_text()) if self.result.exists() else None

    def opened(self):
        return self.calls.read_text().split() if self.calls.exists() else []


@pytest.fixture
def mac(tmp_path):
    return Mac(tmp_path)


def test_a_new_version_that_answers_replaces_the_old_one_and_the_old_one_is_removed(mac):
    assert mac.run(mac.hand(answers=True)) == 0
    assert (mac.app / "marker").read_text() == "new"
    assert not mac.old.exists() and not mac.new.exists()
    assert mac.opened() == ["new"]
    assert mac.result_json() == {"status": "ok"}  # what the new version wrote; the script adds nothing


def test_a_new_version_that_does_not_answer_is_replaced_by_the_old_one_and_the_work_is_to_be_put_back(mac):
    assert mac.run(mac.hand(answers=False)) == 1
    assert (mac.app / "marker").read_text() == "old"
    assert not mac.old.exists() and not Path(f"{mac.app}.failed").exists()
    assert mac.result_json() == {"status": "failed", "reason": "no_answer", "restore": True, "from": "0.1.0"}
    assert mac.opened() == ["new", "old"]  # the old version is opened again to show the failed-update screen


def test_an_app_that_does_not_close_in_time_leaves_everything_as_it_was(mac):
    running = subprocess.Popen(["sleep", "30"])
    try:
        assert mac.run(mac.hand(pid=running.pid, close_wait=1)) == 1
    finally:
        running.kill()
        running.wait()
    assert (mac.app / "marker").read_text() == "old" and (mac.new / "marker").read_text() == "new"
    assert mac.result_json() == {"status": "failed", "reason": "close", "restore": False, "from": "0.1.0"}
    assert mac.opened() == []  # the old app is still the one running


def test_an_installed_app_that_cannot_be_moved_aside_is_opened_again_untouched(mac):
    shutil.rmtree(mac.app)  # nothing to move: the move is refused
    assert mac.run(mac.hand()) == 1
    assert (mac.new / "marker").read_text() == "new"
    assert mac.result_json() == {"status": "failed", "reason": "install", "restore": False, "from": "0.1.0"}


def test_a_new_app_that_cannot_be_put_in_place_brings_the_old_one_back(mac):
    assert mac.run(mac.hand(new=mac.root / "missing.app")) == 1
    assert (mac.app / "marker").read_text() == "old" and not mac.old.exists()
    assert mac.result_json() == {"status": "failed", "reason": "install", "restore": False, "from": "0.1.0"}
    assert mac.opened() == ["old"]


def test_a_result_left_by_an_earlier_try_never_passes_for_this_ones(mac):
    mac.result.write_text('{"status":"ok"}')  # the new version never wrote this time
    assert mac.run(mac.hand(answers=False)) == 1
    assert mac.result_json()["status"] == "failed"


def test_the_script_names_what_it_did_in_its_log(mac):
    mac.run(mac.hand(answers=False))
    log = mac.log.read_text()
    assert "waiting for the app to close" in log and "did not answer" in log and "putting the old one back" in log


def test_every_value_is_one_quoted_literal_so_a_path_with_a_quote_or_a_space_changes_nothing():
    hand = Hand(
        pid=5,
        app="/Apps/It's here/Thimbleby.app",
        old="/Apps/.old",
        new="/Apps/.new",
        result="/p/r.json",
        log="/p/l",
        launch=["open", "-n", "/Apps/It's here/Thimbleby.app"],
        from_version="0.1.0; rm -rf /",
        close_wait=1,
        answer_wait=1,
    )
    text = mac_script(hand)
    assert "APP='/Apps/It'\"'\"'s here/Thimbleby.app'" in text
    assert "FROM='0.1.0; rm -rf /'" in text


# ---- Windows: PowerShell, checked as text ----------------------------------------------------------------------------


def win(**more) -> Hand:
    base = dict(
        pid=77,
        app=r"C:\Users\Sam O'Neil\AppData\Local\Programs\Thimbleby",
        old=r"C:\Users\Sam O'Neil\AppData\Local\Programs\Thimbleby.old",
        new=r"C:\Users\Sam O'Neil\AppData\Local\Thimbleby\update-download\setup.exe",
        result=r"C:\Users\Sam O'Neil\AppData\Local\Thimbleby\update-result.json",
        log=r"C:\Users\Sam O'Neil\AppData\Local\Thimbleby\hand-over.log",
        launch=[],
        from_version="0.1.0",
        close_wait=180,
        answer_wait=300,
        install_wait=1800,
    )
    return Hand(**{**base, **more})


def test_the_windows_script_waits_moves_aside_installs_silently_opens_and_waits_for_the_answer_in_that_order():
    text = windows_script(win())
    order = [
        "Wait-Process -Id $AppPid",
        "if (-not (Move-Tree $App $Old))",
        "'/VERYSILENT'",
        "Say 'opening the new version'",
        '-match \'"status":"ok"\'',
        "Say 'the new version is running; removing the old one'",
    ]
    positions = [text.index(piece) for piece in order]
    assert positions == sorted(positions)
    assert "'/CURRENTUSER'" in text and "$InstallWait * 1000" in text and "$Process.Kill()" in text


def test_a_windows_setup_that_fails_or_a_new_version_that_is_silent_puts_the_old_folder_back():
    text = windows_script(win())
    failed_install = text.split("Say 'opening the new version'")[0]
    assert "-ne 0" in failed_install and "Put-Back" in failed_install
    assert "Write-Result 'failed' 'install' 'false'" in failed_install
    after = text.split("Say 'opening the new version'")[1]
    assert "Put-Back" in after and "Write-Result 'failed' 'no_answer' 'true'" in after
    assert "Write-Result 'failed' 'close' 'false'" in text  # the app that never closed changes nothing


def test_the_windows_script_writes_its_result_without_a_byte_order_mark_and_quotes_every_value():
    text = windows_script(win())
    assert "UTF8Encoding $false" in text
    assert "$App = 'C:\\Users\\Sam O''Neil\\AppData\\Local\\Programs\\Thimbleby'" in text
    assert "$AppPid = 77" in text and "$CloseWait = 180" in text and "$AnswerWait = 300" in text
    assert "Invoke-Expression" not in text


def test_the_windows_script_is_valid_when_powershell_is_here():
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("no PowerShell on this computer; the release build runs the script on Windows")
    check = (
        "$text = [string]::Join([Environment]::NewLine, $input); $errors = $null; "
        "[System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$null, [ref]$errors) | Out-Null; "
        "if ($errors) { $errors; exit 1 }"
    )
    done = subprocess.run(
        [shell, "-NoProfile", "-Command", check],
        input=windows_script(win()),
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr
