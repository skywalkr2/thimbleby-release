"""What a draft for someone else may state, and a pause the person states (S-0236, S-0509, S-0547; design 6.19, 6.22).

An inference never reaches another person; a fact older than its freshness limit is held with a "check this" line; a
document the person said is mid-edit yields facts only until they say it is ready. Names and ids come from the
fixtures, and ages are measured from the store's own clock.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from engine.applier import Context, Inputs, _held_after_return, apply_as_person, check
from engine.config.schema import FreshnessDaysSettings
from engine.fact_use import limit_days
from engine.names import People
from engine.ops import CHANGESET
from engine.repeats import local_today
from engine.storage import WriteContext
from tests.conftest import DEMO_B, fixture_records
from tests.test_fact_basis import LINE, OTHER, PM, fact, from_outside
from tests.test_knowledge_records import (  # noqa: F401  (the fixture is used by name)
    app,
    apply,
    reasons,
    request,
    source,
)

_ASSISTANT = WriteContext(actor="assistant", trust="trusted", op="test.fact-trust")
PROJECT = fixture_records(DEMO_B, "project")[0]["id"]
PM_NAME = next(p["full_name"] for p in fixture_records(DEMO_B, "person") if p["id"] == PM)


def today(store, cfg=None) -> date:
    """The day the freshness check counts from: the workspace's own day (the applier's `local_day` in its zone), never
    the UTC day, which differs from it each evening before midnight in the workspace's zone."""
    if cfg is None:
        return datetime.fromisoformat(store.clock()).date()
    return local_today(store, cfg)


def make_fact(store, text, *, days_old=0, cfg=None, **more) -> str:
    with store.transaction() as tx:
        return tx.create(
            "fact",
            {
                "text": text,
                "basis": "person",
                "as_of": (today(store, cfg) - timedelta(days=days_old)).isoformat(),
                **more,
            },
            _ASSISTANT,
        ).id


def draft(to, text="The file is final.", **more):
    return {
        "op": "act.draft",
        "channel": "copy",
        "target": {"kind": "message", "recipients": [{"person": to}]},
        "parts": {"subject": "The file", "body": text},
        **more,
    }


def checked(store, cfg, op, *, trust="trusted"):
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(request(store, "pm"), None, "", "", trust),
    )
    return ctx, cs, check(cs, ctx)


def named(problems, check_name):
    return [p for p in problems if p.check == check_name]


# ---- S-0236: an inference never reaches anyone else ------------------------------------------------------------------


def test_a_draft_that_names_an_inferred_fact_is_refused_and_a_fact_the_person_said_passes(app):  # noqa: F811
    _, store, cfg, _ = app
    guessed = make_fact(store, "The interior file went out.", basis="inferred")
    said = make_fact(store, "The cover proof is approved.")
    _, _, problems = checked(store, cfg, draft(OTHER["full_name"], facts=[guessed]))
    (refused,) = named(problems, "inferred-fact")
    assert refused.severity == "refuse" and guessed in refused.message
    assert named(checked(store, cfg, draft(OTHER["full_name"], facts=[said]))[2], "inferred-fact") == []


def test_a_draft_that_states_an_inferred_facts_words_without_naming_it_is_refused(app):  # noqa: F811
    _, store, cfg, _ = app
    guessed = make_fact(store, "The interior file went out with the afternoon batch.", basis="inferred")
    sentence = "Good news: the interior file went out with the afternoon batch."
    (refused,) = named(checked(store, cfg, draft(OTHER["full_name"], sentence))[2], "inferred-fact")
    assert guessed in refused.message
    assert named(checked(store, cfg, draft(OTHER["full_name"], "The file is on its way."))[2], "inferred-fact") == []


def test_a_draft_naming_a_fact_that_does_not_exist_is_refused(app):  # noqa: F811
    _, store, cfg, _ = app
    (refused,) = named(checked(store, cfg, draft(OTHER["full_name"], facts=["FACT-9999"]))[2], "inferred-fact")
    assert "isn't the id of a fact" in refused.message


def test_a_deduction_the_person_confirms_rests_on_them_and_may_then_be_stated(app):  # noqa: F811
    _, store, cfg, _ = app
    guessed = make_fact(store, "Both spines are in the folder.", basis="inferred")
    op = draft(OTHER["full_name"], facts=[guessed])
    assert named(checked(store, cfg, op)[2], "inferred-fact")
    apply_as_person(
        store,
        cfg,
        [
            {
                "op": "record.edit",
                "record": {"kind": "fact", "id": guessed},
                "fields": {"basis": "person"},
                "read_version": 1,
            }
        ],
        "Confirmed",
    )
    assert store.read().get("fact", guessed).data["basis"] == "person"
    assert named(checked(store, cfg, op)[2], "inferred-fact") == []


