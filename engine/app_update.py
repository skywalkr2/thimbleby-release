"""The installed app updates itself (design 11.7: an update is all or nothing).

The person's click on "Update and restart" runs `run`, one step after another, each a function with its outside work
(the network, the system's disk-image and process tools, the disk) passed in, so each is tested alone and with a
failure:

1. `copy_work`: a consistent copy of the workspace's database (`engine.updating`), taken first and again just before the
   hand-over, so what changed while the download ran is in it too;
2. `download`: the installer the release feed names for this system, streamed to a file in the private folder, its
   SHA-256 checked against the feed's before anything else happens (a mismatch deletes the file and stops here);
3. the Mac: `stage_mac` opens the disk image read-only and puts the new app beside the installed one; Windows: the
   setup program is the file itself, and `check_folder` makes sure its folder can be changed;
4. `hand_over`: writes the plan, starts the small script outside the app (`engine.update_scripts`) and returns; the
   caller then ends the app. The script swaps the programs, opens the new version, waits for it to write `ok` to the
   result file, and puts the old version back if anything fails.

Any failure before the hand-over is an `UpdateFailed` with one reason; nothing has changed by then. A failure after it
is the script's: it writes the failed result, and the next start of the old version (`engine.update_flow`) puts the
database copy back when the new version had been opened, and shows the failed-update screen.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from engine import update_scripts
from engine.release_check import LOOPBACK
from engine.state_file import write_whole

PLAN_FILE = "update-plan.json"
RESULT_FILE = "update-result.json"
DOWNLOAD_FOLDER = "update-download"
HELPER_FOLDER = "update-helper"
#: The installer's kind for each system.
SUFFIXES = {"Darwin": ".dmg", "Windows": ".exe"}
#: The progress steps in order, by the wording key's last part.
STEPS = ("copy", "download", "check", "install", "open")
#: The largest installer the app will download.
MAX_BYTES = 2 * 1024**3
CHUNK = 256 * 1024
#: The room an update needs on the disk, as a multiple of the installer's size (the file, and the new app beside it).
ROOM_FACTOR = 3
#: A plan with no result this old is left over from a hand-over that never finished.
STALE_PLAN_SECONDS = 1800
#: What a failure can be, each with its words in the wording sheet (`desktop.update.reason.<kind>`).
KINDS = (
    "not_installed",
    "copy",
    "offline",
    "download",
    "disk_full",
    "mismatch",
    "unreadable",
    "folder",
    "install",
    "close",
    "no_answer",
    "other",
)

#: Runs a program with its arguments and a time limit; returns its exit code and what it said.
Run = Callable[[Sequence[str], float], tuple[int, str]]
#: Reports a step as it begins (its name from `STEPS`), how far along it is (0 to 1, or none) and a short detail.
Progress = Callable[[str, float | None, str], None]


class UpdateFailed(Exception):
    """An update step that didn't finish: `kind` says which way, in `KINDS`; `detail` is for "Copy details"."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind if kind in KINDS else "other"
        self.detail = detail


@dataclass(frozen=True)
class Install:
    """Where the running app is installed: the Mac's app bundle or the Windows folder holding the program."""

    system: str
    folder: Path
    executable: Path


def own_install(
    system: str | None = None, frozen: bool | None = None, executable: str | Path | None = None
) -> Install | None:
    """The installed app this process is, or none when it isn't one (run from a checkout, or from the package): only an
    installed app can replace itself."""
    system = system or platform.system()
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not frozen or system not in SUFFIXES:
        return None
    exe = Path(executable if executable is not None else sys.executable)
    if system == "Darwin":
        bundle = exe.parent.parent.parent
        if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents" and bundle.suffix == ".app":
            return Install(system, bundle, exe)
        return None
    if exe.suffix.lower() == ".exe":
        return Install(system, exe.parent, exe)
    return None


def default_run(argv: Sequence[str], timeout: float) -> tuple[int, str]:
    """Run a system program without a shell; a program that can't start or doesn't finish in time is exit code 127."""
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as err:
        return 127, err.__class__.__name__
    return done.returncode, (done.stdout + done.stderr).strip()


# ---- the files an update keeps -------------------------------------------------------------------------------------


