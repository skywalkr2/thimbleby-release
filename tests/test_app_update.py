"""The installed app updates itself (S-0625, design 11.7): each step with its outside work passed in, and a failure at
every step that leaves the old version and the work as they were. Nothing here reaches a network or runs a system
program: the download is an httpx mock, the disk-image tools are a fake runner, and the hand-over is a recording."""

from __future__ import annotations

import errno
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from engine import app_update, updating
from engine.app_update import Install, Steps, UpdateFailed
from engine.update_offer import Offer
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

BODY = b"the installer's bytes" * 5000
SHA = hashlib.sha256(BODY).hexdigest()
PAGE = "https" + "://releases.example.com/tag/v0.2.0"
URL = "https" + "://releases.example.com/v0.2.0/Thimbleby-0.2.0-macos-arm64.dmg"
SETTINGS = SimpleNamespace(close_wait_seconds=30, answer_wait_seconds=60, install_wait_seconds=600)
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


@pytest.fixture
def ws(tmp_path):
    made = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    made.private_dir.mkdir(exist_ok=True)
    return made


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def serving(body=BODY, **headers):
    def handler(request):
        return httpx.Response(200, content=body, headers={"content-length": str(len(body)), **headers})

    return client(handler)


def offer(**more):
    return Offer("0.2.0", "2026-11-16", ["Faster start"], PAGE, URL, SHA, **more)


def mac_install(tmp_path):
    apps = tmp_path / "Applications"
    exe = apps / "Thimbleby.app" / "Contents" / "MacOS" / "Thimbleby"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"old")
    return Install("Darwin", apps / "Thimbleby.app", exe)


def windows_install(tmp_path):
    folder = tmp_path / "Programs" / "Thimbleby"
    folder.mkdir(parents=True)
    (folder / "Thimbleby.exe").write_bytes(b"old")
    return Install("Windows", folder, folder / "Thimbleby.exe")


# ---- which copy can update itself ----------------------------------------------------------------------------------


def test_only_the_frozen_app_in_its_own_place_can_update_itself():
    mac = "/Applications/Thimbleby.app/Contents/MacOS/Thimbleby"
    assert app_update.own_install("Darwin", True, mac) == Install(
        "Darwin", Path("/Applications/Thimbleby.app"), Path(mac)
    )
    windows = r"C:\Users\me\AppData\Local\Programs\Thimbleby\Thimbleby.exe"
    assert app_update.own_install("Windows", True, windows).system == "Windows"
    assert app_update.own_install("Darwin", False, mac) is None  # run from a checkout or the package
    assert app_update.own_install("Linux", True, "/usr/bin/thimbleby") is None
    assert app_update.own_install("Darwin", True, "/opt/python3.13/bin/python") is None  # not inside a bundle


# ---- the download and its checksum -----------------------------------------------------------------------------------


def test_the_installer_is_streamed_to_a_file_with_progress_and_its_checksum_is_checked(tmp_path):
    seen = []
    path = app_update.download(
        URL, SHA, tmp_path / "dl", "Darwin", client=serving(), progress=lambda done, total: seen.append((done, total))
    )
    assert path.read_bytes() == BODY and path.name == "Thimbleby-0.2.0-macos-arm64.dmg"
    assert [d for d, _ in seen] == sorted(d for d, _ in seen) and seen[-1] == (len(BODY), len(BODY))
    assert not list((tmp_path / "dl").glob("*.part"))


def test_a_file_that_is_not_the_published_one_stops_the_update_and_leaves_nothing_behind(tmp_path):
    with pytest.raises(UpdateFailed) as caught:
        app_update.download(URL, SHA, tmp_path / "dl", "Darwin", client=serving(body=BODY + b"x"))
    assert caught.value.kind == "mismatch"
    assert list((tmp_path / "dl").iterdir()) == []


