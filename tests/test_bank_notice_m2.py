# ruff: noqa: F811
"""A bank's "your statement is available" notice (S-0569): the sorting files it as a notice, a fix round says up front
which ops it must keep, a line names the service and never a machine-made address, and the stopped line says what
happened once, in plain words, with its three ways on. Names come from the fixtures; the stand-in is the AI account."""

import json

from engine.ai.adapters.stub import set_responder
from engine.mail_sorting import RULE
from engine.titles import readable_sender
from tests.test_mail_sorting import make, read, snapshots
from tests.test_set_aside import mail, requests_in

SERVICE_ADDRESS = "no-reply@northfield-bank.example"
STATEMENT = "Your statement is available"


def statement_notice(key="stmt-1", subject=STATEMENT, **kw):
    """A fictional bank notice: a bare machine-made address, marked bulk by the mail service, to the person alone."""
    item = mail(key, SERVICE_ADDRESS, subject=subject, bulk=True, **kw)
    item["message"]["sender"] = SERVICE_ADDRESS
    item["author"] = SERVICE_ADDRESS
    return item


def test_a_statement_notice_is_filed_as_a_notice_by_the_stand_in_and_a_statement_with_an_amount_is_not(tmp_path):
    items = [statement_notice(), statement_notice("stmt-2", subject="Your statement of $182.40 is due on Nov 3")]
    ws, cfg, store = make(tmp_path, items)
    set_responder(None)
    try:
        read(ws, store)
        found = snapshots(store)
        assert found["stmt-1"]["set_aside"]["rule"] == RULE and found["stmt-1"]["set_aside"]["section"] == "notices"
        assert not found["stmt-2"].get("set_aside"), (
            "a statement with an amount owed is a bill: tracked, never set aside"
        )
        assert len(requests_in(store, "queued")) == 1, "only the bill reaches the assistant's work"
    finally:
        store.close()
        set_responder(None)


def test_a_machine_made_address_is_never_a_name_and_a_person_s_bare_address_is_read_as_a_name():
    assert readable_sender(SERVICE_ADDRESS) == "Northfield Bank"
    assert readable_sender("no-reply@alerts.northfield-bank.co.uk") == "Northfield Bank"
    assert readable_sender("pat.marsh@club.example.com") == "Pat Marsh"
    assert readable_sender("noreply@x") == "", "nothing to say: the caller keeps what it had"


# ---- the return round ----------------------------------------------------------------------------------------------

from engine.ai.router import Router  # noqa: E402
from engine.dispatcher import process  # noqa: E402
from engine.intake import hand_in  # noqa: E402
from tests.test_pipeline import NOW, env, outcomes  # noqa: E402, F401
from tests.test_retry_keeps_ops import BAD, FIXED, GOOD, INPUT, JACKET  # noqa: E402


def test_the_first_return_round_names_the_ops_to_keep_so_a_correction_that_obeys_loses_nothing(env):
    """With the shipped one fix round, a correction that dropped an op which was fine used to be refused with no word
    of warning: three such runs stopped the item. The first return round now says which ops had no problem."""
    ws, cfg, store = env
    assert cfg.dispatch.fix_rounds == 1
    asked = []

    def model(task):
        asked.append(task)
        if len(asked) == 1:
            return json.dumps({"ops": [GOOD, BAD, JACKET]})
        # A model that only repeats the op it was told was wrong, unless it is told to keep the others.
        told = "had no problem: fact" in task.request
        return json.dumps({"ops": [GOOD, FIXED, JACKET] if told else [FIXED]})

    set_responder(model)
    handed = hand_in(ws, store, note="", pasted=INPUT, now=NOW)
    cs_id = process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    assert len(asked) == 2, "no extra round and no stronger tier were needed"
    assert "had no problem: fact. Answer with each of them exactly as it was" in asked[1].request
    assert [o["status"] for o in outcomes(store, cs_id)] == ["applied"] * 3


def test_a_fix_round_shows_the_answer_it_is_about_so_the_ops_to_keep_can_be_copied(env):
    """A fix round is a fresh call: unless its request holds the answer it is about, "op 1" and "keep the others exactly
    as they were" point at nothing the model can see, and a correction can only rebuild its answer from scratch."""
    ws, cfg, store = env
    asked = []

    def model(task):
        asked.append(task)
        if len(asked) == 1:
            return json.dumps({"ops": [GOOD, BAD, JACKET]})
        # A model that copies its earlier ops from the request when they are there, and can only send the fix when not.
        marker = "Your previous answer (its ops are numbered from 0):\n"
        if marker not in task.request:
            return json.dumps({"ops": [FIXED]})
        earlier = json.loads(task.request.split(marker, 1)[1].split("\n", 1)[0])["ops"]
        return json.dumps({"ops": [earlier[0], FIXED, earlier[2]]})

    set_responder(model)
    handed = hand_in(ws, store, note="", pasted=INPUT, now=NOW)
    cs_id = process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    assert len(asked) == 2
    assert [o["status"] for o in outcomes(store, cs_id)] == ["applied"] * 3
