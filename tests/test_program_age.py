"""An agent program older than the versions the catalog says were tested is named with how to update it, in the
account's check at setup and in an account's Test; a program in the range, a newer one or one that can't say adds
nothing, and an older program still passes."""

from __future__ import annotations

import os

from engine.ai import key_check
from engine.ai.program_age import cleaned_tested, older_note, read_version
from engine.ai.task import AiResult
from engine.config import load_config
from engine.config.schema import ProviderSettings
from engine.setup import known_endpoints
from tests.conftest import DEMO_B
from tests.test_first_run_ai import connection_answer

ENTRY = {
    "name": "Some Agent",
    "tested_versions": {"oldest": "2.1.326", "newest": "2.1.332"},
    "update_hint": "the package manager's upgrade, or its own update for a native install",
}


def test_an_older_version_says_so_with_how_to_update():
    note = older_note(ENTRY, "2.1.285 (Some Agent)")
    assert note == (
        "Some Agent 2.1.285 is older than the tested 2.1.326: update it with "
        "the package manager's upgrade, or its own update for a native install."
    )


def test_a_version_in_the_range_or_newer_or_unreadable_says_nothing():
    for line in ("2.1.326 (Some Agent)", "2.1.330", "2.1.332", "2.2.0", "3.0", "2.1.1000", None, "", "no number here"):
        assert older_note(ENTRY, line) is None, line


def test_versions_compare_as_numbers_not_text():
    assert older_note(ENTRY, "2.1.99") is not None  # 99 < 326 as numbers
    assert older_note(ENTRY, "2.0.9999") is not None
    assert older_note(ENTRY, "2.1.1000") is None  # "1000" < "326" as text


def test_an_entry_without_a_readable_range_or_hint_says_nothing():
    assert older_note(None, "1.0.0") is None
    assert older_note({**ENTRY, "tested_versions": {"oldest": "soon", "newest": "2.1.332"}}, "1.0.0") is None
    assert older_note({**ENTRY, "tested_versions": {}}, "1.0.0") is None
    assert older_note({**ENTRY, "update_hint": ""}, "1.0.0") is None
    assert read_version("v2.1.285-beta")[1] == (2, 1, 285)
    assert cleaned_tested({"oldest": "2.1.326"}) == {}


def test_the_command_line_agents_catalog_entry_states_its_tested_range_and_how_to_update():
    entry = next(e for e in known_endpoints() if e["adapter"] == "cli-agent" and e["tested_versions"])
    oldest, newest = (read_version(entry["tested_versions"][k])[1] for k in ("oldest", "newest"))
    assert oldest <= newest
    assert entry["update_hint"]
    assert older_note(entry, entry["tested_versions"]["oldest"]) is None
    assert older_note(entry, "0.0.1") is not None


def _check(version):
    class Agent:
        def __init__(self, settings, secret=None):
            pass

        def run(self, task, model):
            return AiResult(text=connection_answer(task), model_served=model, seconds=0.0)

        def identity(self):
            return None

        def lockdown_test(self, model):
            return []

        def program_version(self):
            return version

    cfg = load_config(DEMO_B / "config", env={})
    settings = ProviderSettings(adapter="agent-x", models={"everyday": "m"})
    return key_check.check_account(
        cfg, os.environ, settings, None, adapter_factory=lambda name, s, secret: Agent(s), entry=ENTRY
    )


def test_setups_check_of_an_older_program_passes_with_the_advice_and_a_tested_one_has_none():
    old = _check("2.1.285 (Some Agent)")
    assert old.ok and old.program_note and "2.1.285" in old.program_note and "2.1.326" in old.program_note
    assert _check("2.1.330 (Some Agent)").program_note is None
    assert _check(None).program_note is None


def _agent_workspace(tmp_path, monkeypatch, version):
    """A workspace with a saved account of the catalog's command-line agent kind, whose program reports `version`."""
    import yaml

    from engine.ai import adapters, smoke
    from tests.test_setup import client, make

    kind = next(e for e in known_endpoints() if e["adapter"] == "cli-agent" and e["tested_versions"])
    ws, cfg, store = make(tmp_path)
    path = ws.config_dir / "ai.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["providers"]["prog"] = {**kind["settings"], "adapter": "cli-agent", "kind": kind["id"], "models": {"m": "m"}}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    class Program:
        def program_version(self):
            return version

    monkeypatch.setattr(adapters, "make_adapter", lambda *a, **k: Program())
    monkeypatch.setattr(smoke, "account_test", lambda *a, **k: [])
    c, api = client(ws, load_config(ws.config_dir, env={}), store)
    return c, api, kind


def test_an_accounts_test_names_an_older_program_and_still_passes(tmp_path, monkeypatch):
    c, api, kind = _agent_workspace(tmp_path, monkeypatch, "2.1.285 (Some Agent)")
    line = c.post(f"{api}/ai/accounts/prog/test").json()[0]
    assert line["ok"] is True and line["detail"] == "answered"
    assert line["program_note"].startswith(f"{kind['name']} 2.1.285 is older than the tested 2.1.326: update it with ")
    assert kind["update_hint"] in line["program_note"]


def test_an_accounts_test_of_a_tested_program_says_nothing_extra(tmp_path, monkeypatch):
    c, api, _ = _agent_workspace(tmp_path, monkeypatch, "2.1.332 (Some Agent)")
    assert c.post(f"{api}/ai/accounts/prog/test").json()[0]["program_note"] is None