def _file(ws: Any, name: str) -> Path:
    return Path(ws.private_dir) / name


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_plan(ws: Any) -> dict[str, Any] | None:
    return _read(_file(ws, PLAN_FILE))


def read_result(ws: Any) -> dict[str, Any] | None:
    """What the last hand-over came to: `status` ok (written by the new version once it runs) or failed (written by the
    script, with `reason`, `restore` and `from`)."""
    return _read(_file(ws, RESULT_FILE))


def clear(ws: Any, *names: str) -> None:
    for name in names or (PLAN_FILE, RESULT_FILE):
        _file(ws, name).unlink(missing_ok=True)


def record_started(ws: Any, version: str, now: datetime | None = None) -> bool:
    """The new version is running: write the result the script waits for, and clear what the update left on disk. False
    when no hand-over was waiting for it."""
    plan = read_plan(ws)
    if plan is None:
        return False
    stamp = (now or datetime.now(UTC)).isoformat()
    body = {
        "status": "ok",
        "version": version,
        "from": plan.get("from"),
        "at": stamp,
        "page": plan.get("page"),
        "notes": plan.get("notes") or [],
    }
    write_whole(_file(ws, RESULT_FILE), json.dumps(body, separators=(",", ":")))
    clear(ws, PLAN_FILE)
    shutil.rmtree(_file(ws, DOWNLOAD_FOLDER), ignore_errors=True)
    return True


def updated(ws: Any) -> dict[str, Any] | None:
    """The finished update Today still says once (its version, page and notes), until the person has seen it."""
    found = read_result(ws)
    if found is None or found.get("status") != "ok" or found.get("seen"):
        return None
    return found


def mark_seen(ws: Any) -> None:
    found = read_result(ws)
    if found is not None and found.get("status") == "ok":
        write_whole(_file(ws, RESULT_FILE), json.dumps({**found, "seen": True}, separators=(",", ":")))


def drop_stale_plan(ws: Any, now: datetime | None = None) -> bool:
    """Remove a plan that no result ever followed and that is too old for its script to be still running."""
    path = _file(ws, PLAN_FILE)
    plan = read_plan(ws)
    if plan is None or read_result(ws) is not None:
        return False
    try:
        made = datetime.fromisoformat(str(plan.get("at")))
    except ValueError:
        made = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    if ((now or datetime.now(UTC)) - made).total_seconds() < STALE_PLAN_SECONDS:
        return False
    path.unlink(missing_ok=True)
    return True


# ---- step 1: the copy of the work ----------------------------------------------------------------------------------


def copy_work(ws: Any, version: str, backup: Callable[[Any, str], Any] | None = None) -> None:
    """Copy the workspace's database aside with the version it came from. Nothing else changes when it can't."""
    from engine import updating

    try:
        (backup or updating.backup)(ws, version)
    except updating.UpdateError as err:
        raise UpdateFailed("copy", str(err)) from None
    except OSError as err:
        kind = "disk_full" if err.errno in (errno.ENOSPC, errno.EDQUOT) else "copy"
        raise UpdateFailed(kind, f"{err.__class__.__name__}: {err}") from None


# ---- step 2: the download ------------------------------------------------------------------------------------------


def _address_ok(url: str) -> bool:
    parts = urlsplit(url)
    if not parts.hostname or any(c.isspace() for c in url) or parts.username or parts.password:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK)


def installer_name(url: str, system: str) -> str:
    """A safe file name for the download: the address's last part when it has the system's installer suffix."""
    last = Path(unquote(urlsplit(url).path)).name
    suffix = SUFFIXES.get(system, "")
    safe = "".join(c for c in last if c.isalnum() or c in "-_.")
    return safe if suffix and safe.lower().endswith(suffix) and not safe.startswith(".") else f"update{suffix}"


def _hash_file(path: Path) -> str:
    with path.open("rb") as payload:
        return hashlib.file_digest(payload, "sha256").hexdigest()


