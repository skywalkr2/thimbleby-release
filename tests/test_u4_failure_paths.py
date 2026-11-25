# ruff: noqa: F811
"""U4-0a: the failure paths the first tests of a fresh install found. Each test below that
is marked as an expected failure reproduces the person's path and fails on today's code for the reason in its mark;
when the fix lands the test passes, the strict mark fails, and the fixer removes it."""

from __future__ import annotations

import pytest

from engine.ai import adapters
from engine.ai.router import Router
from engine.ai.task import AiError, AiResult
from tests.conftest import connection_answer
from tests.test_first_run_ai import HOSTED, check_body
from tests.test_people_suggestions import fake_reads_mail  # noqa: F401  (the people tests' autouse stand-in)
from tests.test_pipeline import env as env_pipeline  # noqa: F401  (the pipeline fixture, used by name below)
from tests.test_setup import COMMON, client, make
from tests.test_silent_stops import env  # noqa: F401  (the engine fixture: a workspace, its settings, store and clock)

# ---- item 2: a rate limit while checking a new key ----------


def a_service_that_limits_after(answers: int):
    """The common adapter with a service behind it that answers the first calls and then says to wait (429)."""
    base = adapters.ADAPTERS[COMMON]
    seen = {"calls": 0}

    class Fake(base):
        def __init__(self, settings, secret=None):
            self.settings, self.secret = settings, secret

        def run(self, task, model):
            seen["calls"] += 1
            if seen["calls"] > answers:
                raise AiError("rate_limited", "HTTP 429: too many requests", retry_after=30)
            return AiResult(text=connection_answer(task), model_served=model, seconds=0.0)

        def list_models(self):
            return {}

    return Fake, seen


def test_item_2_a_valid_key_that_meets_the_services_rate_limit_is_not_called_a_failure(tmp_path, monkeypatch):
    fake, seen = a_service_that_limits_after(2)
    monkeypatch.setitem(adapters.ADAPTERS, COMMON, fake)
    ws, cfg, store = make(tmp_path)
    c, api = client(ws, cfg, store)
    got = c.post(f"{api}/ai/account-check", json=check_body(HOSTED[0])).json()
    assert seen["calls"] > 2, "the check reached the limit"
    # The service answered the first calls with this key, so the key is good; a request to wait says nothing against it.
    assert got["ok"] is True, f"a good key was reported as: {got['reason']} / {got['message']}"


# ---- item 3: a model with no known price is still tried by the check ----------


def test_item_3_a_model_with_no_known_price_is_tried_by_the_check_and_not_held_for_its_price(tmp_path, monkeypatch):
    from engine.ai.shipped_prices import price_for

    seen: list = []
    base = adapters.ADAPTERS[COMMON]

    class Fake(base):
        def __init__(self, settings, secret=None):
            self.settings, self.secret = settings, secret

        def run(self, task, model):
            seen.append(model)
            return AiResult(text=connection_answer(task), model_served=model, seconds=0.0)

        def list_models(self):
            return {}

    monkeypatch.setitem(adapters.ADAPTERS, COMMON, Fake)
    ws, cfg, store = make(tmp_path)
    c, api = client(ws, cfg, store)
    kind = HOSTED[0]
    unpriced = "model-nobody-has-priced"
    assert price_for(kind["id"], unpriced) is None
    asked = c.post(f"{api}/ai/prices/missing", json={"endpoint": kind["id"], "models": [unpriced]}).json()
    assert asked == {"unpriced": [unpriced]}
    got = c.post(
        f"{api}/ai/account-check",
        json=check_body(kind, models={"everyday": unpriced, "harder": unpriced}),
    ).json()
    # The check runs on the model whether or not a price was given; the price is asked for beside it, never first.
    assert seen and set(seen) == {unpriced}, "the check never tried the unpriced model"
    assert got["ok"] is True, got


# ---- items 10 and 11: the people step ----------


@pytest.mark.parametrize("machine_id", ["h7Kq2LmN9xPz4RtVwQ", "x9fK2mQ7vL3nB8tR5w", "Qp3Zk8Wm1Xv6Lt9Rb2"])
def test_item_10_a_reply_address_that_is_a_long_machine_id_reaches_the_run_with_a_code_hint_beside_the_real_one(
    tmp_path, machine_id
):
    """Who is a person is the assistant's reading (S-0590): the address is in the tally with the mark a code gives it,
    for the run to weigh, and the real correspondent is there untouched."""
    from engine import contact_tally
    from tests.test_people_suggestions import message, setup, who

    items = [message("sent1", "me@example.com", [who(0), f"<{machine_id}@mail.example.com>"])]
    _ws, cfg, store = setup(tmp_path, items, sent=True)
    found = {c.address: c for c in contact_tally.tally(store, cfg)}
    store.close()
    assert found["c0@example.com"].hints == ()
    assert found[f"{machine_id.lower()}@mail.example.com"].hints == (contact_tally.CODE,)


