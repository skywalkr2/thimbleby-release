"""A stopped request's cause on What changed: one the screen has no single action for is not drawn, never an error."""

from api.routes import _cause_view


def _stopped(cause):
    return {"state": "needs_you", "cause": cause}


def test_a_cause_with_an_action_is_shown():
    shown = _cause_view(_stopped({"kind": "data_level", "level": "restricted", "accounts": ["main/standard"]}))
    assert shown is not None and shown.kind == "data_level" and shown.account == "main"
    assert _cause_view(_stopped({"kind": "no_person"})).kind == "no_person"


def test_a_request_stopped_for_having_no_ai_account_is_not_an_error_on_the_screen():
    """S-0375 (X60): what changed answered 500 for a request that stopped because no AI account was set up."""
    for kind in ("no_account", "paused", "retry", "offline", "identity", "no_fit"):
        assert _cause_view(_stopped({"kind": kind})) is None
