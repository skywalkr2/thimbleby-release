"""A fact is written as a sentence, not a raw run of its source (design 6.7). Fictional notice text throughout."""

from __future__ import annotations

import pytest

from engine.applier import Context, Inputs, check
from engine.fact_wording import raw_run
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

NOTICE = (
    "Thanks for your AutoPay payment!\nUnit Number: 1134\nUnit Size: 10x10\nPAYMENT AMOUNT: $104.94\n"
    "Past Due Due Now Due Next 12/01/2026 Example Town, ST 12345"
)
TUNING = {"min_words": 12, "copied_share": 0.8, "caps_run": 2}


def test_a_run_of_lines_or_a_capitalized_label_or_a_long_copy_is_raw():
    lines = "Unit Number: 1134\nUnit Size: 10x10"
    assert "line breaks" in raw_run(lines, NOTICE, **TUNING)
    assert "capital letters" in raw_run("PAYMENT AMOUNT $104.94 was paid", NOTICE, **TUNING)
    copied = "Thanks for your AutoPay payment Unit Number 1134 Unit Size 10x10 PAYMENT amount 104 94 Past Due"
    assert "own words" in raw_run(copied.replace("PAYMENT", "payment"), NOTICE + "\n" + copied.lower(), **TUNING)


def test_a_sentence_about_the_source_is_not_raw():
    sentence = "Unit 1134 (10x10) was paid by AutoPay for $104.94, and the next payment is due on December 1, 2026"
    assert raw_run(sentence, NOTICE, **TUNING) is None
    # A short fact may be the words as they stood, and one capitalized word alone is no label.
    assert raw_run("The proof is approved.", "The proof is approved.", **TUNING) is None
    assert raw_run("Ship via UPS on Friday", NOTICE, **TUNING) is None


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def _lints(env, text, actor="assistant"):
    _, cfg, store = env
    op = {"op": "fact", "text": text, "evidence": {"quote": "Unit Size: 10x10"}}
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store, cfg, People(store, cfg), ("fact",), Inputs("REQ-1", None, NOTICE, "", "untrusted"), actor=actor
    )
    return [p for p in check(cs, ctx) if p.check == "fact-is-raw-run"]


def test_the_check_returns_a_raw_fact_once_it_reaches_the_applier_and_the_persons_own_is_left_alone(env):
    found = _lints(env, "Unit Number: 1134\nUnit Size: 10x10 PAYMENT AMOUNT: $104.94")
    assert [p.severity for p in found] == ["return"] and "one plain sentence" in found[0].message
    assert _lints(env, "Unit 1134 (10x10) was paid by AutoPay, $104.94; next payment due Dec 1, 2026") == []
    assert _lints(env, "Unit Number: 1134\nUnit Size: 10x10", actor="pm") == []


def test_a_real_models_fact_for_the_storage_notice_passes_the_lint_and_is_applied_with_a_full_date(env):
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    from engine.applier import apply_changeset

    answer = json.loads(Path("tests/fixtures/real_answers/storage-autopay-fact-as-a-sentence.json").read_text())
    (fact,) = answer["ops"]
    assert _lints(env, fact["text"]) == []
    _, cfg, store = env
    cs = CHANGESET.validate_python({"ops": answer["ops"]}, context={"op_models": store.plugins.ops})
    raw = "Due Past Due $0.00 Due Now $0.00 Due Next 12/01/2026"
    ctx = Context(
        store, cfg, People(store, cfg), ("fact",), Inputs("REQ-1", None, raw, "", "untrusted", cites="mail:1")
    )
    cs_id = apply_changeset(cs, [], ctx, run=None, now=datetime(2026, 11, 17, 9, 0, tzinfo=UTC))
    (outcome,) = [o for o in store.read().get("changeset", cs_id).data["ops"] if o["op"]["op"] == "fact"]
    assert outcome["status"] in ("applied", "held"), outcome
    assert str(outcome["op"]["on"]) == "2026-12-01"
