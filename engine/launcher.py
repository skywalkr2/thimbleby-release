"""Run a local ASGI app in the app's own window, behind a menu-bar or tray item, with a per-folder process lock.

The window and the item belong to `engine/appwindow.py`; this module owns the server, the lock and the loop that
reacts to the person's choices. Nothing here touches a window or the item except through the shell it is given."""

from __future__ import annotations

import hmac
import json
import os
import socket
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class InstanceLock:
    """Hold an OS lock on a persistent file; process exit releases ownership.

    The file is deliberately never unlinked, avoiding lock-inode races. Instances
    sharing a data folder reuse the owner's published port and readiness path.
    """

    def __init__(self, data_folder: str | Path):
        self.path = Path(data_folder) / "launcher.lock"
        self.file = None

    def acquire(self) -> bool:
        if self.file is not None:
            raise RuntimeError("Lock acquisition already attempted successfully")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        except OSError as error:
            handle.close()
            if sys.platform == "win32" and error.errno in {13, 11, 36}:
                return False
            raise
        handle.seek(1)
        handle.truncate()
        handle.flush()
        self.file = handle
        return True

    def publish(self, port: int, readiness_path: str, control_port: int | None = None) -> None:
        if self.file is None:
            raise RuntimeError("Only the lock owner can publish connection details")
        self.file.seek(1)
        self.file.truncate()
        details = {"port": port, "readiness_path": readiness_path}
        if control_port is not None:
            details["control_port"] = control_port
        self.file.write(json.dumps(details).encode("utf-8"))
        self.file.flush()

    def control_port(self) -> int | None:
        """The port the running instance listens on for "show your window", when it published one."""
        try:
            port = json.loads(self.path.read_bytes()[1:].lstrip(b"\0 \r\n")).get("control_port")
            return port if type(port) is int and 1 <= port <= 65535 else None
        except (OSError, ValueError, AttributeError):
            return None

    def connection(self) -> tuple[int, str] | None:
        try:
            # The first byte is the one the lock covers; read past it, and past any padding, to the published details.
            data = json.loads(self.path.read_bytes()[1:].lstrip(b"\0 \r\n"))
            port, path = data["port"], data["readiness_path"]
            if (
                type(port) is int
                and 1 <= port <= 65535
                and isinstance(path, str)
                and path.startswith("/")
                and not any(char in path for char in "?#\r\n")
            ):
                return port, path
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def release(self) -> None:
        handle, self.file = self.file, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def readiness_probe(url: str, timeout: float) -> bool:
    """Check an HTTP readiness endpoint without using system proxy settings."""
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password:
        raise ValueError("Readiness must be an HTTP loopback URL")

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None

    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url, timeout=timeout) as response:
            return response.status == 200 and response.url == url
    except (OSError, URLError):
        return False


def wait_ready(
    url: str,
    *,
    timeout: float = 15,
    interval: float = 0.1,
    request_timeout: float = 0.5,
    probe: Callable[[str, float], bool] = readiness_probe,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
    cancelled: Callable[[], bool] = lambda: False,
    alive: Callable[[], bool] = lambda: True,
) -> bool:
    """Wait within a deadline; injectable I/O and clock make tests deterministic."""
    if timeout <= 0 or interval <= 0 or request_timeout <= 0:
        raise ValueError("Readiness timing values must be positive")
    deadline = clock() + timeout
    while not cancelled() and alive():
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        if probe(url, min(request_timeout, remaining)):
            return not cancelled() and alive()
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        pause(min(interval, remaining))
    return False


def restart_enabled(restart_waiting: Callable[[], bool], busy: bool = False) -> bool:
    """Enable Restart only for a pending restart while no operation is running."""
    return not busy and bool(restart_waiting())


