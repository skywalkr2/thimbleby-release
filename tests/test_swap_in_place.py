"""Replacing the app behind the listening server (`SwappableApp`, batch R1): the port stays, new work is held, the old
app stops once, and a swap waits for a request that is running."""

import socket
import threading
import urllib.request
from contextlib import asynccontextmanager

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from engine.launcher import LocalServer, wait_ready


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Fleet:
    """Builds a small app each time the server asks, and records what each one was told."""

    def __init__(self):
        self.log: list[str] = []
        self.release_build = threading.Event()
        self.release_build.set()
        self.in_slow = threading.Event()
        self.let_slow_finish = threading.Event()
        self.built = 0
        self.stopped = threading.Event()

    def __call__(self):
        self.release_build.wait(10)
        self.built += 1
        name = f"app{self.built}"
        log = self.log

        @asynccontextmanager
        async def lifespan(_app):
            log.append(f"{name} start")
            yield
            log.append(f"{name} stop")
            self.stopped.set()

        def who(_request):
            return JSONResponse({"app": name})

        async def slow(_request):
            self.in_slow.set()
            await __import__("asyncio").to_thread(self.let_slow_finish.wait, 10)
            return JSONResponse({"app": name, "slow": True})

        app = Starlette(routes=[Route("/who", who), Route("/slow", slow)], lifespan=lifespan)
        app.state.events = type("E", (), {"close": lambda self: log.append(f"{name} streams closed")})()
        return app


def ask(port: int, path: str = "/who", timeout: float = 10) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as reply:
        return reply.read().decode()


@pytest.fixture
def served():
    fleet = Fleet()
    port = free_port()
    server = LocalServer(fleet, port, shutdown_timeout=3)
    server.start()
    assert wait_ready(f"http://127.0.0.1:{port}/who", timeout=10)
    try:
        yield fleet, server, port
    finally:
        fleet.release_build.set()
        fleet.let_slow_finish.set()
        server.stop()


def test_a_swap_keeps_the_port_holds_new_work_and_stops_the_old_app_once(served):
    fleet, server, port = served
    assert "app1" in ask(port)
    fleet.release_build.clear()
    swapping = threading.Thread(target=server.swap)
    swapping.start()
    answers: list[str] = []
    asker = threading.Thread(target=lambda: answers.append(ask(port)))
    # The request is sent while the new app is still being built: it waits, and the new app answers it.
    assert fleet.stopped.wait(10)
    asker.start()
    asker.join(0.5)
    assert asker.is_alive() and not answers  # held, not refused
    fleet.release_build.set()
    swapping.join(10)
    asker.join(10)
    assert "app2" in answers[0]
    assert fleet.log.count("app1 stop") == 1 and "app2 start" in fleet.log
    assert fleet.log.index("app1 streams closed") < fleet.log.index("app1 stop") < fleet.log.index("app2 start")
    assert "app2" in ask(port)  # the same port, answering


def test_a_swap_waits_for_a_request_that_is_running(served):
    fleet, server, port = served
    result: list[str] = []
    running = threading.Thread(target=lambda: result.append(ask(port, "/slow")))
    running.start()
    assert fleet.in_slow.wait(5)
    swapping = threading.Thread(target=server.swap)
    swapping.start()
    swapping.join(0.5)
    assert swapping.is_alive() and "app1 stop" not in fleet.log
    fleet.let_slow_finish.set()
    running.join(10)
    swapping.join(10)
    assert '"slow":true' in result[0].replace(" ", "")
    assert fleet.log.count("app1 stop") == 1 and fleet.built == 2


def test_a_swap_whose_new_app_fails_to_build_is_raised_and_nothing_is_served_by_the_old(served):
    fleet, server, port = served
    original = server.front.factory

    def broken():
        raise RuntimeError("add-on would not load")

    server.front.factory = broken
    with pytest.raises(RuntimeError, match="would not load"):
        server.swap()
    server.front.factory = original
    assert fleet.log.count("app1 stop") == 1


def test_the_real_app_swaps_in_place_and_the_new_one_takes_the_workspace_lease(tmp_path):
    """The old app gives back its lease and database before the new one is built, so the swap does not refuse itself."""
    from engine import cli
    from engine.handover import open_or_hold
    from engine.workspace import init_workspace

    ws = init_workspace(tmp_path / "ws", git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/", "storage.backups.automatic": False})
    port = cfg.server.port
    instances: list[str] = []

    def build():
        fresh = ws.config(env={}, flags={"server.base_path": "/", "storage.backups.automatic": False})
        app, _ = cli.make_app(
            ws, fresh, ws.new_install_token(), open_or_hold(ws, fresh), on_restart=lambda: None, on_erased=lambda: None
        )
        return app

    server = LocalServer(build, port, shutdown_timeout=3)
    server.start()
    try:
        assert wait_ready(f"http://127.0.0.1:{port}/api/health", timeout=15)

        def instance() -> str:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/runtime-config", headers={"Authorization": "Bearer " + ws.install_token()}
            )
            # The install token opens a session; the runtime config is read with that session.
            opener = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/session", data=b"", method="POST", headers=request.headers
            )
            import json

            session = json.load(urllib.request.urlopen(opener, timeout=10))["session"]
            request = urllib.request.Request(request.full_url, headers={"Authorization": "Bearer " + session})
            return json.load(urllib.request.urlopen(request, timeout=10))["instance"]

        instances.append(instance())
        server.swap()
        instances.append(instance())
        assert instances[0] != instances[1] and server.front.swaps == 1
    finally:
        server.stop()