def download(
    url: str,
    sha256: str,
    folder: Path,
    system: str,
    *,
    client: Any = None,
    progress: Callable[[int, int | None], None] | None = None,
    free: Callable[[Path], int] | None = None,
) -> Path:
    """The installer, downloaded into `folder` and checked against its SHA-256. A file left by an earlier try that
    still matches is used as it is. A short or interrupted download, a refused one, a full disk and a mismatch each
    raise `UpdateFailed` with their own kind, and no file that failed the check is left. `client` is an httpx client;
    a redirect is followed only to another https address (or one on this computer)."""
    import httpx

    if not _address_ok(url) or not (len(sha256) == 64 and all(c in "0123456789abcdefABCDEF" for c in sha256)):
        raise UpdateFailed("download", "the release names no usable download")
    wanted = sha256.lower()
    target = folder / installer_name(url, system)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if target.is_file() and _hash_file(target) == wanted:
            return target
        for stale in folder.iterdir():
            if stale.is_file():
                stale.unlink()
    except OSError as err:
        raise UpdateFailed("copy", f"the download folder couldn't be prepared: {err.__class__.__name__}") from None
    part = target.with_name(target.name + ".part")
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=90.0), follow_redirects=False)
    digest = hashlib.sha256()
    size = 0
    try:
        address = url
        for _ in range(6):
            with client.stream("GET", address, headers={"Accept": "application/octet-stream"}) as response:
                if response.is_redirect and response.headers.get("location"):
                    address = str(response.url.join(response.headers["location"]))
                    if not _address_ok(address):
                        raise UpdateFailed("download", "the download was sent somewhere it may not go")
                    continue
                if response.status_code >= 400:
                    raise UpdateFailed("download", f"the release host answered {response.status_code}")
                total = int(response.headers["content-length"]) if response.headers.get("content-length") else None
                if total is not None:
                    if total > MAX_BYTES:
                        raise UpdateFailed("download", "the installer is larger than an app may be")
                    room = (free or (lambda p: shutil.disk_usage(p).free))(folder)
                    if room < total * ROOM_FACTOR:
                        raise UpdateFailed("disk_full", f"{room} bytes free, {total * ROOM_FACTOR} needed")
                with part.open("wb") as out:
                    for chunk in response.iter_bytes(CHUNK):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise UpdateFailed("download", "the installer is larger than an app may be")
                        out.write(chunk)
                        digest.update(chunk)
                        if progress is not None:
                            progress(size, total)
                if total is not None and size != total:
                    raise UpdateFailed("download", f"the download stopped at {size} of {total} bytes")
                break
        else:
            raise UpdateFailed("download", "too many redirects")
    except UpdateFailed:
        part.unlink(missing_ok=True)
        raise
    except httpx.ConnectError as err:
        part.unlink(missing_ok=True)
        raise UpdateFailed("offline", f"couldn't connect: {err}") from None
    except httpx.HTTPError as err:
        part.unlink(missing_ok=True)
        raise UpdateFailed("download", f"{err.__class__.__name__}: {err}") from None
    except OSError as err:
        part.unlink(missing_ok=True)
        kind = "disk_full" if err.errno in (errno.ENOSPC, errno.EDQUOT) else "download"
        raise UpdateFailed(kind, f"{err.__class__.__name__}: {err}") from None
    finally:
        if own:
            client.close()
    if digest.hexdigest() != wanted:
        part.unlink(missing_ok=True)
        raise UpdateFailed("mismatch", "the file's SHA-256 is not the one the release lists")
    try:
        os.replace(part, target)
    except OSError as err:
        part.unlink(missing_ok=True)
        raise UpdateFailed("download", f"the file couldn't be kept: {err.__class__.__name__}") from None
    return target


# ---- step 3: the new program beside the old one --------------------------------------------------------------------


def _tree_size(root: Path) -> int:
    total = 0
    for base, _, names in os.walk(root):
        for name in names:
            try:
                total += (Path(base) / name).lstat().st_size
            except OSError:
                continue
    return total


def new_bundle_path(install: Install) -> Path:
    """Where the new Mac app waits: hidden, beside the installed one, so the swap is a rename on one disk."""
    return install.folder.with_name(f".{install.folder.name}.new")


def old_path(install: Install) -> Path:
    """Where the installed program waits while the new one is in place."""
    if install.system == "Darwin":
        return install.folder.with_name(f".{install.folder.name}.old")
    return install.folder.with_name(f"{install.folder.name}.old")


