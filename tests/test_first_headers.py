"""A first sign-in reads a year of headers with no AI cost (S-0585 item 1, plugin API 0.3.100): once, after a mail
source's first read, a connector that can list headers alone is asked for them from `watch.first_headers_days` back to
the day that read began (at most `watch.first_headers_max_items`), and each is kept as a `mail_header` the contact
tally reads. A header is never an input, a request or anything sorted; the first look's packet gains counts from them
(deleted unopened, where messages ended up, what recurs); a failure is told once and not retried. Names and days come
from the fixtures; the AI is the stub."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from engine import contact_tally, person_look, source_intake
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.config import load_config
from engine.config.schema import Price
from engine.dispatcher import process
from engine.packet import build
from engine.plugin_api import RegistrationRefused
from engine.stages import approve_stage_request
from engine.storage import Store
from engine.watch import refresh
from tests.test_look_back_addons import FIXTURE, _manifest
from tests.test_people_suggestions import who
from tests.test_source_intake import mail
from tests.test_today_panels_jobs import workspace

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)

# The fixture's connector also lists headers: the entries of its `headers` setting, with no text.
WITH_HEADERS = (
    FIXTURE.replace(
        '    log: str = ""',
        '    headers: list[dict] = Field(default_factory=list)\n    fail: str = ""\n    log: str = ""',
    )
    .replace(
        "def register(registrar):",
        """def headers(settings, since, before, limit, context):
    note(settings, "headers", limit, [since.isoformat(), before.isoformat()])
    if settings.fail:
        from engine.plugin_api import ConnectorError
        raise ConnectorError(settings.fail, "the sign-in was withdrawn")
    found = [e for e in settings.headers if since <= date.fromisoformat(e["message"]["received"][:10]) < before]
    return [build({**e, "text": ""}) for e in found][-limit:]

