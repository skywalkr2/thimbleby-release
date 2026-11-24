"""A source that serves an older copy is never news (S-0685): the newest copy seen is kept, an older one is never
compared, stored or filed, and the screen says so."""

from __future__ import annotations

from datetime import timedelta

import yaml

from engine.config import load_config
from engine.storage import Store
from engine.watch import refresh
from tests.test_watch import NOW, make

V3 = [{"key": "a", "title": "Plan", "text": "Version three\nLunch at noon."}]
V2 = [{"key": "a", "title": "Plan", "text": "Version two\nLunch at one."}]


def read_as(ws, store, items, made, at):
    store.close()
    current = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
    current["sources"] = [
        {
            "id": "s",
            "connector": "fake",
            "label": "Board",
            "first_run": "all",
            "settings": {"items": items, "generated_at": made.isoformat()},
        }
    ]
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump(current))
    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    return store, refresh(ws, store, cfg, "s", at), cfg


def test_v3_then_v2_then_v3_files_one_change_and_says_the_older_copy_was_not_compared(tmp_path):
    ws, cfg, store = make(tmp_path, [])
    try:
        t3, t2 = NOW - timedelta(hours=1), NOW - timedelta(hours=5)
        store, first, cfg = read_as(ws, store, V3, t3, NOW)
        store, older, cfg = read_as(ws, store, V2, t2, NOW + timedelta(hours=1))
        store, again, cfg = read_as(ws, store, V3, t3, NOW + timedelta(hours=2))
        assert len(first.new) == 1
        assert (older.new, older.changed, older.removed) == ([], [], [])
        assert older.note == "The source served an older copy; nothing compared."
        assert (again.new, again.changed, again.removed) == ([], [], [])
        assert len(store.read().list("request")) == 1
        runs = store.read().find("watch_run", {"source": "s"})
        assert [bool(r.data.get("older_copy")) for r in runs] == [False, True, False]
    finally:
        store.close()


def _reader(ws, store):
    """A read of one item of a source that says no time of its own, as a folder's files are read."""
    holder = {"store": store}

    def read(items, at):
        holder["store"].close()
        current = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
        current["sources"] = [
            {"id": "s", "connector": "fake", "label": "Board", "first_run": "all", "settings": {"items": items}}
        ]
        (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump(current))
        fresh = load_config(ws.config_dir, env={})
        holder["store"] = Store(ws.db_path, cfg=fresh)
        return refresh(ws, holder["store"], fresh, "s", at)

    return read, holder


def test_an_item_with_an_earlier_time_than_its_saved_copy_is_filed_with_a_hint_that_it_may_be_older(tmp_path):
    """S-0774: a folder's file put back from a backup has an older file time; the change is filed, never dropped."""
    from engine.packet import build

    ws, cfg, store = make(tmp_path, [])
    read, holder = _reader(ws, store)
    try:
        t3, t2 = (NOW - timedelta(hours=1)).isoformat(), (NOW - timedelta(hours=5)).isoformat()
        plan = {"key": "a", "title": "Plan"}
        assert len(read([{**plan, "text": "Version three", "changed_at": t3}], NOW).new) == 1
        back = read([{**plan, "text": "Version two", "changed_at": t2}], NOW + timedelta(hours=1))
        assert len(back.changed) == 1  # filed whatever its time
        request = holder["store"].read().get("request", back.changed[0])
        assert request.data["older_item"] is True
        cfg = load_config(ws.config_dir, env={})
        packet = build(ws, holder["store"], cfg, request.id, NOW.date())
        assert "may be an older copy" in packet.task.request
        newer = (NOW + timedelta(hours=1)).isoformat()
        edited = read([{**plan, "text": "Version four", "changed_at": newer}], NOW + timedelta(hours=2))
        assert len(edited.changed) == 1
        assert not holder["store"].read().get("request", edited.changed[0]).data.get("older_item")
    finally:
        holder["store"].close()


def test_content_matching_a_version_seen_before_is_not_filed_and_what_changed_says_it_came_back(tmp_path):
    """S-0774: a restored or re-synced older copy isn't news; it is shown, closed by a rule, never read again."""
    ws, cfg, store = make(tmp_path, [])
    read, holder = _reader(ws, store)
    try:
        plan = {"key": "a", "title": "Plan"}
        t = lambda h: (NOW + timedelta(hours=h)).isoformat()  # noqa: E731
        read([{**plan, "text": "Version two", "changed_at": t(0)}], NOW)
        changed = read([{**plan, "text": "Version three", "changed_at": t(1)}], NOW + timedelta(hours=1))
        assert len(changed.changed) == 1
        back = read([{**plan, "text": "Version two", "changed_at": t(2)}], NOW + timedelta(hours=2))
        (request,) = [holder["store"].read().get("request", r).data for r in back.changed]
        assert request["auto_closed"]["rule"] == "Older version came back"
        assert request["auto_closed"]["reason"].startswith("An older version came back")
        again = read([{**plan, "text": "Version four", "changed_at": t(3)}], NOW + timedelta(hours=3))
        assert len(again.changed) == 1  # genuinely new content is filed
    finally:
        holder["store"].close()


def test_data_older_than_the_sources_refresh_is_never_filed_as_news_and_the_fresh_read_files_it_once(tmp_path):
    """S-0723: old data read after a good read files nothing, keeps the earlier state and says its data is old."""
    ws, cfg, store = make(tmp_path, [])
    try:
        fresh = NOW - timedelta(hours=1)
        store, first, cfg = read_as(ws, store, V3, fresh, NOW)
        stale = NOW + timedelta(days=30)
        added = [*V3, {"key": "n", "title": "New", "text": "Brand new"}]
        store, old, cfg = read_as(ws, store, added, fresh, stale)
        assert (old.new, old.changed, old.removed) == ([], [], [])
        last = store.read().find("watch_run", {"source": "s"})[-1].data
        assert last["old_data"] is True and last["outcome"] == "ok"
        from engine import watch

        # said where the person looks (Today's line and the source's status), never only in a log
        assert watch.old_data(store, cfg, cfg.watch.sources[0], stale) is not None
        store, later, cfg = read_as(ws, store, added, stale - timedelta(hours=1), stale + timedelta(hours=1))
        assert len(later.new) == 1  # what the old read missed, filed once, when the data is fresh
        assert len(first.new) == 1
    finally:
        store.close()
