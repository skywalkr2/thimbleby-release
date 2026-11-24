"""Time the built app on a machine limited like a low-end Windows laptop, and fail past a budget.

The first start (unlimited) walks setup to Today, as the fresh-install check does, so the second start opens on Today.
The second start runs with its cores and memory limited by a job object to the figures in `low_end_budget.json`. The
check measures the seconds from opening to the window showing the app (the second visit's browser test then confirms
that this was Today), and the memory the app's processes hold a minute after opening (their working sets, the sum over
the app's own processes; the system's web view is not counted). It prints both and fails when either is past its
budget. Windows only.

Usage: python low_end_check.py <Thimbleby.exe> <folder for the pictures> [port]"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fresh_install_check import _walk, start_app, visit
from session_check import PROCESS_NAME, pause, running_pids, wait_drawn

from engine.desktop import places
from engine.launcher import InstanceLock, ask_state, wait_ready
from engine.legacy_names import private_dir

BUDGET_FILE = Path(__file__).with_name("low_end_budget.json")


def load_budget(path: Path = BUDGET_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def over_budget(seconds: float, memory_mb: float, budget: dict) -> list[str]:
    """The sentences for each figure past its budget; empty when both are within."""
    problems = []
    if seconds > budget["seconds_to_today"]:
        problems.append(
            f"The app took {seconds:.1f} seconds to open to Today; the budget is {budget['seconds_to_today']}."
        )
    if memory_mb > budget["memory_after_a_minute_mb"]:
        problems.append(
            f"The app held {memory_mb:.0f} MB a minute after opening; "
            f"the budget is {budget['memory_after_a_minute_mb']}."
        )
    return problems


def memory_mb(pids: list[int]) -> float:
    """The working sets of the given processes, summed, in megabytes (from `tasklist`)."""
    out = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {PROCESS_NAME}.exe"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    total_kb = 0
    for line in out.splitlines():
        cells = line.strip().strip('"').split('","')
        if len(cells) >= 5 and cells[1].isdigit() and int(cells[1]) in pids:
            total_kb += int("".join(c for c in cells[4] if c.isdigit()) or 0)
    return total_kb / 1024


class Limits:
    """A Windows job object that holds the app's processes to some cores and an amount of memory."""

    def __init__(self, cores: int, megabytes: int):
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic),
                ("IoInfo", Counters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel.OpenProcess.restype = wintypes.HANDLE
        self._job = self._kernel.CreateJobObjectW(None, None)
        if not self._job:
            raise SystemExit("The job object that limits the app could not be made.")
        info = Extended()
        # JOB_OBJECT_LIMIT_AFFINITY (0x10) and JOB_OBJECT_LIMIT_JOB_MEMORY (0x200)
        info.BasicLimitInformation.LimitFlags = 0x10 | 0x200
        info.BasicLimitInformation.Affinity = (1 << cores) - 1
        info.JobMemoryLimit = megabytes * 1024 * 1024
        # JobObjectExtendedLimitInformation is class 9
        if not self._kernel.SetInformationJobObject(self._job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise SystemExit(f"The limits could not be set on the job object (error {ctypes.get_last_error()}).")
        self._assigned: set[int] = set()

    def take(self, pids: list[int]) -> None:
        """Put each not yet held process in the job; a process the app starts afterwards joins it by itself."""
        for pid in pids:
            if pid in self._assigned:
                continue
            # PROCESS_SET_QUOTA (0x0100) and PROCESS_TERMINATE (0x0001), what assigning a process needs
            handle = self._kernel.OpenProcess(0x0101, False, pid)
            if handle and self._kernel.AssignProcessToJobObject(self._job, handle):
                self._assigned.add(pid)


def main(app: str, pictures_folder: str, port: int = 8794) -> None:
    system = platform.system()
    if system != "Windows":
        raise SystemExit("The low-end check runs on Windows only.")
    budget = load_budget()
    pictures = Path(pictures_folder)
    pictures.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="thimbleby-lowend-")).resolve()
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "THIMBLEBY__SERVER__PORT": str(port),
    }
    try:
        # The first start, unlimited: setup is walked to Today, and the app is quit.
        visit(system, Path(app), env, port, "first start", pictures)
        workspace, logs = places({**os.environ, **env}, home, system)
        limits = Limits(budget["cores"], budget["memory_limit_mb"])
        opened = time.monotonic()
        start_app(system, Path(app), env)
        limits.take(running_pids(system))
        if not wait_ready(f"http://127.0.0.1:{port}/api/health", timeout=180, interval=0.5, request_timeout=2):
            problem = (logs / "desktop.log").read_text() if (logs / "desktop.log").exists() else "no log"
            raise SystemExit(f"The limited app did not answer.\n{problem}")
        token_file = private_dir(workspace) / "token"
        lock = InstanceLock(private_dir(workspace))
        for _ in range(60):
            if lock.control_port() is not None and token_file.is_file():
                break
            pause(1)
        token = token_file.read_text(encoding="utf-8").strip()

        def ask() -> dict | None:
            limits.take(running_pids(system))
            return ask_state(lock.control_port(), token)

        state = wait_drawn(ask, seconds=max(budget["seconds_to_today"] * 2, 60))
        seconds = time.monotonic() - opened
        print(
            f"opening to the window showing the app: {seconds:.1f} seconds "
            f"(budget {budget['seconds_to_today']}), {state}"
        )
        pause(max(budget["stay_seconds"] - (time.monotonic() - opened), 0))
        pids = running_pids(system)
        if not pids:
            raise SystemExit("The limited app was not running a minute after it opened.")
        megabytes = memory_mb(pids)
        print(f"memory after a minute: {megabytes:.0f} MB (budget {budget['memory_after_a_minute_mb']})")
        # The second visit confirms the window opened on Today, then quits the app by the menu's own path.
        _walk(system, workspace, logs, env, port, "again", pictures)
        problems = over_budget(seconds, megabytes, budget)
        if problems:
            raise SystemExit("\n".join(problems))
        print("within the low-end budget")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], *(int(a) for a in sys.argv[3:]))
