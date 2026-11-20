"""The People step on a real-sized year of mail (H5-36): a mailbox where shops and notices write far more than any
person, a service that slows the first headers down, and a look that offers no one. The look waits until it has
headers to count, shows the people the person writes with however many busier senders stand, runs again as the year
comes in, and the step never says "looked" for a look that did not run or that still has mail coming. The year is
`tests/people_year.py`; the AI is the stub."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from engine import mail_headers, person_look, reading_lane
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.config import load_config
from engine.connectors import ConnectorError
from engine.dispatcher import process
from engine.storage import Store
from engine.watch import refresh
from tests import people_year
from tests.test_first_headers import NOW, WITH_HEADERS
from tests.test_look_back_addons import _manifest
from tests.test_today_panels_jobs import workspace

# The fixture's connector also passes on the service's bulk mark.
YEAR = WITH_HEADERS.replace(
    'participants=tuple(m.get("participants", ()))),',
    'participants=tuple(m.get("participants", ())), bulk=m.get("bulk")),',
)
assert "bulk=m.get" in YEAR
PEOPLE = [address for _name, address, _came, _sent in people_year.PEOPLE]
NOBODY = json.dumps({"summary": "Nothing plain enough to suggest.", "ops": []})


@pytest.fixture
def year(tmp_path, monkeypatch):
    """A workspace signed in to an inbox and its sent mail, with the year behind them, not read yet."""
    monkeypatch.setattr("engine.ai.smoke.ai_state", lambda ws, cfg, store: ("ok", None))
    ws, cfg, store = workspace(tmp_path, YEAR)
    store.close()
    (ws.root / "plugins" / "p18" / "plugin.yaml").write_text(yaml.safe_dump(_manifest()))
    inbox = {
        "id": "m",
        "connector": "p18/inbox",
        "label": "Inbox",
        "settings": {"items": people_year.recent(NOW), "headers": people_year.inbox_headers(NOW)},
    }
    sent = {
        "id": "s",
        "connector": "p18/inbox",
        "label": "Sent",
        "author": cfg.workspace.user.person,
        "settings": {"items": [], "headers": people_year.sent_headers(NOW, "Me <me@example.com>")},
    }
    (ws.config_dir / "watch.yaml").write_text(
        yaml.safe_dump({"version": 1, "sources": [inbox, sent], "sorting": "rules"})
    )
    cfg = load_config(ws.config_dir, env={})
    cfg.ai.budgets.first_go = False
    cfg.ai.budgets.confirm_above_usd = 100
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    set_responder(None)
    store.close()


def slow_the_first(monkeypatch, calls: int, seconds: int = 60) -> None:
    """The service refuses the first `calls` requests for headers and asks to wait."""
    real = mail_headers.asker
    made = {"n": 0}

    def asker(store, source):
        inner = real(store, source)

        def ask(*args):
            made["n"] += 1
            if made["n"] <= calls:
                raise ConnectorError("throttled", "HTTP 429", retry_after=seconds)
            return inner(*args)

        return ask

    monkeypatch.setattr(mail_headers, "asker", asker)


def sign_in(ws, cfg, store, at: datetime = NOW) -> None:
    for source in ("m", "s"):
        refresh(ws, store, cfg, source, at)


def shown(store, cfg) -> list[str]:
    return [line.split(" | ")[0] for line in person_look.tally_lines(store, cfg)]


def run_look(ws, cfg, store, at: datetime, answer: str) -> str:
    request = person_look.queue(store, cfg, at, ws)
    assert request is not None
    set_responder(lambda task: answer)
    process(ws, store, cfg, Router(cfg, store, env={}), request, now=at)
    return request


def sweep(ws, cfg, store, at: datetime, to_the_end: bool = False) -> None:
    for _ in range(60):
        _read, more = reading_lane.run_slices(ws, store, cfg, at)
        if not (to_the_end and more):
            return
    raise AssertionError("the rest of the headers never finished")


def test_a_look_waits_for_headers_the_service_slowed_down_and_people_says_until_when(year, monkeypatch):
    ws, cfg, store = year
    slow_the_first(monkeypatch, 2)
    sign_in(ws, cfg, store)
    # The first reads are in, with a dozen messages of the last days: no sender twice, and none of the year's headers.
    assert store.read().list("mail_header") == [] and person_look.first_reads_in(store, cfg, NOW, ws)
    assert not person_look.due(store, cfg, NOW, ws), "a look on almost nothing is not started"
    assert person_look.look_state(ws, store, cfg, NOW) == "not_yet", "and it is never called looked"
    assert person_look.waiting_until(ws, store, cfg, NOW) == NOW + timedelta(seconds=60)
    sweep(ws, cfg, store, NOW + timedelta(seconds=61))
    assert store.read().list("mail_header"), "the headers came once the service's wait ran out"
    assert person_look.due(store, cfg, NOW + timedelta(seconds=61), ws)


def test_the_people_the_person_writes_to_are_shown_however_many_busier_senders_stand(year):
    ws, cfg, store = year
    sign_in(ws, cfg, store)
    sweep(ws, cfg, store, NOW, to_the_end=True)
    standing = [c for c in person_look.contact_tally.tally(store, cfg) if c.total >= 2 and c.apart is None]
    limit = cfg.dispatch.knowledge.person_look_entries
    by_count = [c.address for c in standing[:limit]]  # the tally's own order: the most messages first
    assert len(standing) > limit and not set(PEOPLE) <= set(by_count), "by count alone, people fall off the end"
    lines = shown(store, cfg)
    assert len(lines) == limit and lines[: len(PEOPLE)] == PEOPLE, "those the person writes to come first"


def test_a_sender_only_the_years_headers_show_carries_the_services_bulk_mark(year):
    ws, cfg, store = year
    sign_in(ws, cfg, store)
    _name, address, _count = people_year.SMALL_MACHINES[-1]
    assert not any(s.data["message"]["sender"].endswith(f"<{address}>") for s in store.read().list("snapshot"))
    line = next(line for line in person_look.tally_lines(store, cfg) if line.startswith(address))
    assert "marked bulk mail" in line


def test_while_the_year_is_still_coming_in_a_look_that_offered_no_one_is_not_the_last_word(year, monkeypatch):
    ws, cfg, store = year
    slow_the_first(monkeypatch, 2)
    sign_in(ws, cfg, store)
    # The store stamps the end of a source's headers with its own clock, so the rest of the path runs from the present.
    at = datetime.now(UTC) + timedelta(minutes=1)
    sweep(ws, cfg, store, at)  # one page for each source; the rest is still to read
    assert person_look.more_mail_coming(store, cfg)
    first = run_look(ws, cfg, store, at, NOBODY)
    assert store.read().get("request", first).data["state"] == "done"
    assert person_look.look_state(ws, store, cfg, at) == "reading_more", "not looked: the year is still coming in"
    assert not person_look.due(store, cfg, at + timedelta(minutes=1), ws), "nothing new came in: no second look yet"
    later = at + timedelta(minutes=5)
    sweep(ws, cfg, store, later)  # another page
    assert person_look.due(store, cfg, later + timedelta(seconds=1), ws), (
        "more headers, nobody offered yet: it looks again"
    )
    offer = {"address": PEOPLE[0], "name": people_year.PEOPLE[0][0], "why": "Writes to you and you reply."}
    run_look(
        ws,
        cfg,
        store,
        later + timedelta(seconds=1),
        json.dumps({"summary": "x", "ops": [{"op": "person.offer", "people": [offer]}]}),
    )
    assert [o.data["address"] for o in person_look.waiting_offers(store)] == [PEOPLE[0]]
    after = later + timedelta(minutes=5)
    sweep(ws, cfg, store, after)
    assert person_look.more_mail_coming(store, cfg)
    assert not person_look.due(store, cfg, after + timedelta(seconds=1), ws), (
        "once someone is offered, the next look waits for the year to end: a page is no longer a reason to spend"
    )


def test_looked_is_said_only_of_a_look_that_ran_on_all_there_is(year):
    ws, cfg, store = year
    cfg.watch.first_headers_days = 0  # no year behind the first read: a dozen senders, each seen once
    sign_in(ws, cfg, store)
    assert not person_look.due(store, cfg, NOW, ws)
    assert person_look.look_state(ws, store, cfg, NOW) == "too_little"
    request = person_look._create(store, cfg, NOW)  # a look queued all the same closes with no call
    set_responder(lambda task: pytest.fail("a look with nothing to look at never calls the assistant"))
    process(ws, store, cfg, Router(cfg, store, env={}), request, now=NOW)
    closed = store.read().get("request", request).data
    assert (closed["state"], closed["waiting"]) == ("done", person_look.NOTHING_TO_LOOK_AT)
    assert person_look.look_state(ws, store, cfg, NOW) == "too_little", "a look closed with no call is not a look"


def test_a_look_that_ran_on_the_whole_year_and_offered_no_one_says_looked(year):
    ws, cfg, store = year
    sign_in(ws, cfg, store)
    sweep(ws, cfg, store, NOW, to_the_end=True)
    assert not person_look.more_mail_coming(store, cfg)
    run_look(ws, cfg, store, NOW, NOBODY)
    assert person_look.look_state(ws, store, cfg, NOW) == "looked"


# ---- a real model's answers ------------------------------------------------------------------------------------------

#: What a low-cost real model answered, word for word, to the look's packet at three points of the year coming in: with
#: the sample read, with one page read after the service refused the sample, and with the whole year read. Answers 1
#: to 3 were made on the packet as it was before this file's fixes, 4 to 6 on a later one.
ANSWERS = Path(__file__).parent / "fixtures" / "people_look"
SAMPLE, FIRST_PAGE, WHOLE_YEAR = "sample", "first page", "whole year"
REAL = [(1, SAMPLE), (2, FIRST_PAGE), (3, WHOLE_YEAR), (4, SAMPLE), (5, FIRST_PAGE), (6, WHOLE_YEAR)]


def answer(n: int) -> str:
    return (ANSWERS / f"answer-{n}.json").read_text()


@pytest.mark.parametrize("n", [n for n, _ in REAL])
def test_an_answer_that_is_one_op_by_itself_is_read_as_that_op_never_as_nothing(n):
    """Every answer the model gave was a lone op, with no "ops" list around it. Read as an answer that holds
    nothing, it left the People step saying the assistant looked and found no one."""
    from engine.dispatcher import parse

    text = answer(n)
    assert "ops" not in json.loads(text), "the model's own shape: one op, no list"
    read = parse(text)
    assert [op.op for op in read.ops] == ["person.offer"]
    assert [p.address for p in read.ops[0].people] == [p["address"] for p in json.loads(text)["people"]]


@pytest.mark.parametrize(("n", "point"), REAL)
def test_a_real_models_answer_becomes_the_offers_the_people_step_shows(year, monkeypatch, n, point):
    from fastapi.testclient import TestClient

    from api.app import create_app

    ws, cfg, store = year
    at = datetime.now(UTC) + timedelta(minutes=1)
    if point == FIRST_PAGE:
        slow_the_first(monkeypatch, 2)
    sign_in(ws, cfg, store)
    if point != SAMPLE:
        sweep(ws, cfg, store, at, to_the_end=point == WHOLE_YEAR)
    offered = [p["address"] for p in json.loads(answer(n))["people"]]
    assert set(offered) <= set(PEOPLE) and len(offered) >= 3, "the model offered people, and no shop or notice"
    request = run_look(ws, cfg, store, at, answer(n))
    assert store.read().get("request", request).data["state"] == "done"
    waiting = person_look.waiting_offers(store)
    assert {o.data["address"] for o in waiting} == set(offered), "every person the model offered waits for the person"
    assert all(o.data["why"] and o.data["from_them"] + o.data["to_them"] >= 2 for o in waiting)
    shown_first = [o.data["address"] for o in waiting]
    store.close()
    app = create_app(ws, cfg, "people-year-token", ui_dist=ws.root / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": "Bearer people-year-token"}) as client:
        body = client.get("/api/setup/people-suggestions").json()
    assert body["people"], "the step shows offers, not an empty look"
    assert [p["address"] for p in body["people"]] == shown_first[: len(body["people"])]
    assert {p["name"] for p in body["people"]} <= {name for name, *_ in people_year.PEOPLE}
