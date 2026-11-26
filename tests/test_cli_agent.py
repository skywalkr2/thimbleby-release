"""The command-line agent adapter: a program run locked down in its own folder, its answer read from its output or its
outbox, its errors read from its exit code and error stream only, and a lockdown test in the smoke test."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import content_log
from engine.ai.adapters import make_adapter
from engine.ai.adapters.cli_agent import EARLIER_HOME_FILES, CliAgentAdapter
from engine.ai.task import AiError, AiTask
from engine.config.schema import AgentSettings, ProviderSettings

FAKE_AGENT = r"""
import json, os, re, sys, time
mode = sys.argv[1]
prompt = sys.stdin.read()
paths = re.findall(r"((?:/|\b[\w.-]+/)\S*?\.(?:txt|json|md))\b", prompt)  # whole, or from the working folder
if mode == "stdout":
    print('{"ok": true}')
elif mode == "says-signed-out":
    print("not logged in")
elif mode == "json":
    print(json.dumps({"result": "drafted", "model": "served-model", "usage": {"input_tokens": 12, "output_tokens": 5},
                      "total_cost_usd": 0.02}))
elif mode == "outbox":
    open(paths[-1], "w").write('{"ok": true}')
elif mode == "silent":
    pass
elif mode == "signed-out":
    print("Please sign in again", file=sys.stderr)
    sys.exit(1)
elif mode == "reports-on-output":
    print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in. Please run the login command"}))
    sys.exit(1)
elif mode == "limit":
    sys.exit(7)
elif mode == "banner":
    print("Welcome to the agent. Sign in to continue.")
    sys.exit(1)
elif mode == "banner-stderr":
    print("Welcome to the agent 1.4. Starting up", file=sys.stderr)
    sys.exit(2)
elif mode == "crash":
    print("Traceback (most recent call last): the agent's own bug", file=sys.stderr)
    sys.exit(1)
elif mode == "sleep":
    time.sleep(5)
elif mode == "env":
    print(json.dumps(sorted(os.environ)))
elif mode == "packet-file":
    print(len(open(sys.argv[2]).read()))
elif mode == "packet-argument":
    print(len(sys.argv[2]))
elif mode == "cwd":
    print(os.getcwd())
elif mode == "obedient":
    for path in paths:
        open(path, "w").write("ok")
elif mode == "locked":
    open(paths[0], "w").write("ok")
elif mode == "lists":
    # can run a command, but only reads: it writes nothing anywhere except its answer
    open(paths[0], "w").write("ok")
    print(" ".join(sorted(os.listdir(os.getcwd()))))
elif mode == "pwd":
    open(paths[0], "w").write("ok")
    print(os.getcwd())
elif mode == "pwd-labelled":
    open(paths[0], "w").write("ok")
    print("Working in: " + os.getcwd() + ".")
elif mode == "probably":
    open(paths[0], "w").write("ok")
    print("Your working folder is probably: " + os.getcwd())
elif mode == "bullet":
    open(paths[0], "w").write("ok")
    print("- 4: " + os.getcwd())
elif mode == "json-step-newline":
    # the program's JSON output: the answer's text, with the real folder alone on its own line after other text
    open(paths[0], "w").write("ok")
    print(json.dumps({"type": "result", "result": "Step 4:\n" + os.getcwd()}))
elif mode == "listing-labelled":
    open(paths[0], "w").write("ok")
    print("Files: " + ", ".join(sorted(os.listdir(os.getcwd()))) + ".")
elif mode == "step-arrow":
    open(paths[0], "w").write("ok")
    print("Step 4: ran ls -a -> " + " ".join(sorted(os.listdir(os.getcwd()))))
elif mode == "json-step-listing":
    # the program's JSON output: the listing on its own line after other text, its line break escaped
    open(paths[0], "w").write("ok")
    print(json.dumps({"type": "result", "result": "Step 4:\n" + "\n".join(sorted(os.listdir(os.getcwd())))}))
elif mode == "typed-tool-call":
    # a cheap model types out the call it would make, naming the folder it worked out from the outbox path; nothing runs
    open(paths[0], "w").write("ok")
    print('<parameter name="command">ls -laR ' + os.getcwd() + " && cat notes.txt</parameter>")
elif mode == "typed-json-command":
    open(paths[0], "w").write("ok")
    print(json.dumps({"command": "echo 'ok' > " + paths[0] + " && pwd && ls -la " + os.getcwd()}))
elif mode == "lists-home":
    open(paths[0], "w").write("ok")
    print(" ".join(sorted(os.listdir(os.environ["HOME"]))))
elif mode == "tree":
    found = []
    for folder, _, names in os.walk(os.environ["HOME"]):
        found += [os.path.relpath(os.path.join(folder, n), os.environ["HOME"]) for n in names]
    print(json.dumps(sorted(found)))
elif mode == "limit-json":
    print(json.dumps({"result": "You've hit your usage limit. Try again later.", "pad": "x" * 2000, "is_error": True}))
elif mode == "limit-long-flagged":
    print(json.dumps({"result": "You've hit your usage limit. " + "Details of the plan. " * 60, "is_error": True}))
elif mode == "error-flagged-plain":
    print(json.dumps({"result": "Something went wrong in the agent's own way", "is_error": True}))
elif mode == "long-json-answer":
    print(json.dumps({"result": "Notes on rate limit handling and usage limit reached cases. " * 40}))
elif mode == "home":
    print(json.dumps(sorted(os.listdir(os.environ["HOME"]))))
