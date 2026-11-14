"""A burst from a watched source is one input per project (design 6.2, change log 360): more than `watch.burst_items`
changed items from one read of a page, feed or tracker are filed as one input, each item its own block; mail and
calendars stay one input each, and what a rule closes makes no run and isn't counted."""

from datetime import UTC, datetime

import pytest
import yaml

from engine.config import load_config
from tests.conftest import DEMO_B

NOW = datetime(2030, 3, 4, 9, 0, tzinfo=UTC)


def make(tmp_path, source, **watch):
    from engine.storage import Store
    from engine.workspace import init_workspace

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump({"version": 1, "sources": [source], **watch}))
    cfg = load_config(ws.config_dir, env={})
    return ws, cfg, Store(ws.db_path, cfg=cfg)


def board(items, **more):
    return {
        "id": "s",
        "connector": "fake",
        "label": "Tracker",
        "first_run": "all",
        "settings": {"items": items},
        **more,
    }


def many(count, **more):
    return [{"key": f"k{n}", "title": f"Story {n}", "text": f"Words of story {n}.", **more} for n in range(count)]


def inputs(store):
    return [r for r in store.read().list("request") if r.data.get("origin") == "input"]


def text_of(ws, store, request):
    source = store.read().get("source", request.data["source"])
    return (ws.sources_dir / f"{source.data['content_hash']}.txt").read_text(), source


def test_more_items_than_the_limit_are_one_input_with_each_item_its_own_block(tmp_path):
    from engine.watch import refresh

    ws, cfg, store = make(tmp_path, board(many(7)))
    try:
        result = refresh(ws, store, cfg, "s", NOW)
        assert len(result.new) == 1 and len(inputs(store)) == 1
        text, source = text_of(ws, store, inputs(store)[0])
        for n in range(7):
            assert f'Item {n + 1} of 7 (watch: s; item: "Story {n}")' in text
            assert f"Words of story {n}." in text
        assert source.data["trust"] == "untrusted"
        # every item is still kept as a snapshot, so the next read compares with it
        assert len(store.read().find("snapshot", {"source": "s"})) == 7
        assert refresh(ws, store, cfg, "s", NOW).new == []
    finally:
        store.close()


def test_the_limit_itself_stays_one_input_each(tmp_path):
    from engine.watch import refresh

    ws, cfg, store = make(tmp_path, board(many(5)))
    try:
        assert len(refresh(ws, store, cfg, "s", NOW).new) == 5
    finally:
        store.close()


def test_the_limit_is_a_setting(tmp_path):
    from engine.watch import refresh

    ws, cfg, store = make(tmp_path, board(many(3)), burst_items=2)
    try:
        assert len(refresh(ws, store, cfg, "s", NOW).new) == 1
    finally:
        store.close()


def test_a_burst_from_a_source_with_a_project_is_filed_under_it(tmp_path):
    from engine.watch import refresh

    ws, cfg, store = make(tmp_path, board(many(6)))
    project = store.read().list("project")[0].id
    store.close()
    (ws.config_dir / "watch.yaml").write_text(
        yaml.safe_dump({"version": 1, "sources": [board(many(6), project=project)]})
    )
    from engine.storage import Store

    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    try:
        refresh(ws, store, cfg, "s", NOW)
        assert len(inputs(store)) == 1
        assert text_of(ws, store, inputs(store)[0])[1].data["projects"] == [project]
    finally:
        store.close()


def test_mail_and_calendar_items_stay_one_input_each_however_many(tmp_path):
    from engine.watch import refresh

    mail = many(8, message={"sender": "Someone <someone@example.com>", "received": "2030-03-04T08:00:00Z"})
    ws, cfg, store = make(tmp_path, board(mail), sorting="rules")
    try:
        assert len(refresh(ws, store, cfg, "s", NOW).new) == 8
    finally:
        store.close()


def test_items_a_rule_closes_are_closed_one_by_one_and_not_counted_toward_a_burst(tmp_path):
    from engine.watch import refresh

    items = many(4) + [{"key": f"c{n}", "title": f"Scratch {n}", "text": "x"} for n in range(4)]
    rule = {"name": "scratch", "kind": "terms-absent", "params": {"terms": ["story"]}}
    ws, cfg, store = make(tmp_path, board(items), triage=[rule])
    try:
        result = refresh(ws, store, cfg, "s", NOW)
        states = sorted(store.read().get("request", r).data["state"] for r in result.new)
        # four stay open, one input each (under the limit); four are closed by the rule at once
        assert states.count("queued") == 4 and states.count("done") == 4
    finally:
        store.close()


def test_a_limit_below_one_is_refused_with_the_setting_named(tmp_path):
    from engine.config import ConfigError

    with pytest.raises(ConfigError, match="burst_items"):
        make(tmp_path, board(many(1)), burst_items=0)


def test_items_the_rules_place_under_a_project_are_one_input_for_it_and_the_rest_one_for_those_nobody_placed(tmp_path):
    """The grouping itself, as `_compare` hands it items: an item placed by a rule files under that project."""
    from engine.watch import SourceItem, _Entry, _hand_in_burst

    ws, cfg, store = make(tmp_path, board([]))
    try:
        source = cfg.watch.sources[0]
        home = store.read().list("project")[0].id

        def entry(n, personal):
            item = SourceItem(f"k{n}", f"Story {n}", f"Words {n}.", author=None)
            return _Entry(item, "d", None, {}, "new", None, None, True, personal=personal)

        made = _hand_in_burst(
            ws,
            store,
            cfg,
            source,
            [entry(0, True), entry(1, True), entry(2, False)],
            NOW,
            home,
            set(),
            lambda tx, e: None,
        )
        assert len(made) == 2
        by_project = {}
        for rid in made:
            request = store.read().get("request", rid)
            by_project[request.data.get("project")] = text_of(ws, store, request)[0]
        assert "Story 0" in by_project[home] and "Story 1" in by_project[home] and "Story 2" not in by_project[home]
        assert "Story 2" in by_project[None] and "Item 1 of 1" in by_project[None]
    finally:
        store.close()


def test_a_burst_that_fails_to_file_marks_no_item_as_seen_so_the_next_read_hands_them_in(tmp_path, monkeypatch):
    import engine.watch as watch

    ws, cfg, store = make(tmp_path, board(many(7)))
    try:
        real = watch._hand_in

        def fails(*args, **kwargs):
            raise RuntimeError("the disk is full")

        monkeypatch.setattr(watch, "_hand_in", fails)
        with pytest.raises(RuntimeError):
            watch.refresh(ws, store, cfg, "s", NOW)
        assert store.read().find("snapshot", {"source": "s"}) == []
        monkeypatch.setattr(watch, "_hand_in", real)
        assert len(watch.refresh(ws, store, cfg, "s", NOW).new) == 1
    finally:
        store.close()
