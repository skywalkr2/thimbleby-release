"""What goes out to other people (design 6.12): a message can't be approved without a subject the person saw, nothing
credits the assistant unless the name is someone in People or a recipient (the colleague who shares it is one click),
renaming the assistant after someone in People warns, and a message drafted from a run's inputs is held to their
audience. Names, ids and addresses come from the fixtures; addresses are on example.com."""

from __future__ import annotations

import pytest

from engine import acts, outward
from engine.applier import check
from engine.storage import StoreError, WriteContext
from tests.test_publisher import api, env  # noqa: F401  (the fixtures)

_TEST = WriteContext(actor="pm", trust="trusted", op="test.credit")
CREDITING = (
    "{name} says the date moved",
    "According to {name}, the date moved",
    "{name}'s analysis shows it slips",
    "Drafted with {name}",
    "Drafted by {name}",
    "Per {name}, it slips",
)
PLAIN = ("I'll copy {name} from accounts", "Can we meet on Monday, {name}?", "Ask {name} about the meeting")


# ---- S-0698: no subject ---------------------------------------------------------------------------------------------


def test_a_message_without_a_subject_cannot_be_approved_and_the_channel_never_adds_one(env):  # noqa: F811
    bare = env.draft(parts={"body": "The proofs ship on Monday."})
    with pytest.raises(StoreError, match="no subject"):
        env.yes(bare)
    assert env.act(bare)["status"] == "draft"
    blank = env.draft(parts={"subject": "   ", "body": "The proofs ship on Monday."})
    with pytest.raises(StoreError, match="no subject"):
        env.yes(blank)
    # once the person writes one, it can be approved and goes out as written
    env.person_op(
        "act.edit",
        bare,
        read_version=env.store.read().get("act", bare).version,
        parts={"subject": "Proofs", "body": "Monday."},
    )
    env.yes(bare)
    assert env.act(bare)["status"] == "approved"


def test_a_subject_of_only_invisible_characters_is_no_subject(env):  # noqa: F811
    """S-0728: zero-width, joiner, Braille-blank and Hangul-filler characters draw nothing, so they are no subject."""
    for blank in (
        "\u200b",
        "\u200b \u200d\ufeff",
        "\u2800",
        "\u3164 ",
        "\u00a0\u2060",
        "\u034f",
        "\u17b4",
        "\ufe0f",
        "\u034f\ufe0f \u17b4",
    ):
        draft = env.draft(parts={"subject": blank, "body": "The proofs ship on Monday."})
        with pytest.raises(StoreError, match="no subject"):
            env.yes(draft)
        op = env.message(parts={"subject": blank, "body": "Monday."})
        changeset, ctx = env.as_assistant([op], trust="trusted", origin="pm")
        assert [p for p in check(changeset, ctx) if p.check == "message-without-subject"], repr(blank)
    assert (
        acts.has_text("Proofs")
        and acts.has_text("\u200bProofs")
        and acts.has_text("e\u0301")
        and acts.has_text("\u2764\ufe0f")
    )


def test_the_mailbox_channel_refuses_a_message_with_no_subject_instead_of_adding_one():
    import engine.channels_mailbox as module

    with open(module.__file__, encoding="utf-8") as source:
        assert "(no subject)" not in source.read()


def test_an_assistants_draft_with_no_subject_is_returned_with_the_reason(env):  # noqa: F811
    op = env.message(parts={"body": "The proofs ship on Monday."})
    changeset, ctx = env.as_assistant([op], trust="trusted", origin="pm")
    found = [p for p in check(changeset, ctx) if p.check == "message-without-subject"]
    assert found and "subject" in found[0].message
    with_one, ctx = env.as_assistant([env.message()], trust="trusted", origin="pm")
    assert not [p for p in check(with_one, ctx) if p.check == "message-without-subject"]


# ---- S-0690: crediting the assistant --------------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", CREDITING)
def test_each_crediting_phrase_waits_with_the_name_the_person_can_say_is_a_person(env, phrase):  # noqa: F811
    name = env.cfg.workspace.assistant_name
    draft = env.draft(parts={"subject": "Dates", "body": phrase.format(name=name)})
    data = env.act(draft)
    assert acts.name_problem(env.store.read(), env.cfg, data) is not None
    assert acts.credited_name(env.store.read(), env.cfg, data) == name
    with pytest.raises(StoreError, match="Held back"):
        env.yes(draft)


@pytest.mark.parametrize("phrase", PLAIN)
def test_a_plain_mention_goes(env, phrase):  # noqa: F811
    name = env.cfg.workspace.assistant_name
    draft = env.draft(parts={"subject": "Dates", "body": phrase.format(name=name)})
    assert acts.name_problem(env.store.read(), env.cfg, env.act(draft)) is None
    env.yes(draft)
    assert env.act(draft)["status"] == "approved"