elif mode == "refresh":
    open(os.path.join(os.environ["HOME"], ".signin", "token"), "w").write("refreshed")
    open(os.path.join(os.environ["HOME"], ".signin.json"), "w").write("refreshed")
"""


@pytest.fixture
def agent_script(tmp_path):
    path = tmp_path / "fake_agent.py"
    path.write_text(FAKE_AGENT)
    return str(path)


def settings(script, mode, *extra, **agent):
    return ProviderSettings(
        adapter=CliAgentAdapter.name,
        models={"default": "agent-model"},
        timeout_seconds=5,
        agent=AgentSettings(command=[sys.executable, script, mode, *extra], **agent),
    )


def task(output="json"):
    return AiTask("notes", "Follow the rules.", "Stable part.", "The request.", {}, output=output)


def test_the_answer_comes_from_the_agents_output(agent_script):
    result = make_adapter(CliAgentAdapter.name, settings(agent_script, "stdout"), None).run(task(), "agent-model")
    assert result.text == '{"ok": true}' and result.model_served == "agent-model"
    assert result.cost_usd is None and result.input_tokens is None


def test_usage_and_cost_come_from_the_agents_json_where_the_settings_say(agent_script):
    fields = {"text": "result", "input_tokens": "usage.input_tokens", "output_tokens": "usage.output_tokens"}
    s = settings(
        agent_script, "json", output_json=True, output_fields={**fields, "cost_usd": "total_cost_usd", "model": "model"}
    )
    result = CliAgentAdapter(s).run(task("text"), "agent-model")
    assert (result.text, result.input_tokens, result.output_tokens) == ("drafted", 12, 5)
    assert result.cost_usd == 0.02 and result.model_served == "served-model"


def test_the_answer_can_come_from_the_outbox(agent_script):
    result = CliAgentAdapter(settings(agent_script, "outbox", output_via="outbox")).run(task(), "agent-model")
    assert result.text == '{"ok": true}'
    with pytest.raises(AiError) as missing:
        CliAgentAdapter(settings(agent_script, "silent", output_via="outbox")).run(task(), "agent-model")
    assert missing.value.kind == "no_output"


def test_the_packet_can_go_in_as_a_file(agent_script):
    s = settings(agent_script, "packet-file", "{packet}", packet_via="file")
    result = CliAgentAdapter(s).run(task(), "agent-model")
    assert int(result.text) == len("Follow the rules.\n\nStable part.\n\nThe request.")


def test_the_packet_can_go_in_as_an_argument_up_to_a_limit(agent_script):
    from engine.ai.adapters.cli_agent import MAX_ARGUMENT_CHARS

    s = settings(agent_script, "packet-argument", "{prompt}", packet_via="argument")
    result = CliAgentAdapter(s).run(task(), "agent-model")
    assert int(result.text) == len("Follow the rules.\n\nStable part.\n\nThe request.")
    huge = AiTask("notes", "x" * (MAX_ARGUMENT_CHARS + 1), "", "", {})
    with pytest.raises(AiError):
        CliAgentAdapter(s).run(huge, "agent-model")


def test_the_agent_runs_in_its_own_folder_with_a_small_environment(agent_script, monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_SECRET_THING", "x")
    monkeypatch.setenv("AGENT_CONFIG", "y")
    names = json.loads(CliAgentAdapter(settings(agent_script, "env", pass_env=["AGENT_CONFIG"])).run(task(), "m").text)
    assert "AGENT_CONFIG" in names and "COCKPIT_SECRET_THING" not in names
    keyed = CliAgentAdapter(settings(agent_script, "env", key_env="AGENT_KEY"), "secret-value")
    assert "AGENT_KEY" in json.loads(keyed.run(task(), "m").text)
    folder = CliAgentAdapter(settings(agent_script, "cwd")).run(task(), "m").text
    assert "cockpit-agent-" in folder and str(tmp_path) not in folder


def test_errors_are_read_from_the_exit_code_and_error_stream_only(agent_script):
    hint = "Run the agent's login command"
    s = settings(agent_script, "signed-out", errors={"auth": ["sign in"]}, sign_in_hint=hint)
    with pytest.raises(AiError) as signed_out:
        CliAgentAdapter(s).run(task(), "m")
    assert signed_out.value.kind == "auth" and signed_out.value.hint == hint
    with pytest.raises(AiError) as limited:
        CliAgentAdapter(settings(agent_script, "limit", errors={"exit_codes": {7: "quota"}})).run(task(), "m")
    assert limited.value.kind == "quota"
    with pytest.raises(AiError) as unknown:
        CliAgentAdapter(settings(agent_script, "limit")).run(task(), "m")
    assert unknown.value.kind == "no_work", "an exit that said nothing on the error stream did no work"
    with pytest.raises(AiError) as crashed:
        CliAgentAdapter(settings(agent_script, "crash")).run(task(), "m")
    assert crashed.value.kind == "other" and "Traceback" in crashed.value.detail
    # The model writing words that look like an error is an answer, not a failure.
    said = CliAgentAdapter(settings(agent_script, "says-signed-out", errors={"auth": ["logged in"]})).run(task(), "m")
    assert said.text == "not logged in"


def test_a_missing_program_and_a_slow_one_are_classified(agent_script):
    gone = ProviderSettings(adapter=CliAgentAdapter.name, agent=AgentSettings(command=["no-such-agent-program"]))
    with pytest.raises(AiError) as missing:
        CliAgentAdapter(gone).run(task(), "m")
    assert missing.value.kind == "provider_down"
    slow = settings(agent_script, "sleep").model_copy(update={"timeout_seconds": 1})
    with pytest.raises(AiError) as late:
        CliAgentAdapter(slow).run(task(), "m")
    assert late.value.kind == "timeout"


@pytest.mark.parametrize(
    ("stream", "kind"),
    [
        ("Error: You have exceeded your monthly quota (Request ID: 0000:1111)", "quota"),
        ("Usage limit reached for this plan.", "quota"),
        ("429 Too Many Requests", "rate_limited"),
        # An account added before the catalog named this program's refusal of a personal account.
        (
            "Warning: 256-color support not detected.\nIneligibleTierError: this account tier is not eligible",
            "unsupported",
        ),
    ],
)
def test_an_agent_with_no_error_patterns_of_its_own_still_reads_a_usage_limit(agent_script, stream, kind):
    """An account set up with no patterns of its own gets the common ones, so a spent plan stops the work instead of
    being retried as an unknown failure."""
    adapter = CliAgentAdapter(settings(agent_script, "stdout"))
    assert adapter.classify_error(1, stream, None).kind == kind


def test_an_account_without_a_command_is_refused():
    with pytest.raises(AiError):
        CliAgentAdapter(ProviderSettings(adapter=CliAgentAdapter.name))


def test_the_lockdown_test_catches_an_agent_that_writes_anywhere(agent_script):
    loose = CliAgentAdapter(settings(agent_script, "obedient", output_via="outbox")).lockdown_test("m")
    assert {c.name: c.ok for c in loose} == {"outbox": True, "outside": False, "shell": False, "memory": True}
    # A failed probe says what happened in plain words: no "shell", no "outbox", no "refused".
    said = " ".join(c.detail for c in loose).lower()
    assert not any(word in said for word in ("shell", "outbox", "refused"))
    tight = CliAgentAdapter(settings(agent_script, "locked", output_via="outbox")).lockdown_test("m")
    assert all(c.ok for c in tight)
    answers_on_output = CliAgentAdapter(settings(agent_script, "silent")).lockdown_test("m")
    assert [c.name for c in answers_on_output] == ["outside", "shell", "memory"]
    assert all(c.ok for c in answers_on_output)


def test_a_program_that_runs_a_command_fails_the_check_though_it_writes_nothing(agent_script):
    """A read-only sandbox that still runs commands is not locked down: it can read the disk."""
    checks = CliAgentAdapter(settings(agent_script, "lists", output_via="outbox")).lockdown_test("m")
    by_name = {c.name: c.ok for c in checks}
    assert by_name["outside"] is True and by_name["shell"] is False
    assert any("run commands" in c.detail for c in checks if not c.ok)


def test_the_agent_runs_in_a_home_of_its_own_with_only_its_sign_in_folder(agent_script, tmp_path, monkeypatch):
    real = tmp_path / "real-home"
    (real / ".signin").mkdir(parents=True)
    (real / ".signin" / "token").write_text("old", encoding="utf-8")
    (real / ".signin.json").write_text("old", encoding="utf-8")
    os.chmod(real / ".signin.json", 0o600)
    (real / "private").mkdir()
    (real / "private" / "keys.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setenv("HOME", str(real))
    kept = {"home": "fresh", "home_files": [".signin", ".signin.json"]}
    seen = json.loads(CliAgentAdapter(settings(agent_script, "home", **kept)).run(task(), "m").text)
    assert seen == [".signin", ".signin.json"]  # the rest of the real home isn't there
    adapter = CliAgentAdapter(settings(agent_script, "refresh", **kept))
    adapter._start("go", "m", tmp_path, tmp_path)  # noqa: SLF001 - one run, no answer wanted
    assert (real / ".signin" / "token").read_text(encoding="utf-8") == "refreshed"  # the folder is linked
    assert (real / ".signin.json").read_text(encoding="utf-8") == "refreshed"  # the file was copied back
    assert stat.S_IMODE((real / ".signin.json").stat().st_mode) == 0o600  # with the permissions it had, never wider


def test_the_smoke_test_runs_the_lockdown_test_once_per_agent_account(agent_script, tmp_path):
    from engine.ai.smoke import smoke_test

    providers = {
        "agent": settings(agent_script, "obedient", output_via="outbox").model_dump(),
    }
    cfg = SimpleNamespace(
        ai=SimpleNamespace(
            providers={"agent": ProviderSettings(**providers["agent"])},
            tiers={
                "routine": SimpleNamespace(use="agent/default", fallback=[], escalate_to=None, effort=None),
                "deep": SimpleNamespace(use="agent/default", fallback=[], escalate_to=None, effort=None),
            },
            tasks={},
        )
    )
    results = smoke_test(cfg, {})
    lockdown = [r for r in results if "lockdown" in r.account]
    assert [r.account for r in lockdown] == [
        "agent/default (lockdown: outbox)",
        "agent/default (lockdown: outside)",
        "agent/default (lockdown: shell)",
        "agent/default (lockdown: memory)",
    ]
    assert [r.ok for r in lockdown] == [True, False, False, True] and all(r.main for r in lockdown)


def test_a_sign_in_failure_says_what_to_do():
    from engine.dispatcher import _ai_failure

    told = _ai_failure(AiError("auth", "Please sign in again", hint="Run the agent's login command"))
    assert told.startswith("The AI account isn't signed in (Please sign in again).")
    assert told.endswith("Run the agent's login command, then try again.")


def test_the_agent_sees_the_user_name_its_own_sign_in_is_kept_under(agent_script, monkeypatch):
    """An agent whose sign-in is kept in the system's keychain finds it by the user name."""
    monkeypatch.setenv("USER", "someone")
    monkeypatch.setenv("LOGNAME", "someone")
    names = json.loads(CliAgentAdapter(settings(agent_script, "env")).run(task(), "m").text)
    assert {"USER", "LOGNAME"} <= set(names)


