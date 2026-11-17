"""Run a local ASGI app in the app's own window, behind a menu-bar or tray item, with a per-folder process lock.

The window and the item belong to `engine/appwindow.py`; this module owns the server, the lock and the loop that
reacts to the person's choices. Nothing here touches a window or the item except through the shell it is given."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
import socket
import socketserver
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

#: Where the installed app keeps its notes as well (the logs folder's desktop log); None outside the installed app.
NOTE_FILE: Path | None = None


def note(words: str) -> None:
    """One line on the app's own error stream, which nobody sees but the build machines' start check prints; the
    installed app also adds it to its desktop log, which the build machines' checks print when one fails."""
    line = f"launcher[{os.getpid()}]: {words}"
    print(line, file=sys.stderr, flush=True)
    if NOTE_FILE is not None:
        with contextlib.suppress(OSError):
            NOTE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with NOTE_FILE.open("a", encoding="utf-8") as out:
                out.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")


class InstanceLock:
    """Hold an OS lock on a persistent file; process exit releases ownership.

    The file is deliberately never unlinked, avoiding lock-inode races. Instances
    sharing a data folder reuse the owner's published port and readiness path, which
    the owner writes whole to a separate file beside the lock: the lock file is for
    locking only, since how a locked file can be written and read differs by system.
    """

    def __init__(self, data_folder: str | Path):
        self.path = Path(data_folder) / "launcher.lock"
        self.details = Path(data_folder) / "launcher.json"
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
        self.details.unlink(missing_ok=True)  # a previous owner's, left by a crash
        self.file = handle
        return True

    def publish(self, port: int, readiness_path: str, control_port: int | None = None) -> None:
        if self.file is None:
            raise RuntimeError("Only the lock owner can publish connection details")
        details = {"port": port, "readiness_path": readiness_path}
        if control_port is not None:
            details["control_port"] = control_port
        from engine.state_file import write_whole

        write_whole(self.details, json.dumps(details))  # whole or not at all, for a reader in another process

    def _published(self) -> dict:
        data = json.loads(self.details.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data

    def control_port(self) -> int | None:
        """The port the running instance listens on for "show your window", when it published one."""
        try:
            port = self._published().get("control_port")
            return port if type(port) is int and 1 <= port <= 65535 else None
        except (OSError, ValueError, AttributeError):
            return None

    def connection(self) -> tuple[int, str] | None:
        try:
            data = self._published()
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
        self.details.unlink(missing_ok=True)
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


class _AppLifespan:
    """Drive one ASGI app's lifespan by hand, so an app can be started and stopped while the server keeps listening."""

    def __init__(self, app: Any):
        self.app = app
        self.to_app: asyncio.Queue = asyncio.Queue()
        self.from_app: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None

    async def _answer(self) -> dict:
        assert self.task is not None
        getting = asyncio.ensure_future(self.from_app.get())
        await asyncio.wait({getting, self.task}, return_when=asyncio.FIRST_COMPLETED)
        if getting.done():
            return getting.result()
        getting.cancel()
        error = self.task.exception()
        raise RuntimeError("The app ended before it answered") from error

    async def start(self) -> None:
        async def receive() -> dict:
            return await self.to_app.get()

        async def send(message: dict) -> None:
            await self.from_app.put(message)

        self.task = asyncio.ensure_future(
            self.app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send)
        )
        await self.to_app.put({"type": "lifespan.startup"})
        message = await self._answer()
        if message["type"] != "lifespan.startup.complete":
            raise RuntimeError(message.get("message") or "The app could not start")

    async def stop(self) -> None:
        if self.task is None:
            return
        await self.to_app.put({"type": "lifespan.shutdown"})
        try:
            await self._answer()
        finally:
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


