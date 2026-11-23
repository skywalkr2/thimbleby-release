"""No network is never a failure (design 6.16): a command-line program's offline wording classifies as offline (after
its color codes are removed), a plan limit pauses the account whether colored or printed as an answer with exit code 0,
and an add-on job that finds no network is not counted toward turning the add-on off."""

from __future__ import annotations

import pytest

from engine.ai.adapters.cli_agent import CliAgentAdapter
from engine.ai.task import AiError, AiTask
from engine.config.schema import AgentSettings, ProviderSettings

SETTINGS = ProviderSettings(
    adapter=CliAgentAdapter.name, models={"default": "m"}, agent=AgentSettings(command=["agent"])
)


def adapter() -> CliAgentAdapter:
    return CliAgentAdapter(SETTINGS)


@pytest.mark.parametrize(
    "stream",
    [
        "Error: getaddrinfo ENOTFOUND api.example.com",
        "TypeError: fetch failed",
        "curl: (6) Could not resolve host: api.example.com",
        "Error: connect ETIMEDOUT 203.0.113.9:443",
        "\x1b[31mError:\x1b[0m getaddrinfo \x1b[1mENOTFOUND\x1b[0m api.example.com",
        "\x1b[31mfetch\x1b[0m \x1b[31mfailed\x1b[0m",
    ],
)
def test_each_offline_wording_is_offline_even_with_color_codes(stream):
    assert adapter().classify_error(1, stream, None).kind == "offline"


def test_a_colored_plan_limit_pauses_the_account_until_its_reset():
    error = adapter().classify_error(1, "\x1b[1mUsage limit\x1b[0m \x1b[31mreached\x1b[0m. Resets in 2 hours", None)
    assert error.kind == "quota"


def test_a_plan_limit_the_program_prints_as_its_answer_with_exit_code_0_is_the_limit(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text('print("\\x1b[31mUsage limit reached\\x1b[0m. Try again later.")\n')
    import sys

    s = ProviderSettings(
        adapter=CliAgentAdapter.name,
        models={"default": "m"},
        timeout_seconds=5,
        agent=AgentSettings(command=[sys.executable, str(script)]),
    )
    with pytest.raises(AiError) as stopped:
        CliAgentAdapter(s).run(AiTask("notes", "Do it.", "Stable.", "Request.", {}), "m")
    assert stopped.value.kind == "quota"


def test_an_answer_that_merely_mentions_a_limit_is_still_an_answer(tmp_path):
    import sys

    script = tmp_path / "agent.py"
    long = "The vendor's usage limit reached last week, so the plan was changed. " + "More detail. " * 80
    script.write_text(f"print({long!r})\n")
    s = ProviderSettings(
        adapter=CliAgentAdapter.name,
        models={"default": "m"},
        timeout_seconds=5,
        agent=AgentSettings(command=[sys.executable, str(script)]),
    )
    result = CliAgentAdapter(s).run(AiTask("notes", "Do it.", "Stable.", "Request.", {}, output="text"), "m")
    assert result.text.startswith("The vendor's usage limit")


def test_three_runs_of_a_job_with_no_network_leave_the_add_on_on(tmp_path):
    from dataclasses import replace

    from engine.connectors import ConnectorError
    from tests.test_plugin_api_0319 import staging_workspace

    ws, cfg, store = staging_workspace(tmp_path)
    try:
        registrar = store.plugins.registrars["p18"]

        def no_network(context):
            raise ConnectorError("offline", "couldn't connect")

        registrar.jobs["p18/tidy"] = replace(registrar.jobs["p18/tidy"], run=no_network)
        limit = store.plugins.cfg.workspace.plugins.failures_before_off
        for _ in range(limit + 2):
            assert store.plugins.run_job("p18/tidy") == "offline"
        assert store.plugins.active("p18"), "no network is not the add-on's failure"
        assert not store.plugins.status["p18"].notes
        assert store.plugins.last_job_run("p18/tidy").data["outcome"] == "offline"

        def broken(context):
            raise RuntimeError("its own bug")

        registrar.jobs["p18/tidy"] = replace(registrar.jobs["p18/tidy"], run=broken)
        for _ in range(limit):
            assert store.plugins.run_job("p18/tidy") == "failed"
        assert not store.plugins.active("p18"), "a real failure still counts: no network never counted before it"
    finally:
        store.close()
