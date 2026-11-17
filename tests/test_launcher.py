"""Test launcher behavior with local locks and injected clocks, servers, and UI."""

import subprocess
import sys
import threading
from types import SimpleNamespace
from urllib.error import URLError

import pytest

import engine.launcher as launcher
from engine.launcher import InstanceLock, LocalServer, readiness_probe, restart_enabled, wait_ready


class Clock:
    def __init__(self):
        self.value = 0
        self.pauses = []

    def now(self):
        return self.value

    def pause(self, duration):
        self.pauses.append(duration)
        self.value += duration


def test_readiness_immediate_and_retry():
    clock = Clock()
    replies = iter([False, False, True])
    calls = []

    def probe(url, timeout):
        calls.append((url, timeout))
        return next(replies)

    assert wait_ready("http://127.0.0.1:8123/healthz", probe=probe, clock=clock.now, pause=clock.pause)
    assert len(calls) == 3
    assert clock.pauses == [0.1, 0.1]


def test_readiness_timeout_has_bounded_probe_and_pause():
    clock = Clock()
    timeouts = []

    def probe(url, timeout):
        timeouts.append(timeout)
        return False

    assert not wait_ready(
        "http://127.0.0.1:8123/", timeout=0.25, interval=0.2, probe=probe, clock=clock.now, pause=clock.pause
    )
    assert clock.value == 0.25
    assert timeouts == [0.25, pytest.approx(0.05)]


@pytest.mark.parametrize("option", ["timeout", "interval", "request_timeout"])
def test_invalid_readiness_timing(option):
    with pytest.raises(ValueError):
        wait_ready("http://127.0.0.1:8123/", **{option: 0})


@pytest.mark.parametrize("option", ["cancelled", "alive"])
def test_cancelled_or_dead_server_does_not_probe(option):
    def unexpected(*args):
        raise AssertionError("Probe must not run")

    options = {option: lambda: option == "cancelled"}
    assert not wait_ready("http://127.0.0.1:8123/", probe=unexpected, **options)


def test_cancelled_after_successful_probe():
    values = iter([False, True])
    assert not wait_ready("http://127.0.0.1:8123/", probe=lambda *args: True, cancelled=lambda: next(values))


@pytest.mark.parametrize("url", ["https://127.0.0.1/", "http://192.0.2.1/", "http://localhost/", "http://x@127.0.0.1/"])
def test_probe_rejects_nonloopback_urls(url):
    with pytest.raises(ValueError):
        readiness_probe(url, 1)


@pytest.mark.parametrize("status,redirected,expected", [(200, False, True), (204, False, False), (200, True, False)])
def test_probe_response(monkeypatch, status, redirected, expected):
    url = "http://127.0.0.1:8123/healthz"

    class Response:
        def __enter__(self):
            self.status = status
            self.url = "http://192.0.2.1/" if redirected else url
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        launcher, "build_opener", lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response())
    )
    assert readiness_probe(url, 1) is expected


def test_probe_connection_error(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError("Not ready")

    monkeypatch.setattr(launcher, "build_opener", lambda *args: SimpleNamespace(open=fail))
    assert not readiness_probe("http://127.0.0.1:8123/", 1)


def test_os_lock_exclusion_release_and_persistent_file(tmp_path):
    first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
    try:
        assert first.acquire()
        assert not second.acquire()
        with pytest.raises(RuntimeError):
            first.acquire()
        first.release()
        first.release()
        assert first.path.exists()
        assert second.acquire()
    finally:
        first.release()
        second.release()


def test_lock_is_exclusive_between_processes(tmp_path):
    lock = InstanceLock(tmp_path)
    script = (
        "from engine.launcher import InstanceLock; import sys; "
        "lock=InstanceLock(sys.argv[1]); won=lock.acquire(); lock.release(); "
        "print('acquired' if won else 'busy')"
    )
    try:
        assert lock.acquire()
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)], check=True, capture_output=True, text=True
        )
        assert result.stdout.strip() == "busy"
    finally:
        lock.release()
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "acquired"


@pytest.mark.parametrize(
    "pending,busy,expected", [(False, False, False), (True, False, True), (False, True, False), (True, True, False)]
)
def test_menu_restart_state(pending, busy, expected):
    assert restart_enabled(lambda: pending, busy) is expected