@pytest.mark.parametrize("sent", [True, False])
def test_item_11_one_machine_address_among_several_real_correspondents_does_not_hide_the_others_from_the_run(
    tmp_path, sent
):
    from engine import contact_tally
    from tests.test_people_suggestions import message, setup, who

    machine = "<reply-7f3a9c2e4b1d@mail.example.com>"
    if sent:
        items = [
            message("sent1", "me@example.com", [machine, who(0), who(1), who(2)]),
            message("sent2", "me@example.com", [who(3)]),
        ]
    else:
        items = [message("m0", "Bulk News <" + machine[1:], bulk=False)] + [
            message(f"m{n}", who(n)) for n in range(1, 5)
        ]
    _ws, cfg, store = setup(tmp_path, items, sent=sent)
    found = contact_tally.tally(store, cfg)
    store.close()
    real = [c for c in found if c.hints == ()]
    assert len(real) == 4, f"found only {[c.address for c in real]}"


# ---- item 15: out of credit with no reset time ----------

#: Words of the app's own plumbing a person never reads on Today.
INTERNAL = ("tier", "'routine'", "routine", "provider", "adapter")


def _today_lines(env):
    from engine.today_queue import queue

    ws, cfg, store, clock = env
    return [line for line in queue(ws, store, cfg, clock()) if line.kind in ("paused", "refused", "failed")]


def test_item_15_credit_run_out_with_no_reset_time_is_one_line_for_the_account_with_no_internal_word(env):
    """The guard for the credit path itself: three items, the account says no credit and no reset time."""
    from tests.test_silent_stops import NOTE, Scripted, account_of, data, hand, set_responder, worker_of

    _ws, cfg, _store, _clock = env
    set_responder(Scripted(AiError("quota", "no credit")))
    requests = [hand(env, NOTE + f" Variant {n} with other words.") for n in range(3)]
    worker_of(env).run_pending()
    assert {data(env, r)["state"] for r in requests} == {"queued"}
    lines = _today_lines(env)
    assert len(lines) == 1 and lines[0].count == 3 and lines[0].account == account_of(cfg)
    assert not any(word in (lines[0].waiting or "").lower() for word in INTERNAL)


def test_item_15_items_with_no_account_to_run_on_are_one_line_naming_no_internal_word(env):
    from engine.today_queue import queue
    from tests.test_silent_stops import NOTE, Scripted, data, hand, set_responder, worker_of

    ws, cfg, store, clock = env
    set_responder(Scripted("{}"))
    cfg.ai.tiers["routine"].use = ""
    cfg.ai.tiers["routine"].fallback = []
    requests = [hand(env, NOTE + f" Variant {n} with other words.") for n in range(3)]
    worker_of(env).run_pending()
    assert {data(env, r)["state"] for r in requests} == {"queued"}
    assert _today_lines(env) == [], "waiting for an account is no stop"
    lines = [line for line in queue(ws, store, cfg, clock()) if line.kind == "no_account"]
    assert len(lines) == 1, f"{len(lines)} lines for one cause"
    assert not any(word in (lines[0].waiting or "").lower() for word in INTERNAL), lines[0].waiting


def test_a_hand_in_with_no_account_waits_with_no_stop_and_runs_when_an_account_is_added(env):
    """The person's path: no account, hand in a note. It waits (no Stopped line, nothing to try again, no try counted);
    Today's one line asks for an account; adding one lets the work run."""
    from engine.worker import release_paused
    from tests.test_silent_stops import ANSWER, NOTE, Scripted, data, hand, set_responder, worker_of

    _ws, cfg, store, _clock = env
    set_responder(Scripted(ANSWER))
    given = cfg.ai.tiers["routine"].model_copy()
    cfg.ai.tiers["routine"].use = ""
    cfg.ai.tiers["routine"].fallback = []
    request = hand(env, NOTE)
    worker_of(env).run_pending()
    waiting = data(env, request)
    assert waiting["state"] == "queued" and waiting["cause"]["kind"] == "no_account"
    assert waiting["attempts"] == 0 and "account" in waiting["waiting"].lower()
    lines = _today_lines(env)
    assert not any(line.kind in ("stopped", "failed") for line in lines)
    cfg.ai.tiers["routine"].use, cfg.ai.tiers["routine"].fallback = given.use, given.fallback
    assert release_paused(store) == 1
    worker_of(env).run_pending()
    assert data(env, request)["state"] in ("review", "done")


