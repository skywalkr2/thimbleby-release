"""Sign-in reads recent mail and a bounded sample of headers; the rest of the year is read later, in the account's
lane, at the pace the service allows (S-0666, decision 2026-11-19). A mail service that counts one request for the list
and one for each message, and notes any request made while it asked to wait, stands in for a real one. Time is passed
in, never waited for. Names and days come from the fixtures."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from engine import mail_headers, reading_lane, source_intake
from engine.connectors import ConnectorError, MessageDetails, Poll, SourceItem
from engine.watch import refresh
from tests.test_older_read_carries_on import NOW
from tests.test_source_intake import mail
from tests.test_source_intake import make as make_core

TOTAL = 5000


class Mailbox:
    """A mailbox of `TOTAL` messages spread over the days before the first read's window, newest first. A call costs one
    request for the list and one for each message it returns. `script` names the calls the service answers with a wait:
    ("throttled", seconds) refuses the call, ("partial", seconds) gives half a page and then asks to wait."""

    def __init__(self, script: dict[int, tuple[str, int]] | None = None):
        self.script = script or {}
        self.items = [mail(f"h{i}", 8 + i * 5.5 / TOTAL) for i in range(TOTAL)]
        self.calls = 0
        self.requests = 0
        self.sizes: list[int] = []
        self.penalty_until: datetime | None = None
        self.inside_penalty = 0  # calls made while the service was asking to wait

    def __call__(self, settings, since, before, limit, context):
        self.calls += 1
        self.sizes.append(limit)
        if self.penalty_until is not None and context.now < self.penalty_until:
            self.inside_penalty += 1
        found = [m for m in self.items if since <= date.fromisoformat(m["message"]["received"][:10]) < before]
        page = [
            SourceItem(**{k: v for k, v in m.items() if k != "message"}, message=MessageDetails(**m["message"]))
            for m in found[:limit]
        ]
        kind, seconds = self.script.get(self.calls, ("", 0))
        if not kind:
            self.requests += 1 + len(page)
            return page
        self.penalty_until = context.now + timedelta(seconds=seconds)
        err = ConnectorError("throttled", "HTTP 429", retry_after=seconds)
        if kind == "partial" and page:
            half = page[: len(page) // 2]
            self.requests += 1 + len(half)
            return Poll(half, stopped=err)
        self.requests += 1
        raise err


def signed_in(tmp_path, monkeypatch, script=None):
    """A source about to be read for the first time, with `TOTAL` headers behind it."""
    box = Mailbox(script)
    monkeypatch.setattr(mail_headers, "asker", lambda store, source: box)
    ws, cfg, store = make_core(tmp_path, [mail(f"m{d}", d) for d in (1, 2, 3)], settings_extra={"capped": False})
    cfg.ai.budgets.first_go = False
    cfg.watch.first_headers_max_items = TOTAL
    return ws, cfg, store, box


def drain(ws, store, cfg, now, rounds=80):
    for _ in range(rounds):
        _read, more = reading_lane.run_slices(ws, store, cfg, now)
        if not more:
            return
    raise AssertionError("the lane never finished")


def kept(store):
    return {h.data["key"] for h in store.read().list("mail_header")}


def runs(store):
    return [(r.data["outcome"], r.data.get("retry_at")) for r in store.read().find("watch_run", {"source": "m"})]


def test_a_sign_in_over_a_big_mailbox_reads_only_the_sample_and_queues_the_rest(tmp_path, monkeypatch):
    ws, cfg, store, box = signed_in(tmp_path, monkeypatch)
    try:
        refresh(ws, store, cfg, "m", NOW)
        sample = cfg.watch.first_headers_sample_items
        # One request for the list and one for each of the sample: 301, where the whole year was 5,001.
        assert box.calls == 1 and box.sizes == [sample] and box.requests == 1 + sample
        assert len(kept(store)) == sample
        waiting = mail_headers.sweep_waiting(store.read(), "m")
        assert waiting["kind"] == "queued" and waiting["left"] == cfg.watch.first_headers_max_items - sample
    finally:
        store.close()


def test_the_rest_of_the_year_arrives_later_and_no_call_is_made_inside_the_services_wait(tmp_path, monkeypatch):
    ws, cfg, store, box = signed_in(tmp_path, monkeypatch, {3: ("throttled", 60), 5: ("partial", 90)})
    try:
        refresh(ws, store, cfg, "m", NOW)
        drain(ws, store, cfg, NOW)
        waiting = mail_headers.sweep_waiting(store.read(), "m")
        assert waiting["kind"] == "throttled" and waiting["tries"] == 0 and not waiting["gave_up"]
        assert datetime.fromisoformat(waiting["at"]) == NOW + timedelta(seconds=60)
        calls = box.calls
        drain(ws, store, cfg, NOW + timedelta(seconds=59))
        assert box.calls == calls, "nothing is asked inside the wait"
        at = NOW + timedelta(seconds=60)
        for _ in range(6):
            drain(ws, store, cfg, at)
            waiting = mail_headers.sweep_waiting(store.read(), "m")
            if waiting is None:
                break
            at = datetime.fromisoformat(waiting["at"])
        assert mail_headers.sweep_waiting(store.read(), "m") is None
        # Its end is kept, so the look at who the person deals with looks again after it.
        assert any(r.data.get("header_sweep_finished_at") for r in store.read().find("watch_run", {"source": "m"}))
        assert box.inside_penalty == 0, "no request was made inside a penalty window"
        assert len(kept(store)) == cfg.watch.first_headers_max_items == TOTAL, "the whole year arrived, none twice"
    finally:
        store.close()


def test_a_stopped_header_sweep_leaves_the_sources_read_as_it_was(tmp_path, monkeypatch):
    ws, cfg, store, box = signed_in(tmp_path, monkeypatch, {1: ("throttled", 600), 3: ("throttled", 600)})
    try:
        refresh(ws, store, cfg, "m", NOW)  # the sample itself is refused
        assert kept(store) == set() and runs(store) == [("baseline", None)]
        waiting = mail_headers.sweep_waiting(store.read(), "m")
        assert waiting["kind"] == "throttled" and datetime.fromisoformat(waiting["at"]) == NOW + timedelta(minutes=10)
        later = NOW + timedelta(minutes=10)
        drain(ws, store, cfg, later)  # the next pages: one is read, then the service asks to wait again
        assert runs(store) == [("baseline", None)], "a throttled header sweep is not the source's latest run"
        assert mail_headers.sweep_waiting(store.read(), "m")["kind"] == "throttled"
        assert len(store.read().list("request")) == 3, "the first read's own mail is as it was"
    finally:
        store.close()


def test_the_look_further_back_from_a_menu_returns_at_once_and_the_lane_reads_it(tmp_path, monkeypatch):
    from tests.test_older_read_carries_on import world

    ws, cfg, store, service = world(tmp_path, monkeypatch, {})
    try:
        before = service.calls
        queued = source_intake.queue_look_further_back(ws, store, cfg, "m", 14, NOW)
        assert queued.stopped == "queued" and service.calls == before, "nothing is asked of the service in the request"
        assert source_intake.older_read_waiting(store.read(), "m")["kind"] == "queued"
        drain(ws, store, cfg, NOW)
        assert service.calls > before and source_intake.older_read_waiting(store.read(), "m") is None
    finally:
        store.close()
