"""The full-read choice asks the mail service for its counts once per reach and keeps them (S-0644), and a source whose
read stopped partway is not offered the choice again (S-0645)."""

from __future__ import annotations

from datetime import timedelta

from engine import connectors, source_intake
from engine.connectors import ConnectorError, OlderMail
from tests.test_older_read_carries_on import NOW, Service, world


class Counting(Service):
    def __init__(self, script):
        super().__init__(script)
        self.counted: list[tuple] = []

    def count(self, settings, since, before, limit, context):
        self.counted.append((since, before))
        return super().count(settings, since, before, limit, context)


def counting_world(tmp_path, monkeypatch, script=None):
    ws, cfg, store, service = world(tmp_path, monkeypatch, script or {})
    counting = Counting(script or {})
    monkeypatch.setitem(connectors._OLDER, "fake", OlderMail(counting.count, counting.read))
    return ws, cfg, store, counting


def test_the_choices_ask_the_service_once_per_reach_within_the_time_and_again_after_it_or_after_a_read(
    tmp_path, monkeypatch
):
    ws, cfg, store, service = counting_world(tmp_path, monkeypatch, {2: ConnectorError("outage", "HTTP 503")})
    try:
        reaches = len(cfg.watch.full_read_choices)
        first = source_intake.full_read_options(ws, store, cfg, "m", NOW)
        asked = len(service.counted)
        assert 0 < asked <= reaches
        for minutes in (1, 5, 14):  # refreshes, focus, every change: all answered from what is kept
            again = source_intake.full_read_options(ws, store, cfg, "m", NOW + timedelta(minutes=minutes))
            assert again == first
        assert len(service.counted) == asked
        source_intake.full_read_options(ws, store, cfg, "m", NOW + timedelta(minutes=cfg.watch.full_read_count_minutes))
        assert len(service.counted) == 2 * asked, "asked again once the time has passed"
        # A read of the source's older mail drops what was kept.
        source_intake.full_read_options(ws, store, cfg, "m", NOW + timedelta(minutes=16))
        before = len(service.counted)
        source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW + timedelta(minutes=16))
        # Only this workspace's: the kept counts are shared by the process, and other tests' workspaces have an "m" too.
        assert not [k for k in source_intake._KEPT_COUNTS if k[0] == str(ws.root) and k[1] == "m"]
        assert len(service.counted) > before
    finally:
        store.close()


def test_a_changed_setting_asks_again_and_zero_minutes_asks_every_time(tmp_path, monkeypatch):
    ws, cfg, store, service = counting_world(tmp_path, monkeypatch)
    try:
        source_intake.full_read_options(ws, store, cfg, "m", NOW)
        asked = len(service.counted)
        cfg.watch.sources[0].settings = {**cfg.watch.sources[0].settings, "capped": True}
        source_intake.full_read_options(ws, store, cfg, "m", NOW)
        assert len(service.counted) == 2 * asked
        cfg.watch.full_read_count_minutes = 0
        source_intake.full_read_options(ws, store, cfg, "m", NOW)
        source_intake.full_read_options(ws, store, cfg, "m", NOW)
        assert len(service.counted) == 4 * asked, "0 asks every time"
    finally:
        store.close()


def test_a_source_whose_read_stopped_and_waits_is_not_offered_the_full_read_again(tmp_path, monkeypatch):
    ws, cfg, store, _ = world(tmp_path, monkeypatch, {2: ConnectorError("throttled", "HTTP 429", retry_after=60)})
    try:
        source = cfg.watch.sources[0]
        assert source_intake.full_read_pending(store, cfg, source)
        source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        assert source_intake.older_read_waiting(store.read(), "m") is not None
        assert not source_intake.full_read_pending(store, cfg, source)
        # Even if the answer were lost, a waiting read alone keeps the question closed.
        source_intake._record_full_read(store, "m", None)
        assert not source_intake.full_read_pending(store, cfg, source)
    finally:
        store.close()