def test_busy_does_not_call_waiting_callback():
    def unexpected():
        raise AssertionError("Busy state should short-circuit")

    assert not restart_enabled(unexpected, True)


class Server:
    instances = None

    def __init__(self, factory, port):
        self.calls = []
        self.error = None
        self.thread = None
        self.instances.append(self)

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def swap(self):
        self.calls.append("swap")

    def alive(self):
        return True


class FakeShell:
    """What launch drives: it records the calls, and ends the loop when told to after the app is shown."""

    def __init__(self, during=None):
        self.calls = []
        self.actions = {}
        self.quit_event = threading.Event()
        self.restart_enabled = lambda: False
        self.during = during

    def on(self, key, action):
        self.actions[key] = action

    def step(self, done):
        self.calls.append(("step", done))
        if done == 3:
            if self.during:
                self.during(self)
            self.quit()

    def show_app(self, url):
        self.calls.append(("show_app", url))

    def set_state(self, state):
        self.calls.append(("state", state))

    def bring_forward(self, fragment=""):
        self.calls.append(("forward", fragment))

    def quit(self):
        self.quit_event.set()

    quit_from_menu = quit

    def window_state(self):
        return {"state": "live", "address": "http://127.0.0.1:1/", "drawn": True}


@pytest.fixture
def environment(monkeypatch):
    servers = []
    monkeypatch.setattr(Server, "instances", servers)
    monkeypatch.setattr(launcher, "LocalServer", Server)
    monkeypatch.setattr(launcher, "wait_ready", lambda *args, **kwargs: True)
    return servers


def launch(tmp_path, shell, **more):
    launcher.launch(lambda: object(), 8123, tmp_path, shell=shell, open_path="/", **more)


def test_the_window_opens_on_the_app_only_after_it_answers(environment, tmp_path, monkeypatch):
    order = []
    shell = FakeShell()
    monkeypatch.setattr(launcher, "wait_ready", lambda *args, **kwargs: order.append("ready") or True)
    real = shell.show_app
    shell.show_app = lambda url: (order.append("window"), real(url))
    launch(tmp_path, shell)
    assert order == ["ready", "window"]
    assert environment[0].calls == ["start", "stop"]
    assert ("show_app", "http://127.0.0.1:8123/") in shell.calls and ("state", "live") in shell.calls
    lock = InstanceLock(tmp_path)
    try:
        assert lock.acquire()
    finally:
        lock.release()


def test_a_second_open_asks_the_first_to_show_its_window_and_starts_nothing(environment, tmp_path):
    shown, quit_by = [], []
    control = launcher.ControlServer(lambda: "install-token", lambda: shown.append(True), lambda: quit_by.append(True))
    lock = InstanceLock(tmp_path)
    try:
        assert lock.acquire()
        lock.publish(8123, "/healthz", control.start())
        launch(tmp_path, FakeShell(), token=lambda: "install-token")
        assert shown == [True] and not environment
        with pytest.raises(RuntimeError, match="did not show"):
            launch(tmp_path, FakeShell(), token=lambda: "wrong")
        assert shown == [True] and quit_by == []
        assert launcher.ask_to_show(lock.control_port(), "install-token", what="quit") and quit_by == [True]
        assert not launcher.ask_to_show(lock.control_port(), "wrong", what="quit") and quit_by == [True]
    finally:
        control.stop()
        lock.release()


def test_a_second_open_of_an_instance_that_is_not_ready_fails(environment, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "wait_ready", lambda *args, **kwargs: False)
    lock = InstanceLock(tmp_path)
    try:
        assert lock.acquire()
        with pytest.raises(RuntimeError, match="existing instance"):
            launch(tmp_path, FakeShell())
    finally:
        lock.release()


def test_is_running_only_looks(tmp_path):
    assert not launcher.is_running(tmp_path)
    lock = InstanceLock(tmp_path)
    try:
        assert lock.acquire()
        assert launcher.is_running(tmp_path)
    finally:
        lock.release()
    assert not launcher.is_running(tmp_path) and InstanceLock(tmp_path).acquire()