def test_an_act_made_and_stored_keeps_the_facts_it_states(app):  # noqa: F811
    _, store, cfg, _ = app
    said = make_fact(store, "The cover proof is approved.")
    from engine.applier import apply_changeset

    cs = CHANGESET.validate_python(
        {"ops": [draft(OTHER["full_name"], facts=[said, said])]}, context={"op_models": store.plugins.ops}
    )
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(request(store, "pm"), None, "", "", "trusted"),
        actor="pm",
    )
    changed = store.read().get("changeset", apply_changeset(cs, [], ctx, run=None)).data["ops"][0]
    if changed["status"] == "applied":
        (act,) = store.read().list("act")
        assert act.data["facts"] == [said]


# ---- S-0509: a fact's freshness is checked before an outward draft ---------------------------------------------------


def test_a_fact_past_its_limit_in_a_draft_for_someone_else_is_held_with_a_check_this_line(app):  # noqa: F811
    _, store, cfg, _ = app
    limit = cfg.steward.facts.freshness_days.other
    old = make_fact(store, "The cover proof is approved.", days_old=limit + 1, cfg=cfg)
    ctx, cs, problems = checked(store, cfg, draft(OTHER["full_name"], facts=[old]))
    (late,) = named(problems, "stale-fact")
    assert late.severity == "return" and late.message.startswith("Check this")
    assert "The cover proof is approved." in late.message and str(limit + 1) in late.message
    assert _held_after_return(cs.ops[0], [late], ctx)  # it reaches another person, so it is held after the return round


def test_a_fresh_fact_passes_and_one_at_the_limit_is_not_yet_old(app):  # noqa: F811
    _, store, cfg, _ = app
    limit = cfg.steward.facts.freshness_days.other
    fresh = make_fact(store, "The cover proof is approved.", days_old=1, cfg=cfg)
    edge = make_fact(store, "The spine width is set.", days_old=limit, cfg=cfg)
    assert named(checked(store, cfg, draft(OTHER["full_name"], facts=[fresh, edge]))[2], "stale-fact") == []


def test_the_limit_is_per_kind_and_a_limit_of_zero_never_holds(app):  # noqa: F811
    _, store, cfg, _ = app
    days = cfg.steward.facts.freshness_days.deadline + 1
    assert cfg.steward.facts.freshness_days.deadline < cfg.steward.facts.freshness_days.other
    deadline = make_fact(
        store,
        "The proof is due Friday.",
        days_old=days,
        cfg=cfg,
        on=(today(store, cfg)).isoformat(),
        on_kind="deadline",
    )
    other = make_fact(store, "The cover proof is approved.", days_old=days, cfg=cfg)
    (late,) = named(checked(store, cfg, draft(OTHER["full_name"], facts=[deadline, other]))[2], "stale-fact")
    assert "The proof is due Friday." in late.message
    cfg.steward.facts.freshness_days.deadline = 0
    assert named(checked(store, cfg, draft(OTHER["full_name"], facts=[deadline]))[2], "stale-fact") == []


def test_a_stale_fact_in_a_draft_to_the_person_themselves_is_returned_but_never_held(app):  # noqa: F811
    _, store, cfg, _ = app
    old = make_fact(store, "The cover proof is approved.", days_old=cfg.steward.facts.freshness_days.other + 1, cfg=cfg)
    ctx, cs, problems = checked(store, cfg, draft(PM_NAME, facts=[old]))
    (late,) = named(problems, "stale-fact")
    assert not _held_after_return(cs.ops[0], [late], ctx)


def test_the_severity_is_a_setting_and_every_kind_has_a_limit_with_a_description(app):  # noqa: F811
    _, store, cfg, _ = app
    old = make_fact(store, "The cover proof is approved.", days_old=cfg.steward.facts.freshness_days.other + 1, cfg=cfg)
    cfg.checks.lints["stale-fact"] = "off"
    assert named(checked(store, cfg, draft(OTHER["full_name"], facts=[old]))[2], "stale-fact") == []
    for name, field in FreshnessDaysSettings.model_fields.items():
        assert field.description and field.default > 0, name
        assert limit_days(cfg, {"on_kind": name if name != "other" else None}) == getattr(
            cfg.steward.facts.freshness_days, name
        )


# ---- S-0547: a pause the person states holds until they say it is ready ----------------------------------------------

SPEC_LINE = "The spec is mid-edit; the review waits until I say it is ready."
ASK = {
    "op": "question.add",
    "would_change": {"what": "setting", "setting": "ui.today.stale_after_days"},
    "to": OTHER["full_name"],
    "title": "Is the spec final?",
    "matters_for": "The date the spec goes out",
    "project": PROJECT,
    "links": [fixture_records(DEMO_B, "project")[0]["links"][0]],
}


def pause_op(target, **more):
    return {
        "op": "rule.add",
        "text": "The spec is mid-edit; wait until I say it is ready.",
        "pauses": target,
        "until": "I say the spec is ready",
        **more,
    }


def paused_problems(store, cfg, src, op):
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(request(store, "input", source=src), src, LINE, "", "untrusted"),
    )
    return named(check(cs, ctx), "paused")


def stated_pause(store, cfg, target):
    cs_id, statuses = apply(store, cfg, [pause_op(target)], origin="pm")
    assert statuses == ["applied"], statuses
    return store.read().get("changeset", cs_id).data["ops"][0]["records"][0]["id"]