def test_a_name_that_is_someone_in_people_is_theirs_and_credits_nothing(env):  # noqa: F811
    name = env.cfg.workspace.assistant_name
    view = env.store.read()
    assert outward.crediting_name(view, env.cfg, f"{name} says it slips") == name
    with env.store.transaction() as tx:
        tx.create("person", {"full_name": f"{name} Archer"}, _TEST)
    assert outward.crediting_name(env.store.read(), env.cfg, f"{name} says it slips") is None
    draft = env.draft(parts={"subject": "Dates", "body": f"{name} says the date moved"})
    env.yes(draft)
    assert env.act(draft)["status"] == "approved"


def test_a_recipient_with_the_name_in_their_address_is_not_the_assistant(env):  # noqa: F811
    name = env.cfg.workspace.assistant_name
    text = f"According to {name}, the date moved"
    assert outward.crediting_name(env.store.read(), env.cfg, text) == name
    named = acts.recipient_names(
        env.store.read(), {"target": {"recipients": [{"person": None, "address": f"{name.lower()}.smith@example.com"}]}}
    )
    assert outward.crediting_name(env.store.read(), env.cfg, text, recipients=named) is None


def test_saying_the_name_is_a_person_adds_them_to_people_and_releases_the_message(api):  # noqa: F811
    client = api
    name = client.cfg.workspace.assistant_name
    op = {
        "op": "act.draft",
        "channel": "fake",
        "target": {"kind": "message", "recipients": [{"person": client.person, "kind": "email"}]},
        "parts": {"subject": "Dates", "body": f"{name} says the date moved"},
    }
    made = client.post(
        "/api/acts",
        json={"kind": "message", "recipients": [{"person": client.person, "kind": "email"}], "parts": op["parts"]},
    )
    assert made.status_code == 200, made.text
    shown = made.json()
    assert shown["withheld"] and shown["credited_name"] == name
    people_before = len(client.store.read().list("person"))
    freed = client.post(f"/api/acts/{shown['id']}/name-is-a-person")
    assert freed.status_code == 200, freed.text
    assert freed.json()["withheld"] is None and freed.json()["credited_name"] is None
    assert len(client.store.read().list("person")) == people_before + 1
    # nothing was sent by it: the person's yes is still asked
    assert client.fake.calls == [] and freed.json()["status"] == "draft"
    nothing = client.post(f"/api/acts/{shown['id']}/name-is-a-person")
    assert nothing.status_code == 409


def test_the_person_can_reword_a_draft_and_it_needs_a_new_yes(api):  # noqa: F811
    client = api
    name = client.cfg.workspace.assistant_name
    made = client.post(
        "/api/acts",
        json={
            "kind": "message",
            "recipients": [{"person": client.person, "kind": "email"}],
            "parts": {"subject": "Dates", "body": f"According to {name}, it slips"},
        },
    ).json()
    reworded = client.post(
        f"/api/acts/{made['id']}/edit",
        json={"read_version": made["version"], "parts": {"subject": "Dates", "body": "It slips by a week."}},
    )
    assert reworded.status_code == 200, reworded.text
    assert reworded.json()["withheld"] is None and reworded.json()["parts"]["body"] == "It slips by a week."
    stale = client.post(
        f"/api/acts/{made['id']}/edit", json={"read_version": made["version"], "parts": {"subject": "x", "body": "y"}}
    )
    assert stale.status_code == 409


def test_naming_the_assistant_after_someone_in_people_warns_and_keeps_the_name(env):  # noqa: F811
    someone = env.name(env.ana)
    kept = outward.name_warnings(
        env.store.read(), env.cfg, [{"key": outward.NAME_KEY, "before": "an earlier name", "after": someone}]
    )
    assert kept == [env.cfg.language.messages.assistant_named_like_person.format(name=someone)]
    assert not outward.name_warnings(
        env.store.read(), env.cfg, [{"key": outward.NAME_KEY, "before": "an earlier name", "after": "Zephyrine"}]
    )
    assert not outward.name_warnings(env.store.read(), env.cfg, [{"key": "workspace.name", "after": someone}])


# ---- S-0690: restriction of a run's inputs --------------------------------------------------------------------------


def test_a_message_drafted_from_a_limited_input_cannot_go_to_someone_outside_its_audience(env):  # noqa: F811
    with env.store.transaction() as tx:
        limited = tx.create(
            "source",
            {
                "received_at": env.clock.text(),
                "kind": "pasted",
                "title": "A limited message",
                "content_hash": "0" * 64,
                "trust": "trusted",
                "audience": {"people": [env.pm, env.ana]},
            },
            _TEST,
        )
    # the assistant lists no source at all, but the run was handed the limited input
    changeset, ctx = env.as_assistant([env.message(to=[env.ben])], trust="trusted", origin="pm")
    ctx.inputs = type(ctx.inputs)(ctx.inputs.request, limited.id, "", "", "trusted")
    problems = [p for p in check(changeset, ctx) if p.severity == "refuse"]
    assert {p.check for p in problems} == {"audience"}, problems
    inside, ctx = env.as_assistant([env.message(to=[env.ana])], trust="trusted", origin="pm")
    ctx.inputs = type(ctx.inputs)(ctx.inputs.request, limited.id, "", "", "trusted")
    assert not [p for p in check(inside, ctx) if p.severity == "refuse"]
