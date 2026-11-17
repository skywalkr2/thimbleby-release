"""One real update of the built app on this system (S-0625): the installed app updates itself to the built installer.

It installs the built installer into a throwaway place with an empty home, as the fresh-install check does, and serves
a release feed from this computer (a loopback address; nothing leaves it) that lists the same installer as a much newer
version. The app is told where its feed is by the setting `updates.feed_address` (an environment variable here), so it
runs the code a person's click runs and nothing else is special:
  1. the app looks at the feed and Today offers the update (the row's install is POST /api/update/<version>/install);
  2. the check puts a marker in the workspace's database, then makes the same request the row's button makes;
  3. the app copies the work, downloads the installer from the feed, checks its SHA-256, hands over and ends; the script
     outside the app swaps the programs (the Mac) or runs the setup silently (Windows), opens the new version, and
     waits for it to say it runs;
  4. the check waits for that, then confirms the new version answers and shows its page, the old copy is gone, the
     marker is still in the workspace, and a copy of the work was made first.
Each step's time is printed, taken from the app's own log, so a slow disk shows where the time went.

Usage: python update_check.py <setup .exe or disk image .dmg> <folder for the pictures> [port] [feed port]"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fresh_install_check import install_windows, keep_log, mount_mac, put_mac, start_app, wait_exit
from session_check import capture, page_drawn, pause, running_pids, wait_drawn

from engine.desktop import places
from engine.launcher import InstanceLock, ask_state, ask_to_show, wait_ready
from engine.legacy_names import private_dir

#: The version the feed claims for the installer: far above any real one, so the running app sees it as newer.
FEED_VERSION = "999.0.0"
OFFER_SECONDS = 300
UPDATE_SECONDS = 900
LOCAL = "http://127.0.0.1"


def serve_feed(installer: Path, system: str, port: int) -> tuple[ThreadingHTTPServer, str]:
    """A release feed and the installer's download, on this computer only. Returns the server and the feed's address."""
    suffix = ".dmg" if system == "Darwin" else ".exe"
    name = f"Thimbleby-{FEED_VERSION}-{'macos-arm64' if system == 'Darwin' else 'windows-x64-setup'}{suffix}"
    with installer.open("rb") as payload:
        digest = hashlib.file_digest(payload, "sha256").hexdigest()
    size = installer.stat().st_size

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/releases":
                body = json.dumps(
                    [
                        {
                            "tag_name": f"v{FEED_VERSION}",
                            "prerelease": False,
                            "draft": False,
                            "published_at": "2026-01-01T00:00:00Z",
                            "html_url": f"https://releases.example.com/tag/v{FEED_VERSION}",
                            "body": "- Installed by the release build's update check",
                            "assets": [
                                {
                                    "name": name,
                                    "browser_download_url": f"{LOCAL}:{self.server.server_address[1]}/download/{name}",
                                    "digest": f"sha256:{digest}",
                                }
                            ],
                        }
                    ]
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == f"/download/{name}":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with installer.open("rb") as payload:
                    shutil.copyfileobj(payload, self.wfile, 1024 * 1024)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, name="release-feed", daemon=True).start()
    return server, f"{LOCAL}:{server.server_address[1]}/releases"


def call(method: str, url: str, token: str, port: int) -> object:
    """A request to the app as its own page makes it: the install token, and the page's own origin."""
    request = urllib.request.Request(
        url,
        method=method,
        data=b"" if method == "POST" else None,
        headers={"Authorization": f"Bearer {token}", "Origin": f"{LOCAL}:{port}"},
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30) as answer:
        text = answer.read().decode()
    return json.loads(text) if text else None


def wait_for_offer(port: int, token: str) -> dict:
    """The update row on Today, with an install (its state is not "manual")."""
    deadline = time.monotonic() + OFFER_SECONDS
    while time.monotonic() < deadline:
        try:
            lines = call("GET", f"{LOCAL}:{port}/api/today/queue", token, port)
        except OSError:
            lines = []
        for line in lines or []:
            if line.get("kind") == "update":
                if line.get("state") == "manual":
                    raise SystemExit(
                        "The app offered the update but cannot install it: it doesn't know it is installed."
                    )
                return line
        pause(3)
    raise SystemExit(f"Today offered no update within {OFFER_SECONDS} seconds.")


