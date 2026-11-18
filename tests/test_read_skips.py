"""A read takes in everything it can and says what it skipped (S-0633, plugin API 0.3.101), and the full-read
choices say when a count stopped at its cap instead of showing a figure that reads as exact (S-0631). Every kind of
read (a poll, the look further back, the full read and the year of headers) sets aside an item it can't read, counts
it by kind on the read's record, takes the rest in, and never fails as a whole for one item; an answer over the
client's limit for a whole read reads nothing and says so in plain words. Names and days come from the fixtures; the
AI is the stub."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import yaml
from fastapi.testclient import TestClient

from engine import connectors, source_intake, watch
from engine.config import load_config
from engine.config.schema import Price
from engine.connectors import Poll, Unreadable, skipped_counts
from engine.net import AnswerTooLarge
from engine.plugin_host import _as_read
from engine.sides import words_sheet
from engine.storage import Store, StoreError
from engine.watch import refresh
from tests.test_first_headers import WITH_HEADERS, header
from tests.test_first_headers import make as make_headers
from tests.test_look_back_addons import _manifest
from tests.test_people_suggestions import who
from tests.test_source_intake import mail
from tests.test_source_intake import make as make_core
from tests.test_today_panels_jobs import workspace

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
TOKEN = "read-skips-token"

# The fixture's connector reports an entry marked `big` as one it couldn't read, as a Poll, for older mail and headers.
SKIPPING = (
    WITH_HEADERS.replace(
        "    return [build(e) for e in within(settings, since, before)][-limit:]",
        "    found = within(settings, since, before)[-limit:]\n"
        "    return Poll([build(e) for e in found if not e.get('big')], {'ignored': 1}, complete=True,\n"
        "                unreadable=[Unreadable(e['key'], 'too large to read here', kind='too_large')\n"
        "                            for e in found if e.get('big')])",
    )
    .replace(
        '    return [build({**e, "text": ""}) for e in found][-limit:]',
        "    found = found[-limit:]\n"
        '    return Poll([build({**e, "text": ""}) for e in found if not e.get("big")], {}, complete=False,\n'
        '                unreadable=[Unreadable(e["key"], "too large to read here", kind="too_large")\n'
        '                            for e in found if e.get("big")])',
    )
    .replace("import MessageDetails, Poll,", "import MessageDetails, Poll, Unreadable,")
)
assert SKIPPING.count("Unreadable(") == 2 and "Unreadable," in SKIPPING


def open_questions(store, source_id="m"):
    return [
        q
        for q in store.read().list("question")
        if (q.data.get("resolves") or {}).get("kind") == "watch_unreadable"
        and q.data["resolves"]["source"] == source_id
        and q.data["status"] == "open"
    ]


# ---- a poll ----------------------------------------------------------------------------------------------------


def test_a_read_with_oversized_messages_among_normal_ones_takes_the_others_in_and_counts_each_kind(tmp_path):
    bad = [
        {"key": "message 8", "reason": "too large to read here", "kind": "too_large"},
        {"key": "message 9", "reason": "too large to read here", "kind": "too_large"},
        {"key": "message 10", "reason": "it couldn't be read"},
    ]
    ws, cfg, store = make_core(tmp_path, [mail("a", 1), mail("b", 2), mail("c", 3)], settings_extra={"unreadable": bad})
    try:
        refresh(ws, store, cfg, "m", NOW)
        run = watch.last_read(store, "m")
        assert run.data["outcome"] in ("ok", "baseline")
        assert run.data["skipped"] == {"too_large": 2, "other": 1}
        assert [u.get("kind") for u in run.data["unreadable"]] == ["too_large", "too_large", None]
        assert len(store.read().find("snapshot", {"source": "m"})) == 3, "the others were taken in"
        assert len(open_questions(store)) == 1, "the person is told, once"
    finally:
        store.close()


def test_a_read_that_skipped_nothing_records_no_skipping(tmp_path):
    ws, cfg, store = make_core(tmp_path, [mail("a", 1)])
    try:
        refresh(ws, store, cfg, "m", NOW)
        assert watch.last_read(store, "m").data["skipped"] == {}
    finally:
        store.close()


def test_skipped_items_are_counted_by_kind_and_an_unknown_kind_counts_as_other():
    found = [Unreadable("a", "x", "too_large"), Unreadable("b", "y"), Unreadable("c", "z", "something-new")]
    assert skipped_counts(found) == {"too_large": 1, "other": 2}
    assert skipped_counts([]) == {}


def test_an_unreadable_with_an_empty_kind_is_refused_by_the_check():
    with pytest.raises(ValueError):
        connectors.checked_poll(Poll([], unreadable=[Unreadable("a", "why", "")]))


def test_an_answer_over_the_limit_for_a_whole_read_reads_nothing_and_says_so_without_the_services_text(
    tmp_path, monkeypatch
):
    def too_big(settings, state, context):
        raise AnswerTooLarge("outage", "the answer is larger than 5120 KB")

    monkeypatch.setitem(
        connectors.CORE,
        "fake",
        connectors.Connector("fake", "A stand-in", connectors.FakeSettings, too_big, test_only=True),
    )
    ws, cfg, store = make_core(tmp_path, [mail("a", 1)])
    try:
        refresh(ws, store, cfg, "m", NOW)
        run = watch.last_run(store, "m")
        assert run.data["outcome"] == "failed" and run.data["error_own"] is True
        assert run.data["error"] == words_sheet()["read.failed.too_large"]
        assert "KB" not in run.data["error"] and not store.read().find("snapshot", {"source": "m"})
        assert "KB" not in (watch.problem_text(store, "m") or "")
    finally:
        store.close()


# ---- the look further back and the full read -----------------------------------------------------------------------


def older_world(tmp_path, big=("o21",), now=NOW):
    ws, cfg, store = workspace(tmp_path, SKIPPING)
    store.close()
    (ws.root / "plugins" / "p18" / "plugin.yaml").write_text(yaml.safe_dump(_manifest()))
    first = [mail(f"m{d}", d, now=now) for d in (1, 2, 3)]
    older = [{**mail(f"o{d}", d, now=now), **({"big": True} if f"o{d}" in big else {})} for d in (20, 21, 22, 60)]
    source = {"id": "m", "connector": "p18/inbox", "label": "Inbox", "settings": {"items": first, "older": older}}
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump({"version": 1, "sources": [source], "sorting": "rules"}))
    cfg = load_config(ws.config_dir, env={})
    cfg.ai.prices[cfg.ai.tiers["routine"].use] = Price(input_per_million=50.0, output_per_million=50.0)
    cfg.ai.budgets.confirm_above_usd = 0.10
    cfg.ai.budgets.first_go = False
    store = Store(ws.db_path, cfg=cfg)
    assert store.plugins.active("p18"), store.plugins.status["p18"].reason
    return ws, cfg, store


def test_the_full_read_takes_in_what_it_can_when_one_message_is_too_large_and_counts_it_on_the_first_read(tmp_path):
    ws, cfg, store = older_world(tmp_path)
    try:
        refresh(ws, store, cfg, "m", NOW)
        done = source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        assert done is not None and done.taken == 2, "the other two older messages were taken in"
        assert done.skipped == {"too_large": 1}
        run = source_intake.intake_run(store.read(), "m")
        assert run.data["older_skipped"] == {"too_large": 1} and run.data["full_read"] == 30
        kept = {s.data["key"] for s in store.read().find("snapshot", {"source": "m"})}
        assert "o20" in kept and "o22" in kept and "o21" not in kept
        assert len(open_questions(store)) == 1
    finally:
        store.close()


def test_a_look_that_skipped_nothing_records_nothing_and_says_nothing_about_skipping(tmp_path):
    ws, cfg, store = older_world(tmp_path, big=())
    try:
        refresh(ws, store, cfg, "m", NOW)
        done = source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        assert done.skipped == {} and done.taken == 3
        assert not source_intake.intake_run(store.read(), "m").data.get("older_skipped")
        assert open_questions(store) == []
    finally:
        store.close()


def test_a_skipped_message_never_makes_a_look_think_it_has_read_everything_there_is(tmp_path, monkeypatch):
    older = [mail(f"o{d}", d) for d in (20, 22)]

    def read_old(settings, since, before, cap, context):
        items = [
            connectors.SourceItem(
                **{k: v for k, v in m.items() if k != "message"}, message=connectors.MessageDetails(**m["message"])
            )
            for m in older
        ]
        return Poll(items, complete=False, unreadable=[Unreadable("message 9", "too large to read here", "too_large")])

    monkeypatch.setitem(connectors._OLDER, "fake", connectors.OlderMail(lambda *a: 3, read_old))
    ws, cfg, store = make_core(tmp_path, [mail(f"m{d}", d) for d in (1, 2, 3)], settings_extra={"capped": False})
    try:
        cfg.watch.look_back_max_items = cfg.watch.full_read_max_items = 3
        refresh(ws, store, cfg, "m", NOW)
        done = source_intake.look_further_back(ws, store, cfg, "m", 16, NOW, exact=True)
        assert done.skipped == {"too_large": 1} and done.taken == 2
        # Three came (two read, one skipped): the cap was reached, so the look stops where the mail it took does.
        stopped = source_intake.back_to_of(store.read(), "m")
        assert stopped == (NOW - timedelta(days=22)).date() != (NOW - timedelta(days=30)).date()
    finally:
        store.close()


def test_the_account_row_says_what_the_latest_read_and_the_first_reads_older_reads_skipped(tmp_path):
    now = datetime.now(UTC)
    ws, cfg, store = older_world(tmp_path, now=now)
    store.close()
    from api.app import create_app

    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        live = app.state.store
        refresh(ws, live, cfg, "m", now)
        assert client.get("/api/watch").json()[0]["skipped"] == {}, "nothing skipped: nothing said"
        answered = client.post("/api/watch/m/full-read", json={"days": 30})
        assert answered.status_code == 200 and answered.json()["skipped"] == {"too_large": 1}
        row = client.get("/api/watch").json()[0]
        assert row["skipped"] == {"too_large": 1} and row["last"]["skipped"] == {}


def test_a_count_that_the_service_refuses_as_too_large_says_so_in_plain_words(tmp_path, monkeypatch):
    ws, cfg, store = make_core(tmp_path, [mail("a", 1), mail("b", 2)], settings_extra={"capped": True})
    try:
        refresh(ws, store, cfg, "m", NOW)

        def too_big(*args):
            raise AnswerTooLarge("outage", "the answer is larger than 5120 KB")

        monkeypatch.setitem(connectors._OLDER, "fake", connectors.OlderMail(too_big, too_big))
        with pytest.raises(StoreError) as raised:
            source_intake.look_back_preview(ws, store, cfg, "m", 30, NOW)
        assert str(raised.value) == words_sheet()["full_read.failed.too_large"]
        with pytest.raises(StoreError) as raised:
            source_intake.look_further_back(ws, store, cfg, "m", 30, NOW)
        assert str(raised.value) == words_sheet()["full_read.failed.too_large"]
        assert not [s for s in store.read().find("snapshot", {"source": "m"}) if s.data["key"] not in ("a", "b")]
    finally:
        store.close()


# ---- the year of headers -------------------------------------------------------------------------------------------


def test_the_year_of_headers_keeps_what_it_can_and_counts_one_too_large_on_the_first_read(tmp_path, monkeypatch):
    import tests.test_first_headers as headers_tests

    monkeypatch.setattr(headers_tests, "WITH_HEADERS", SKIPPING)
    found = [header(f"s{i}", who(2), 21 + 7 * i, subject=f"Notice {i}") for i in range(4)]
    found[1] = {**found[1], "big": True}
    ws, cfg, store, _log = make_headers(tmp_path, headers=found)
    try:
        refresh(ws, store, cfg, "m", NOW)
        assert {h.data["key"] for h in store.read().list("mail_header")} == {"s0", "s2", "s3"}
        run = source_intake.intake_run(store.read(), "m")
        assert run.data["older_skipped"] == {"too_large": 1}
        assert watch.last_run(store, "m").data["outcome"] != "failed"
    finally:
        store.close()


# ---- what the plugin host takes from an older-items or headers function --------------------------------------------


def test_a_function_may_return_a_list_or_a_poll_and_only_the_items_and_unreadable_of_a_poll_are_used():
    item = connectors.SourceItem(key="a", title="A", text="t")
    plain = _as_read([item], 10)
    assert plain.items == [item] and plain.unreadable == [] and plain.complete is False
    poll = Poll(
        [item, connectors.SourceItem(key="b", title="B", text="t")],
        state={"x": 1},
        complete=True,
        unreadable=[Unreadable("c", "too large to read here", "too_large")],
    )
    used = _as_read(poll, 1)
    assert [i.key for i in used.items] == ["a"] and used.state == {} and used.complete is False
    assert [(u.key, u.kind) for u in used.unreadable] == [("c", "too_large")]
    with pytest.raises(ValueError):
        _as_read(Poll([], unreadable=[Unreadable("", "why")]), 10)


# ---- S-0631: a capped count reads as at least ----------------------------------------------------------------------


def three_months_of_mail(monkeypatch, tmp_path, limit=5, now=NOW):
    """A mailbox with 3 older messages inside a month and 5 more inside three months, asked with a cap of `limit`."""
    older = [mail(f"o{d}", d, now=now) for d in (20, 22, 25, 40, 50, 60, 70, 80)]

    def of(since, before):
        inside = [m for m in older if since <= datetime.fromisoformat(m["message"]["received"]).date() < before]
        return sorted(
            inside, key=lambda m: m["message"]["received"]
        )  # oldest first: a read keeps the newest at the end

    def count(settings, since, before, cap, context):
        return min(len(of(since, before)), cap)

    def read_old(settings, since, before, cap, context):
        return [
            connectors.SourceItem(
                **{k: v for k, v in m.items() if k != "message"}, message=connectors.MessageDetails(**m["message"])
            )
            for m in of(since, before)[-cap:]
        ]

    monkeypatch.setitem(connectors._OLDER, "fake", connectors.OlderMail(count, read_old))
    ws, cfg, store = make_core(
        tmp_path, [mail(f"m{d}", d, now=now) for d in (1, 2, 3)], settings_extra={"capped": False}
    )
    cfg.watch.look_back_max_items = limit
    return ws, cfg, store


def test_a_full_read_counts_its_whole_reach_past_the_page_size_and_says_at_least_only_past_the_ceiling(
    tmp_path, monkeypatch
):
    ws, cfg, store = three_months_of_mail(monkeypatch, tmp_path, limit=2)
    try:
        refresh(ws, store, cfg, "m", NOW)
        cfg.watch.full_read_choices = [14, 30, 90]
        cfg.watch.full_read_max_items = 100
        options = {o.days: o for o in source_intake.full_read_options(ws, store, cfg, "m", NOW)}
        assert (options[30].count, options[90].count) == (3, 8), "more than one page of mail is counted exactly"
        assert not options[30].capped and not options[90].capped
        assert options[90].estimate_usd > options[30].estimate_usd
        assert options[14].count == 0 and options[14].capped is False
        cfg.watch.full_read_max_items = 5
        options = {o.days: o for o in source_intake.full_read_options(ws, store, cfg, "m", NOW)}
        assert (options[30].count, options[30].capped) == (3, False)
        assert (options[90].count, options[90].capped) == (5, True), "past the ceiling: at least 5"
    finally:
        store.close()


def test_a_look_further_back_still_counts_only_one_page_and_says_at_least(tmp_path, monkeypatch):
    ws, cfg, store = three_months_of_mail(monkeypatch, tmp_path, limit=2)
    try:
        refresh(ws, store, cfg, "m", NOW)
        cfg.watch.full_read_max_items = 100
        found = source_intake.look_back_preview(ws, store, cfg, "m", 90)
        assert (found.count, found.capped) == (2, True)
    finally:
        store.close()


def test_the_full_read_takes_in_every_page_of_its_reach_and_stops_at_the_ceiling(tmp_path, monkeypatch):
    ws, cfg, store = three_months_of_mail(monkeypatch, tmp_path, limit=2)
    try:
        refresh(ws, store, cfg, "m", NOW)
        cfg.watch.full_read_choices = [14, 30, 90]
        cfg.watch.full_read_max_items = 100
        cfg.ai.budgets.confirm_above_usd = 100
        source_intake.answer_full_read(ws, store, cfg, "m", 90, NOW)
        keys = {s.data["key"] for s in store.read().find("snapshot", {"source": "m"})}
        assert {f"o{d}" for d in (20, 22, 25, 40, 50, 60, 70, 80)} <= keys, "all eight older messages, in pages of two"
    finally:
        store.close()


def test_a_full_read_past_the_ceiling_reads_the_newest_of_its_reach(tmp_path, monkeypatch):
    ws, cfg, store = three_months_of_mail(monkeypatch, tmp_path, limit=2)
    try:
        refresh(ws, store, cfg, "m", NOW)
        cfg.watch.full_read_choices = [90]
        cfg.watch.full_read_max_items = 4
        cfg.ai.budgets.confirm_above_usd = 100
        source_intake.answer_full_read(ws, store, cfg, "m", 90, NOW)
        keys = {s.data["key"] for s in store.read().find("snapshot", {"source": "m"})}
        assert {"o20", "o22", "o25", "o40"} <= keys and "o80" not in keys
    finally:
        store.close()


def test_a_day_with_more_messages_than_a_page_and_older_days_are_all_taken_in(tmp_path, monkeypatch):
    now = NOW
    day = [mail(f"d{n}", 40 + n / 100, now=now) for n in range(7)]  # seven messages on one day, pages hold two
    older = day + [mail(f"o{d}", d, now=now) for d in (20, 60, 70)]

    def of(since, before):
        inside = [m for m in older if since <= datetime.fromisoformat(m["message"]["received"]).date() < before]
        return sorted(inside, key=lambda m: m["message"]["received"])

    def count(settings, since, before, cap, context):
        return min(len(of(since, before)), cap)

    def read_old(settings, since, before, cap, context):
        return [
            connectors.SourceItem(
                **{k: v for k, v in m.items() if k != "message"}, message=connectors.MessageDetails(**m["message"])
            )
            for m in of(since, before)[-cap:]
        ]

    monkeypatch.setitem(connectors._OLDER, "fake", connectors.OlderMail(count, read_old))
    ws, cfg, store = make_core(
        tmp_path, [mail(f"m{d}", d, now=now) for d in (1, 2, 3)], settings_extra={"capped": False}
    )
    try:
        cfg.watch.look_back_max_items = 2
        cfg.watch.full_read_choices = [90]
        cfg.watch.full_read_max_items = 100
        cfg.ai.budgets.confirm_above_usd = 100
        refresh(ws, store, cfg, "m", NOW)
        source_intake.answer_full_read(ws, store, cfg, "m", 90, NOW)
        keys = {s.data["key"] for s in store.read().find("snapshot", {"source": "m"})}
        assert {m["key"] for m in older} <= keys, "the crowded day and every older day are taken in"
    finally:
        store.close()


def test_answer_too_large_is_part_of_the_plugin_api_and_is_a_connector_error():
    from engine import plugin_api
    from engine.connectors import ConnectorError

    assert plugin_api.AnswerTooLarge is AnswerTooLarge and issubclass(AnswerTooLarge, ConnectorError)
    assert "AnswerTooLarge" in plugin_api.__all__


def test_the_routes_carry_whether_a_count_was_capped(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    ws, cfg, store = three_months_of_mail(monkeypatch, tmp_path, now=now)
    store.close()
    from api.app import create_app

    watching = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
    (ws.config_dir / "watch.yaml").write_text(
        yaml.safe_dump({**watching, "look_back_max_items": 5, "full_read_max_items": 5})
    )

    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        refresh(ws, app.state.store, cfg, "m", now)
        shown = client.get("/api/watch/m/full-read").json()
        assert {o["days"]: o["capped"] for o in shown["options"]} == {14: False, 30: False, 90: True}
        assert client.get("/api/watch/m/look-back", params={"days": 90}).json()["capped"] is True
