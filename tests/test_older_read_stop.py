"""An add-on's read of older mail or of headers that the service slows down partway hands in what it read and says
where it stopped (S-0663, plugin API 0.3.103): the core keeps the items, records the stop as it does for its own reads
and asks again after the wait for the days below the oldest item it holds. A try counts as getting further only when it
took something new, so a service that keeps handing back the same messages is given up on after the setting's tries.
Time is passed in, never waited for. Names and days come from the fixtures."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from engine import connectors, source_intake
from engine.connectors import ConnectorError, MessageDetails, OlderMail, Poll, SourceItem
from tests.test_older_read_carries_on import DAYS, NOW, Service, handed_in, older_keys, world


class SlowingService(Service):
    """A service whose calls named in `stops` hand back what they read as a `Poll` that says the service slowed down
    (`count` of the newest messages of the range); every other call answers as a plain list."""

    def __init__(self, stops: dict[int, tuple[int, ConnectorError]], same_page: bool = False):
        super().__init__({})
        self.stops, self.same_page = stops, same_page

    def read(self, settings, since, before, size, context):
        self.calls += 1
        self.asked.append((since, before, size))
        found = self.within(date(2000, 1, 1), date(2100, 1, 1)) if self.same_page else self.within(since, before)
        if self.calls in self.stops:
            count, error = self.stops[self.calls]
            return Poll([build(m) for m in found[:count]], complete=False, stopped=error)
        return [build(m) for m in found[:size]]


def build(m):
    return SourceItem(**{k: v for k, v in m.items() if k != "message"}, message=MessageDetails(**m["message"]))


def slowed(tmp_path, monkeypatch, stops, page=8, same_page=False):
    service = SlowingService(stops, same_page)
    monkeypatch.setitem(connectors._OLDER, "fake", OlderMail(service.count, service.read))
    ws, cfg, store, _ = world(tmp_path, monkeypatch, {}, page=page)
    monkeypatch.setitem(connectors._OLDER, "fake", OlderMail(service.count, service.read))
    return ws, cfg, store, service


def test_an_older_read_that_hands_in_items_and_a_stop_keeps_them_and_carries_on_below_them_after_the_wait(
    tmp_path, monkeypatch
):
    slow = ConnectorError("throttled", "HTTP 429", retry_after=90)
    ws, cfg, store, service = slowed(tmp_path, monkeypatch, {1: (5, slow)})
    try:
        stopped = source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        assert stopped.stopped == "throttled" and stopped.taken == 5
        assert older_keys(store) == {f"o{d}" for d in DAYS[:5]} and handed_in(store) >= older_keys(store)
        waiting = source_intake.older_read_waiting(store.read(), "m")
        oldest = max(DAYS[:5])
        assert datetime.fromisoformat(waiting["at"]) == NOW + timedelta(seconds=90) and waiting["taken"] == 5
        assert date.fromisoformat(waiting["before"]) == (NOW - timedelta(days=oldest)).date() + timedelta(days=1)
        assert source_intake.continue_older_read(ws, store, cfg, "m", NOW + timedelta(seconds=89)) is None
        done = source_intake.continue_older_read(ws, store, cfg, "m", NOW + timedelta(seconds=90))
        assert done.stopped is None and service.asked[1][1].isoformat() == waiting["before"]
        assert older_keys(store) == {f"o{d}" for d in DAYS}, "every message was read, none twice"
        assert not source_intake.older_read_waiting(store.read(), "m")
    finally:
        store.close()


def test_tries_that_take_nothing_new_give_up_after_the_setting(tmp_path, monkeypatch):
    # An outage counts as a try (a wait the service asks for never does: tests/test_reading_lane.py).
    slow = ConnectorError("outage", "HTTP 503")
    ws, cfg, store, service = slowed(tmp_path, monkeypatch, {n: (3, slow) for n in range(1, 40)}, same_page=True)
    try:
        cfg.watch.older_read_tries = 3
        at = NOW
        done = source_intake.read_full_now(ws, store, cfg, "m", 14, at)
        assert done.taken == 3 and not done.gave_up
        rounds = 0
        while not done.gave_up:
            rounds += 1
            assert rounds <= 5, "the read never gave up"
            at = datetime.fromisoformat(done.continues_at)
            done = source_intake.continue_older_read(ws, store, cfg, "m", at)
        assert done.taken == 0 and done.continues_at is None
        assert service.calls == 4, "one try that got further, then three that took nothing new"
        assert len(older_keys(store)) == 3
        assert source_intake.continue_older_read(ws, store, cfg, "m", at + timedelta(days=1)) is None
        assert service.calls == 4
    finally:
        store.close()


@pytest.mark.parametrize(("taken", "tries"), [(0, 3), (2, 1)])
def test_a_page_of_messages_already_taken_is_no_progress_but_a_new_one_is(taken, tries):
    cfg = SimpleNamespace(
        watch=SimpleNamespace(older_read_tries=9, older_read_retry_minutes=5, older_read_throttle_minutes=5)
    )
    stop = ConnectorError("outage", "HTTP 503")
    fetched = source_intake.Fetched(40, {}, stop, date(2026, 10, 1))
    now = NOW
    carry = source_intake._carry(cfg, stop, fetched, date(2026, 9, 1), 100, now, {"tries": 2, "taken": 7}, None, taken)
    assert carry["tries"] == tries and carry["taken"] == 7 + taken


def test_a_slow_down_before_anything_was_read_keeps_the_choice_and_carries_on_when_the_service_allows(
    tmp_path, monkeypatch
):
    # A wait the service asks for on the very first page is scheduled like one partway through: nothing is taken,
    # the choice is kept, and the read carries on at the time the service gave.
    slow = ConnectorError("throttled", "HTTP 429", retry_after=60)
    ws, cfg, store, _ = slowed(tmp_path, monkeypatch, {1: (0, slow)})
    try:
        done = source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        assert done is not None and done.stopped == "throttled" and done.taken == 0
        waiting = source_intake.older_read_waiting(store.read(), "m")
        assert waiting is not None and waiting["kind"] == "throttled" and not waiting["gave_up"]
        assert waiting["at"] == (NOW + timedelta(seconds=60)).isoformat()
        assert older_keys(store) == set()
    finally:
        store.close()


def test_a_stop_the_person_must_deal_with_before_anything_was_read_is_said_at_once(tmp_path, monkeypatch):
    from engine.storage import StoreError

    signed_out = ConnectorError("auth", "the sign-in was withdrawn")
    ws, cfg, store, _ = slowed(tmp_path, monkeypatch, {1: (0, signed_out)})
    try:
        with pytest.raises(StoreError):
            source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        assert older_keys(store) == set() and not source_intake.older_read_waiting(store.read(), "m")
    finally:
        store.close()


def test_the_plugin_host_keeps_the_stop_of_an_older_or_headers_read_and_refuses_it_on_a_poll():
    from engine.plugin_host import PluginHost, _as_read

    slow = ConnectorError("throttled", "HTTP 429", retry_after=30)
    kept = _as_read(
        Poll([build(__import__("tests.test_source_intake", fromlist=["mail"]).mail("a", 5))], stopped=slow), 10
    )
    assert kept.stopped is slow and len(kept.items) == 1 and kept.complete is False
    assert _as_read([], 10).stopped is None
    with pytest.raises(ValueError):
        connectors.checked_poll(Poll([], stopped="slow"))
    host = SimpleNamespace(
        connector_context=lambda *a: SimpleNamespace(web=None),
        failed=lambda *a: None,
        succeeded=lambda *a: None,
    )
    polled = SimpleNamespace(name="p/c", poll=lambda settings, state, context: Poll([], stopped=slow))
    with pytest.raises(ConnectorError) as raised:
        PluginHost.poll_connector(host, polled, None, {}, SimpleNamespace(workspace_root=None))
    assert raised.value.kind == "outage" and "stopped" in str(raised.value)


def test_a_headers_read_that_stops_keeps_its_headers_and_waits_in_the_lane_without_becoming_the_sources_read(tmp_path):
    from tests import test_first_headers as fh

    stopping = fh.WITH_HEADERS.replace(
        '    return [build({**e, "text": ""}) for e in found][-limit:]',
        '    items = [build({**e, "text": ""}) for e in found][-limit:]\n'
        "    if settings.stop:\n"
        "        from engine.plugin_api import ConnectorError as Slow, Poll\n"
        '        return Poll(items[:3], stopped=Slow("throttled", "slow", retry_after=60))\n'
        "    return items",
    ).replace('    fail: str = ""', '    fail: str = ""\n    stop: bool = False')
    assert "settings.stop" in stopping
    original = fh.WITH_HEADERS
    fh.WITH_HEADERS = stopping
    try:
        ws, cfg, store, _ = fh.make(tmp_path, stop=True)
    finally:
        fh.WITH_HEADERS = original
    try:
        fh.refresh(ws, store, cfg, "m", NOW)
        assert len(fh.kept(store)) == 3, "what the headers read gave is kept"
        runs = store.read().find("watch_run", {"source": "m"})
        assert [r.data["outcome"] for r in runs] == ["baseline"], "a stopped header read is not the source's read"
        from engine import mail_headers

        waiting = mail_headers.sweep_waiting(store.read(), "m")
        assert waiting["kind"] == "throttled" and waiting["at"] == (NOW + timedelta(seconds=60)).isoformat()
    finally:
        store.close()