def step_times(logs: Path) -> list[str]:
    """The app's own notes of each update step, with the time each began."""
    try:
        text = (logs / "desktop.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [line for line in text.splitlines() if "update step" in line]


def hand_over_log(workspace: Path) -> str:
    try:
        return (private_dir(workspace) / "update-helper" / "hand-over.log").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return "no hand-over log"


def wait_for_result(workspace: Path, logs: Path, started: float) -> dict:
    """The result file the new version writes once it runs; a failed result, or none in time, fails the check."""
    path = private_dir(workspace) / "update-result.json"
    deadline = time.monotonic() + UPDATE_SECONDS
    while time.monotonic() < deadline:
        try:
            result = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            result = None
        if result and result.get("status") == "ok":
            print(f"the new version says it runs, {time.monotonic() - started:.0f} seconds after the click")
            return result
        if result and result.get("status") == "failed":
            print("\n".join(step_times(logs)))
            print(hand_over_log(workspace))
            raise SystemExit(f"The update failed and was rolled back: {result}")
        pause(2)
    print("\n".join(step_times(logs)))
    print(hand_over_log(workspace))
    raise SystemExit(f"No result from the update within {UPDATE_SECONDS} seconds.")


def marker(workspace: Path, write: bool = False) -> str | None:
    """A row the check puts in the workspace's database, standing for the person's work; read it back after."""
    from engine.legacy_names import db_file

    conn = sqlite3.connect(db_file(workspace), timeout=60)
    try:
        if write:
            conn.execute("CREATE TABLE IF NOT EXISTS update_check_marker(v TEXT)")
            conn.execute("INSERT INTO update_check_marker VALUES('kept')")
            conn.commit()
            return "kept"
        row = conn.execute("SELECT v FROM update_check_marker").fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def main(installer: str, pictures_folder: str, port: int = 8794, feed_port: int = 8795) -> None:
    system = platform.system()
    pictures = Path(pictures_folder)
    pictures.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="thimbleby-update-")).resolve()
    home = scratch / "home"
    home.mkdir()
    place = scratch / "installed"
    place.mkdir()
    server, feed = serve_feed(Path(installer), system, feed_port)
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "THIMBLEBY__SERVER__PORT": str(port),
        "THIMBLEBY__UPDATES__FEED_ADDRESS": feed,
    }
    workspace, logs = places({**os.environ, **env}, home, system)
    mounted: Path | None = None
    try:
        if system == "Darwin":
            mounted = mount_mac(Path(installer), scratch)
            app = put_mac(mounted, place)
        else:
            app = install_windows(Path(installer), place / "Thimbleby")
        print(f"installed at {app}")
        start_app(system, app, env)
        if not wait_ready(f"{LOCAL}:{port}/api/health", timeout=180, interval=0.5, request_timeout=2):
            raise SystemExit("The installed app did not answer.")
        lock = InstanceLock(private_dir(workspace))
        token_file = private_dir(workspace) / "token"
        for _ in range(30):
            if lock.control_port() is not None and token_file.is_file():
                break
            pause(1)
        token = token_file.read_text(encoding="utf-8").strip()
        old_pids = running_pids(system)
        offered = wait_for_offer(port, token)
        print(f"Today offers {offered.get('subject')}")
        marker(workspace, write=True)
        started = time.monotonic()
        call("POST", f"{LOCAL}:{port}/api/update/{offered['subject']}/install", token, port)
        wait_for_result(workspace, logs, started)
        print("\n".join(step_times(logs)))
        # The new version answers, shows its page, and is a different process from the one that was updated.
        if not wait_ready(f"{LOCAL}:{port}/api/health", timeout=180, interval=0.5, request_timeout=2):
            raise SystemExit("The new version did not answer.")
        for _ in range(30):
            if lock.control_port() is not None:
                break
            pause(1)
        new_token = token_file.read_text(encoding="utf-8").strip()
        state = wait_drawn(lambda: ask_state(lock.control_port(), new_token))
        capture(system, pictures / "after-update.png")
        if not page_drawn(state):
            raise SystemExit(f"The new version's window had not drawn the app: {state}")
        now_pids = running_pids(system)
        if not now_pids or set(now_pids) & set(old_pids):
            raise SystemExit(f"The running program did not change: before {old_pids}, now {now_pids}")
        left = [p for p in place.iterdir() if re.search(r"\.old$|\.new$", p.name)]
        if left:
            raise SystemExit(f"The update left its working copies behind: {left}")
        if marker(workspace) != "kept":
            raise SystemExit("The workspace lost its work in the update.")
        if not any((private_dir(workspace) / "update-backup").glob("*.db*")):
            raise SystemExit("No copy of the work was made before the update.")
        rows = call("GET", f"{LOCAL}:{port}/api/today/queue", new_token, port)
        if not any(line.get("kind") == "updated" for line in rows or []):
            raise SystemExit("Today did not say the app was updated.")
        print("Today says the app was updated; the work is kept; the old copy is gone")
        if not ask_to_show(lock.control_port(), new_token, what="quit"):
            raise SystemExit("The updated app did not take the quit by the menu's path.")
        wait_exit(system, "Quit")
        print("update: passed")
    finally:
        keep_log(logs, pictures / "app-log-update")
        server.shutdown()
        if mounted is not None:
            subprocess.run(["hdiutil", "detach", str(mounted.parent), "-force", "-quiet"], check=False)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4, 5):
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], *(int(a) for a in sys.argv[3:]))
