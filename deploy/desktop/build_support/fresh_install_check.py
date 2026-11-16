"""A fresh install of the built app, from the first start to the uninstall, in the runner's desktop session (S-0459).

It installs the built installer into a throwaway place with an empty home, opens the app as a person does, and
drives its page in a browser (`web/e2e-install/fresh-install.spec.ts`, through `web/playwright.install.config.ts`):
  1. first start: the walkthrough opens by itself, and skipping every step reaches Today;
  2. close the app, start it again: Today opens straight away, so the work was kept;
  3. update: the same installer is put over the installed version, the app starts again on the same work;
  4. uninstall: the app is gone, and the work is still where it was (nothing deletes work).
On Windows the installer runs silently into the throwaway folder and is removed by its own uninstaller; on the Mac the
disk image's app is copied to a throwaway folder (put over the old one for the update) and removed by deleting it, which
is how a Mac removes an app.

Usage: python fresh_install_check.py <setup .exe or disk image .dmg> <folder for the pictures> [port]"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from session_check import capture, page_drawn, pause, running_pids, wait_drawn

from engine.desktop import places
from engine.launcher import InstanceLock, ask_state, ask_to_show, wait_ready
from engine.legacy_names import private_dir

WEB = Path(__file__).resolve().parents[3] / "web"


def start_app(system: str, app: Path, env: dict[str, str]) -> None:
    """Open the installed app the way a person does: `open` on the Mac, Start-Process on Windows."""
    if system == "Darwin":
        subprocess.run(
            ["open", "-n", *[a for k, v in env.items() for a in ("--env", f"{k}={v}")], str(app)], check=True
        )
        return
    os.environ.update(env)
    quoted = str(app).replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-Command", f"Start-Process -FilePath '{quoted}'"], check=True)


def wait_exit(system: str, what: str) -> None:
    for _ in range(60):
        if not running_pids(system):
            return
        pause(1)
    raise SystemExit(f"The app was still running after {what}.")


def visit(system: str, app: Path, env: dict[str, str], port: int, which: str, pictures: Path) -> None:
    """Start the app, run one visit of the browser test against it, and quit it through the menu's own path."""
    workspace, logs = places({**os.environ, **env}, Path(env["HOME"]), system)
    start_app(system, app, env)
    try:
        _walk(system, workspace, logs, env, port, which, pictures)
    finally:
        keep_log(logs, pictures / f"app-log-{which.replace(' ', '-')}")


def keep_log(logs: Path, into: Path) -> None:
    """Copy the app's log folder beside the pictures after every visit, passed or failed, so a slow or failing install
    shows what the app said (the browser test keeps its own list of slow or failed requests in the same place)."""
    try:
        if logs.is_dir():
            shutil.copytree(logs, into, dirs_exist_ok=True)
    except OSError as err:
        # A log that cannot be copied never hides why the visit failed.
        print(f"The app's log could not be kept: {err}")


def _walk(system: str, workspace: Path, logs: Path, env: dict[str, str], port: int, which: str, pictures: Path) -> None:
    """The visit itself: wait for the app, find its sign-in link, run the browser test, quit by the menu path."""
    if not wait_ready(f"http://127.0.0.1:{port}/api/health", timeout=120, interval=0.5, request_timeout=2):
        problem = (logs / "desktop.log").read_text() if (logs / "desktop.log").exists() else "no log"
        raise SystemExit(f"The app did not answer on the {which} visit.\n{problem}")
    token_file = private_dir(workspace) / "token"
    lock = InstanceLock(private_dir(workspace))
    for _ in range(30):
        if lock.control_port() is not None and token_file.is_file():
            break
        pause(1)
    if lock.control_port() is None or not token_file.is_file():
        raise SystemExit("The app published no control address.")
    token = token_file.read_text(encoding="utf-8").strip()
    state = wait_drawn(lambda: ask_state(lock.control_port(), token))
    capture(system, pictures / f"window-{which}.png")
    if not page_drawn(state):
        raise SystemExit(f"The window had not drawn the app on the {which} visit: {state}")
    npx = shutil.which("npx") or "npx"
    result = subprocess.run(
        [npx, "playwright", "test", "-c", "playwright.install.config.ts"],
        cwd=WEB,
        env={
            **os.environ,
            "FRESH_INSTALL_URL": f"http://127.0.0.1:{port}/",
            "FRESH_INSTALL_TOKEN": token,
            "FRESH_INSTALL_VISIT": "first" if which == "first start" else "again",
            "FRESH_INSTALL_PICTURES": str(pictures / f"browser-{which.replace(' ', '-')}"),
        },
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"The browser test failed on the {which} visit.")
    if not ask_to_show(lock.control_port(), token, what="quit"):
        raise SystemExit("The app did not take the quit by the menu's path.")
    wait_exit(system, "Quit")
    print(f"{which}: passed")


def install_windows(setup: Path, folder: Path) -> Path:
    subprocess.run(
        [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", f"/DIR={folder}", "/TASKS="],
        check=True,
    )
    exe = folder / "Thimbleby.exe"
    if not exe.is_file():
        raise SystemExit("The setup finished but the app is not in its folder.")
    return exe


def uninstall_windows(folder: Path) -> None:
    subprocess.run([str(folder / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True)
    for _ in range(60):
        if not (folder / "Thimbleby.exe").exists():
            return
        pause(1)
    raise SystemExit("The uninstaller finished but the app is still there.")


def mount_mac(image: Path, into: Path) -> Path:
    mount = into / "volume"
    mount.mkdir()
    subprocess.run(["hdiutil", "attach", str(image), "-mountpoint", str(mount), "-nobrowse", "-quiet"], check=True)
    return mount / "Thimbleby.app"


def put_mac(source: Path, folder: Path) -> Path:
    target = folder / "Thimbleby.app"
    shutil.rmtree(target, ignore_errors=True)
    subprocess.run(["ditto", str(source), str(target)], check=True)
    return target


def main(installer: str, pictures_folder: str, port: int = 8793) -> None:
    system = platform.system()
    pictures = Path(pictures_folder)
    pictures.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="thimbleby-fresh-")).resolve()
    home = scratch / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "THIMBLEBY__SERVER__PORT": str(port),
    }
    workspace, _ = places({**os.environ, **env}, home, system)
    place = scratch / "installed"
    place.mkdir()
    mounted: Path | None = None
    try:
        if system == "Darwin":
            mounted = mount_mac(Path(installer), scratch)
            app = put_mac(mounted, place)
        else:
            app = install_windows(Path(installer), place / "Thimbleby")
        visit(system, app, env, port, "first start", pictures)
        if not (workspace / "config").is_dir():
            raise SystemExit("The first start made no workspace.")
        visit(system, app, env, port, "start again", pictures)
        # The update: the same installer over the installed version, with the work in place.
        app = put_mac(mounted, place) if system == "Darwin" else install_windows(Path(installer), place / "Thimbleby")
        visit(system, app, env, port, "after the update", pictures)
        if system == "Darwin":
            shutil.rmtree(app)
            gone = not app.exists()
        else:
            uninstall_windows(place / "Thimbleby")
            gone = not (place / "Thimbleby" / "Thimbleby.exe").exists()
        if not gone:
            raise SystemExit("The app is still there after it was removed.")
        if not (workspace / "config").is_dir() or not (workspace / "data").is_dir():
            raise SystemExit("Removing the app removed the person's work.")
        print("uninstalled: the app is gone and the work is still there")
    finally:
        if mounted is not None:
            subprocess.run(["hdiutil", "detach", str(mounted.parent), "-force", "-quiet"], check=False)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], *(int(a) for a in sys.argv[3:]))
