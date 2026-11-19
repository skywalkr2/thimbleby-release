"""The hand-over script outside the app (design 11.7: an update is all or nothing). The Mac script is plain `sh`, so it
runs here for real, on folders standing for the two app bundles and stand-ins for the program that opens the app; the
Windows script is PowerShell, so its text is checked for its steps and its quoting (the release build runs it for
real on Windows)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine import app_update
from engine.update_scripts import Hand, mac_script, windows_script

ATTEMPT = "5f1d0c7a9b"
#: A stand-in for the Mac's `ps -axo pid=,comm=`, which prints each process's id and its program's whole path.
PS = """#!/bin/sh
for d in /proc/[0-9]*; do
  exe=$(readlink "$d/exe" 2>/dev/null) || continue
  printf '%s %s\\n' "${d#/proc/}" "$exe"
done
"""
#: A stand-in for `mv` that refuses the call whose number is in MV_FAILS, and is the real one otherwise.
MV = """#!/bin/sh
n=$(($(cat "$MV_COUNT" 2>/dev/null || echo 0) + 1))
echo "$n" > "$MV_COUNT"
[ "$n" = "$MV_FAILS" ] && exit 1
exec /bin/mv "$@"
"""


class Mac:
    """Folders for the installed app and the new one, each holding a marker, and a stand-in for `open`."""

    def __init__(self, tmp_path: Path, folder: str = "Applications"):
        self.root = tmp_path / folder
        self.root.mkdir(parents=True)
        self.app, self.new = self.root / "Thimbleby.app", self.root / ".Thimbleby.app.new"
        for bundle, marker in ((self.app, "old"), (self.new, "new")):
            (bundle / "Contents" / "MacOS").mkdir(parents=True)
            (bundle / "marker").write_text(marker)
            (bundle / "Contents" / "current").symlink_to("MacOS")
        self.old = self.root / ".Thimbleby.app.old"
        self.result, self.log, self.calls = tmp_path / "result.json", tmp_path / "hand-over.log", tmp_path / "calls"
        self.sums = tmp_path / "staged.sha256"
        self.tools = tmp_path / "tools"
        self.tools.mkdir()
        for name, text in (("ps", PS), ("mv", MV)):
            (self.tools / name).write_text(text)
            (self.tools / name).chmod(0o755)
        self.mv_fails = 0

    def opener(self, *, answers: bool | str, runs: bool = False) -> Path:
        """What opens the app: records which version it opened; the new version answers with this attempt's id
        (`answers` true), with another status (`answers` text), or not at all. With `runs`, the app's own program is
        started and left running, its process id kept."""
        path = self.root / "open.sh"
        status = answers if isinstance(answers, str) else "ok"
        reply = f'printf \'{{"status":"{status}","attempt":"{ATTEMPT}"}}\' > "{self.result}"' if answers else ":"
        program = f'"{self.app}/Contents/MacOS/Thimbleby" 300 > /dev/null 2>&1 &\necho $! > "{self.root}/pid"'
        start = program if runs else ":"
        path.write_text(
            f'#!/bin/sh\necho "$(cat "{self.app}/marker")" >> "{self.calls}"\n'
            f'if [ "$(cat "{self.app}/marker")" = new ]; then\n{reply}\n{start}\nfi\n'
        )
        return path

    def hand(self, *, answers=True, runs=False, pid=None, close_wait=2, answer_wait=1, new=None) -> Hand:
        if pid is None:
            done = subprocess.Popen(["true"])
            done.wait()
            pid = done.pid
        # What the app checked when it staged the new version: the script holds the new app to it.
        sums, files, links = app_update.tree_facts(self.new)
        self.sums.write_text(sums)
        return Hand(
            pid=pid,
            app=str(self.app),
            old=str(self.old),
            new=str(new or self.new),
            result=str(self.result),
            log=str(self.log),
            launch=["/bin/sh", str(self.opener(answers=answers, runs=runs))],
            from_version="0.1.0",
            close_wait=close_wait,
            answer_wait=answer_wait,
            attempt=ATTEMPT,
            sums=str(self.sums),
            files=files,
            links=links,
        )

    def run(self, hand: Hand) -> int:
        script = self.root / "hand-over.sh"
        script.write_text(mac_script(hand))
        env = {
            **os.environ,
            "PATH": f"{self.tools}{os.pathsep}{os.environ['PATH']}",
            "MV_COUNT": str(self.root / "mv-count"),
            "MV_FAILS": str(self.mv_fails),
        }
        return subprocess.run(["/bin/sh", str(script)], check=False, timeout=120, env=env).returncode

    def result_json(self):
        return json.loads(self.result.read_text()) if self.result.exists() else None

    def opened(self):
        return self.calls.read_text().split() if self.calls.exists() else []


@pytest.fixture
def mac(tmp_path):
    return Mac(tmp_path)


def failed(reason: str, restore: bool) -> dict:
    return {"status": "failed", "reason": reason, "restore": restore, "from": "0.1.0"}


def test_a_new_version_that_answers_replaces_the_old_one_and_the_old_one_is_removed(mac):
    assert mac.run(mac.hand(answers=True)) == 0
    assert (mac.app / "marker").read_text() == "new"
    assert not mac.old.exists() and not mac.new.exists()
    assert mac.opened() == ["new"]
    # What the new version wrote; the script adds nothing.
    assert mac.result_json() == {"status": "ok", "attempt": ATTEMPT}


def test_a_new_version_that_does_not_answer_is_replaced_by_the_old_one_and_the_work_is_to_be_put_back(mac):
    assert mac.run(mac.hand(answers=False)) == 1
    assert (mac.app / "marker").read_text() == "old"
    assert not mac.old.exists() and not Path(f"{mac.app}.failed").exists()
    assert mac.result_json() == failed("no_answer", True)
    assert mac.opened() == ["new", "old"]  # the old version is opened again to show the failed-update screen


def test_an_app_that_does_not_close_in_time_leaves_everything_as_it_was(mac):
    running = subprocess.Popen(["sleep", "30"])
    try:
        assert mac.run(mac.hand(pid=running.pid, close_wait=1)) == 1
    finally:
        running.kill()
        running.wait()
    assert (mac.app / "marker").read_text() == "old" and (mac.new / "marker").read_text() == "new"
    assert mac.result_json() == failed("close", False)
    assert mac.opened() == []  # the old app is still the one running


def test_an_installed_app_that_cannot_be_moved_aside_is_opened_again_untouched(mac):
    mac.mv_fails = 1  # the first move, of the installed app, is refused
    assert mac.run(mac.hand()) == 1
    assert (mac.app / "marker").read_text() == "old" and (mac.new / "marker").read_text() == "new"
    assert mac.result_json() == failed("install", False)


def test_a_new_app_that_cannot_be_put_in_place_brings_the_old_one_back(mac):
    mac.mv_fails = 2  # the second move, of the new app into place, is refused
    assert mac.run(mac.hand()) == 1
    assert (mac.app / "marker").read_text() == "old" and not mac.old.exists()
    assert mac.result_json() == failed("install", False)
    assert mac.opened() == ["old"]


# ---- what was checked is checked again before it is used (H5-28, H1) -------------------------------------------------


def swap_a_file(mac):
    (mac.new / "marker").write_text("someone else's program")


def add_a_file(mac):
    (mac.new / "Contents" / "MacOS" / "extra").write_text("not in the disk image")


def turn_a_link(mac):
    (mac.new / "Contents" / "current").unlink()
    (mac.new / "Contents" / "current").symlink_to("/tmp")


def put_a_link_in_its_place(mac):
    real = mac.root / "elsewhere.app"
    mac.new.rename(real)
    mac.new.symlink_to(real)


def take_it_away(mac):
    shutil.rmtree(mac.new)


@pytest.mark.parametrize("change", [swap_a_file, add_a_file, turn_a_link, put_a_link_in_its_place, take_it_away])
def test_a_new_app_changed_after_it_was_checked_is_never_put_in_place_and_nothing_changes(mac, change):
    """The review's sequence: the app stages and checks the new version, then something else is put where it waits
    before the script swaps the programs."""
    hand = mac.hand()
    change(mac)
    assert mac.run(hand) == 1
    assert (mac.app / "marker").read_text() == "old" and not mac.old.exists()
    assert mac.result_json() == failed("mismatch", False)  # the work was never touched, so nothing is put back
    assert mac.opened() == ["old"]  # only the installed version was ever opened
    assert "not the one that was checked" in mac.log.read_text()


def test_the_script_is_never_written_without_what_it_checks_the_new_app_against(mac):
    hand = mac.hand()
    for missing in ({"sums": ""}, {"links": ""}, {"attempt": ""}, {"attempt": 'x"; rm -rf /'}):
        with pytest.raises(ValueError):
            mac_script(Hand(**{**hand.__dict__, **missing}))


# ---- only this attempt's answer counts (H5-28, H3) -------------------------------------------------------------------


def test_a_result_left_by_an_earlier_try_never_passes_for_this_ones(mac):
    mac.result.write_text('{"status":"ok"}')  # the new version never wrote this time
    assert mac.run(mac.hand(answers=False)) == 1
    assert mac.result_json()["status"] == "failed"


def test_an_answer_without_this_attempts_id_is_no_answer(mac):
    """An `ok` that another attempt, or another version, wrote while this script waits never ends the update as done."""
    hand = mac.hand(answers=True, answer_wait=2)
    opener = mac.root / "open.sh"
    opener.write_text(opener.read_text().replace(ATTEMPT, "0000another"))
    assert mac.run(hand) == 1
    assert (mac.app / "marker").read_text() == "old"
    assert mac.result_json() == failed("no_answer", True)


def test_a_version_that_is_not_the_one_expected_is_put_back_at_once_with_its_own_reason(mac):
    assert mac.run(mac.hand(answers="wrong", answer_wait=60)) == 1  # at once: nowhere near the minute's wait
    assert (mac.app / "marker").read_text() == "old" and not mac.old.exists()
    assert mac.result_json() == failed("wrong_version", True)
    assert mac.opened() == ["new", "old"]
    assert "not the one expected" in mac.log.read_text()


# ---- the new version is stopped by its own path, read as text (H5-28, H4) --------------------------------------------


def running(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


@pytest.mark.skipif(not Path("/proc/self/exe").exists(), reason="the stand-in for the Mac's ps reads /proc")
def test_a_new_version_in_a_folder_with_brackets_is_stopped_before_the_old_one_is_put_back(tmp_path):
    """The review's sequence: the app is installed under a folder whose name has brackets, the new version opens and
    never answers. Its process is the one stopped, and it has gone before the old version is put back. A program at a
    path the brackets would match as a pattern is left alone."""
    mac = Mac(tmp_path / "one", "Apps [new] (1)")
    program = shutil.which("sleep")
    shutil.copy(program, mac.new / "Contents" / "MacOS" / "Thimbleby")
    other = Mac(tmp_path / "two", "Apps n (1)")  # what `[new]` read as a pattern would match
    shutil.copy(program, other.app / "Contents" / "MacOS" / "Thimbleby")
    bystander = subprocess.Popen([str(other.app / "Contents" / "MacOS" / "Thimbleby"), "300"])
    try:
        assert mac.run(mac.hand(answers=False, runs=True)) == 1
        started = int((mac.root / "pid").read_text())
        assert not running(started)  # the new version was stopped
        assert bystander.poll() is None  # and nothing else was
    finally:
        bystander.kill()
        bystander.wait()
    assert (mac.app / "marker").read_text() == "old" and not mac.old.exists()
    assert mac.result_json() == failed("no_answer", True)
    log = mac.log.read_text()
    assert "still running" not in log and "pgrep" not in mac_script(mac.hand())


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
        attempt=ATTEMPT,
        sums="/p/it's.sha256",
        files=3,
        links="c" * 64,
    )
    text = mac_script(hand)
    assert "APP='/Apps/It'\"'\"'s here/Thimbleby.app'" in text
    assert "FROM='0.1.0; rm -rf /'" in text
    assert "SUMS='/p/it'\"'\"'s.sha256'" in text and f"ATTEMPT={ATTEMPT}" in text
    # Each use of a value in the checks is quoted, so a space or a bracket in a path is never split or matched.
    for use in ('cd "$NEW"', '-c "$SUMS"', '"$APP/Contents/MacOS/"*', '= "$FILES"', '= "$LINKS"'):
        assert use in text


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
        attempt=ATTEMPT,
        sha256="ab" * 32,
    )
    return Hand(**{**base, **more})


def test_the_windows_script_waits_moves_aside_installs_silently_opens_and_waits_for_the_answer_in_that_order():
    text = windows_script(win())
    order = [
        "Wait-Process -Id $AppPid",
        "if (-not (Move-Tree $App $Old))",
        "Get-FileHash -LiteralPath $Setup -Algorithm SHA256",
        "'/VERYSILENT'",
        "Say 'opening the new version'",
        """$Text.Contains('"attempt":"' + $Attempt + '"')""",
        """$Text.Contains('"status":"ok"')""",
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
    assert "Put-Back" in after and "$Reason = 'no_answer'" in after and "Write-Result 'failed' $Reason 'true'" in after
    assert "Write-Result 'failed' 'close' 'false'" in text  # the app that never closed changes nothing


def test_the_windows_setup_is_held_and_its_checksum_taken_again_just_before_it_runs_and_another_file_never_runs():
    """H5-28, H1: the setup program is checked in the app and then run by path from the script; the script takes its
    SHA-256 again, with the file held open against changes, and anything else is refused before it is started."""
    text = windows_script(win())
    assert f"$Sha = '{'ab' * 32}'" in text
    check = text[text.index("Say 'checking the setup'") : text.index("Say 'running the setup'")]
    assert "[System.IO.File]::Open($Setup," in check and "$Share = [System.IO.FileShare]::Read" in check
    assert "Get-FileHash -LiteralPath $Setup -Algorithm SHA256" in check and ".ToLowerInvariant()" in check
    refused = check[check.index("if ($Found -ne $Sha)") :]
    assert "Put-Back" in refused and "Write-Result 'failed' 'mismatch' 'false'" in refused and "exit 1" in refused
    assert "Start-Process -FilePath $Setup" not in check  # the setup starts only after the check
    assert text.index("Start-Process -FilePath $Setup") > text.index("if ($Found -ne $Sha)")
    for bad in ("", "xyz", "ab" * 31, "ab" * 32 + "'; calc; '"):
        with pytest.raises(ValueError):
            windows_script(win(sha256=bad))


def test_the_windows_script_takes_only_this_attempts_answer_and_puts_back_a_version_that_is_not_the_one_expected():
    """H5-28, H3."""
    text = windows_script(win())
    assert f"$Attempt = '{ATTEMPT}'" in text and '-match \'"status":"ok"\'' not in text
    waiting = text[text.index("Say 'opening the new version'") :]
    carried = waiting.index("""if ($Text.Contains('"attempt":"' + $Attempt + '"'))""")
    assert carried < waiting.index("""$Text.Contains('"status":"ok"')""") < waiting.index("exit 0")
    assert "$Reason = 'wrong_version'" in waiting and "Write-Result 'failed' $Reason 'true'" in waiting
    with pytest.raises(ValueError):
        windows_script(win(attempt="it's"))


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