def test_a_stated_pause_is_an_active_rule_that_every_run_reads_with_its_end_condition(app):  # noqa: F811
    from engine.knowledge_section import stable_section

    _, store, cfg, _ = app
    spec = source(store, title="The spec")
    rule_id = stated_pause(store, cfg, spec)
    rule = store.read().get("rule", rule_id).data
    assert (rule["status"], rule["pauses"], rule["until"]) == ("active", spec, "I say the spec is ready")
    text = stable_section(store.read(), "notes", cfg.dispatch.knowledge).text
    assert rule_id in text and spec in text and "I say the spec is ready" in text


def test_a_pause_needs_a_record_that_exists_and_an_end_and_never_starts_from_outside_content(app):  # noqa: F811
    _, store, cfg, _ = app
    spec = source(store)
    cs_id, statuses = apply(store, cfg, [pause_op("SRC-9999")], origin="pm")
    assert statuses == ["refused"]
    try:
        CHANGESET.validate_python(
            {"ops": [{**pause_op(spec), "until": None}]}, context={"op_models": store.plugins.ops}
        )
    except ValueError as err:
        assert "both or neither" in str(err)
    else:
        raise AssertionError("a pause with no end was accepted")
    outside, _ = from_outside(store, cfg, [pause_op(spec)])
    (touched,) = store.read().get("changeset", outside).data["ops"][0]["records"]
    assert store.read().get("rule", touched["id"]).data["status"] == "proposed"
    assert paused_problems(store, cfg, spec, ASK) == []


def test_while_paused_a_change_to_the_document_yields_a_fact_and_no_question(app):  # noqa: F811
    _, store, cfg, _ = app
    spec = source(store, title="The spec")
    rule_id = stated_pause(store, cfg, spec)
    (hit,) = paused_problems(store, cfg, spec, ASK)
    assert hit.severity == "refuse" and rule_id in hit.message and "I say the spec is ready" in hit.message
    assert paused_problems(store, cfg, spec, fact()) == []
    cs_id, statuses = apply(store, cfg, [fact(), ASK], origin="input", trust="untrusted", source_id=spec, raw=LINE)
    assert statuses == ["applied", "refused"]


def test_a_later_version_of_the_same_watched_document_is_paused_too_and_another_document_is_not(app):  # noqa: F811
    _, store, cfg, _ = app
    watched = {"source": "docs", "key": "spec", "change": "changed"}
    first = source(store, watched=watched)
    later = source(store, watched=watched)
    elsewhere = source(store, watched={**watched, "key": "other"})
    stated_pause(store, cfg, first)
    assert len(paused_problems(store, cfg, later, ASK)) == 1
    assert paused_problems(store, cfg, elsewhere, ASK) == []


def test_the_persons_own_question_is_never_held_by_their_pause(app):  # noqa: F811
    _, store, cfg, _ = app
    spec = source(store)
    stated_pause(store, cfg, spec)
    cs_id, _ = apply(store, cfg, [ASK], origin="pm", source_id=spec)
    assert not any("held while" in (why or "") for why in reasons(store, cs_id))


def test_the_persons_ready_ends_the_pause_and_the_review_runs(app):  # noqa: F811
    _, store, cfg, _ = app
    spec = source(store, title="The spec")
    rule_id = stated_pause(store, cfg, spec)
    assert paused_problems(store, cfg, spec, ASK)
    before = {r.id for r in store.read().list("request")}
    _, statuses = apply(store, cfg, [{"op": "rule.retire", "id": rule_id}], origin="pm")
    assert statuses == ["applied"] and store.read().get("rule", rule_id).data["status"] == "retired"
    (review,) = [r for r in store.read().list("request") if r.id not in before and r.data["origin"] == "input"]
    assert paused_problems(store, cfg, spec, ASK) == []
    assert (review.data["task"], review.data["source"], review.data["state"]) == ("notes", spec, "queued")


def test_the_golden_case_passes_with_a_fact_only_and_fails_when_the_assistant_asks_about_the_paused_document(tmp_path):
    import shutil

    from engine.evaluate import evaluate

    only = ["paused-document-change-is-a-fact-only"]
    result = evaluate(DEMO_B, stub=True, runs=1, env={}, only=only).results[0]
    assert result.passed, (result.missing, result.forbidden, result.got)
    copy = tmp_path / "template"
    shutil.copytree(DEMO_B, copy)
    path = copy / "evals" / f"{only[0]}.yaml"
    asking = (
        f"  - op: question.add\n    to: {PM_NAME}\n    title: Is the paper section final?\n"
        f"    text: The spec says TBD for paper, so say whether it is final\n    project: {PROJECT}\n"
        "    would_change: {what: setting, setting: ui.today.stale_after_days}\n    matters_for: The print order\n"
    )
    path.write_text(path.read_text().rstrip("\n") + "\n" + asking)
    assert not evaluate(copy, stub=True, runs=1, env={}, only=only).results[0].passed