# ---- item 16, second half: who added a calendar entry ----------


def test_item_16b_a_calendar_entry_the_assistant_found_does_not_look_like_one_the_person_added(tmp_path):
    import json
    from dataclasses import asdict
    from datetime import UTC, datetime

    from engine.add_meeting import add_meeting
    from engine.ai.adapters.stub import set_responder
    from engine.ai.router import Router
    from engine.dispatcher import process
    from engine.intake import hand_in
    from engine.storage import Store
    from engine.today import agenda
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B

    now = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    cfg.ui.today.agenda_days_ahead = 20
    mail = "Your order has shipped.\n\nEstimated delivery: Tuesday, October 20 - Thursday, October 22\n\nThank you."
    window = {
        "op": "event.add",
        "title": "Delivery window",
        "start": "2026-10-20",
        "end": "2026-10-22",
        "evidence": {"quote": "Estimated delivery: Tuesday, October 20 - Thursday, October 22"},
    }
    try:
        set_responder(lambda task: json.dumps({"ops": [window]}))
        handed = hand_in(ws, store, note="", pasted=mail, now=now)
        process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=now)
        add_meeting(store, cfg, "Person typed this", "2026-10-20")
        rows = {a.title: asdict(a) for a in agenda(store, cfg, now)}
    finally:
        set_responder(None)
        store.close()
    assert set(rows) == {"Delivery window", "Person typed this"}
    own_words = {"title", "snapshot", "entry", "agenda", "start", "end", "days", "all_day", "source"}
    found, typed = (
        {k: v for k, v in rows[t].items() if k not in own_words} for t in ("Delivery window", "Person typed this")
    )
    assert found != typed, "both rows say the same thing about who added them, so the screen can only say 'you'"


# ---- item 19: a notice sent only to the person ----------


def test_item_19_a_notice_sent_only_to_the_person_is_never_set_aside_as_sent_to_many_people(tmp_path):
    from engine.triage import first_match
    from tests.test_set_aside import BUILDS, change, make

    me = "me@example.com"
    notice = {
        **change(f"notifications@{BUILDS}", bulk=True, participants=[me]),
        "title": "You have a new subscriber",
    }
    ws, cfg, store = make(tmp_path, [])
    try:
        found = first_match(store, cfg, notice)
    finally:
        store.close()
    said = (found or {}).get("reason", "")
    assert "many" not in said.lower(), f"set aside as: {said}"


def test_item_19_the_same_notice_sent_to_a_list_is_still_set_aside_as_an_automated_notice(tmp_path):
    from engine.triage import first_match
    from tests.test_set_aside import BUILDS, change, make

    people = ["a@example.com", "b@example.com", "c@example.com"]
    notice = {
        **change(f"notifications@{BUILDS}", bulk=True, participants=people),
        "title": "You have a new subscriber",
    }
    ws, cfg, store = make(tmp_path, [])
    try:
        found = first_match(store, cfg, notice)
    finally:
        store.close()
    assert found and found["section"] == "notices"


def test_item_19_a_notice_to_the_person_alone_reaches_the_assistant_not_the_set_aside_folder(tmp_path):
    from engine.triage import first_match
    from tests.test_set_aside import BUILDS, change, make

    notice = change(f"notifications@{BUILDS}", bulk=True, participants=["Me <me@example.com>"])
    ws, cfg, store = make(tmp_path, [])
    try:
        assert first_match(store, cfg, notice) is None
    finally:
        store.close()


def test_a_deals_newsletter_with_list_headers_is_still_set_aside_with_no_ai_call_even_when_sent_to_the_person_alone(
    tmp_path,
):
    """Item 19 protects a notice written to the person; a mailing list's newsletter (bulk, a promotions category or an
    ordinary sender) is addressed to each reader alone and is still sales."""
    from engine.triage import first_match
    from tests.test_set_aside import LISTS, change, make

    alone = ["Me <me@example.com>"]
    plain = change(f"deals@{LISTS}", bulk=True, participants=alone)
    promo = change(f"offers@{LISTS}", bulk=True, categories=["promotions"], participants=alone)
    ws, cfg, store = make(tmp_path, [])
    try:
        assert (first_match(store, cfg, plain) or {}).get("section") == "sales"
        assert (first_match(store, cfg, promo) or {}).get("section") == "sales"
    finally:
        store.close()


