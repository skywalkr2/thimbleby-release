"""Each command-line agent's own signed-out message is classified as a sign-in problem (design 6.16, P30).

The messages are captured from the real programs, signed out, into `tests/fixtures/agent_signed_out/<entry id>.txt`;
nothing is made up. An entry without a capture yet is an expected failure in the run, so the gap stays visible."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.ai.adapters.cli_agent import CliAgentAdapter
from engine.config.schema import ProviderSettings
from engine.setup import known_endpoints

CAPTURES = Path(__file__).parent / "fixtures" / "agent_signed_out"
AGENTS = {e["id"]: e for e in known_endpoints() if e["settings"].get("agent")}


def adapter(entry_id: str) -> CliAgentAdapter:
    settings = ProviderSettings(
        adapter=CliAgentAdapter.name, models={"default": "m"}, agent=dict(AGENTS[entry_id]["settings"]["agent"])
    )
    return CliAgentAdapter(settings)


def test_a_capture_belongs_to_an_entry_the_catalog_has():
    assert {p.stem for p in CAPTURES.glob("*.txt")} <= set(AGENTS)


@pytest.mark.parametrize("entry_id", sorted(AGENTS))
def test_a_captured_signed_out_message_is_a_sign_in_problem_with_the_entrys_hint(entry_id):
    """An entry with no capture yet is an expected gap, shown in every run until it is captured."""
    file = CAPTURES / f"{entry_id}.txt"
    if not file.is_file():
        pytest.xfail("not captured yet: someone runs the program signed out and saves what it printed (P30)")
    said = file.read_text(encoding="utf-8")
    error = adapter(entry_id).classify_error(1, said, None)
    assert error.kind == "auth"
    assert error.hint == AGENTS[entry_id]["settings"]["agent"]["sign_in_hint"]


def test_a_signed_out_message_the_entry_does_not_know_is_not_taken_for_a_sign_in():
    """A message no pattern knows is never guessed to be a sign-in: it is another failure, said in the agent's words."""
    knowing = next(i for i, e in AGENTS.items() if e["settings"]["agent"].get("errors", {}).get("auth"))
    error = adapter(knowing).classify_error(1, "something went wrong in a way nobody listed", None)
    assert error.kind == "other"