def test_an_agent_that_reports_its_failure_on_its_output_is_understood(agent_script):
    """Some agents print their errors on their output, not on the error stream; the account says so, and only then
    (and only for a failed run) is that report read."""
    fields = {"text": "result"}
    told = settings(
        agent_script,
        "reports-on-output",
        output_json=True,
        output_fields=fields,
        errors={"auth": ["not logged in"], "report_on_output": True},
        sign_in_hint="Run the agent's login command",
    )
    with pytest.raises(AiError) as failed:
        CliAgentAdapter(told).run(task(), "m")
    assert failed.value.kind == "auth" and "Not logged in" in failed.value.detail
    untold = settings(agent_script, "reports-on-output", output_json=True, output_fields=fields)
    with pytest.raises(AiError) as unread:
        CliAgentAdapter(untold).run(task(), "m")
    assert unread.value.kind == "no_work" and "Not logged in" not in unread.value.detail


def test_a_run_that_only_printed_a_banner_did_no_work_whatever_the_banner_says(agent_script):
    """From the exit code and the error stream only: a failure with nothing on the error stream, a banner the account's
    patterns name, or a program ended by a signal is `no_work`: not a mistake of the model, not a usage limit."""
    on_output = settings(agent_script, "banner", errors={"auth": ["sign in"]})
    with pytest.raises(AiError) as printed:
        CliAgentAdapter(on_output).run(task(), "m")
    assert printed.value.kind == "no_work", "the output is never read for an error; its banner is not a sign-in error"
    plain = settings(agent_script, "banner-stderr")
    with pytest.raises(AiError) as unnamed:
        CliAgentAdapter(plain).run(task(), "m")
    assert unnamed.value.kind == "other", "an unknown message on the error stream stays an unknown failure"
    named = settings(agent_script, "banner-stderr", errors={"no_work": [r"welcome to the agent"]})
    with pytest.raises(AiError) as banner:
        CliAgentAdapter(named).run(task(), "m")
    assert banner.value.kind == "no_work"
    by_code = settings(agent_script, "limit", errors={"exit_codes": {7: "no_work"}})
    with pytest.raises(AiError) as coded:
        CliAgentAdapter(by_code).run(task(), "m")
    assert coded.value.kind == "no_work"
    adapter = CliAgentAdapter(settings(agent_script, "stdout"))
    assert adapter.classify_error(-9, "", None).kind == "no_work"
    assert adapter.classify_error(1, "Please sign in", None).kind == "other"
    # A sign-in the account's patterns know is still a sign-in, and a usage limit still a usage limit.
    known = CliAgentAdapter(settings(agent_script, "stdout", errors={"auth": ["sign in"]}))
    assert known.classify_error(1, "Please sign in", None).kind == "auth"
    assert known.classify_error(1, "Usage limit reached", None).kind == "quota"