def register(registrar):""",
    )
    .replace(
        'older=older, older_count=older_count)\n    registrar.connector("p18/uncounted"',
        'older=older, older_count=older_count, headers=headers)\n    registrar.connector("p18/uncounted"',
    )
    .replace(
        'message=MessageDetails(sender=m.get("sender"), received=m.get("received"), unread=True),',
        'message=MessageDetails(sender=m.get("sender"), received=m.get("received"), unread=m.get("unread", True), '
        'where=m.get("where"), participants=tuple(m.get("participants", ()))),',
    )
)
assert WITH_HEADERS.count("headers=headers") == 1 and "participants=tuple" in WITH_HEADERS


def header(key: str, sender: str, days: float, *, subject: str, where: str = "deleted", unread: bool = True) -> dict:
    entry = mail(key, days, subject=subject, now=NOW)
    entry["message"] = {**entry["message"], "sender": sender, "where": where, "unread": unread}
    return entry


def year_of_headers() -> list[dict]:
    """Weekly shipping notices from one sender, always deleted unopened; a colleague's mail kept in the inbox, with
    some archived; and one message that is also in the first read."""
    found = [header(f"s{i}", who(2), 21 + 7 * i, subject=f"Shipping notice {100 + i}") for i in range(8)]
    found += [header(f"c{i}", who(3), 40 + 11 * i, subject=f"Plan {i}", where="inbox", unread=False) for i in range(4)]
    found += [
        header(f"k{i}", who(3), 45 + 11 * i, subject=f"Notes {i}", where="archived", unread=False) for i in range(2)
    ]
    found.append(header("m1", who(0), 2, subject="Also in the first read"))
    return found


def make(tmp_path, *, connector="p18/inbox", headers=None, **settings):
    ws, cfg, store = workspace(tmp_path, WITH_HEADERS)
    store.close()
    (ws.root / "plugins" / "p18" / "plugin.yaml").write_text(yaml.safe_dump(_manifest()))
    log = tmp_path / "calls.log"
    entry = {
        "id": "m",
        "connector": connector,
        "label": "Inbox",
        "settings": {
            "items": [
                {**mail(f"m{d}", d, now=NOW), "message": {**mail("x", d, now=NOW)["message"], "sender": who(d % 2)}}
                for d in (1, 2, 3)
            ],
            "headers": year_of_headers() if headers is None else headers,
            "log": str(log),
            **settings,
        },
    }
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump({"version": 1, "sources": [entry], "sorting": "rules"}))
    cfg = load_config(ws.config_dir, env={})
    use = cfg.ai.tiers["routine"].use
    cfg.ai.prices[use] = Price(input_per_million=50.0, output_per_million=50.0)
    cfg.ai.budgets.confirm_above_usd = 0.10
    cfg.ai.budgets.first_go = False
    store = Store(ws.db_path, cfg=cfg)
    assert store.plugins.active("p18"), store.plugins.status["p18"].reason
    return ws, cfg, store, log


def calls(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def env(tmp_path):
    ws, cfg, store, log = make(tmp_path)
    yield ws, cfg, store, log
    store.close()
    set_responder(None)


def kept(store):
    return store.read().list("mail_header")


def test_a_first_read_is_followed_by_the_headers_of_a_year_with_no_ai_request(env):
    ws, cfg, store, log = env
    asked = []
    set_responder(lambda task: asked.append(task.kind) or "{}")
    refresh(ws, store, cfg, "m", NOW)
    assert asked == []
    keys = {h.data["key"] for h in kept(store)}
    assert keys == {e["key"] for e in year_of_headers()} - {"m1"}  # the one the first read also holds stands as itself
    assert all(h.data["source"] == "m" and h.data["message"]["where"] for h in kept(store))
    assert [c[0] for c in calls(log)] == ["headers"]


def test_the_headers_are_asked_from_the_setting_back_to_the_day_the_read_began_and_no_more_than_the_cap(tmp_path):
    ws, cfg, store, log = make(tmp_path)
    try:
        cfg.watch.first_headers_days = 100
        cfg.watch.first_headers_max_items = 7
        refresh(ws, store, cfg, "m", NOW)
        (asked,) = calls(log)
        back_to = source_intake.back_to_of(store.read(), "m")
        assert asked[1] == 7 and asked[2] == [(back_to - timedelta(days=100)).isoformat(), back_to.isoformat()]
        assert len(kept(store)) <= 7
    finally:
        store.close()


def test_nothing_is_asked_when_the_setting_is_zero_or_the_connector_cannot_list_headers(tmp_path):
    ws, cfg, store, log = make(tmp_path)
    try:
        cfg.watch.first_headers_days = 0
        refresh(ws, store, cfg, "m", NOW)
        assert calls(log) == [] and kept(store) == []
    finally:
        store.close()
    ws, cfg, store, log = make(tmp_path / "plain", connector="p18/plain")
    try:
        result = refresh(ws, store, cfg, "m", NOW)
        assert result.outcome == "baseline" and calls(log) == [] and kept(store) == []
    finally:
        store.close()


def test_a_header_is_never_an_input_a_request_or_a_snapshot_and_only_the_first_read_asks(env):
    ws, cfg, store, log = env
    refresh(ws, store, cfg, "m", NOW)
    view = store.read()
    header_keys = {h.data["key"] for h in kept(store)}
    assert header_keys and not header_keys & {s.data["key"] for s in view.list("snapshot")}
    assert not header_keys & {(s.data.get("watched") or {}).get("key") for s in view.list("source")}
    assert len(view.list("request")) == 3  # the first read's own three messages
    refresh(ws, store, cfg, "m", NOW + timedelta(hours=1))
    assert len(calls(log)) == 1 and len(kept(store)) == len(header_keys)


def test_the_tally_reads_the_headers_and_counts_a_message_once_when_a_snapshot_stands_for_it(env):
    ws, cfg, store, _ = env
    refresh(ws, store, cfg, "m", NOW)
    found = {c.address: c for c in contact_tally.tally(store, cfg)}
    assert found["c2@example.com"].from_them == 8 and found["c3@example.com"].from_them == 6
    assert found["c0@example.com"].from_them + found["c1@example.com"].from_them == 3  # the first read's messages only


def test_a_headers_error_is_never_recorded_as_the_sources_read_and_a_sign_in_error_is_not_retried(tmp_path):
    ws, cfg, store, log = make(tmp_path, fail="auth")
    try:
        result = refresh(ws, store, cfg, "m", NOW)
        assert result.outcome == "baseline" and kept(store) == []
        runs = store.read().find("watch_run", {"source": "m"})
        assert [r.data["outcome"] for r in runs] == ["baseline"], "the headers' failure is not a read of the source"
        assert len(store.read().list("request")) == 3  # the first read still took its mail in
        refresh(ws, store, cfg, "m", NOW + timedelta(hours=1))
        assert len(calls(log)) == 1
    finally:
        store.close()


def test_a_connector_cannot_register_headers_that_are_not_a_function():
    from engine.plugin_api import Registrar

    registrar = Registrar.__new__(Registrar)
    registrar.connectors = {}
    registrar._name = lambda name: None
    with pytest.raises(RegistrationRefused):
        registrar.connector("p/x", label="X", settings=object, poll=lambda *a: None, headers="no")


def test_the_first_look_packet_gets_counts_from_the_headers_inside_outside_content_and_the_go_starts_one_run(env):
    ws, cfg, store, _ = env
    asked = []
    set_responder(lambda task: asked.append(task.kind) or json.dumps({"ops": []}))
    refresh(ws, store, cfg, "m", NOW)
    request = person_look.queue(store, cfg, NOW)
    assert request is not None
    process(ws, store, cfg, Router(cfg, store, env={}), request, now=NOW)
    assert person_look.held_for_go(store).id == request and asked == [] and not store.read().has("run")
    packet = build(ws, store, cfg, request, NOW.date())
    text = packet.task.request
    block = text.split(f'<untrusted source="{person_look.HABITS_BLOCK}">')[1].split("</untrusted>")[0]
    assert "deleted unopened | c2@example.com" in block and "8 of 8 messages" in block
    assert "where they ended up | c3@example.com" in block and "archived 2, inbox 4" in block
    assert 'recurs | c2@example.com | "Shipping notice 100"' in block and "about every 7 days" in block
    assert "Words about" not in text  # counts and subjects only, never message text
    approve_stage_request(store, request, store.read().get("request", request).version)
    process(ws, store, cfg, Router(cfg, store, env={}), request, now=NOW)
    assert len(store.read().list("run")) == 1 and set(asked) <= {"knowledge-person"}
    assert len(store.read().list("request")) == 4  # the first read's three and the one look