def test_restart_runs_only_when_the_app_asked_and_shows_the_new_sign_in(environment, tmp_path):
    acknowledged = []

    def restart(shell):
        assert shell.restart_enabled()
        shell.actions["restart"]()

    shell = FakeShell(restart)
    launch(tmp_path, shell, restart_waiting=lambda: True, restarted=lambda: acknowledged.append(True))
    # In place: the server is not stopped and started again, and the window is not pointed at the app a second time.
    assert environment[0].calls == ["start", "swap", "stop"]
    assert acknowledged == [True]
    assert [c for c in shell.calls if c[0] == "show_app"] == [("show_app", "http://127.0.0.1:8123/")]
    assert ("state", "restarting") in shell.calls


def test_restart_when_nothing_is_waiting_does_nothing(environment, tmp_path):
    def restart(shell):
        assert not shell.restart_enabled()
        shell.actions["restart"]()

    launch(tmp_path, FakeShell(restart))
    assert environment[0].calls == ["start", "stop"]


def test_a_restart_that_fails_ends_the_run_with_a_reason(environment, tmp_path, monkeypatch):
    answers = iter([True, False])
    monkeypatch.setattr(launcher, "wait_ready", lambda *args, **kwargs: next(answers))
    shell = FakeShell(lambda s: s.actions["restart"]())
    with pytest.raises(RuntimeError, match="could not restart"):
        launch(tmp_path, shell, restart_waiting=lambda: True)
    assert ("state", "failed") in shell.calls


def test_the_app_deleting_its_workspace_ends_the_loop_as_quit_would(environment, tmp_path):
    done = threading.Event()
    done.set()
    shell = FakeShell()
    shell.step = lambda n: shell.calls.append(("step", n))
    launch(tmp_path, shell, quit_requested=done)
    assert shell.quit_event.is_set() and environment[0].calls == ["start", "stop"]


def test_startup_failure_releases_lock(environment, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "wait_ready", lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError, match="failed readiness"):
        launch(tmp_path, FakeShell())
    assert environment[0].calls == ["start", "stop"]
    lock = InstanceLock(tmp_path)
    try:
        assert lock.acquire()
    finally:
        lock.release()


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_port(port):
    with pytest.raises(ValueError):
        LocalServer(lambda: None, port)


def test_local_server_stop_sets_graceful_exit():
    joined = []
    server = LocalServer(lambda: None, 8123)
    server.server = SimpleNamespace(should_exit=False)
    inner = server.server
    server.thread = SimpleNamespace(join=joined.append, is_alive=lambda: False)
    server.stop()
    assert inner.should_exit
    assert joined == [12]
    assert server.thread is None


def test_local_server_refuses_restart_if_stop_hangs():
    server = LocalServer(lambda: None, 8123)
    server.server = SimpleNamespace(should_exit=False)
    server.thread = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: True)
    with pytest.raises(RuntimeError, match="did not stop"):
        server.stop()


def test_lock_metadata_validation(tmp_path):
    lock = InstanceLock(tmp_path)
    assert lock.connection() is None
    with pytest.raises(RuntimeError):
        lock.publish(8123, "/healthz")
    try:
        assert lock.acquire()
        assert lock.connection() is None
        lock.publish(8123, "/healthz")
        assert lock.connection() == (8123, "/healthz")
    finally:
        lock.release()


def test_local_server_start_uses_one_factory_worker(monkeypatch):
    captured = {}

    class Socket:
        def setsockopt(self, *args):
            pass

        def bind(self, address):
            captured["address"] = address

        def listen(self, backlog):
            pass

        def close(self):
            captured["closed"] = True

    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

        def is_alive(self):
            return False

        def join(self, *args):
            pass

    def config(app_factory, **kwargs):
        captured.update(kwargs)
        captured["factory_callable"] = app_factory
        return object()

    def server(config):
        return SimpleNamespace(run=lambda **kwargs: captured.update(kwargs), should_exit=False)

    monkeypatch.setattr(launcher.socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(launcher.threading, "Thread", Thread)
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(Config=config, Server=server))

    def factory():
        return object()

    controller = LocalServer(factory, 8123)
    controller.start()
    assert captured["address"] == ("127.0.0.1", 8123)
    assert captured["workers"] == 1 and captured["reload"] is False and captured["factory"] is True
    # The server runs the thin front, which builds the app with the factory when the server starts.
    assert captured["factory_callable"]() is controller.front and controller.front.factory is factory
    assert len(captured["sockets"]) == 1
    controller.stop()


