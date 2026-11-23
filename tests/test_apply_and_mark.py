"""Applying a run and marking its request done are one step (design 6.14): a stop between the change and the mark runs
nothing again, and an answer received but not yet applied is applied on the next start, not asked for again."""

from __future__ import annotations

import pytest

from engine.ai.adapters.stub import set_responder
from engine.worker import APPLYING_KEPT_ANSWER, requeue_interrupted
from tests.test_silent_stops import ANSWER, Scripted, data, env, hand, worker_of  # noqa: F401  (fixtures and helpers)


class Killed(BaseException):
    """A stop of the whole process: not an error the code can catch and handle."""


def changesets_of(env, request: str) -> list:  # noqa: F811
    return [c for c in env[2].read().find("changeset", {}) if c.data.get("request") == request]


def test_a_stop_after_the_change_is_committed_runs_nothing_again(env, monkeypatch):  # noqa: F811
    provider = Scripted(ANSWER)
    set_responder(provider)
    request = hand(env)

    def stop(*_a, **_k):
        raise Killed

    monkeypatch.setattr("engine.dispatcher.record_applied", stop)  # the first thing after the change was committed
    with pytest.raises(Killed):
        worker_of(env).run_pending()
    monkeypatch.undo()
    # The mark was part of the change's own transaction: the request is already with the person, answer cleared.
    after = data(env, request)
    assert after["state"] == "review" and after["held_answer"] is None and after["changeset"]
    assert requeue_interrupted(env[2]) == ([], [])
    worker_of(env).run_pending()
    assert provider.calls == 1 and len(changesets_of(env, request)) == 1
    # The kept answer leaves no copy of its words in the request's history.
    kept = [e for e in env[2].read().ledger(kind="request", record_id=request) if e.get("field") == "held_answer"]
    assert kept and all(e["before"] in (None, "null") and e["after"] in (None, "null") for e in kept)


def test_an_answer_received_but_not_applied_is_applied_on_restart_without_asking_again(env, monkeypatch):  # noqa: F811
    provider = Scripted(ANSWER)
    set_responder(provider)
    request = hand(env)

    def stop(*_a, **_k):
        raise Killed

    monkeypatch.setattr("engine.dispatcher.apply_changeset", stop)  # the process dies as the change would be applied
    with pytest.raises(Killed):
        worker_of(env).run_pending()
    monkeypatch.undo()
    stuck = data(env, request)
    assert stuck["state"] == "running" and stuck["held_answer"]["changeset"]["summary"] == "Nothing to do."
    assert changesets_of(env, request) == []
    attempts = stuck["attempts"]

    queued, held = requeue_interrupted(env[2])
    assert queued == [request] and held == []
    assert data(env, request)["waiting"] == APPLYING_KEPT_ANSWER
    worker_of(env).run_pending()
    after = data(env, request)
    assert provider.calls == 1, "the answer was kept, so nothing is asked or charged a second time"
    assert after["state"] in ("review", "done") and after["held_answer"] is None
    assert len(changesets_of(env, request)) == 1 and after["attempts"] == attempts
    # A second stop in the same place is still no second "interruption": the answer is what is waiting.
    assert requeue_interrupted(env[2]) == ([], [])


def test_a_change_that_fails_clears_the_kept_answer_so_the_retry_asks_again(env, monkeypatch):  # noqa: F811
    from engine.applier import ChangeFailed

    provider = Scripted(ANSWER)
    set_responder(provider)
    request = hand(env)
    real = __import__("engine.dispatcher", fromlist=["x"]).apply_changeset
    boom = {"once": True}

    def apply(*a, **k):
        if boom.pop("once", False):
            raise ChangeFailed("CS-0", "a step failed")
        return real(*a, **k)

    monkeypatch.setattr("engine.dispatcher.apply_changeset", apply)
    worker_of(env).run_pending()
    assert data(env, request)["held_answer"] is None
