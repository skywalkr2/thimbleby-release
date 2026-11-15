"""Open the frozen app the way a person does, in the runner's desktop session, and check that it stays up.

It opens the app (`open` on the Mac, `Start-Process` on Windows), waits for the app to answer, checks that it is still
running a minute later, takes a picture of the screen with the window showing (and, on the Mac, with the menu-bar
item's menu open, when the session lets the script click it), then quits it through the menu's own path (the loopback
"quit" the app offers with its install token) and checks that it exits. On the Mac the app runs under Apple's
main-thread checker, set to stop the app on any report; a crash report written during the run fails the check.

Usage: python session_check.py <the app: Thimbleby.app or Thimbleby.exe> <folder for the pictures> [port]"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from engine.desktop import places
from engine.launcher import InstanceLock, ask_to_show, wait_ready
from engine.legacy_names import private_dir

STAY_UP_SECONDS = 60
PROCESS_NAME = "Thimbleby"


def pause(seconds: float) -> None:
    threading.Event().wait(seconds)


def running_pids(system: str) -> list[int]:
    """The ids of the running app's processes (looked up, never signalled)."""
    if system == "Windows":
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {PROCESS_NAME}.exe"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return [int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"') and '","' in line]
    out = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True, text=True, check=False).stdout
    pids = []
    for line in out.splitlines():
        pid, _, command = line.strip().partition(" ")
        if command.strip().endswith(f"/MacOS/{PROCESS_NAME}"):
            pids.append(int(pid))
    return pids


def capture(system: str, target: Path) -> None:
    if system == "Darwin":
        subprocess.run(["screencapture", "-x", str(target)], check=True)
        return
    script = (
        "Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
        "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size); "
        f"$bmp.Save('{target}', [System.Drawing.Imaging.ImageFormat]::Png)"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)


def open_menu_on_mac(pictures: Path) -> bool:
    """Click the menu-bar item through the system's scripting and take a picture with the menu open; false when the
    session does not let the script do it (the window picture is still kept)."""
    click = 'tell application "System Events" to tell process "Thimbleby" to click menu bar item 1 of menu bar 2'
    if subprocess.run(["osascript", "-e", click], capture_output=True, check=False).returncode != 0:
        return False
    pause(1.5)
    capture("Darwin", pictures / "menu-open.png")
    subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 53'], check=False)
    return True


def crash_reports(since: float) -> list[Path]:
    folder = Path.home() / "Library" / "Logs" / "DiagnosticReports"
    return [p for p in folder.glob(f"{PROCESS_NAME}*") if p.stat().st_mtime >= since] if folder.is_dir() else []


def main(app: str, pictures_folder: str, port: int = 8792) -> None:
    system = platform.system()
    pictures = Path(pictures_folder)
    pictures.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="thimbleby-session-")).resolve()
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "THIMBLEBY__SERVER__PORT": str(port),
    }
    workspace, logs = places({**os.environ, **env}, home, system)
    started = time.time()
    if system == "Darwin":
        checker = Path(
            subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, check=True).stdout.strip()
        )
        checker = checker / "usr" / "lib" / "libMainThreadChecker.dylib"
        env.update({"DYLD_INSERT_LIBRARIES": str(checker), "MTC_CRASH_ON_REPORT": "1"})
        print(f"main-thread checker present: {checker.is_file()} ({checker})")
        command = ["open", "-n"] + [a for k, v in env.items() for a in ("--env", f"{k}={v}")] + [app]
        subprocess.run(command, check=True)
    else:
        for key, value in env.items():
            os.environ[key] = value
        quoted = app.replace("'", "''")
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Start-Process -FilePath '{quoted}'"], check=True)
    try:
        if not wait_ready(f"http://127.0.0.1:{port}/api/health", timeout=120, interval=0.5, request_timeout=2):
            problem = (logs / "desktop.log").read_text() if (logs / "desktop.log").exists() else "no log"
            raise SystemExit(f"The app did not answer in its desktop session.\n{problem}")
        print("answering")
        pause(5)
        capture(system, pictures / "window.png")
        if system == "Darwin" and not open_menu_on_mac(pictures):
            print("note: the session did not let the script open the menu; no menu picture")
        remaining = STAY_UP_SECONDS - (time.time() - started)
        deadline = time.time() + max(remaining, 0)
        while time.time() < deadline:
            if not running_pids(system):
                raise SystemExit("The app stopped by itself within its first minute.")
            pause(5)
        if not running_pids(system):
            raise SystemExit("The app is not running a minute after it opened.")
        if system == "Darwin" and (reports := crash_reports(started)):
            raise SystemExit(f"The app left a crash report: {[str(r) for r in reports]}")
        print(f"still running after {STAY_UP_SECONDS} seconds")
        lock = InstanceLock(private_dir(workspace))
        connection_port = lock.control_port()
        token = (private_dir(workspace) / "token").read_text(encoding="utf-8").strip()
        if connection_port is None or not ask_to_show(connection_port, token, what="quit"):
            raise SystemExit("The app did not take the quit by the menu's path.")
        for _ in range(60):
            if not running_pids(system):
                print("quit through the menu's path, and exited")
                return
            pause(1)
        raise SystemExit("The app did not exit after Quit.")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], *(int(a) for a in sys.argv[3:]))