def test_an_agent_preset_shows_why_a_signed_out_test_failed_in_plain_words(agent_script):
    """The person's path: an agent account made from a preset whose agent prints its errors on its output, not signed
    in, tested. The test says it isn't signed in, quotes the agent's own words and says what to do, with no internal
    label."""
    from engine.ai.smoke import smoke_test
    from engine.setup import known_endpoints

    presets = [e for e in known_endpoints() if e["adapter"] == CliAgentAdapter.name]
    reporting = [e for e in presets if e["settings"].get("agent", {}).get("errors", {}).get("report_on_output")]
    assert reporting
    for preset in reporting:
        agent = dict(preset["settings"]["agent"])
        agent["command"] = [sys.executable, agent_script, "reports-on-output"]
        account = ProviderSettings(adapter=CliAgentAdapter.name, models={"default": "agent-model"}, agent=agent)
        tier = SimpleNamespace(use="agent/default", fallback=[], escalate_to=None, effort=None)
        cfg = SimpleNamespace(ai=SimpleNamespace(providers={"agent": account}, tiers={"account": tier}, tasks={}))
        first = smoke_test(cfg, {})[0]
        assert not first.ok, preset["id"]
        assert "Not logged in" in first.detail and agent["sign_in_hint"].rstrip(".") in first.detail, first.detail
        assert not first.detail.startswith(("auth", "other")) and "exit code" not in first.detail


# ---- the program's version -------------------------------------------------------------------------------------------


def test_the_program_version_is_the_first_line_the_version_check_prints(agent_script):
    one = settings(
        agent_script, "stdout", version_command=[sys.executable, "-c", "print('agent 1.2.3'); print('more')"]
    )
    assert CliAgentAdapter(one).program_version() == "agent 1.2.3"
    assert CliAgentAdapter(settings(agent_script, "stdout")).program_version().startswith("Python "), (
        "with no version check set up, the program is asked for --version"
    )


def test_a_version_that_cannot_be_read_is_none_never_a_guess(agent_script):
    failing = settings(agent_script, "stdout", version_command=[sys.executable, "-c", "raise SystemExit(3)"])
    silent = settings(agent_script, "stdout", version_command=[sys.executable, "-c", "pass"])
    missing = settings(agent_script, "stdout", version_command=["no-such-agent-program-here"])
    assert [CliAgentAdapter(s).program_version() for s in (failing, silent, missing)] == [None, None, None]

    def too_slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    slow = CliAgentAdapter(settings(agent_script, "stdout", version_timeout_seconds=2), runner=too_slow)
    assert slow.program_version() is None