def check_folder(install: Install) -> None:
    """The folder the program is in must be one the person can change: a rename there is how the swap is made."""
    parent = install.folder.parent
    if not os.access(parent, os.W_OK) or not os.access(install.folder, os.W_OK):
        raise UpdateFailed("folder", f"{parent} can't be changed by this account")


def stage_mac(
    image: Path,
    install: Install,
    run: Run = default_run,
    *,
    scratch: Path,
    free: Callable[[Path], int] | None = None,
    wait: float = 900.0,
) -> Path:
    """Open the disk image read-only, copy the new app beside the installed one, and close the image again whatever
    happens. Returns the new app's path. The copy keeps the app's signature and attributes (the system's `ditto`)."""
    check_folder(install)
    mount = Path(tempfile.mkdtemp(prefix="mount-", dir=scratch))
    staged = new_bundle_path(install)
    try:
        code, said = run(
            [
                "hdiutil",
                "attach",
                "-readonly",
                "-nobrowse",
                "-noverify",
                "-noautoopen",
                "-mountpoint",
                str(mount),
                str(image),
            ],
            wait,
        )
        if code != 0:
            raise UpdateFailed("unreadable", f"the disk image didn't open ({code}): {said[:300]}")
        source = mount / install.folder.name
        if not (source / "Contents" / "MacOS" / install.executable.name).is_file():
            raise UpdateFailed("unreadable", "the disk image holds no app of this name")
        needed = _tree_size(source)
        room = (free or (lambda p: shutil.disk_usage(p).free))(install.folder.parent)
        if room < needed * 1.2:
            raise UpdateFailed("disk_full", f"{room} bytes free, {int(needed * 1.2)} needed")
        shutil.rmtree(staged, ignore_errors=True)
        code, said = run(["ditto", str(source), str(staged)], wait)
        if code != 0:
            shutil.rmtree(staged, ignore_errors=True)
            raise UpdateFailed("install", f"the new app couldn't be copied ({code}): {said[:300]}")
        if not (staged / "Contents" / "MacOS" / install.executable.name).is_file():
            shutil.rmtree(staged, ignore_errors=True)
            raise UpdateFailed("install", "the copied app is incomplete")
        return staged
    finally:
        code, _ = run(["hdiutil", "detach", str(mount)], 60)
        if code != 0:
            run(["hdiutil", "detach", "-force", str(mount)], 60)
        shutil.rmtree(mount, ignore_errors=True)


# ---- step 4: the hand-over -----------------------------------------------------------------------------------------


def launch_command(install: Install, environ: Mapping[str, str]) -> list[str]:
    """The command that opens the installed app: on the Mac `open`, with the settings given to this copy by environment
    variables passed on to the new one."""
    if install.system != "Darwin":
        return [str(install.executable)]
    passed = [
        arg
        for key, value in sorted(environ.items())
        if key.startswith("THIMBLEBY")
        for arg in ("--env", f"{key}={value}")
    ]
    return ["open", "-n", *passed, str(install.folder)]


#: Windows' flag that starts a process outside the job its parent is in, so closing the parent's job can't end it.
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def spawn_output(argv: Sequence[str]) -> Path:
    """Where a started script's own output goes, beside the script (its last argument): what it printed before its log
    began, such as a refusal to run, is kept for the person's details and the build's check."""
    return Path(argv[-1]).with_name(Path(argv[-1]).name + ".out")


def spawn_detached(argv: Sequence[str]) -> None:
    """Start a program that goes on after this one ends, its output kept beside it (`spawn_output`)."""
    with spawn_output(argv).open("wb") as out:
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            for extra in (CREATE_BREAKAWAY_FROM_JOB, 0):  # a job that refuses breakaway is started in place
                try:
                    subprocess.Popen(
                        list(argv),
                        creationflags=flags | extra,
                        close_fds=True,
                        stdin=subprocess.DEVNULL,
                        stdout=out,
                        stderr=subprocess.STDOUT,
                    )
                    return
                except OSError:
                    if not extra:
                        raise
        else:
            subprocess.Popen(
                list(argv),
                start_new_session=True,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
            )


