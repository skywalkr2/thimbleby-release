"""The notice above Today while older mail is being read (design 6.32): when it shows."""

from __future__ import annotations

from types import SimpleNamespace

from engine.learning_notice import standing


def _view(*requests: dict) -> SimpleNamespace:
    return SimpleNamespace(list=lambda kind: [SimpleNamespace(data=d) for d in requests] if kind == "request" else [])


def test_it_shows_while_an_older_read_is_queued_or_running_with_how_far_along():
    found = standing(
        _view(
            {"intake_older": True, "state": "done"},
            {"intake_older": True, "state": "running"},
            {"intake_older": True, "state": "queued"},
        )
    )
    assert (found.active, found.read, found.of) == (True, 1, 3)


def test_it_does_not_show_when_no_older_read_is_under_way():
    assert not standing(_view()).active
    assert not standing(_view({"intake_older": True, "state": "done"})).active
    # The first window and other work never count; a go still to give, a stopped or a dismissed read is not under way.
    assert not standing(_view({"intake": "S-1", "state": "running"})).active
    assert not standing(_view({"intake_older": True, "state": "needs_you"})).active
    assert not standing(_view({"intake_older": True, "state": "running", "dismissed": True})).active