def test_the_version_check_runs_with_the_agents_small_environment(agent_script, monkeypatch):
    monkeypatch.setenv("COCKPIT_SECRET_THING", "x")
    show = [sys.executable, "-c", "import os; print(','.join(sorted(os.environ)))"]
    seen = CliAgentAdapter(settings(agent_script, "stdout", version_command=show)).program_version()
    assert "PATH" in seen and "COCKPIT_SECRET_THING" not in seen


# ---- S-0714, S-0715, S-0721, S-0722 ----------------------------------------------------------------------------------


def _presets():
    from engine.setup import known_endpoints

    return [e for e in known_endpoints() if e["adapter"] == CliAgentAdapter.name and e["settings"].get("agent")]


def _preset_account(script, mode, kind, **agent):
    """An account as an earlier version saved it: the kind it was made from, and only the agent settings that existed
    then (the program swapped for the stand-in)."""
    return ProviderSettings(
        adapter=CliAgentAdapter.name,
        kind=kind,
        models={"default": "agent-model"},
        timeout_seconds=5,
        agent=AgentSettings(command=[sys.executable, script, mode], **agent),
    )


def test_an_account_saved_before_its_preset_named_sign_in_files_still_finds_its_sign_in(
    agent_script, tmp_path, monkeypatch
):
    """S-0714: an account that never had `home_files` takes them from the preset it was made from, so it runs in a home
    holding its sign-in and nothing else of the real home."""
    presets = [e for e in _presets() if any("/" in f for f in e["settings"]["agent"].get("home_files", []))]
    assert presets
    for number, preset in enumerate(presets):
        real = tmp_path / f"real-home-{number}"
        files = [f for f in preset["settings"]["agent"]["home_files"] if f != "Library/Keychains"]
        for name in files:
            (real / name).parent.mkdir(parents=True, exist_ok=True)
            (real / name).write_text(json.dumps({"signed": "in"}), encoding="utf-8")
        (real / Path(files[0]).parent / "history.jsonl").write_text("another session", encoding="utf-8")
        (real / "private").mkdir()
        (real / "private" / "keys.txt").write_text("secret", encoding="utf-8")
        monkeypatch.setenv("HOME", str(real))
        old = _preset_account(agent_script, "tree", preset["id"])
        assert old.agent.home_files == []  # what the earlier settings held
        assert json.loads(CliAgentAdapter(old).run(task(), "m").text) == sorted(files), preset["id"]
        # An account saved with a list a preset once shipped (a whole program folder) takes the current sign-in files.
        for earlier in [e for e in EARLIER_HOME_FILES if e[0] == Path(files[0]).parts[0]]:
            saved = _preset_account(agent_script, "tree", preset["id"], home_files=earlier)
            assert json.loads(CliAgentAdapter(saved).run(task(), "m").text) == sorted(files), (preset["id"], earlier)
        # An account that changed the setting keeps its own, and one made from no preset gets nothing.
        own = _preset_account(agent_script, "tree", preset["id"], home_files=[files[0]])
        assert json.loads(CliAgentAdapter(own).run(task(), "m").text) == [files[0]]
        none = _preset_account(agent_script, "tree", None)
        assert json.loads(CliAgentAdapter(none).run(task(), "m").text) == []


def test_every_agent_preset_names_sign_in_files_not_whole_program_folders():
    """S-0721: a linked folder would give the program every session history in it."""
    for preset in _presets():
        for name in preset["settings"]["agent"].get("home_files", []):
            assert name == "Library/Keychains" or "/" in name or name.endswith(".json"), (preset["id"], name)
            assert not (name.startswith(".") and "/" not in name and not name.endswith(".json")), (preset["id"], name)


def test_an_expired_sign_in_is_read_as_a_sign_in_problem_by_the_preset_that_prints_it(agent_script):
    """S-0715: the exact text a program prints when its sign-in has expired gives the sign-in hint."""
    mine = [e for e in _presets() if e["settings"]["agent"].get("errors", {}).get("report_on_output")]
    assert mine
    for preset in mine:
        agent = dict(preset["settings"]["agent"])
        agent["command"] = [sys.executable, agent_script, "stdout"]
        account = ProviderSettings(adapter=CliAgentAdapter.name, models={"default": "m"}, agent=agent)
        for said in (
            "Failed to authenticate: OAuth session expired and could not be refreshed",
            "failed to authenticate",
            "Session expired",
            'API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"Invalid bearer token"}}',
            "Your credentials have expired. Run /login to sign in again.",
        ):
            err = CliAgentAdapter(account).classify_error(1, said, None)
            assert err.kind == "auth" and err.hint == agent["sign_in_hint"], (preset["id"], said)


@pytest.mark.parametrize("mode", ["lists", "listing-labelled", "step-arrow", "json-step-listing", "lists-home"])
def test_a_program_that_lists_its_folder_or_its_home_fails_the_probe_however_it_prints_it(agent_script, mode):
    """S-0721: a command that ran and wrote nothing is still a command that ran: a hidden name only a listing shows,
    alone, after a label or a step, or inside JSON output with its line breaks escaped."""
    checks = CliAgentAdapter(settings(agent_script, mode, output_via="outbox")).lockdown_test("m")
    assert {c.name: c.ok for c in checks}["shell"] is False