# ---- item 22: a PDF reader's warnings on the terminal ----------


def test_item_22_reading_a_pdf_with_wrong_offsets_writes_nothing_to_the_terminal():
    import os
    import re
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import re\n"
        "from engine.extract import fixtures\n"
        "from engine.extract.pdf import read_pdf\n"
        "data = fixtures.pdf()\n"
        "bad = re.sub(rb'(\\d{10}) 00000 n', lambda m: b'%010d 00000 n' % (int(m.group(1)) + 7), data)\n"
        "read_pdf(bad, 10000)\n"
    )
    root = Path(__file__).resolve().parents[1]
    ran = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert re.search(r"\S", ran.stderr) is None, f"the terminal got: {ran.stderr[:200]!r}"


# ---- P128: a network drop is not a broken account ----------


def _agent(tmp_path_factory=None):
    import sys

    from engine.ai.adapters.cli_agent import CliAgentAdapter
    from engine.config.schema import AgentSettings, ProviderSettings

    return CliAgentAdapter(
        ProviderSettings(
            adapter=CliAgentAdapter.name,
            models={"default": "agent-model"},
            timeout_seconds=5,
            agent=AgentSettings(command=[sys.executable, "-c", "pass"]),
        )
    )


def test_p128_a_cut_connection_on_the_programs_error_stream_sorts_as_the_network():
    error = _agent().classify_error(1, "Error: connection closed before message completed", None)
    assert error.kind == "offline", f"sorted as {error.kind}"


def test_p128_an_unknown_model_with_an_empty_list_sorts_as_the_network():
    error = _agent().classify_error(1, "Error: Unknown model: agent-model. Available models:", None)
    assert error.kind == "offline", f"sorted as {error.kind}"


def test_p128_an_unknown_model_with_a_filled_list_is_a_real_wrong_model_not_the_network():
    error = _agent().classify_error(1, "Error: Unknown model: agent-model. Available models: alpha, beta", None)
    assert error.kind != "offline", "a filled list means the model really is wrong"


def test_p128_an_account_that_failed_and_then_succeeded_has_no_open_problem(env):
    from engine.ai.smoke import ai_state
    from tests.test_silent_stops import ANSWER, TASK, Scripted, adapters_by_account, as_a_real_account

    ws, cfg, store, clock = env
    account = as_a_real_account(cfg)

    def call_with(provider, request_id):
        clock.move(seconds=1)
        factory = adapters_by_account(cfg, {account: provider})
        return Router(cfg, store, env={}, now=clock, adapter_factory=factory).call(TASK, request_id=request_id)

    with pytest.raises(AiError):
        call_with(Scripted(AiError("auth", "HTTP 401")), "REQ-1")
    assert ai_state(ws, cfg, store)[0] == "failing"
    call_with(Scripted(ANSWER), "REQ-2")
    assert ai_state(ws, cfg, store)[0] != "failing", "the account's next good run clears its problem"


def test_p128_an_item_that_failed_for_an_odd_reason_and_then_succeeded_leaves_no_line(env):
    from tests.test_silent_stops import ANSWER, NOTE, Scripted, data, hand, set_responder, worker_of

    _ws, _cfg, _store, clock = env
    set_responder(Scripted(AiError("other", "something odd"), ANSWER))
    request = hand(env, NOTE)
    worker = worker_of(env)
    worker.run_pending()
    clock.move(hours=1)
    worker.run_pending()
    assert data(env, request)["state"] == "review"
    assert _today_lines(env) == []


# ---- P129: nothing that is fixing itself shows as failed ----------


@pytest.mark.parametrize("kind", ["provider_down", "timeout"])
def test_p129_a_fix_round_that_ends_in_a_retry_queued_for_later_shows_no_failed_state_or_line(env, kind):
    from tests.test_silent_stops import ANSWER, BAD, NOTE, Scripted, data, hand, set_responder, worker_of

    set_responder(Scripted(BAD, AiError(kind, "HTTP 503"), ANSWER))
    request = hand(env, NOTE)
    worker_of(env).run_pending()
    pending = data(env, request)
    assert pending["state"] == "queued", f"while a retry is pending the item is {pending['state']}"
    assert _today_lines(env) == [], "a retry that is pending is no problem line"


# ---- P131, the cut only: a long mail is not cut at a fixed size ----------