class SwappableApp:
    """A thin ASGI front that hands each request to the current app, so the app can be replaced while the server keeps
    its port and keeps answering.

    A swap holds new requests (they wait, and are answered by the new app, so the screen sees a slower answer and no
    error; after `hold_seconds` a request that is still waiting gets a 503), ends the old app's live streams, waits for
    the requests it is answering, stops it (its worker, its database and its instance lease: the new app takes the lease
    the old one gives back, so the old goes first), then builds, starts and switches to the new one."""

    def __init__(self, factory: Callable[[], Any], *, hold_seconds: float = 30, drain_seconds: float = 10):
        self.factory = factory
        self.hold_seconds = hold_seconds
        self.drain_seconds = drain_seconds
        self.current: Any = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._run: _AppLifespan | None = None
        self._serving: asyncio.Event | None = None
        self._idle: asyncio.Event | None = None
        self._busy = 0
        self.swaps = 0

    def close_streams(self) -> None:
        """End the live streams of the current app (the screen reconnects); safe from any thread."""
        events = getattr(getattr(self.current, "state", None), "events", None)
        if events is not None:
            events.close()

    async def _start(self) -> None:
        app = await asyncio.to_thread(self.factory)
        run = _AppLifespan(app)
        await run.start()
        self.current, self._run = app, run

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        assert self._serving is not None and self._idle is not None
        try:
            await asyncio.wait_for(self._serving.wait(), self.hold_seconds)
        except TimeoutError:
            if scope["type"] == "http":
                body = b'{"detail":"The app is not ready yet."}'
                headers = [
                    (b"content-type", b"application/json"),
                    (b"retry-after", b"2"),
                    (b"content-length", str(len(body)).encode()),
                ]
                await send({"type": "http.response.start", "status": 503, "headers": headers})
                await send({"type": "http.response.body", "body": body})
            else:
                await send({"type": "websocket.close", "code": 1013})
            return
        self._busy += 1
        self._idle.clear()
        try:
            await self.current(scope, receive, send)
        finally:
            self._busy -= 1
            if self._busy == 0:
                self._idle.set()

    async def _lifespan(self, receive: Callable, send: Callable) -> None:
        self.loop = asyncio.get_running_loop()
        self._serving, self._idle = asyncio.Event(), asyncio.Event()
        self._idle.set()
        await receive()
        try:
            await self._start()
        except BaseException as error:
            await send({"type": "lifespan.startup.failed", "message": str(error)})
            raise
        self._serving.set()
        await send({"type": "lifespan.startup.complete"})
        await receive()
        self._serving.clear()
        if self._run is not None:
            await self._run.stop()
        await send({"type": "lifespan.shutdown.complete"})

    async def swap(self) -> None:
        """Replace the app with a new one built by the factory. A failure to build leaves the front holding requests
        (the old app has given back what the new one needs) and is raised to the caller."""
        assert self._serving is not None and self._idle is not None
        self._serving.clear()
        old, run = self.current, self._run
        self.current = self._run = None
        if old is not None and run is not None:
            events = getattr(getattr(old, "state", None), "events", None)
            if events is not None:
                events.close()
            try:
                await asyncio.wait_for(self._idle.wait(), self.drain_seconds)
            except TimeoutError:
                note("a request was still running when the app was replaced")
            await run.stop()
        await self._start()
        self.swaps += 1
        self._serving.set()


