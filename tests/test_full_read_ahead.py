"""The full-read question ahead of a source's first read (design 6.32): it is open from the moment the source exists, so
an account's choice never waits for a read; an answer given then is kept, nothing is read or asked of the service, and
it takes effect when the first read lands. Names and days come from the fixtures of the first sign-in's tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import source_intake
from engine.storage import StoreError
from engine.watch import refresh
from tests.test_first_sign_in import NOW, TOKEN, make


@pytest.fixture
def env(tmp_path):
    ws, cfg, store = make(tmp_path)
    yield ws, cfg, store
    store.close()


def _intake_lines(ws, cfg, store):
    from engine.today_queue import queue

    return [x for x in queue(ws, store, cfg, NOW) if x.kind == "intake_go"]


def _requests(store) -> int:
    return len(store.read().list("request"))


def test_the_question_is_open_before_the_first_read_and_its_reaches_ask_the_service_nothing(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    assert source_intake.full_read_ahead(ws, store, cfg, source)
    assert not source_intake.full_read_pending(store, cfg, source)  # that one speaks once a read has landed
    options = source_intake.full_read_options(ws, store, cfg, source.id, NOW)
    assert [o.days for o in options] == list(cfg.watch.full_read_choices)
    assert all(o.unknown and o.count == 0 and o.estimate_usd is None for o in options)
    assert store.read().find("watch_run", {"source": source.id}) == []  # looking read nothing


def test_an_answer_given_before_the_first_read_is_kept_and_applied_when_it_lands(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    reach = cfg.watch.full_read_choices[1]
    said = source_intake.answer_full_read(ws, store, cfg, source.id, reach, NOW)
    assert said is not None and said.stopped == "first_look" and said.taken == 0
    # Nothing was read, recorded or spent, and the question is not asked again.
    assert store.read().find("watch_run", {"source": source.id}) == [] and _requests(store) == 0
    assert source_intake.answers_ahead(ws) == {source.id: reach}
    assert not source_intake.full_read_ahead(ws, store, cfg, source)

    refresh(ws, store, cfg, source.id, NOW)
    run = source_intake.intake_run(store.read(), source.id)
    assert run.data["full_read"] == reach
    queued = run.data["older_read"]
    assert queued["kind"] == "queued" and queued["reach"] == reach  # the lane reads it, with no further press
    assert not source_intake.full_read_pending(store, cfg, source)
    assert source_intake.answers_ahead(ws) == {}  # recorded with the read, so nothing is kept any more


def test_not_now_before_the_first_read_ends_the_question_and_reads_no_older_mail(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    assert source_intake.answer_full_read(ws, store, cfg, source.id, 0, NOW) is None
    assert not source_intake.full_read_ahead(ws, store, cfg, source)
    refresh(ws, store, cfg, source.id, NOW)
    run = source_intake.intake_run(store.read(), source.id)
    assert run.data["full_read"] == 0 and not run.data.get("older_read")
    assert not source_intake.full_read_pending(store, cfg, source)


def test_a_reach_that_is_not_offered_is_refused_before_the_first_read_and_nothing_is_kept(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    wrong = max(cfg.watch.full_read_choices) + 1
    with pytest.raises(StoreError):
        source_intake.answer_full_read(ws, store, cfg, source.id, wrong, NOW)
    assert source_intake.answers_ahead(ws) == {}
    assert source_intake.full_read_ahead(ws, store, cfg, source)


def test_one_sources_answer_ahead_leaves_another_accounts_question_alone(env):
    ws, cfg, store = env
    first, second = cfg.watch.sources[0], cfg.watch.sources[1]
    source_intake.answer_full_read(ws, store, cfg, first.id, cfg.watch.full_read_choices[1], NOW)
    assert source_intake.full_read_ahead(ws, store, cfg, second)
    refresh(ws, store, cfg, second.id, NOW)
    assert source_intake.answers_ahead(ws) == {first.id: cfg.watch.full_read_choices[1]}  # still waiting for its read


def test_a_source_of_the_account_that_appears_after_the_answer_is_not_asked_again_and_takes_it(env):
    ws, cfg, store = env
    first, second = cfg.watch.sources[0], cfg.watch.sources[1]
    first.account = second.account = "one-account"
    reach = cfg.watch.full_read_choices[1]
    # The account was answered through its first source, before any read; its other source has no answer of its own.
    source_intake.answer_full_read(ws, store, cfg, first.id, reach, NOW)
    assert not source_intake.full_read_ahead(ws, store, cfg, second)  # asked once per account
    refresh(ws, store, cfg, second.id, NOW)
    assert source_intake.intake_run(store.read(), second.id).data["full_read"] == reach
    assert not source_intake.full_read_pending(store, cfg, second)
    assert _intake_lines(ws, cfg, store) == []  # the account's one answer was its go too


def test_a_source_that_is_off_or_takes_nothing_in_on_its_first_read_is_never_asked_ahead(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    source.enabled = False
    assert not source_intake.full_read_ahead(ws, store, cfg, source)
    source.enabled, source.first_run = True, "baseline"
    assert not source_intake.full_read_ahead(ws, store, cfg, source)
    source.first_run = "intake"
    cfg.watch.full_read_choices = []
    assert not source_intake.full_read_ahead(ws, store, cfg, source)


def test_the_routes_keep_an_answer_given_ahead_and_show_it_until_the_read_lands(tmp_path):
    ws, cfg, store = make(tmp_path)
    store.close()
    from api.app import create_app

    reach = cfg.watch.full_read_choices[1]
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        first = lambda: client.get("/api/watch").json()[0]  # noqa: E731
        assert first()["full_read_open"] and first()["full_read_chosen"] is None
        said = client.post(f"/api/watch/{first()['id']}/full-read", json={"days": reach})
        assert said.status_code == 200 and said.json()["stopped"] == "first_look" and said.json()["taken"] == 0
        assert not first()["full_read_open"] and first()["full_read_chosen"] == reach
        assert first()["older_read"] is None  # nothing is being read yet
        assert client.post(f"/api/watch/{first()['id']}/read").status_code == 200
        after = first()
        assert not after["full_read_open"] and after["full_read_chosen"] is None
        assert after["older_read"]["kind"] == "queued"
        assert client.get(f"/api/watch/{after['id']}/full-read").json()["answered"] == reach


# ---- the choice is also the go for the source's first window ---------------------------------------------------------


def test_a_reach_shows_one_cost_for_the_first_window_and_the_older_mail_together(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    refresh(ws, store, cfg, source.id, NOW)
    window = source_intake.waiting_cost(ws, store, cfg, source.id)
    assert window.count and window.likely and window.at_most
    covered, month, _ = source_intake.full_read_options(ws, store, cfg, source.id, NOW)
    older = source_intake.look_back_preview(
        ws,
        store,
        cfg,
        source.id,
        source_intake._days_beyond_first_read(store, source.id, month.days, NOW),
        NOW,
        exact=True,
    )
    assert older.estimate_usd and month.count == older.count
    assert month.estimate_usd == pytest.approx(older.estimate_usd + window.likely, abs=1e-3)
    assert month.estimate_max_usd == pytest.approx(
        (older.estimate_max_usd or older.estimate_usd) + window.at_most, abs=1e-3
    )
    assert covered.count == 0 and covered.estimate_usd is None  # no number, so no cost is shown for it


def test_choosing_a_reach_is_the_go_for_the_first_window_and_for_what_the_older_read_brings(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    refresh(ws, store, cfg, source.id, NOW)
    (line,) = _intake_lines(ws, cfg, store)
    held = line.count
    assert held == len(source_intake.waiting(store.read(), source.id)) > 0
    reach = cfg.watch.full_read_choices[1]
    source_intake.answer_full_read(ws, store, cfg, source.id, reach, NOW)
    # One step: nothing of the first window waits for a second ask, and no run was made to say so.
    assert _intake_lines(ws, cfg, store) == [] and source_intake.waiting(store.read(), source.id) == []
    started = [r for r in store.read().list("request") if r.data.get("intake") == source.id]
    assert len(started) == held and all(
        r.data["state"] == "queued" and r.data["approval"] == "granted" for r in started
    )
    assert not store.read().has("run")
    # The older mail the reach brings starts under the same go, slice after slice.
    assert source_intake.intake_run(store.read(), source.id).data["older_read"]["go"] is True
    done = source_intake.continue_older_read(ws, store, cfg, source.id, NOW)
    assert done is not None and done.taken > 0 and done.started
    assert _intake_lines(ws, cfg, store) == [] and source_intake.waiting(store.read(), source.id) == []
    brought = [r for r in store.read().list("request") if r.data.get("intake") == source.id]
    assert len(brought) == held + done.taken and all(r.data["approval"] == "granted" for r in brought)


def test_not_now_gives_no_go_so_the_first_window_keeps_its_own_ask_on_today(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    refresh(ws, store, cfg, source.id, NOW)
    held = _intake_lines(ws, cfg, store)[0].count
    assert source_intake.answer_full_read(ws, store, cfg, source.id, 0, NOW) is None
    assert _intake_lines(ws, cfg, store)[0].count == held


def test_a_reach_the_first_read_already_covers_is_still_the_go_for_its_window(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    refresh(ws, store, cfg, source.id, NOW)
    assert source_intake.answer_full_read(ws, store, cfg, source.id, cfg.watch.full_read_choices[0], NOW) is None
    assert _intake_lines(ws, cfg, store) == [] and not store.read().has("run")


def test_a_reach_chosen_before_the_first_read_is_the_go_once_the_read_lands_with_no_second_ask(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    source_intake.answer_full_read(ws, store, cfg, source.id, cfg.watch.full_read_choices[1], NOW)
    refresh(ws, store, cfg, source.id, NOW)
    run = source_intake.intake_run(store.read(), source.id)
    assert run.data["older_read"]["kind"] == "queued" and run.data["older_read"]["go"] is True
    assert _intake_lines(ws, cfg, store) == [] and source_intake.waiting(store.read(), source.id) == []
    taken = [r for r in store.read().list("request") if r.data.get("intake") == source.id]
    assert taken and all(r.data["state"] == "queued" and r.data["approval"] == "granted" for r in taken)
    assert not store.read().has("run")  # recorded and queued: the worker does the work


def test_not_now_chosen_before_the_first_read_gives_no_go_when_it_lands(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    source_intake.answer_full_read(ws, store, cfg, source.id, 0, NOW)
    refresh(ws, store, cfg, source.id, NOW)
    assert _intake_lines(ws, cfg, store)[0].count > 0


def test_a_go_that_clashes_with_another_write_is_made_again_and_never_fails(env, monkeypatch):
    from engine.storage import ConflictError

    ws, cfg, store = env
    source = cfg.watch.sources[0]
    refresh(ws, store, cfg, source.id, NOW)
    held = len(source_intake.waiting(store.read(), source.id))
    real, calls = store.transaction, []

    def clashing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ConflictError("request", "another", ["state"])
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "transaction", clashing)
    assert source_intake.grant_go(ws, store, cfg, source.id, now=NOW) == held
    assert len(calls) == 2 and source_intake.waiting(store.read(), source.id) == []


def test_the_route_takes_the_go_with_the_choice_and_today_has_no_take_in_line_left(tmp_path):
    ws, cfg, store = make(tmp_path)
    store.close()
    from api.app import create_app

    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        source = client.get("/api/watch").json()[0]["id"]
        assert client.post(f"/api/watch/{source}/read").status_code == 200
        live = app.state.store
        shown = client.get(f"/api/watch/{source}/full-read").json()["options"]
        pick = next(o for o in shown if o["count"] > 0 and not o["unknown"])
        said = client.post(f"/api/watch/{source}/full-read", json={"days": pick["days"]})
        assert said.status_code == 200 and said.json()["stopped"] == "queued"
        assert source_intake.waiting(live.read(), source) == []
        assert source_intake.intake_run(live.read(), source).data["older_read"]["go"] is True  # the go came with it
        assert not live.read().has("run")  # the press asked the assistant nothing


def test_an_answer_waiting_to_be_applied_never_shows_the_question_again(env):
    ws, cfg, store = env
    first, second = cfg.watch.sources[0], cfg.watch.sources[1]
    first.account = second.account = "one-account"
    assert source_intake.full_read_open(ws, store, cfg, first) and source_intake.full_read_open(ws, store, cfg, second)
    assert not source_intake.full_read_open(ws, store, cfg, first, signed_in=False)
    source_intake.answer_full_read(ws, store, cfg, first.id, cfg.watch.full_read_choices[1], NOW)
    # The first read has landed and is still taking its mail in: its record is there, the answer not yet applied.
    from engine.watch import _refresh

    _refresh(ws, store, cfg, first.id, NOW)
    _refresh(ws, store, cfg, second.id, NOW)
    assert source_intake.full_read_pending(store, cfg, first) and source_intake.full_read_pending(store, cfg, second)
    assert not source_intake.full_read_open(ws, store, cfg, first)  # its own answer is kept
    assert not source_intake.full_read_open(ws, store, cfg, second)  # its account was answered
