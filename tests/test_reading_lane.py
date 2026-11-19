"""Reading older mail goes through one background lane per account (S-0665, decision 2026-11-19): the person's choice is
recorded and answered at once, the worker reads one slice (a page) for each account in turn, a wait the service asks for
is a wait and never a try, only an outage or no network counts toward giving up, and a count the service can't
give never blocks or fails the choice. Time is passed in, never waited for. Names and days come from the fixtures."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from engine import connectors, reading_lane, source_intake
from engine.connectors import ConnectorError, OlderCount, OlderMail
from tests.test_older_read_carries_on import DAYS, NOW, older_keys, world


def drain(ws, store, cfg, now, rounds=60):
    """Run the lane until nothing is due at `now`; returns the sources read, in order."""
    order: list[str] = []
    for _ in range(rounds):
        read, more = reading_lane.run_slices(ws, store, cfg, now)
        order += read
        if not more:
            return order
    raise AssertionError("the lane never finished")


def test_read_it_returns_at_once_with_the_choice_recorded_even_when_the_count_is_refused(tmp_path, monkeypatch):
    refused = ConnectorError("throttled", "HTTP 429", retry_after=600)
    ws, cfg, store, service = world(tmp_path, monkeypatch, {})

    def count(settings, since, before, limit, context):
        raise refused

    monkeypatch.setitem(connectors._OLDER, "fake", OlderMail(count, service.read))
    try:
        options = source_intake.full_read_options(ws, store, cfg, "m", NOW)
        assert [o.unknown for o in options if o.days > 14] == [True, True], "no number, and asked once, not per reach"
        before = service.calls
        queued = source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        assert queued.stopped == "queued" and service.calls == before, "nothing was read in the request"
        run = source_intake.intake_run(store.read(), "m")
        assert run.data["full_read"] == 30 and run.data["older_read"]["kind"] == "queued"
        assert older_keys(store) == set()
        drain(ws, store, cfg, NOW)
        assert older_keys(store) == {f"o{d}" for d in DAYS}, "the read went on with no count"
        assert not source_intake.older_read_waiting(store.read(), "m")
    finally:
        store.close()


def test_a_throttled_slice_resumes_at_its_time_with_no_try_counted_and_never_gives_up(tmp_path, monkeypatch):
    throttled = ConnectorError("throttled", "HTTP 429", retry_after=60)
    ws, cfg, store, service = world(tmp_path, monkeypatch, {n: throttled for n in (2, 4, 6, 8, 10, 12, 14, 16)})
    try:
        cfg.watch.older_read_tries = 1
        source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        at = NOW
        for _ in range(8):
            drain(ws, store, cfg, at)
            waiting = source_intake.older_read_waiting(store.read(), "m")
            if waiting is None:
                break
            assert waiting["kind"] == "throttled" and not waiting["gave_up"] and waiting["tries"] == 0
            calls = service.calls
            drain(ws, store, cfg, at + timedelta(seconds=59))
            assert service.calls == calls, "nothing is asked inside the wait"
            at = datetime.fromisoformat(waiting["at"])
        assert older_keys(store) == {f"o{d}" for d in DAYS}
    finally:
        store.close()


def test_an_outage_counts_toward_giving_up_but_a_throttle_between_outages_does_not(tmp_path, monkeypatch):
    outage = ConnectorError("outage", "HTTP 503")
    ws, cfg, store, _ = world(tmp_path, monkeypatch, {n: outage for n in range(1, 30)})
    try:
        cfg.watch.older_read_tries = 2
        source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        at = NOW
        for expected in (1, 2):
            drain(ws, store, cfg, at)
            waiting = source_intake.older_read_waiting(store.read(), "m")
            assert waiting["tries"] == expected and not waiting["gave_up"]
            at = datetime.fromisoformat(waiting["at"])
        drain(ws, store, cfg, at)
        assert source_intake.older_read_waiting(store.read(), "m")["gave_up"]
    finally:
        store.close()


def test_two_accounts_take_turns_one_slice_each_and_a_wait_holds_only_its_own_account(tmp_path, monkeypatch):

    ws, cfg, store, service = world(tmp_path, monkeypatch, {})
    try:
        source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        # A second source on another account, read in the same lane pass.
        run = source_intake.intake_run(store.read(), "m")
        twin = cfg.watch.sources[0].model_copy(update={"id": "n", "account": "other@example.com"})
        cfg.watch.sources.append(twin)
        cfg.watch.sources[0].account = "person@example.com"
        with store.transaction() as tx:
            tx.create(
                "watch_run",
                {**{k: v for k, v in run.data.items() if k != "id"}, "source": "n"},
                source_intake._MOVED,
            )
        order = []
        for _ in range(4):
            read, _more = reading_lane.run_slices(ws, store, cfg, NOW)
            order += read
        assert order[:2] == ["m", "n"] and order[2:4] == ["m", "n"], (
            "one slice each, in turn, not one account to the end"
        )
        # A wait on one account's read holds that account only: the other goes on in the same pass.
        service.script[service.calls + 1] = ConnectorError("throttled", "HTTP 429", retry_after=300)
        read, _more = reading_lane.run_slices(ws, store, cfg, NOW)
        assert read[0] == "m", "m asked first and was told to wait"
        waiting = source_intake.older_read_waiting(store.read(), "m")
        assert waiting["kind"] == "throttled" and reading_lane.account_wait(
            store.read(), cfg, "person@example.com", NOW
        )
        calls = service.calls
        read, _more = reading_lane.run_slices(ws, store, cfg, NOW + timedelta(seconds=10))
        assert read in (["n"], []) and "m" not in read, "m waits for its time while n goes on"
        assert service.calls <= calls + 1
    finally:
        store.close()


def test_a_full_read_of_a_real_sized_mailbox_under_a_low_limit_completes_unattended_with_few_repeats(
    tmp_path, monkeypatch
):
    """The stand-in mail service limits one account to a request a second and refuses for a penalty after a burst; its
    log (`/__e2e/requests`) is what the read is judged by: every refusal is a wait the lane keeps, no request is made
    inside one, and the requests made stay near the pages the mailbox needs."""
    from starlette.testclient import TestClient

    from engine.connectors import MessageDetails, SourceItem
    from tests.fake_services import SECURE_SERVICES, State, big_mailbox, build_app

    state = State(tmp_path / "stand-in")
    state.big_mailbox, state.moment, state.accounts = True, NOW, 1
    state.access.add("tok")
    state.account_of["tok"] = 0
    helpers = TestClient(build_app(state, 0, {}))
    mail_service = TestClient(build_app(state, 0, SECURE_SERVICES, helpers=False))
    clock = {"now": NOW.timestamp()}
    assert helpers.post("/__e2e/quota", json={"rate": 1, "penalty": 30}).json() == {"quota": True}
    state.quota.clock = lambda: clock["now"]
    fetched = {"messages": 0}

    def read(settings, since, before, size, context):
        answer = mail_service.get(
            "/mail/v1/older",
            params={"folder": "inbox", "since": since.isoformat(), "before": before.isoformat()},
            headers={"Authorization": "Bearer tok"},
        )
        if answer.status_code == 429:
            raise ConnectorError("throttled", "HTTP 429", retry_after=int(answer.headers["Retry-After"]))
        found = sorted(answer.json()["messages"], key=lambda m: m["received"], reverse=True)[:size]
        fetched["messages"] += len(found)
        return [
            SourceItem(
                key=m["id"],
                title=m["subject"],
                text=m["body"],
                author=m["from"]["address"],
                message=MessageDetails(sender=m["from"]["address"], received=m["received"], unread=False),
            )
            for m in found
        ]

    ws, cfg, store, service = world(tmp_path, monkeypatch, {})
    monkeypatch.setitem(connectors._OLDER, "fake", OlderMail(lambda *a: 0, read))
    try:
        cfg.watch.full_read_page_items = cfg.watch.look_back_max_items = 50
        cfg.watch.full_read_max_items = 5000
        cfg.watch.full_read_choices = [90]
        first_look = source_intake.back_to_of(store.read(), "m")
        source_intake.answer_full_read(ws, store, cfg, "m", 90, NOW)
        at, throttled = NOW, 0
        for _ in range(200):
            clock["now"] = at.timestamp()
            drain(ws, store, cfg, at)
            waiting = source_intake.older_read_waiting(store.read(), "m")
            if waiting is None:
                break
            assert waiting["kind"] == "throttled" and not waiting["gave_up"], "a wait is never a failure"
            throttled += 1
            at = datetime.fromisoformat(waiting["at"])
        assert throttled >= 2, "the low limit did slow the read down"
        assert source_intake.older_read_waiting(store.read(), "m") is None, "the read completed unattended"
        assert source_intake.intake_run(store.read(), "m").data.get("older_finished_at"), (
            "the look at people may look again"
        )
        reach = {
            s.data["key"] for s in store.read().find("snapshot", {"source": "m"}) if s.data["key"].startswith("big-")
        }
        held = len([m for m in big_mailbox(NOW)["inbox"] if m["received"][:10] < first_look.isoformat()])
        assert held > 100 and len(reach) == held, "the whole reach was read, every message once"
        log = helpers.get("/__e2e/requests").json()["requests"]
        answers = [r["answer"] for r in log]
        assert answers.count("refused") == throttled, (
            "a refusal only ever came from a burst, never from a request inside a wait"
        )
        assert "refused refused" not in " ".join(answers)
        pages = -(-held // cfg.watch.full_read_page_items)
        assert answers.count("ok") <= pages + 3, "requests stay near the pages the mailbox needs"
        assert fetched["messages"] <= len(reach) * 1.15, "few messages were fetched twice"
    finally:
        store.close()


def test_a_count_the_service_gives_is_still_shown_and_kept(tmp_path, monkeypatch):
    ws, cfg, store, service = world(tmp_path, monkeypatch, {})
    try:
        monkeypatch.setitem(connectors._OLDER, "fake", OlderMail(lambda *a: OlderCount(7, True), service.read))
        options = source_intake.full_read_options(ws, store, cfg, "m", NOW)
        assert all(not o.unknown for o in options) and options[1].count == 7 and options[1].estimate
    finally:
        store.close()


def test_a_lane_page_never_repeats_more_than_the_oldest_day_of_the_one_before(tmp_path, monkeypatch):
    ws, cfg, store, service = world(tmp_path, monkeypatch, {})
    try:
        source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        drain(ws, store, cfg, NOW)
        asked = [(since, before) for since, before, _ in service.asked]
        assert all(isinstance(a, date) for pair in asked for a in pair)
        # Each page starts where the last whole day ended, never at the top of the range again.
        assert len({before for _, before in asked}) == len(asked)
    finally:
        store.close()
