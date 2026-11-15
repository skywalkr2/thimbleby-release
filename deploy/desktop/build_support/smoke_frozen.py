"""Start a frozen build as a person would, on an empty home folder, and check that it makes its workspace, serves the
app on this computer only, and that a second start only brings the first forward. Stops the app it started, by its
process id. Usage: python smoke_frozen.py <the executable> [port]"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from engine.desktop import places
from engine.launcher import wait_ready


def fetch(url: str) -> tuple[int, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=10) as response:
            return response.status, response.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, ""


def main(executable: str, port: int = 8791) -> None:
    home = Path(tempfile.mkdtemp(prefix="thimbleby-smoke-")).resolve()
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "THIMBLEBY__SERVER__PORT": str(port),
    }
    if sys.platform.startswith("linux"):
        env["BROWSER"] = "true"  # a program that does nothing, so no browser opens, or waits on a terminal
    for name in ("THIMBLEBY_WORKSPACE", "COCKPIT_WORKSPACE"):
        env.pop(name, None)
    workspace, logs = places(env, home, platform.system())
    log = home / "app-output.txt"
    with log.open("wb") as output:
        app = subprocess.Popen([executable], env=env, stdout=output, stderr=output)
    try:
        base = f"http://127.0.0.1:{port}"
        if not wait_ready(
            base + "/api/health", timeout=90, interval=0.5, request_timeout=2, alive=lambda: app.poll() is None
        ):
            problem = (logs / "desktop.log").read_text() if (logs / "desktop.log").exists() else ""
            raise SystemExit(f"The app did not become ready (exit {app.poll()}).\n{problem}\n{log.read_text()[-2000:]}")
        if not (workspace / "config").is_dir():
            raise SystemExit(f"The app did not make its workspace at {workspace}")
        if (status := fetch(base + "/")[0]) != 401:
            raise SystemExit(f"The app answered {status} to a visit with no sign-in link; it should refuse")
        token = (workspace / ".thimbleby" / "token").read_text(encoding="utf-8").strip()
        status, page = fetch(f"{base}/?token={token}")
        if status != 200 or "<html" not in page.lower():
            raise SystemExit(f"The screens were not served to the sign-in link (status {status})")
        second = subprocess.run([executable], env=env, timeout=120, capture_output=True, check=False)
        if second.returncode != 0 or app.poll() is not None:
            said = (second.stdout + second.stderr).decode(errors="replace")[-3000:]
            raise SystemExit(
                f"A second start did not just bring the first forward (exit {second.returncode}, first app "
                f"{'running' if app.poll() is None else f'ended with {app.poll()}'}).\n{said}"
            )
        print(f"ok: workspace {workspace}, served on {base}")
    except BaseException:
        # Whatever failed, show what the app itself said, so a red run names its cause.
        print(f"--- the app's output ({log}) ---")
        print(log.read_text(errors="replace")[-4000:] if log.exists() else "(none)")
        problem = logs / "desktop.log"
        print(f"--- {problem} ---")
        print(problem.read_text(errors="replace")[-4000:] if problem.exists() else "(none)")
        raise
    finally:
        if app.poll() is None:
            app.terminate()
            try:
                app.wait(30)
            except subprocess.TimeoutExpired:
                app.kill()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    main(sys.argv[1], *(int(a) for a in sys.argv[2:]))