@pytest.mark.parametrize(
    "mode", ["pwd", "pwd-labelled", "probably", "bullet", "json-step-newline", "typed-tool-call", "typed-json-command"]
)
def test_the_working_folders_path_is_no_proof_that_a_command_ran(agent_script, mode):
    """The #67 re-check (N-1, N-13): an agent program may tell the model its working folder itself (a shipped preset
    does, with the app's own instructions and its tools off), so the folder's path in the answer, in any shape, proves
    nothing; the check passes a clean account. The reviewer's #66 false positives are two of the shapes."""
    checks = CliAgentAdapter(settings(agent_script, mode, output_via="outbox")).lockdown_test("m")
    assert {c.name: c.ok for c in checks}["shell"] is True


def test_the_probe_never_names_the_working_folder(agent_script, monkeypatch):
    """The outbox is named from the working folder, so the probe's words never hold that folder's path."""
    seen = {}
    real = CliAgentAdapter._start

    def start(self, prompt, model, scratch, outbox, *args, **kwargs):
        seen.setdefault("prompt", prompt)  # the probe is the first run; the memory check comes after it
        seen.setdefault("folder", str(scratch))
        return real(self, prompt, model, scratch, outbox, *args, **kwargs)

    monkeypatch.setattr(CliAgentAdapter, "_start", start)
    CliAgentAdapter(settings(agent_script, "locked", output_via="outbox")).lockdown_test("m")
    assert seen["folder"] not in seen["prompt"] and "outbox" in seen["prompt"]


def test_a_limit_notice_inside_long_json_is_the_limit_and_a_long_real_answer_is_not(agent_script):
    """S-0722: the program's text field is what is read, so the JSON's size neither hides a notice nor makes a long
    answer that mentions limits one."""
    fields = {"text": "result"}
    limited = settings(agent_script, "limit-json", output_json=True, output_fields=fields)
    with pytest.raises(AiError) as err:
        CliAgentAdapter(limited).run(task(), "m")
    assert err.value.kind == "quota"
    fine = settings(agent_script, "long-json-answer", output_json=True, output_fields=fields)
    assert "usage limit reached" in CliAgentAdapter(fine).run(task(), "m").text


def test_a_json_sign_in_file_reaches_the_run_with_only_its_keys_and_a_refresh_is_merged_back(
    agent_script, tmp_path, monkeypatch
):
    """S-0721: a preset that names keys of a JSON sign-in file copies only those into the run's home (never the rest of
    the file, such as the person's repository paths), and a refreshed key goes back into the real file, whose other keys
    stay as they were."""
    preset = next(e for e in _presets() if e["settings"]["agent"].get("home_keys"))
    name, keys = next(iter(preset["settings"]["agent"]["home_keys"].items()))
    real = tmp_path / "real-home"
    real.mkdir()
    whole = {key: f"{key}-before" for key in keys} | {"elsewhere": ["a private path"]}
    (real / name).write_text(json.dumps(whole), encoding="utf-8")
    monkeypatch.setenv("HOME", str(real))
    adapter = CliAgentAdapter(_preset_account(agent_script, "tree", preset["id"]))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    home = adapter._fresh_home(scratch)
    assert json.loads((home / name).read_text(encoding="utf-8")) == {key: f"{key}-before" for key in keys}
    copied = adapter._copied_in(home)
    (home / name).write_text(json.dumps({keys[0]: "refreshed", "added by the run": 1}), encoding="utf-8")
    adapter._copy_back(copied)
    after = json.loads((real / name).read_text(encoding="utf-8"))
    assert after[keys[0]] == "refreshed" and after["elsewhere"] == ["a private path"]
    assert "added by the run" not in after


def test_a_json_sign_in_file_open_elsewhere_keeps_its_own_keys_and_is_untouched_when_nothing_differs(
    agent_script, tmp_path, monkeypatch
):
    """S-0721: the person's own session of the program rewrites the real file while a run is going; the write-back reads
    it again right before writing, so that session's keys stay; it keeps the file's permissions; and a run that changed
    nothing of the named keys leaves the file alone."""
    preset = next(e for e in _presets() if e["settings"]["agent"].get("home_keys"))
    name, keys = next(iter(preset["settings"]["agent"]["home_keys"].items()))
    real = tmp_path / "real-home"
    real.mkdir()
    (real / name).write_text(json.dumps({key: "before" for key in keys}), encoding="utf-8")
    os.chmod(real / name, 0o600)
    monkeypatch.setenv("HOME", str(real))
    adapter = CliAgentAdapter(_preset_account(agent_script, "tree", preset["id"]))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    home = adapter._fresh_home(scratch)
    copied = adapter._copied_in(home)
    # The person's own session writes the real file while the run goes on.
    (real / name).write_text(json.dumps({key: "before" for key in keys} | {"theirs": "kept"}), encoding="utf-8")
    os.chmod(real / name, 0o600)
    unchanged = (real / name).stat().st_mtime_ns
    adapter._copy_back(copied)  # the run changed nothing: the file is left alone
    assert (real / name).stat().st_mtime_ns == unchanged
    (home / name).write_text(json.dumps({key: "before" for key in keys} | {keys[0]: "refreshed"}), encoding="utf-8")
    adapter._copy_back(copied)
    after = json.loads((real / name).read_text(encoding="utf-8"))
    assert after[keys[0]] == "refreshed" and after["theirs"] == "kept"
    assert stat.S_IMODE((real / name).stat().st_mode) == 0o600


