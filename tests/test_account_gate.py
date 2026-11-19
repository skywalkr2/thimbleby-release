"""One gate per sign-in, account and host (S-0664, the core part): every request for an account's service passes one
shared allowance, a wait the service asks for holds all of them and sends nothing, and the refusing answer's status,
reason and wait are kept on the run record. Time is injected, never waited for; no network."""

from __future__ import annotations

import threading
import time

import httpx
import pytest

from engine import gate as gates
from engine.connectors import ConnectorError
from engine.gate import Gates, GateSettings
from engine.net import WebClient
from tests.test_watch import NOW, make

HOST = "service.example.com"
OTHER_HOST = "other.example.com"
SIGN_IN = "demo/sign-in"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []
        self._lock = threading.Lock()

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.slept.append(seconds)


@pytest.fixture(autouse=True)
def fresh_gates():
    gates.reset()
    yield
    gates.reset()


def settings(**over) -> GateSettings:
    return GateSettings(**{**dict(wait_seconds=100.0, recover_seconds=300.0), **over})


def client(clock, account="a@example.com", rate=1.0, answer=None, sent=None, **over):
    def respond(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append((account, request.url.host))
        return answer(request) if answer else httpx.Response(200, content=b"ok")

    return WebClient(
        [HOST, OTHER_HOST],
        transport=httpx.MockTransport(respond),
        gates=Gates(SIGN_IN, account, settings(**over), rate, clock, clock.sleep),
    )


def test_two_threads_on_one_account_share_one_pace():
    clock = Clock()
    first, second = client(clock, rate=2.0), client(clock, rate=2.0)

    def run(web):
        for _ in range(5):
            web.get(f"https://{HOST}/a")

    threads = [threading.Thread(target=run, args=(w,)) for w in (first, second)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    waits = sorted([0.0] * (10 - len(clock.slept)) + clock.slept)
    assert waits == pytest.approx([i * 0.5 for i in range(10)]), "ten requests take ten turns, half a second apart"


def test_a_request_whose_turn_is_past_the_bound_stops_as_slowed_down_with_the_time_left():
    clock = Clock()
    web = client(clock, rate=1.0, wait_seconds=1.5)
    sent: list = []
    web2 = client(clock, rate=1.0, wait_seconds=1.5, sent=sent)
    for _ in range(2):
        web2.get(f"https://{HOST}/a")
    with pytest.raises(ConnectorError) as stopped:
        for _ in range(3):
            web.get(f"https://{HOST}/a")
    assert stopped.value.kind == "throttled" and stopped.value.retry_after >= 1 and stopped.value.reason == "gate"


def test_a_throttle_closes_the_gate_for_every_client_and_nothing_is_sent_while_it_is_closed():
    clock, sent = Clock(), []
    refuse = lambda request: httpx.Response(429, headers={"Retry-After": "30"})  # noqa: E731
    one = client(clock, answer=refuse, sent=sent)
    two = client(clock, sent=sent)
    with pytest.raises(ConnectorError) as first:
        one.get(f"https://{HOST}/a")
    assert first.value.kind == "throttled" and first.value.retry_after == 30 and len(sent) == 1
    clock.now += 10
    with pytest.raises(ConnectorError) as held:
        two.get(f"https://{HOST}/b")
    assert held.value.kind == "throttled" and held.value.retry_after == pytest.approx(20) and len(sent) == 1
    clock.now += 21
    assert two.get(f"https://{HOST}/b").status == 200 and len(sent) == 2


def test_a_refusal_with_another_status_that_the_connector_calls_throttled_closes_the_gate_too():
    clock, sent = Clock(), []
    web = client(clock, answer=lambda r: httpx.Response(403, content=b'{"reason":"rateLimitExceeded"}'), sent=sent)
    with pytest.raises(ConnectorError) as refused:
        web.get(f"https://{HOST}/a")
    assert refused.value.kind == "no_access" and refused.value.status == 403
    web.note_throttle(ConnectorError("throttled", "slow down", retry_after=45, status=403, reason="rate_limit"))
    with pytest.raises(ConnectorError) as held:
        web.get(f"https://{HOST}/a")
    assert held.value.kind == "throttled" and held.value.retry_after == pytest.approx(45) and len(sent) == 1


def test_another_account_and_another_host_are_not_held():
    clock, sent = Clock(), []
    refuse = lambda request: (  # noqa: E731
        httpx.Response(429, headers={"Retry-After": "30"}) if request.url.host == HOST else httpx.Response(200)
    )
    mine = client(clock, "a@example.com", answer=refuse, sent=sent)
    with pytest.raises(ConnectorError):
        mine.get(f"https://{HOST}/a")
    elsewhere = client(clock, "b@example.com", sent=sent)
    assert elsewhere.get(f"https://{HOST}/a").status == 200
    assert mine.get(f"https://{OTHER_HOST}/a").status == 200
    with pytest.raises(ConnectorError):
        mine.get(f"https://{HOST}/a")
    assert sent == [("a@example.com", HOST), ("b@example.com", HOST), ("a@example.com", OTHER_HOST)]


def test_each_throttle_halves_the_pace_to_the_floor_and_quiet_minutes_raise_it_back():
    clock = Clock()
    gate = gates.gate_for(SIGN_IN, "a@example.com", HOST, settings(floor_per_second=0.4), 2.0, clock, clock.sleep)
    for expected in (1.0, 0.5, 0.4, 0.4):
        gate.close(1)
        assert gate.rate == pytest.approx(expected)
        clock.now += 2
    clock.now += 300
    gate.acquire()
    assert gate.rate == pytest.approx(0.6)
    clock.now += 3000
    gate.acquire()
    assert gate.rate == 2.0, "never above the pace the add-on declared"


def test_the_same_answer_seen_twice_halves_the_pace_once_and_a_wait_without_a_time_uses_the_setting():
    clock = Clock()
    gate = gates.gate_for(SIGN_IN, "a@example.com", HOST, settings(throttle_seconds=60.0), 2.0, clock, clock.sleep)
    gate.close(None)
    gate.close(60)
    assert gate.rate == 1.0 and gate.closed_for() == pytest.approx(60)


def _fail(store, cfg, err):
    from engine import watch

    watch._failed_read(store, cfg, cfg.watch.sources[0], err, NOW, time.monotonic())
    return watch.last_run(store, cfg.watch.sources[0].id).data


@pytest.mark.parametrize(
    ("err", "outcome", "status", "reason", "wait"),
    [
        (
            ConnectorError("throttled", "x", retry_after=75, status=429, headers={"retry-after": "75"}),
            "throttled",
            429,
            "throttled",
            75,
        ),
        (
            ConnectorError("throttled", "x", retry_after=300, status=403, reason="rate_limit"),
            "throttled",
            403,
            "throttled:rate_limit",
            300,
        ),
    ],
)
def test_a_429_and_a_403_rate_limit_answer_are_kept_with_their_status_reason_and_wait(
    tmp_path, err, outcome, status, reason, wait
):
    ws, cfg, store = make(tmp_path, [{"id": "s", "connector": "fake"}])
    try:
        data = _fail(store, cfg, err)
        assert data["outcome"] == outcome and data["wait_seconds"] == wait
        assert data["refused_status"] == status and data["refused_reason"] == reason
        assert "x" not in data["refused_reason"].split(":")[0], "never the service's own words"
    finally:
        store.close()


def test_a_reason_that_is_not_a_short_code_is_dropped():
    assert ConnectorError("throttled", reason="Too many requests, please slow down").reason is None
    assert ConnectorError("throttled", reason="rate_limit").reason == "rate_limit"


def test_the_sign_in_declares_a_pace_and_the_gate_starts_at_it(tmp_path):
    from engine.plugin_api import PLUGIN_API_VERSION, Registrar, RegistrationRefused

    assert PLUGIN_API_VERSION >= "0.3.104"  # the sign-in pace arrived in 0.3.104
    registrar = Registrar("demo", {})
    registrar.sign_in(
        "demo/in",
        label="Demo",
        authorize_url=f"https://{HOST}/x",
        token_url=f"https://{HOST}/t",
        scopes=["s"],
        requests_per_second=3,
    )
    assert registrar.sign_ins["demo/in"].requests_per_second == 3.0
    for bad in (0, -1, 101, True, "fast"):
        with pytest.raises(RegistrationRefused):
            registrar.sign_in(
                f"demo/bad{bad}",
                label="Demo",
                authorize_url=f"https://{HOST}/x",
                token_url=f"https://{HOST}/t",
                scopes=["s"],
                requests_per_second=bad,
            )


def test_a_request_asleep_for_its_turn_is_not_sent_when_the_service_asks_to_wait_meanwhile():
    """Another request of the account is refused while this one waits for its slot: the gate closes, and this one, whose
    turn comes inside the wait, sends nothing."""
    clock = Clock()
    gate = gates.Gate(settings(), 1.0, clock, clock.sleep)
    gate.acquire()  # takes the first slot; the next one's turn is a second off

    def sleep_while_refused(seconds: float) -> None:
        gate.close(5.0)  # the refusal of another request arrives during the sleep

    gate.sleep = sleep_while_refused
    with pytest.raises(ConnectorError) as err:
        gate.acquire()
    assert err.value.kind == "throttled" and err.value.reason == "gate"
    assert gate.counts.sent == 1 and gate.counts.held == 1