def hand_over(
    ws: Any,
    install: Install,
    new: Path,
    *,
    from_version: str,
    version: str,
    page: str | None,
    notes: Sequence[str],
    settings: Any,
    environ: Mapping[str, str] | None = None,
    spawn: Callable[[Sequence[str]], None] = spawn_detached,
    pid: int | None = None,
    now: datetime | None = None,
) -> Path:
    """Write the plan and the script and start the script. The caller ends the app next. Returns the script's path."""
    folder = _file(ws, HELPER_FOLDER)
    hand = update_scripts.Hand(
        pid=pid if pid is not None else os.getpid(),
        app=str(install.folder),
        old=str(old_path(install)),
        new=str(new),
        result=str(_file(ws, RESULT_FILE)),
        log=str(folder / "hand-over.log"),
        launch=launch_command(install, os.environ if environ is None else environ),
        from_version=from_version,
        close_wait=settings.close_wait_seconds,
        answer_wait=settings.answer_wait_seconds,
        install_wait=settings.install_wait_seconds,
        setup_log=str(folder / "setup.log"),
    )
    mac = install.system == "Darwin"
    script = folder / (update_scripts.SH_NAME if mac else update_scripts.PS_NAME)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        write_whole(script, update_scripts.mac_script(hand) if mac else update_scripts.windows_script(hand))
        clear(ws, RESULT_FILE)
        plan = {
            "version": version,
            "from": from_version,
            "page": page,
            "notes": list(notes),
            "at": (now or datetime.now(UTC)).isoformat(),
        }
        write_whole(_file(ws, PLAN_FILE), json.dumps(plan, separators=(",", ":")))
        if mac:
            spawn(["/bin/sh", str(script)])
        else:
            spawn(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(script),
                ]
            )
    except OSError as err:
        clear(ws, PLAN_FILE)
        raise UpdateFailed("install", f"the hand-over couldn't be started: {err.__class__.__name__}: {err}") from None
    return script


# ---- all of it -----------------------------------------------------------------------------------------------------


@dataclass
class Steps:
    """The outside work of an update, each replaceable."""

    backup: Callable[[Any, str], Any] | None = None
    download: Callable[..., Path] = download
    stage: Callable[..., Path] = stage_mac
    hand_over: Callable[..., Path] = hand_over
    run: Run = default_run
    client: Any = None
    free: Callable[[Path], int] | None = None
    spawn: Callable[[Sequence[str]], None] = spawn_detached


def _megabytes(count: int) -> str:
    return f"{count / (1024 * 1024):.0f}"


def run(
    ws: Any,
    offer: Any,
    settings: Any,
    *,
    install: Install | None,
    from_version: str,
    progress: Progress,
    steps: Steps | None = None,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Every step of an update up to the hand-over, in order. Raises `UpdateFailed` at the first that doesn't finish,
    with nothing changed. Returning means the script is running and the caller ends the app."""
    steps = steps or Steps()
    if install is None:
        raise UpdateFailed("not_installed", "this copy isn't the installed app")
    if not offer.download_url or not offer.sha256:
        raise UpdateFailed("download", "the release lists no installer for this system")
    progress("copy", None, "")
    copy_work(ws, from_version, steps.backup)
    progress("download", 0.0, "")

    def moved(done: int, total: int | None) -> None:
        progress(
            "download",
            None if not total else min(1.0, done / total),
            f"{_megabytes(done)}/{_megabytes(total)}" if total else _megabytes(done),
        )

    installer = steps.download(
        offer.download_url,
        offer.sha256,
        _file(ws, DOWNLOAD_FOLDER),
        install.system,
        client=steps.client,
        progress=moved,
        free=steps.free,
    )
    progress("check", None, "")
    progress("install", None, "")
    if install.system == "Darwin":
        scratch = _file(ws, HELPER_FOLDER)
        scratch.mkdir(parents=True, exist_ok=True)
        new = steps.stage(installer, install, steps.run, scratch=scratch, free=steps.free)
    else:
        check_folder(install)
        new = installer
    copy_work(ws, from_version, steps.backup)  # again, so what changed during the download is in it
    steps.hand_over(
        ws,
        install,
        new,
        from_version=from_version,
        version=offer.version,
        page=offer.page,
        notes=offer.notes,
        settings=settings,
        environ=environ,
        spawn=steps.spawn,
    )
    progress("open", None, "")