def test_a_download_that_stops_short_is_a_failed_download_not_a_short_installer(tmp_path):
    def short(_request):
        return httpx.Response(200, content=BODY[:100], headers={"content-length": str(len(BODY))})

    with pytest.raises(UpdateFailed) as caught:
        app_update.download(URL, SHA, tmp_path / "dl", "Darwin", client=client(short))
    assert caught.value.kind == "download" and list((tmp_path / "dl").iterdir()) == []


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (httpx.ConnectError("no route"), "offline"),
        (httpx.ReadTimeout("slow"), "download"),
        (httpx.RemoteProtocolError("cut off"), "download"),
    ],
)
def test_a_network_that_fails_is_offline_or_a_stopped_download(tmp_path, error, kind):
    def broken(_request):
        raise error

    with pytest.raises(UpdateFailed) as caught:
        app_update.download(URL, SHA, tmp_path / "dl", "Darwin", client=client(broken))
    assert caught.value.kind == kind and list((tmp_path / "dl").iterdir()) == []


def test_a_refusing_host_and_a_missing_release_are_a_failed_download(tmp_path):
    for status in (403, 404, 500):
        with pytest.raises(UpdateFailed) as caught:
            app_update.download(
                URL, SHA, tmp_path / "dl", "Darwin", client=client(lambda _r, s=status: httpx.Response(s))
            )
        assert caught.value.kind == "download"