def test_a_sign_in_file_the_persons_own_session_refreshed_during_the_run_is_never_overwritten(
    agent_script, tmp_path, monkeypatch
):
    """The #65 re-check (S-0721 F0-1): the person's own session of the program refreshed its token while a run went on;
    the run's copy, changed too, is older, and writing it back would sign the person out. Both kinds of copy read the
    real file again first: a whole file is left as the person's session wrote it, and a key it changed keeps its
    value."""
    real = tmp_path / "real-home"
    real.mkdir()
    (real / ".signin.json").write_text("token-1", encoding="utf-8")
    monkeypatch.setenv("HOME", str(real))
    adapter = CliAgentAdapter(settings(agent_script, "home", home="fresh", home_files=[".signin.json"]))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    home = adapter._fresh_home(scratch)
    copied = adapter._copied_in(home)
    (real / ".signin.json").write_text("token-2 from the person's own session", encoding="utf-8")
    (home / ".signin.json").write_text("token-1 refreshed by the run", encoding="utf-8")
    adapter._copy_back(copied)
    assert (real / ".signin.json").read_text(encoding="utf-8") == "token-2 from the person's own session"

    preset = next(e for e in _presets() if e["settings"]["agent"].get("home_keys"))
    name, keys = next(iter(preset["settings"]["agent"]["home_keys"].items()))
    (real / name).write_text(json.dumps({key: "before" for key in keys}), encoding="utf-8")
    adapter = CliAgentAdapter(_preset_account(agent_script, "tree", preset["id"]))
    scratch = tmp_path / "scratch-2"
    scratch.mkdir()
    home = adapter._fresh_home(scratch)
    copied = adapter._copied_in(home)
    (real / name).write_text(json.dumps({key: "before" for key in keys} | {keys[0]: "theirs, newer"}), encoding="utf-8")
    (home / name).write_text(json.dumps({key: "run's" for key in keys}), encoding="utf-8")
    adapter._copy_back(copied)
    after = json.loads((real / name).read_text(encoding="utf-8"))
    assert after[keys[0]] == "theirs, newer", "a key the person's session changed keeps their value"
    assert all(after[key] == "run's" for key in keys[1:]), "keys only the run changed still come back"


def test_a_run_that_runs_out_of_time_says_so_logs_what_it_printed_and_suggests_two_shorter_notes(agent_script, caplog):
    """The #66 re-check (M-1): a meeting note timed out 6 of 6 on an agent. Measured on the cheapest model, the agent's
    fixed overhead is a few seconds and that note about five, so the limit stays; what the program printed when it was
    stopped is logged to show where it was, and the stopped line says a long note may go through as two."""
    from engine.dispatcher import TIMEOUT_HINT

    slow = settings(agent_script, "sleep").model_copy(update={"timeout_seconds": 1})
    with caplog.at_level("WARNING"), pytest.raises(AiError) as late:
        CliAgentAdapter(slow).run(task(), "m")
    assert late.value.kind == "timeout" and "1 seconds" in str(late.value)
    assert any("stopped after 1 seconds" in r.getMessage() for r in caplog.records)
    assert "two shorter" in TIMEOUT_HINT


def test_a_long_limit_notice_and_any_answer_flagged_as_an_error_are_errors_not_answers(agent_script):
    """F1-1: the JSON's own error flag decides, so a notice past the short-notice length is still the limit, and a
    flagged answer is never returned as the model's text."""
    fields = {"text": "result", "error_flag": "is_error"}
    long = settings(agent_script, "limit-long-flagged", output_json=True, output_fields=fields)
    with pytest.raises(AiError) as err:
        CliAgentAdapter(long).run(task(), "m")
    assert err.value.kind == "quota"
    plain_error = settings(agent_script, "error-flagged-plain", output_json=True, output_fields=fields)
    with pytest.raises(AiError) as err:
        CliAgentAdapter(plain_error).run(task(), "m")
    assert err.value.kind != "quota"
    unflagged = settings(agent_script, "error-flagged-plain", output_json=True, output_fields={"text": "result"})
    assert "went wrong" in CliAgentAdapter(unflagged).run(task(), "m").text


# ---- streamed output ----------------------------------------------------------------------------------------------

STREAM_AGENT = r"""
import json, os, sys, time
mode = sys.argv[1]
sys.stdin.read()
def event(**kw):
    print(json.dumps(kw), flush=True)
event(type="system", subtype="init", cwd="/somewhere")
event(type="assistant", message={"content": "working"})
if mode == "answer":
    event(type="result", is_error=False, result="streamed whole", usage={"input_tokens": 7, "output_tokens": 3},
          total_cost_usd=0.01)
elif mode == "error":
    event(type="result", is_error=True, result="Not logged in. Please run the login command")
    sys.exit(1)
elif mode == "flagged":
    event(type="result", is_error=True, result="Something went wrong in the agent's own way")
elif mode == "lists-midstream":
    # a command really ran: its listing is in an event in the middle of the stream, not in the final answer
    event(type="user", message={"content": [{"type": "tool_result", "content": " ".join(os.listdir(os.getcwd()))}]})
    event(type="result", is_error=False, result="Steps 1 to 4 were refused.")
elif mode == "stuck":
    for n in range(20):
        event(type="assistant", message={"content": "step %d" % n})
    time.sleep(30)
"""

STREAM_FIELDS = {
    "text": "result",
    "input_tokens": "usage.input_tokens",
    "output_tokens": "usage.output_tokens",
    "cost_usd": "total_cost_usd",
    "error_flag": "is_error",
}


def streaming(tmp_path, mode, **extra):
    script = tmp_path / "stream_agent.py"
    script.write_text(STREAM_AGENT)
    agent = {
        "output_json": True,
        "output_stream": True,
        "output_fields": STREAM_FIELDS,
        "errors": {"report_on_output": True, "auth": ["not logged in"]},
        **extra,
    }
    return settings(str(script), mode, **agent)


