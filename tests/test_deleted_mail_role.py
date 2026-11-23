"""A sign-in source's role: parsing, the deleted source's reading (packet), and the refusal of a to-do from it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import evaluate as ev
from engine.ai.adapters import stub
from engine.config import load_config
from engine.plugin_api import PLUGIN_API_VERSION
from tests.conftest import fixture_records
from tests.test_sign_in import AUTH
from tests.test_sign_in import signing as signing  # noqa: F401 - the fixture
from tests.test_sign_in_sources import READING, _app, _with_sources, sign_in, sources

DEMO = Path(__file__).resolve().parent.parent / "workspaces" / "demo-a"
CASE = "deleted-booking-confirmation-reaches-the-schedule-no-todo"


def _declare(registrar, entry, name="p18/other"):
    registrar.sign_in(
        name,
        label="Other",
        authorize_url=f"{AUTH}/authorize",
        token_url=f"{AUTH}/token",
        scopes=["read"],
        sources=[entry],
    )
    return registrar.sign_ins[name].sources[0]


def _one(**more):
    return {"connector": "p18/inbox", "label": "Mail", **more}


def test_the_version_is_the_one_with_roles():
    assert PLUGIN_API_VERSION == "0.3.107"


def test_a_role_is_kept_and_the_old_sent_flag_reads_as_the_sent_role(signing):  # noqa: F811
    registrar = signing[2].plugins.registrars["p18"]
    plain = _declare(registrar, _one(), "p18/a")
    sent_flag = _declare(registrar, _one(sent=True), "p18/b")
    sent_role = _declare(registrar, _one(role="sent"), "p18/c")
    deleted = _declare(registrar, _one(role="deleted"), "p18/d")
    assert (plain["role"], plain["sent"]) == (None, False)
    assert (sent_flag["role"], sent_flag["sent"]) == ("sent", True)
    assert (sent_role["role"], sent_role["sent"]) == ("sent", True)
    assert (deleted["role"], deleted["sent"]) == ("deleted", False)


@pytest.mark.parametrize("bad", [{"role": "archived"}, {"role": 3}, {"sent": True, "role": "deleted"}])
def test_a_bad_role_is_refused(signing, bad):  # noqa: F811
    with pytest.raises(ValueError):
        _declare(signing[2].plugins.registrars["p18"], _one(**bad))


READING_DELETED = READING.replace(
    '"settings": {"folders": ["INBOX"]}}],',
    '"settings": {"folders": ["INBOX"]}},\n'
    '        {"connector": "p18/inbox", "label": "Your deleted mail", "settings": {"folders": ["TRASH"]}, '
    '"role": "deleted"}],',
)


def test_signing_in_starts_a_deleted_source_beside_the_inbox_once_with_no_look_back(signing):  # noqa: F811
    from engine import source_intake

    ws, cfg, store = signing[:3]
    store.close()
    _with_sources(ws, READING_DELETED)
    c, api = _app(ws, cfg)
    sign_in(c, api)
    inbox = [s for s in sources(ws) if s["label"] == "Your inbox"]
    deleted = [s for s in sources(ws) if s["label"] == "Your deleted mail"]
    assert len(inbox) == 1 and len(deleted) == 1
    assert deleted[0]["role"] == "deleted" and deleted[0]["first_run"] == "intake"
    assert deleted[0].get("author") is None and inbox[0].get("role") is None
    sign_in(c, api)
    assert c.post(f"{api}/sign-ins/p18/service/sources").status_code == 200
    assert len([s for s in sources(ws) if s["label"] == "Your deleted mail"]) == 1
    watch = load_config(ws.config_dir, env={}).watch.sources
    assert not source_intake.can_look_back(next(s for s in watch if s.role == "deleted"))


def _requests_of(monkeypatch) -> tuple[str, object]:
    seen: list[str] = []

    def spy(responder):
        if responder is None:
            return stub.set_responder(None)

        def wrapped(task):
            seen.append(task.request)
            return responder(task)

        stub.set_responder(wrapped)

    monkeypatch.setattr(ev, "set_responder", spy)
    report = ev.evaluate(DEMO, stub=True, runs=1, only=[CASE])
    return "\n".join(seen), report


def test_a_deleted_sources_packet_says_schedule_and_learning_only(monkeypatch):
    text, report = _requests_of(monkeypatch)
    assert report.results and all(r.passed for r in report.results)
    assert "deleted by the user" in text and "never to find work" in text
    assert "read to learn about the user's life" not in text


def test_an_action_from_deleted_mail_is_refused_by_the_checks(monkeypatch):
    from engine import applier

    seen = {}
    real = applier.check

    def spy(cs, ctx):
        problems = real(cs, ctx)
        seen["checks"] = [p.check for p in problems]
        return problems

    monkeypatch.setattr(applier, "check", spy)
    owner = fixture_records(DEMO, "person")[0]["id"]
    op = {
        "op": "action.add",
        "text": "Confirm the appointment at Harbor Dental",
        "owners": [owner],
        "evidence": {"quote": "Please confirm your appointment by replying to this message."},
    }
    answer = json.dumps({"summary": "x", "ops": [op]})
    monkeypatch.setattr(
        ev, "set_responder", lambda responder: stub.set_responder(None if responder is None else (lambda task: answer))
    )
    ev.evaluate(DEMO, stub=True, runs=1, only=[CASE])
    assert "from-deleted-mail" in seen["checks"]