def test_a_disk_without_room_is_refused_before_anything_is_written_and_a_write_that_runs_out_is_the_same_reason(
    tmp_path,
):
    with pytest.raises(UpdateFailed) as before:
        app_update.download(URL, SHA, tmp_path / "dl", "Darwin", client=serving(), free=lambda _p: 1000)
    assert before.value.kind == "disk_full" and list((tmp_path / "dl").iterdir()) == []

    class Runs:
        status_code, is_redirect, headers = 200, False, {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def iter_bytes(self, _size):
            yield b"abc"
            raise OSError(errno.ENOSPC, "No space left on device")

    class Fake:
        def stream(self, *_a, **_k):
            return Runs()

    with pytest.raises(UpdateFailed) as during:
        app_update.download(URL, SHA, tmp_path / "dl2", "Darwin", client=Fake())
    assert during.value.kind == "disk_full" and list((tmp_path / "dl2").iterdir()) == []


def test_a_redirect_is_followed_to_another_secure_address_and_never_to_a_plain_one(tmp_path):
    other = "https" + "://objects.example.net/file.dmg"

    def hop(request):
        if request.url.host == "releases.example.com":
            return httpx.Response(302, headers={"location": other})
        return httpx.Response(200, content=BODY, headers={"content-length": str(len(BODY))})

    assert app_update.download(URL, SHA, tmp_path / "dl", "Darwin", client=client(hop)).read_bytes() == BODY

    def downgrade(_request):
        return httpx.Response(302, headers={"location": "http" + "://objects.example.net/file.dmg"})

    with pytest.raises(UpdateFailed) as caught:
        app_update.download(URL, SHA, tmp_path / "dl2", "Darwin", client=client(downgrade))
    assert caught.value.kind == "download"


def test_a_file_from_an_earlier_try_that_still_matches_is_used_and_another_is_cleared(tmp_path):
    folder = tmp_path / "dl"
    folder.mkdir()
    (folder / "Thimbleby-0.2.0-macos-arm64.dmg").write_bytes(BODY)
    (folder / "older.dmg").write_bytes(b"older")

    def never(_request):
        raise AssertionError("the file was already there")

    assert app_update.download(URL, SHA, folder, "Darwin", client=client(never)).read_bytes() == BODY
    folder2 = tmp_path / "dl2"
    folder2.mkdir()
    (folder2 / "older.dmg").write_bytes(b"older")
    app_update.download(URL, SHA, folder2, "Darwin", client=serving())
    assert [p.name for p in folder2.iterdir()] == ["Thimbleby-0.2.0-macos-arm64.dmg"]


def test_an_address_that_is_not_secure_or_a_checksum_that_is_not_one_is_refused_before_any_request(tmp_path):
    def never(_request):
        raise AssertionError("no request")

    for url, sha in [("http" + "://releases.example.com/a.dmg", SHA), (URL, "abc"), ("", SHA)]:
        with pytest.raises(UpdateFailed):
            app_update.download(url, sha, tmp_path / "dl", "Darwin", client=client(never))
    # An address on this computer is allowed to be plain (the check against a local feed uses one).
    local = "http" + "://127.0.0.1:8000/a.dmg"
    assert app_update.download(local, SHA, tmp_path / "dl2", "Darwin", client=serving()).name == "a.dmg"


def test_the_file_name_comes_from_the_address_only_when_it_is_the_systems_installer():
    assert app_update.installer_name(URL, "Darwin") == "Thimbleby-0.2.0-macos-arm64.dmg"
    assert app_update.installer_name(URL.replace(".dmg", ".exe"), "Darwin") == "update.dmg"
    assert app_update.installer_name("https" + "://x.example.com/..%2F..%2Fevil.exe", "Windows") == "evil.exe"


# ---- the copy of the work ----------------------------------------------------------------------------------------


def test_the_copy_holds_the_records_and_names_the_version_it_came_from(ws):
    app_update.copy_work(ws, "0.1.0")
    assert updating.note(ws)["version"] == "0.1.0"
    assert (ws.private_dir / updating.FOLDER / updating.DATABASE).is_file()


def test_a_copy_that_cannot_be_made_stops_the_update_with_its_own_reason(ws):
    def refuse(_ws, _version):
        raise updating.UpdateError("The copy made before updating couldn't be made")

    with pytest.raises(UpdateFailed) as caught:
        app_update.copy_work(ws, "0.1.0", refuse)
    assert caught.value.kind == "copy"

    def full(_ws, _version):
        raise OSError(errno.ENOSPC, "No space left on device")

    with pytest.raises(UpdateFailed) as caught:
        app_update.copy_work(ws, "0.1.0", full)
    assert caught.value.kind == "disk_full"


# ---- the Mac: the disk image, read-only, and the new app beside the old --------------------------------------------


class FakeRun:
    """Stands in for the system's disk-image tools: attach puts an app in the mount folder, ditto copies it."""

    def __init__(self, *, app=True, fail=None):
        self.calls, self.app, self.fail = [], app, fail

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        name = argv[0] if argv[0] != "hdiutil" else f"hdiutil {argv[1]}"
        if name == self.fail:
            return 1, "it said no"
        if name == "hdiutil attach":
            mount = Path(argv[argv.index("-mountpoint") + 1])
            if self.app:
                exe = mount / "Thimbleby.app" / "Contents" / "MacOS" / "Thimbleby"
                exe.parent.mkdir(parents=True)
                exe.write_bytes(b"new")
        if name == "ditto":
            import shutil

            shutil.copytree(argv[1], argv[2])
        return 0, ""


def test_the_image_is_opened_read_only_the_new_app_is_copied_beside_the_old_and_the_image_is_closed(tmp_path):
    install, run = mac_install(tmp_path), FakeRun()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    staged = app_update.stage_mac(tmp_path / "x.dmg", install, run, scratch=scratch)
    assert staged == install.folder.parent / ".Thimbleby.app.new"
    assert (staged / "Contents" / "MacOS" / "Thimbleby").read_bytes() == b"new"
    steps = [c[:2] if c[0] == "hdiutil" else c[:1] for c in run.calls]
    assert steps == [["hdiutil", "attach"], ["ditto"], ["hdiutil", "detach"]]
    assert "-readonly" in run.calls[0] and "-nobrowse" in run.calls[0]
    assert (install.executable).read_bytes() == b"old"  # the installed app is untouched
    assert list(scratch.iterdir()) == []  # the mount folder is gone


@pytest.mark.parametrize(
    ("fail", "app", "kind", "calls"),
    [
        ("hdiutil attach", True, "unreadable", ["hdiutil attach", "hdiutil detach"]),
        (None, False, "unreadable", ["hdiutil attach", "hdiutil detach"]),
        ("ditto", True, "install", ["hdiutil attach", "ditto", "hdiutil detach"]),
    ],
)
def test_a_failure_opening_or_copying_leaves_the_installed_app_and_closes_the_image(tmp_path, fail, app, kind, calls):
    install, run = mac_install(tmp_path), FakeRun(app=app, fail=fail)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(UpdateFailed) as caught:
        app_update.stage_mac(tmp_path / "x.dmg", install, run, scratch=scratch)
    assert caught.value.kind == kind
    assert [" ".join(c[:2]) if c[0] == "hdiutil" else c[0] for c in run.calls] == calls
    assert install.executable.read_bytes() == b"old"
    assert not app_update.new_bundle_path(install).exists()


def test_a_disk_too_full_for_the_new_app_and_a_folder_that_cannot_be_changed_are_stopped_before_copying(
    tmp_path, monkeypatch
):
    install, run = mac_install(tmp_path), FakeRun()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(UpdateFailed) as full:
        app_update.stage_mac(tmp_path / "x.dmg", install, run, scratch=scratch, free=lambda _p: 1)
    assert full.value.kind == "disk_full" and not any(c[0] == "ditto" for c in run.calls)
    monkeypatch.setattr(app_update.os, "access", lambda *_a: False)
    with pytest.raises(UpdateFailed) as locked:
        app_update.stage_mac(tmp_path / "x.dmg", install, FakeRun(), scratch=scratch)
    assert locked.value.kind == "folder"


def test_an_image_that_will_not_detach_is_closed_by_force(tmp_path):
    install = mac_install(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    class Stubborn(FakeRun):
        def __call__(self, argv, timeout):
            if argv[:2] == ["hdiutil", "detach"] and "-force" not in argv:
                self.calls.append(list(argv))
                return 1, "busy"
            return super().__call__(argv, timeout)

    run = Stubborn()
    app_update.stage_mac(tmp_path / "x.dmg", install, run, scratch=scratch)
    assert run.calls[-1][:3] == ["hdiutil", "detach", "-force"]


# ---- Windows: the folder must be one the person can change -----------------------------------------------------------


def test_a_windows_folder_that_cannot_be_changed_stops_the_update_before_the_hand_over(tmp_path, monkeypatch):
    install = windows_install(tmp_path)
    app_update.check_folder(install)
    monkeypatch.setattr(app_update.os, "access", lambda *_a: False)
    with pytest.raises(UpdateFailed) as caught:
        app_update.check_folder(install)
    assert caught.value.kind == "folder"


# ---- the hand-over -------------------------------------------------------------------------------------------------


def test_the_hand_over_writes_its_plan_and_script_and_starts_the_script_detached_on_the_mac(ws, tmp_path):
    install, started = mac_install(tmp_path), []
    script = app_update.hand_over(
        ws,
        install,
        app_update.new_bundle_path(install),
        from_version="0.1.0",
        version="0.2.0",
        page=PAGE,
        notes=["Faster start"],
        settings=SETTINGS,
        environ={"THIMBLEBY__SERVER__PORT": "8793", "HOME": "/x"},
        spawn=started.append,
        pid=4242,
        now=NOW,
    )
    assert started == [["/bin/sh", str(script)]]
    text = script.read_text()
    assert "PID=4242" in text and "CLOSE_WAIT=30" in text and "ANSWER_WAIT=60" in text
    assert "--env THIMBLEBY__SERVER__PORT=8793" in text and "HOME=/x" not in text  # only the app's own settings pass
    plan = app_update.read_plan(ws)
    assert plan["from"] == "0.1.0" and plan["version"] == "0.2.0" and plan["notes"] == ["Faster start"]


def test_the_hand_over_on_windows_runs_powershell_with_the_setup_program(ws, tmp_path):
    install, started = windows_install(tmp_path), []
    setup = tmp_path / "setup.exe"
    script = app_update.hand_over(
        ws, install, setup, from_version="0.1.0", version="0.2.0", page=None, notes=[], settings=SETTINGS,
        spawn=started.append, pid=7, now=NOW,
    )  # fmt: skip
    assert started[0][0] == "powershell.exe" and started[0][-2:] == ["-File", str(script)]
    assert str(setup) in script.read_text() and "Wait-Process" in script.read_text()


def test_a_hand_over_that_cannot_start_leaves_no_plan_and_says_so(ws, tmp_path):
    def cannot(_argv):
        raise OSError(errno.EACCES, "denied")

    with pytest.raises(UpdateFailed) as caught:
        app_update.hand_over(
            ws, mac_install(tmp_path), tmp_path / "n", from_version="0.1.0", version="0.2.0", page=None, notes=[],
            settings=SETTINGS, spawn=cannot, pid=1, now=NOW,
        )  # fmt: skip
    assert caught.value.kind == "install" and app_update.read_plan(ws) is None


def test_a_new_hand_over_clears_the_result_of_the_one_before(ws, tmp_path):
    (ws.private_dir / app_update.RESULT_FILE).write_text('{"status":"failed"}')
    app_update.hand_over(
        ws, mac_install(tmp_path), tmp_path / "n", from_version="0.1.0", version="0.2.0", page=None, notes=[],
        settings=SETTINGS, spawn=lambda _a: None, pid=1, now=NOW,
    )  # fmt: skip
    assert app_update.read_result(ws) is None


# ---- all the steps, and a failure at each of them --------------------------------------------------------------------


class Recorder:
    """The outside work of an update, recorded; `fail` names the step that raises."""

    def __init__(self, tmp_path, fail=None, system="Darwin"):
        self.tmp, self.fail, self.system = tmp_path, fail, system
        self.calls, self.progress = [], []
        self.backups = 0

    def _maybe(self, step):
        self.calls.append(step)
        if self.fail == step:
            raise UpdateFailed(
                {"backup": "copy", "download": "offline", "stage": "unreadable", "hand_over": "install"}[step], step
            )

    def backup(self, _ws, _version):
        self.backups += 1
        # The second copy is the last step before the hand-over; failing it is a failed copy too.
        if self.fail == "backup" or (self.fail == "second_backup" and self.backups == 2):
            self.calls.append("backup")
            raise UpdateFailed("copy", "backup")
        self.calls.append("backup")

    def download(self, url, sha, folder, system, **kwargs):
        self._maybe("download")
        kwargs["progress"](50, 100)
        return self.tmp / "installer"

    def stage(self, installer, install, run, **kwargs):
        self._maybe("stage")
        return app_update.new_bundle_path(install)

    def hand_over(self, ws, install, new, **kwargs):
        self._maybe("hand_over")
        return self.tmp / "script"

    def steps(self):
        return Steps(backup=self.backup, download=self.download, stage=self.stage, hand_over=self.hand_over)

    def say(self, step, fraction, detail):
        self.progress.append((step, fraction, detail))


def run_all(ws, tmp_path, recorder, install=None):
    app_update.run(
        ws,
        offer(),
        SETTINGS,
        install=install or mac_install(tmp_path),
        from_version="0.1.0",
        progress=recorder.say,
        steps=recorder.steps(),
    )


def test_every_step_runs_in_order_and_progress_reports_each_one(ws, tmp_path):
    recorder = Recorder(tmp_path)
    run_all(ws, tmp_path, recorder)
    assert recorder.calls == ["backup", "download", "stage", "backup", "hand_over"]
    assert [p[0] for p in recorder.progress] == ["copy", "download", "download", "check", "install", "open"]
    assert ("download", 0.5, "0/0") in [(s, f, d) for s, f, d in recorder.progress if f == 0.5]


def test_on_windows_the_setup_program_is_the_file_itself_and_nothing_is_staged(ws, tmp_path):
    recorder = Recorder(tmp_path, system="Windows")
    run_all(ws, tmp_path, recorder, install=windows_install(tmp_path))
    assert recorder.calls == ["backup", "download", "backup", "hand_over"]


@pytest.mark.parametrize(
    ("fail", "kind", "reached"),
    [
        ("backup", "copy", ["backup"]),
        ("download", "offline", ["backup", "download"]),
        ("stage", "unreadable", ["backup", "download", "stage"]),
        ("second_backup", "copy", ["backup", "download", "stage", "backup"]),
        ("hand_over", "install", ["backup", "download", "stage", "backup", "hand_over"]),
    ],
)
def test_a_failure_at_any_step_stops_there_and_changes_nothing_after_it(ws, tmp_path, fail, kind, reached):
    recorder = Recorder(tmp_path, fail=fail)
    with pytest.raises(UpdateFailed) as caught:
        run_all(ws, tmp_path, recorder)
    assert caught.value.kind == kind and recorder.calls == reached
    assert app_update.read_plan(ws) is None and app_update.read_result(ws) is None
    assert "open" not in [p[0] for p in recorder.progress]


def test_a_copy_of_the_app_that_is_not_installed_and_a_release_with_no_installer_stop_before_any_step(ws, tmp_path):
    recorder = Recorder(tmp_path)
    with pytest.raises(UpdateFailed) as caught:
        app_update.run(
            ws, offer(), SETTINGS, install=None, from_version="0.1.0", progress=recorder.say, steps=recorder.steps()
        )
    assert caught.value.kind == "not_installed" and recorder.calls == []
    bare = Offer("0.2.0", "", [], None, None, None)
    with pytest.raises(UpdateFailed) as caught:
        app_update.run(
            ws, bare, SETTINGS, install=mac_install(tmp_path), from_version="0.1.0", progress=recorder.say,
            steps=recorder.steps(),
        )  # fmt: skip
    assert caught.value.kind == "download" and recorder.calls == []


def test_the_real_steps_with_a_mock_network_and_a_fake_runner_hand_over_a_mac_update(ws, tmp_path):
    """The whole path with only the network, the system's tools and the process start replaced."""
    install, started = mac_install(tmp_path), []
    app_update.run(
        ws,
        offer(),
        SETTINGS,
        install=install,
        from_version="0.1.0",
        progress=lambda *_a: None,
        steps=Steps(client=serving(), run=FakeRun(), spawn=started.append),
        environ={},
    )
    assert started and started[0][0] == "/bin/sh"
    assert (app_update.new_bundle_path(install) / "Contents" / "MacOS" / "Thimbleby").read_bytes() == b"new"
    assert install.executable.read_bytes() == b"old"  # the script swaps them; the app never does
    assert updating.note(ws)["version"] == "0.1.0"


# ---- what the new version leaves, and what Today says ------------------------------------------------------


def test_the_new_version_writes_the_result_the_script_waits_for_and_clears_what_the_update_left(ws, tmp_path):
    assert app_update.record_started(ws, "0.2.0") is False  # no hand-over was waiting
    (ws.private_dir / app_update.DOWNLOAD_FOLDER).mkdir()
    (ws.private_dir / app_update.DOWNLOAD_FOLDER / "x.dmg").write_bytes(b"x")
    app_update.hand_over(
        ws, mac_install(tmp_path), tmp_path / "n", from_version="0.1.0", version="0.2.0",
        page=PAGE, notes=["Faster start"], settings=SETTINGS,
        spawn=lambda _a: None, pid=1, now=NOW,
    )  # fmt: skip
    assert app_update.record_started(ws, "0.2.0", NOW) is True
    raw = (ws.private_dir / app_update.RESULT_FILE).read_text()
    assert '"status":"ok"' in raw  # the exact form the scripts look for
    assert app_update.read_plan(ws) is None and not (ws.private_dir / app_update.DOWNLOAD_FOLDER).exists()
    done = app_update.updated(ws)
    assert (done["version"], done["from"], done["notes"]) == ("0.2.0", "0.1.0", ["Faster start"])
    app_update.mark_seen(ws)
    assert app_update.updated(ws) is None  # shown once


def test_a_result_the_windows_script_wrote_with_a_byte_order_mark_still_reads(ws):
    (ws.private_dir / app_update.RESULT_FILE).write_bytes(
        b'\xef\xbb\xbf{"status":"failed","reason":"install","restore":false,"from":"0.1.0"}'
    )
    assert app_update.read_result(ws)["reason"] == "install"


def test_a_plan_no_result_ever_followed_is_dropped_only_once_it_is_too_old_for_its_script_to_be_running(ws, tmp_path):
    app_update.hand_over(
        ws, mac_install(tmp_path), tmp_path / "n", from_version="0.1.0", version="0.2.0", page=None, notes=[],
        settings=SETTINGS, spawn=lambda _a: None, pid=1, now=NOW,
    )  # fmt: skip
    assert app_update.drop_stale_plan(ws, NOW + timedelta(minutes=5)) is False
    assert app_update.drop_stale_plan(ws, NOW + timedelta(hours=1)) is True
    assert app_update.read_plan(ws) is None


def test_the_copy_put_back_after_a_failed_update_is_the_one_taken_first(ws):
    conn = sqlite3.connect(ws.db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS marker(v TEXT)")
    conn.execute("INSERT INTO marker VALUES('before')")
    conn.commit()
    conn.close()
    app_update.copy_work(ws, "0.1.0")
    conn = sqlite3.connect(ws.db_path)
    conn.execute("DELETE FROM marker")
    conn.commit()
    conn.close()
    assert updating.restore(ws) is True
    assert sqlite3.connect(ws.db_path).execute("SELECT v FROM marker").fetchone() == ("before",)


def test_a_started_hand_over_keeps_its_own_output_beside_its_script(tmp_path):
    """What the script prints before its log begins (a refusal to run) is kept: a silent hand-over says why."""
    from engine.app_update import spawn_detached, spawn_output

    script = tmp_path / "hand-over.sh"
    script.write_text("exit 0\n", encoding="utf-8")
    argv = ["/bin/sh", str(script)]
    assert spawn_output(argv) == tmp_path / "hand-over.sh.out"
    spawn_detached(argv)
    assert spawn_output(argv).exists()


def test_a_hand_over_that_ends_at_once_is_a_failed_update_with_its_code_never_a_quiet_quit(tmp_path):
    from engine.app_update import started_alive

    script = tmp_path / "hand-over.sh"
    script.write_text("echo refused; exit 3\n", encoding="utf-8")
    argv = ["/bin/sh", str(script)]
    (tmp_path / "hand-over.sh.out").write_text("refused\n", encoding="utf-8")

    class Ended:
        def wait(self, timeout):
            return 3

    with pytest.raises(OSError, match="code 3"):
        started_alive(Ended(), argv)


def test_a_hand_over_still_running_after_its_wait_is_left_to_do_its_work(tmp_path):
    import subprocess

    from engine.app_update import started_alive

    class Running:
        def wait(self, timeout):
            raise subprocess.TimeoutExpired("sh", timeout)

    started_alive(Running(), ["/bin/sh", str(tmp_path / "hand-over.sh")])


def test_the_windows_hand_over_gets_a_hidden_console_of_its_own_never_none(tmp_path, monkeypatch):
    # PowerShell started with no console (DETACHED_PROCESS) ends at once with code 0 and runs nothing; the hand-over
    # gets a hidden console instead, and is started in place when the job it is in refuses breakaway.
    from engine import app_update

    started = []

    class Started:
        def __init__(self, argv, creationflags=0, **kwargs):
            started.append(creationflags)
            if creationflags & app_update.CREATE_BREAKAWAY_FROM_JOB:
                raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(app_update.sys, "platform", "win32")
    monkeypatch.setattr(app_update.subprocess, "Popen", Started)
    app_update.spawn_detached(["powershell.exe", "-File", str(tmp_path / "hand-over.ps1")])
    detached = 0x00000008
    assert len(started) == 2 and started[0] & app_update.CREATE_BREAKAWAY_FROM_JOB
    assert all(flags & app_update.CREATE_NO_WINDOW and not flags & detached for flags in started)