class LocalServer:
    """Own one server thread and a prebound socket, detecting bind failures first."""

    def __init__(self, app_factory: Callable[[], Any], port: int, *, shutdown_timeout: float = 10):
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self.app_factory = app_factory
        self.front = SwappableApp(app_factory)
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
            front = self.front
            config = uvicorn.Config(
                lambda: front,
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

    def swap(self, timeout: float = 60) -> None:
        """Replace the app behind the listening server, in place: the port stays and keeps answering."""
        if self.front.loop is None or not self.alive():
            raise RuntimeError("The server is not running")
        asyncio.run_coroutine_threadsafe(self.front.swap(), self.front.loop).result(timeout)

    def stop(self) -> None:
        if self.server is None or self.thread is None:
            return
        self.front.close_streams()  # a screen's open live stream would hold the shutdown for its whole wait
        self.server.should_exit = True
        self.thread.join(self.shutdown_timeout + 2)
        if self.thread.is_alive():
            raise RuntimeError("Server did not stop; refusing to start a duplicate")
        if self.socket is not None:
            self.socket.close()
        self.thread = self.server = self.socket = None


class _LoopbackServer(ThreadingHTTPServer):
    """The standard threading HTTP server, bound without looking up the computer's full name, which the standard one
    does as it starts and a Mac can take half a minute or more to answer."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), int(port)


#: How long quitting waits for the control listener to stop before closing its socket anyway.
CONTROL_STOP_SECONDS = 2.0


class ControlServer:
    """A loopback listener on its own port where a second open of the app asks this one to show its window.

    The request must carry the install token as a bearer header; "/show" brings the window forward and "/quit" ends the
    app by the same path as the menu's Quit (the runners' check uses it). Both are POSTs answered with 204. "GET /state"
    answers with the window's state as JSON (its address and whether the page has drawn); nothing else is served."""

    def __init__(
        self,
        token: Callable[[], str],
        on_show: Callable[[], None],
        on_quit: Callable[[], None] = lambda: None,
        on_state: Callable[[], dict[str, Any]] = lambda: {},
    ):
        self.token = token
        self.on_show = on_show
        self.on_quit = on_quit
        self.on_state = on_state
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> int:
        control = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                offered = self.headers.get("Authorization", "")
                expected = "Bearer " + control.token()
                if self.path != "/state" or not hmac.compare_digest(offered.encode(), expected.encode()):
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = json.dumps(control.on_state()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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

        self.server = _LoopbackServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="show-window-listener", daemon=True)
        self.thread.start()
        return self.server.server_address[1]

    def stop(self, wait_seconds: float = CONTROL_STOP_SECONDS) -> None:
        """Stop listening. Quitting never waits on it for long: past `wait_seconds` the socket is closed anyway."""
        if self.server is None:
            return
        server, self.server = self.server, None
        stopping = threading.Thread(target=server.shutdown, name="control-listener-stop", daemon=True)
        stopping.start()
        stopping.join(wait_seconds)
        if stopping.is_alive():
            note(f"the control listener had not stopped after {wait_seconds} seconds; closing it anyway")
        server.server_close()
        note("the control listener stopped")


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


def ask_state(port: int, token: str, timeout: float = 20) -> dict[str, Any] | None:
    """Ask the running instance, over loopback with the install token, for its window's state."""
    opener = build_opener(ProxyHandler({}))
    request = Request(f"http://127.0.0.1:{port}/state", headers={"Authorization": "Bearer " + token})
    try:
        with opener.open(request, timeout=timeout) as response:
            data = json.loads(response.read())
            return data if response.status == 200 and isinstance(data, dict) else None
    except (OSError, URLError, ValueError):
        return None


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
            said = f"published no address in {lock.details}"
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

    Restart replaces the ASGI app in this process, behind the same listening server (`SwappableApp`); it does not
    replace Python modules, install updates, or restart the interpreter.
    The waiting callback must be thread-safe.
    restarted acknowledges a successful server restart.
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
        note(f"the lock at {lock.path} is held; asking the running copy to show its window")
        show_running(data_folder, token(), timeout=startup_timeout)
        return
    note(f"took the lock at {lock.path}")
    controller = LocalServer(app_factory, port)
    control = ControlServer(token, shell.bring_forward, shell.quit_from_menu, shell.window_state)
    try:
        controller.start()
        lock.publish(port, readiness_path, control.start())
        note(f"published to {lock.details} (there: {lock.details.exists()})")
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
                # In place: the server keeps its port and the page stays open on its session, so no reload.
                controller.swap()
                if not wait_ready(health, timeout=startup_timeout, alive=controller.alive):
                    raise RuntimeError("Restarted server failed readiness") from controller.error
                restarted()
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
        note("stopping the control listener")
        control.stop()
        note("stopping the server")
        # Keep ownership until shutdown finishes; a hung server must not overlap a new one.
        try:
            controller.stop()
            note("the server stopped")
        except Exception:

            def release_after_exit() -> None:
                if controller.thread is not None:
                    controller.thread.join()
                lock.release()

            threading.Thread(target=release_after_exit, name="server-lock-cleanup", daemon=True).start()
            raise
        else:
            lock.release()
