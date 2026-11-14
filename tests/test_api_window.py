"""The window across one minor plugin API release (design 3.3): a pack built for the previous minor stays on, marked."""

import pytest

from engine import api_window, pack_check
from engine.plugin_api import PLUGIN_API_COMPAT, PLUGIN_API_VERSION
from engine.storage import Store
from tests.test_plugins import config, make_plugin

EARLIER = f">={PLUGIN_API_COMPAT},<{PLUGIN_API_VERSION.rsplit('.', 1)[0]}"


def _status(tmp_path, plugin_api):
    make_plugin(tmp_path, edits=lambda d: d.update(plugin_api=plugin_api))
    store = Store(tmp_path / "db", cfg=config(tmp_path, ["scratch"]))
    try:
        return store.plugins.status["scratch"]
    finally:
        store.close()


def test_a_pack_for_the_previous_minor_stays_on_and_says_so(tmp_path):
    status = _status(tmp_path, EARLIER)
    assert status.state == "enabled", status.reason
    assert api_window.EARLIER_NOTE in status.notes


def test_a_pack_for_the_current_minor_carries_no_note(tmp_path):
    status = _status(tmp_path, f">={PLUGIN_API_VERSION.rsplit('.', 1)[0]},<0.4")
    assert status.state == "enabled" and api_window.EARLIER_NOTE not in status.notes


@pytest.mark.parametrize("plugin_api", [">=0.1,<0.2", ">=0.4,<0.5", ">=2"])
def test_a_pack_outside_the_window_is_refused_saying_what_it_needs(tmp_path, plugin_api):
    status = _status(tmp_path, plugin_api)
    assert status.state == "disabled"
    assert plugin_api in status.reason and PLUGIN_API_VERSION in status.reason


def test_the_window_is_one_minor_back_when_the_core_moves_on():
    # On a 0.4 core serving 0.3: a pack ending at <0.4 stays, one ending at <0.3 does not.
    assert api_window.served(">=0.3,<0.4", "0.4.0", "0.3") == "earlier"
    assert api_window.served(">=0.2,<0.3", "0.4.0", "0.3") == "outside"
    assert api_window.served(">=0.4,<0.5", "0.4.0", "0.3") == "current"
    assert api_window.served("not a range") == "outside"
    assert api_window.served(">=0.3,<0.4", "0.4.0", "") == "outside"


def test_pack_check_passes_an_earlier_pack_with_the_note(tmp_path):
    root = make_plugin(tmp_path, edits=lambda d: d.update(plugin_api=EARLIER))
    report = pack_check.check(root)
    assert any("earlier version" in line for line in report.passed)
    assert not any("plugin_api" in line for line in report.failed)