class LocalServer:
    """Own one server thread and a prebound socket, detecting bind failures first."""

    def __init__(self, app_factory: Callable[[], Any], port: int, *, shutdown_timeout: float = 10):
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self.app_factory = app_factory
        self.port = port
        self.shutdown_timeout = shutdown_timeout
        self.thread = None
        self.server = None
        self.socket = None
        self.error = None

    def start(self) -> None:
        import uvicorn

        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("Server is already running")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            elif sys.platform != "win32":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.port))
            listener.listen(128)
            config = uvicorn.Config(
                self.app_factory,
                factory=True,
                host="127.0.0.1",
                port=self.port,
                reload=False,
                workers=1,
                lifespan="on",
                timeout_graceful_shutdown=self.shutdown_timeout,
            )
            self.server = uvicorn.Server(config)
            self.socket = listener
            self.error = None

            def serve() -> None:
                try:
                    self.server.run(sockets=[listener])
                except BaseException as error:
                    self.error = error
                finally:
                    listener.close()

            self.thread = threading.Thread(target=serve, name="local-web-server", daemon=False)
            self.thread.start()
        except BaseException:
            listener.close()
            raise

    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def stop(self) -> None:
        if self.server is None or self.thread is None:
            return
        self.server.should_exit = True
        self.thread.join(self.shutdown_timeout + 2)
        if self.thread.is_alive():
            raise RuntimeError("Server did not stop; refusing to start a duplicate")
        if self.socket is not None:
            self.socket.close()
        self.thread = self.server = self.socket = None