def test_p131_a_long_mail_reaches_the_run_whole_or_saved_where_it_can_be_opened_never_cut_at_a_fixed_size():
    from engine.connectors import mailbox

    last = "The final sentence says the proofs ship on the fifth."
    paragraph = "A paragraph of ordinary words about the printing schedule and the cover files. "
    body = paragraph * (40_000 // len(paragraph)) + last
    raw = (
        b"Message-ID: <long@example.com>\r\nFrom: Casey Kin <casey.kin@example.com>\r\nSubject: Schedule\r\n"
        b"Date: Mon, 09 Nov 2026 09:00:00 +0000\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n" + body.encode()
    )
    item = mailbox.message_item(raw)
    assert item is not None
    reachable = last in item.text or any(last.encode() in f.data for f in item.files)
    assert reachable, "the end of the mail is gone: the text was cut at a fixed size"


# ---- P134: requests ask, and add ----------


def test_p134_a_question_to_another_team_asking_to_replace_a_field_is_flagged_and_one_asking_to_add_is_not(tmp_path):
    from engine.applier import Context, Inputs, check
    from engine.names import People
    from engine.ops import CHANGESET
    from engine.storage import Store
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B
    from tests.test_first_week_lints import SAID, to_other

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)

    def findings(text: str) -> set[str]:
        op = to_other(text=text, links=[])
        cs = CHANGESET.validate_python({"summary": "", "ops": [op]}, context={"op_models": store.plugins.ops})
        ctx = Context(
            store,
            cfg,
            People(store, cfg),
            tuple(store.plugins.ops),
            Inputs("REQ-1", None, SAID, SAID, "untrusted"),
            actor="assistant",
        )
        return {p.check for p in check(cs, ctx) if p.severity in ("return", "refuse", "warn")}

    try:
        adding = findings(
            "Could you add a ship date field beside the delivery date field? It would help to see both. Thanks."
        )
        replacing = findings(
            "Could you replace the delivery date field with a ship date field instead? It would help. Thanks."
        )
    finally:
        store.close()
    assert replacing - adding, f"the ask to replace raised nothing the ask to add did not (both: {sorted(adding)})"


# ---- P135: an alarm names only its own cause ----------


def test_p135_three_items_with_no_access_plus_one_timeout_raise_no_outage_line(tmp_path):
    from datetime import UTC, datetime, timedelta

    import yaml

    from engine import watch
    from engine.config import load_config
    from engine.storage import Store
    from engine.today_queue import queue
    from tests.test_today_dashboard import make

    ws, cfg, store = make(tmp_path, [])
    path = ws.config_dir / "watch.yaml"
    config = yaml.safe_load(path.read_text())
    base = config["sources"][0]
    config["sources"] = [{**base, "id": name, "label": f"Source {name}"} for name in ("a", "b", "c", "d")]
    path.write_text(yaml.safe_dump(config))
    store.close()
    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    now = datetime.now(UTC)
    try:
        for name in ("a", "b", "c"):  # three items the person has no access to
            watch._record(store, name, now - timedelta(days=3), 0.0, "failed", error_kind="no_access", error="refused")
        # One item read well three days ago, and one timeout just now.
        watch._record(store, "d", now - timedelta(days=3), 0.0, "ok")
        watch._record(store, "d", now - timedelta(minutes=2), 0.0, "failed", error_kind="outage", error="timed out")
        kinds = [line.problem_kind for line in queue(ws, store, cfg, now) if line.kind == "source_unread"]
    finally:
        store.close()
    assert kinds.count("no_access") == 3, f"each item with no access is its own: {kinds}"
    assert "outage" not in kinds, f"one timeout raised an outage line: {kinds}"


def test_p135_a_retry_whose_result_says_why_it_left_an_op_out_raises_nothing(env_pipeline):
    from engine.applier import Problem  # noqa: F401
    from engine.dispatcher import DROPPED
    from tests.test_pipeline import outcomes
    from tests.test_retry_keeps_ops import BAD, FIXED, GOOD, JACKET, run

    _, _, store = env_pipeline
    why = "I left out the proof date because the first answer's quote for it was not in the input."
    asked, cs_id = run(
        env_pipeline,
        {"ops": [GOOD, BAD, JACKET]},
        {
            "summary": "Left out the proof date: the first answer's quote for it was not in the input.",
            "omitted": [{"op": "fact", "reason": why}],
            "ops": [FIXED, JACKET],
        },
        {"ops": [GOOD, FIXED, JACKET]},
    )
    assert DROPPED.split("{")[0] not in asked[-1].request, "the explained omission was sent back as a problem"
    assert len(asked) == 2
    assert [o["status"] for o in outcomes(store, cs_id)] == ["applied", "applied"]
