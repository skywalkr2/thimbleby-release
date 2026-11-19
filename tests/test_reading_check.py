"""The reading check on an account's menu (design 6.32, S-0668): a short read of the newest headers through the
account's gate, and what the gate counted. The mail service is the stand-in with its quota on; its own request log
is the check on the counts. Time is a manual clock the gate, the stand-in and the sleep all share, never waited for.
Names come from the fixtures."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StandIn

from api.app import create_app
from engine import gate as gates
from engine import mail_headers, net, reading_check
from engine.connectors import MessageDetails, SourceItem
from engine.gate import Gates, GateSettings
from tests.fake_services import SECURE_SERVICES, State, build_app
from tests.test_source_intake import mail
from tests.test_source_intake import make as make_core

TOKEN = "check-token"
HOST = "service.example.com"
SIGN_IN = "demo/sign-in"
ACCOUNT = "person@example.com"


class Clock:
    """One time for the gate, its sleeping and the stand-in's quota."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def fresh_gates():
    gates.reset()
    yield
    gates.reset()
    net.TRANSPORT = None


def rig(tmp_path, monkeypatch, *, rate: int | None, penalty: float = 10):
    """A source whose headers are asked of the stand-in over the web client and one shared gate, as an add-on does: the
    list, then one request for each message, stopping at the first refusal."""
    clock = Clock()
    state = State(tmp_path / "stand-in")
    helpers = StandIn(build_app(state, 0, {}))
    service = StandIn(build_app(state, 0, SECURE_SERVICES, helpers=False))
    state.access.add("tok")
    state.account_of["tok"] = 0
    if rate:
        assert helpers.post("/__e2e/quota", json={"rate": rate, "penalty": penalty}).json() == {"quota": True}
        state.quota.clock = clock

    def forward(request: httpx.Request) -> httpx.Response:
        answered = service.get(request.url.raw_path.decode(), headers={"Authorization": "Bearer tok"})
        return httpx.Response(answered.status_code, headers=dict(answered.headers), content=answered.content)

    net.TRANSPORT = httpx.MockTransport(forward)
    settings = GateSettings(wait_seconds=100.0)
    web = net.WebClient(
        [HOST], gates=Gates(SIGN_IN, ACCOUNT, settings, declared_per_second=2.0, clock=clock, sleep=clock.sleep)
    )

    def asking(_settings, _since, _before, limit, _context):
        found = []
        for n in range(limit + 1):
            web.get(f"https://{HOST}/mail/v1/messages")
            if n:
                found.append(
                    SourceItem(
                        key=f"h{n}", title=f"Header {n}", text="", message=MessageDetails(sender=ACCOUNT, received="x")
                    )
                )
        return found

    monkeypatch.setattr(mail_headers, "asker", lambda store, source: asking)
    monkeypatch.setattr(reading_check, "gates_of", lambda store, source, root: web.gates.all())
    ws, cfg, store = make_core(tmp_path, [mail("a", 2)], account=ACCOUNT)
    store.close()
    application = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    client = TestClient(application, headers={"Authorization": f"Bearer {TOKEN}"})
    return client, helpers, application.state.store, cfg


def check(client):
    return client.post("/api/watch/m/check-reading")


def test_a_check_through_a_quota_shows_the_counts_the_stand_in_logged(tmp_path, monkeypatch):
    client, helpers, store, _cfg = rig(tmp_path, monkeypatch, rate=1)
    with client:
        found = check(client)
        assert found.status_code == 200
        shown = found.json()
        logged = helpers.get("/__e2e/requests").json()["requests"]
        # The one request let through and the one it refused: what the gate sent is what the service counted.
        assert shown["requests"] == len(logged) == 2
        assert [r["answer"] for r in logged] == ["ok", "refused"]
        assert [(r["status"], r["reason"]) for r in shown["refusals"]] == [(429, "throttled")]
        assert shown["refusals"][0]["wait_seconds"] == 10
        assert shown["ended"] == "throttled" and shown["read"] == 0 and shown["held"] == 0
        # The pace halved from the declared 2 a second, and the gate is still holding requests, until a time.
        assert (shown["pace_per_second"], shown["declared_per_second"]) == (1.0, 2.0)
        assert shown["waiting_until"] is not None
        assert shown["log_line"].startswith("check-reading requests=2 ")
        assert "refused(429 throttled wait=10s" in shown["log_line"]


def test_a_check_with_no_limit_reads_the_newest_headers_and_sees_no_refusal(tmp_path, monkeypatch):
    client, helpers, store, cfg = rig(tmp_path, monkeypatch, rate=None)
    with client:
        shown = check(client).json()
        asked = cfg.watch.check_reading_headers
        assert (shown["asked"], shown["read"], shown["ended"]) == (asked, asked, "read")
        assert shown["requests"] == asked + 1 and shown["refusals"] == [] and shown["waiting_until"] is None
        assert shown["paced_seconds"] > 0  # requests waited for their turn at the declared pace


def test_a_check_while_the_gate_is_holding_sends_nothing_and_says_until_when(tmp_path, monkeypatch):
    client, helpers, store, _cfg = rig(tmp_path, monkeypatch, rate=1)
    with client:
        check(client)
        again = check(client).json()
        logged = helpers.get("/__e2e/requests").json()["requests"]
        # The second check sent nothing: the service's log still holds the first check's two requests.
        assert again["requests"] == 0 and again["held"] == 1 and len(logged) == 2
        assert again["ended"] == "throttled" and again["waiting_until"] is not None
        assert again["refusals"] == []


def test_a_check_keeps_nothing_and_records_no_read(tmp_path, monkeypatch):
    client, _helpers, store, _cfg = rig(tmp_path, monkeypatch, rate=None)
    with client:
        before = (len(store.read().list("mail_header")), len(store.read().list("watch_run")))
        check(client)
        assert (len(store.read().list("mail_header")), len(store.read().list("watch_run"))) == before


def test_a_source_that_cannot_list_headers_is_refused_with_a_reason(tmp_path, monkeypatch):
    client, _helpers, _store, _cfg = rig(tmp_path, monkeypatch, rate=None)
    monkeypatch.setattr(mail_headers, "asker", lambda store, source: None)
    with client:
        answered = check(client)
        assert answered.status_code == 409 and "can't be checked" in answered.json()["detail"]
        assert client.post("/api/watch/nope/check-reading").status_code == 404