class ControlServer:
    """A loopback listener on its own port where a second open of the app asks this one to show its window.

    The request must carry the install token as a bearer header; "/show" brings the window forward and "/quit" ends the
    app by the same path as the menu's Quit (the runners' check uses it). The answer is 204; nothing else is served."""

    def __init__(
        self, token: Callable[[], str], on_show: Callable[[], None], on_quit: Callable[[], None] = lambda: None
    ):
        self.token = token
        self.on_show = on_show
        self.on_quit = on_quit
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> int:
        control = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                offered = self.headers.get("Authorization", "")
                expected = "Bearer " + control.token()
                known = self.path in ("/show", "/quit")
                if not known or not hmac.compare_digest(offered.encode(), expected.encode()):
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                (control.on_show if self.path == "/show" else control.on_quit)()
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="show-window-listener", daemon=True)
        self.thread.start()
        return self.server.server_address[1]

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def ask_to_show(port: int, token: str, timeout: float = 3, what: str = "show") -> bool:
    """Ask the running instance, over loopback with the install token, to show its window (or to quit)."""
    opener = build_opener(ProxyHandler({}))
    request = Request(
        f"http://127.0.0.1:{port}/{what}", data=b"", method="POST", headers={"Authorization": "Bearer " + token}
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status == 204
    except (OSError, URLError):
        return False


def is_running(data_folder: str | Path) -> bool:
    """Whether another instance holds the folder's lock (the lock is only looked at, never kept)."""
    path = Path(data_folder) / "launcher.lock"
    if not path.exists():
        return False
    probe = InstanceLock(data_folder)
    if probe.acquire():
        probe.release()
        return False
    return True


def show_running(data_folder: str | Path, token: str, *, timeout: float = 15) -> None:
    """A second open: wait for the running instance to answer, then ask it to bring its window forward."""
    lock = InstanceLock(data_folder)
    seen: list[tuple[int, str] | None] = []

    def existing_ready(candidate_url: str, wait: float) -> bool:
        connection = lock.connection()
        seen[:] = [connection]
        return connection is not None and readiness_probe(f"http://127.0.0.1:{connection[0]}{connection[1]}", wait)

    # Each check may take two seconds: a busy computer answers its own app slowly; half a second was too short.
    if not wait_ready("http://127.0.0.1/", timeout=timeout, request_timeout=2, probe=existing_ready):
        where = seen[0] if seen else None
        if where is None:
            try:
                held = repr(lock.path.read_bytes()[:160])
            except OSError as err:
                held = f"unreadable ({err.__class__.__name__})"
            said = f"published no address in {lock.path} (it holds {held})"
        else:
            said = f"did not answer at port {where[0]} ({where[1]})"
        raise RuntimeError(f"The existing instance is not ready: it {said}")
    control = lock.control_port()
    if control is None or not ask_to_show(control, token):
        raise RuntimeError("The existing instance did not show its window")


def launch(
    app_factory: Callable[[], Any],
    port: int,
    data_folder: str | Path,
    *,
    shell: Any,
    open_path: str | Callable[[], str],
    readiness_path: str = "/healthz",
    restart_waiting: Callable[[], bool] = lambda: False,
    restarted: Callable[[], None] = lambda: None,
    startup_timeout: float = 15,
    restart_requested: threading.Event | None = None,
    quit_requested: threading.Event | None = None,
    token: Callable[[], str] = lambda: "",
) -> None:
    """Run the app until the person quits: the server, the window's address and the loop that reacts to the menu.

    shell is the app's window and menu-bar item (`engine/appwindow.py`); every call to it is safe from this thread.
    open_path is the path (with the base path and any query) the window opens, on this instance's port; a function is
    asked each time, so a query that changes when the app starts again (a new sign-in link) is always the current one.
    A second launch asks the running instance to show its window and returns. restart_requested, when given, is set
    by the app itself when the person chose Restart in it: the restart then runs as the menu's would. quit_requested,
    when given, is set by the app when it has nothing left to run (the person deleted the workspace): the loop then
    ends as Quit would.

    Restart recreates the ASGI app in this process; it does not replace Python modules, install updates, or restart the
    interpreter. The waiting callback must be thread-safe. restarted acknowledges a successful server restart.
    """
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if not readiness_path.startswith("/") or any(char in readiness_path for char in "?#\r\n"):
        raise ValueError("readiness_path must be a local absolute path without query or fragment")

    def url_now() -> str:
        path = open_path() if callable(open_path) else open_path
        if not path.startswith("/") or any(char in path for char in "\r\n"):
            raise ValueError("open_path must be a local absolute path")
        return f"http://127.0.0.1:{port}{path}"

    if not callable(open_path):
        url_now()
    health = f"http://127.0.0.1:{port}{readiness_path}"
    lock = InstanceLock(data_folder)
    if not lock.acquire():
        show_running(data_folder, token(), timeout=startup_timeout)
        return
    controller = LocalServer(app_factory, port)
    control = ControlServer(token, shell.bring_forward, shell.quit_from_menu)
    try:
        controller.start()
        lock.publish(port, readiness_path, control.start())
        if not wait_ready(health, timeout=startup_timeout, alive=controller.alive):
            raise RuntimeError("The local server failed readiness") from controller.error
        shell.step(2)
        busy = threading.Lock()
        shell.on("open", shell.bring_forward)
        shell.on("help", lambda: shell.bring_forward("#setup"))

        def restart() -> None:
            if not busy.acquire(blocking=False):
                return
            try:
                if not restart_waiting():
                    return
                shell.set_state("restarting")
                controller.stop()
                controller.start()
                if not wait_ready(health, timeout=startup_timeout, alive=controller.alive):
                    raise RuntimeError("Restarted server failed readiness") from controller.error
                restarted()
                shell.show_app(url_now())
                shell.set_state("live")
            except Exception as error:
                failures.append(error)
                shell.set_state("failed")
                shell.quit()
            finally:
                busy.release()

        failures: list[Exception] = []
        shell.on("restart", restart)
        shell.restart_enabled = lambda: restart_enabled(restart_waiting, busy.locked())
        shell.show_app(url_now())
        shell.set_state("live")
        shell.step(3)
        while not shell.quit_event.is_set():
            if quit_requested is not None and quit_requested.is_set():
                shell.quit()
                break
            if restart_requested is not None and restart_requested.is_set():
                restart_requested.clear()
                shell.set_state("restart")
                if restart_waiting():
                    restart()
            shell.quit_event.wait(0.5)
        if failures:
            raise RuntimeError("The server could not restart") from failures[0]
    finally:
        control.stop()
        # Keep ownership until shutdown finishes; a hung server must not overlap a new one.
        try:
            controller.stop()
        except Exception:

            def release_after_exit() -> None:
                if controller.thread is not None:
                    controller.thread.join()
                lock.release()

            threading.Thread(target=release_after_exit, name="server-lock-cleanup", daemon=True).start()
            raise
        else:
            lock.release()