def test_the_window_opens_on_the_base_path_and_the_current_sign_in(environment, tmp_path):
    answers = iter(["/a/?token=one", "/a/?token=two"])
    # A swap in place keeps the page open on its session, so only the first start points the window at the app.
    shell = FakeShell(lambda s: s.actions["restart"]())
    launcher.launch(
        lambda: object(),
        8123,
        tmp_path,
        shell=shell,
        open_path=lambda: next(answers),
        restart_waiting=lambda: True,
    )
    assert [c[1] for c in shell.calls if c[0] == "show_app"] == [
        "http://127.0.0.1:8123/a/?token=one",
    ]


def test_launch_refuses_a_path_that_is_not_local(tmp_path):
    with pytest.raises(ValueError):
        launcher.launch(lambda: object(), 8123, tmp_path, shell=FakeShell(), open_path="cockpit/")


def test_the_app_asking_for_a_restart_runs_it_as_the_menu_would(environment, tmp_path):
    asked = threading.Event()
    asked.set()
    shell = FakeShell()
    shell.quit_event.wait = lambda timeout=None: shell.quit() or True  # the loop's first pause ends it
    shell.step = lambda n: shell.calls.append(("step", n))
    launch(tmp_path, shell, restart_waiting=lambda: True, restart_requested=asked)
    assert environment[0].calls == ["start", "swap", "stop"]
    assert not asked.is_set() and ("state", "restart") in shell.calls


def test_the_owner_publishes_beside_the_lock_and_another_open_reads_it_while_the_lock_is_held(tmp_path):
    """The details are not kept in the locked file: a Mac runner's second open read only the lock byte there, and a
    Windows reader can't read the locked byte at all."""
    from engine.launcher import InstanceLock

    owner = InstanceLock(tmp_path)
    assert owner.acquire()
    owner.publish(8765, "/api/health", 50123)
    other = InstanceLock(tmp_path)
    assert not other.acquire()  # still held
    assert other.connection() == (8765, "/api/health") and other.control_port() == 50123
    owner.release()
    assert other.connection() is None and other.control_port() is None


def test_the_listener_for_a_second_open_starts_without_looking_up_the_computers_name(monkeypatch):
    """The standard HTTP server looks up the computer's full name as it starts, which a Mac can take half a minute or
    more to answer; the running app then published its address too late for a second open."""
    import socket

    from engine.launcher import ControlServer

    def slow_lookup(*args):
        raise AssertionError("the listener looked up the computer's name")

    monkeypatch.setattr(socket, "getfqdn", slow_lookup)
    control = ControlServer(lambda: "token", lambda: None)
    try:
        assert control.start() > 0
    finally:
        control.stop()


def test_the_state_answer_needs_the_install_token_and_reports_the_window():
    """The runners' check reads it to fail on a blank window, so it is the window's own answer, and token-guarded."""
    state = {"address": "http://127.0.0.1:1/", "drawn": True}
    control = launcher.ControlServer(lambda: "install-token", lambda: None, on_state=lambda: state)
    port = control.start()
    try:
        assert launcher.ask_state(port, "install-token") == state
        assert launcher.ask_state(port, "wrong") is None
        assert not launcher.ask_to_show(port, "install-token", what="state")  # a POST to it is refused
    finally:
        control.stop()


def test_quitting_never_waits_long_on_the_control_listener():
    """A listener whose stop doesn't return (as one did on a Mac while quitting) is closed anyway after its wait, so
    the quit goes on."""
    import threading

    control = launcher.ControlServer(lambda: "install-token", lambda: None)
    control.start()
    never = threading.Event()
    real = control.server
    real.shutdown = lambda: never.wait(30)  # a stop that hangs
    stopping = threading.Thread(target=control.stop, kwargs={"wait_seconds": 0.2}, daemon=True)
    stopping.start()
    stopping.join(5)
    stopped = not stopping.is_alive()
    never.set()
    assert stopped and control.server is None


def test_ready_is_called_once_the_server_answers_and_a_failing_side_call_never_stops_the_app(environment, tmp_path):
    said = []
    shell = FakeShell()
    launch(tmp_path, shell, ready=lambda: said.append("ready"))
    assert said == ["ready"] and ("step", 3) in shell.calls

    def broken():
        raise RuntimeError("no")

    launch(tmp_path, FakeShell(), ready=broken, poll=broken)  # noted, and the app still starts and ends
    assert launcher._quietly(broken, "poll") is None