def test_a_streamed_answer_is_read_whole_from_the_final_result_event(tmp_path):
    result = make_adapter(CliAgentAdapter.name, streaming(tmp_path, "answer"), None).run(task(), "agent-model")
    assert result.text == "streamed whole"
    assert (result.input_tokens, result.output_tokens, result.cost_usd) == (7, 3, 0.01)


def test_a_streamed_error_is_classified_as_a_plain_one_is(tmp_path):
    adapter = make_adapter(CliAgentAdapter.name, streaming(tmp_path, "error"), None)
    with pytest.raises(AiError) as failed:
        adapter.run(task(), "agent-model")
    assert failed.value.kind == "auth"
    flagged = make_adapter(CliAgentAdapter.name, streaming(tmp_path, "flagged"), None)
    with pytest.raises(AiError) as other:
        flagged.run(task(), "agent-model")
    assert other.value.kind != "no_output"


def test_a_timed_out_streamed_run_logs_the_last_events_it_streamed(tmp_path, caplog):
    stuck = streaming(tmp_path, "stuck").model_copy(update={"timeout_seconds": 2})
    with caplog.at_level("WARNING"), pytest.raises(AiError) as late:
        make_adapter(CliAgentAdapter.name, stuck, None).run(task(), "agent-model")
    assert late.value.kind == "timeout"
    # What it printed can hold the assistant's answer: it goes to the private content log only, never the app's log,
    # whose end a report offers to send (the #68 re-check, N-3).
    kept = " ".join(r.getMessage() for r in caplog.records if r.name == content_log.NAME)
    shared = " ".join(r.getMessage() for r in caplog.records if r.name != content_log.NAME)
    assert "step 19" in kept and "step 5" not in kept and "/somewhere" not in kept
    assert "step 19" not in shared and "stopped after 2 seconds" in shared
    assert "step 19" not in str(late.value)


def test_the_kinds_output_limit_reaches_the_program_through_the_variable_its_settings_name(tmp_path):
    seen = []

    def runner(args, **kwargs):
        seen.append(kwargs["env"])
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": "ok"}), "")

    base = {"output_json": True, "output_fields": {"text": "result"}}
    limited = settings(str(tmp_path / "x.py"), "stdout", max_output_env="AGENT_MAX_OUT", **base)
    limited.agent.command[0] = sys.executable
    CliAgentAdapter(limited, runner=runner).run(AiTask("notes", "i", "s", "r", {}, output="text", max_output=1234), "m")
    plain_settings = settings(str(tmp_path / "x.py"), "stdout", **base)
    plain_settings.agent.command[0] = sys.executable
    CliAgentAdapter(plain_settings, runner=runner).run(task("text"), "m")
    assert seen[0]["AGENT_MAX_OUT"] == "1234" and "AGENT_MAX_OUT" not in seen[1]


def test_a_listing_in_the_middle_of_a_stream_fails_the_probe(tmp_path):
    """The lockdown probe reads the whole stream, never only its final answer: a listing a real command printed
    mid-stream is proof a command ran, whatever the answer says."""
    checks = CliAgentAdapter(streaming(tmp_path, "lists-midstream")).lockdown_test("m")
    assert {c.name: c.ok for c in checks}["shell"] is False


def test_an_account_saved_with_the_presets_earlier_command_streams_and_gets_its_output_limit():
    """An account added before its preset streamed kept the old command, so a looping run still hung for 90 s (the #67
    re-check, A-2): an account that never changed the command takes the preset's current one, read as a stream, and
    every account takes the variable that carries its output limit. A command the person changed stays theirs."""
    from engine.ai.adapters.cli_agent import EARLIER_COMMANDS, _with_preset_settings

    preset = next(p for p in _presets() if p["settings"]["agent"].get("output_stream"))
    current = preset["settings"]["agent"]
    # Every command the preset ever shipped, the first one from before it turned off the connections' tools too (the
    # #68 re-check, N-9).
    assert len(EARLIER_COMMANDS) >= 2
    for earlier in EARLIER_COMMANDS:
        old = _with_preset_settings(AgentSettings(command=list(earlier)), preset["id"])
        assert old.command == current["command"] and old.output_stream is True
        assert old.max_output_env == current["max_output_env"]
    own = [*EARLIER_COMMANDS[0], "--verbose"]
    kept = _with_preset_settings(AgentSettings(command=own), preset["id"])
    assert kept.command == own and kept.output_stream is False and kept.max_output_env == current["max_output_env"]


def test_the_apps_instructions_to_an_agent_start_by_saying_it_has_no_tools(agent_script, monkeypatch):
    """The #67 re-check (J-5): with its tools off, a model that believes it has tools types tool calls and made-up
    results until its output limit ends the run. The app's own instructions, given in place of the program's, start by
    saying there are no tools and tool-call markup is never read."""
    seen = {}
    real = CliAgentAdapter._start

    def start(self, prompt, model, scratch, outbox, effort=None, system="", *args, **kwargs):
        seen["system"] = system
        return real(self, prompt, model, scratch, outbox, effort, system, *args, **kwargs)

    monkeypatch.setattr(CliAgentAdapter, "_start", start)
    account = settings(agent_script, "stdout", system_option=["--system-prompt-file", "{system}"])
    CliAgentAdapter(account).run(task(), "agent-model")
    first = seen["system"].split("\n\n", 1)[0]
    assert first.startswith("You have no tools in this run") and "never read" in first
    assert "Follow the rules." in seen["system"] and "Stable part." in seen["system"]
