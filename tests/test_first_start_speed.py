"""A first start answers the setup screens at once: the settings are read from the files once for a request and again
only when something they depend on changed, a look for installed programs runs once and not inside each request, and a
setup step's save tells the screens which of them to read again instead of all of them."""

import yaml

from engine import setup as setup_steps
from engine.config import loader
from engine.config.current import load_config_now
from engine.worker import Events
from tests.test_setup import client, make

# ---- the settings are read once ----------------------------------------------------------------------------------


def counted_loads(monkeypatch):
    calls = []
    real = loader.load_config

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("engine.config.current.load_config", counting)
    return calls


def test_the_settings_are_read_from_the_files_once_not_for_every_part_of_the_answer(tmp_path, monkeypatch):
    ws, cfg, store = make(tmp_path)
    c, api = client(ws, cfg, store)
    calls = counted_loads(monkeypatch)
    assert c.get(f"{api}/settings").status_code == 200
    assert len(calls) <= 1
    before = len(calls)
    for _ in range(4):
        assert c.get(f"{api}/settings").status_code == 200
    assert len(calls) == before  # nothing changed, so nothing is read again


def test_a_changed_settings_file_is_read_again_at_once(tmp_path, monkeypatch):
    ws, cfg, store = make(tmp_path)
    first = load_config_now(ws.config_dir, env={})
    assert load_config_now(ws.config_dir, env={}) is first
    path = ws.config_dir / "workspace.yaml"
    data = yaml.safe_load(path.read_text()) or {}
    data["name"] = "Another name"
    path.write_text(yaml.safe_dump(data))
    again = load_config_now(ws.config_dir, env={})
    assert again is not first and again.workspace.name == "Another name"
    # An environment variable that overrides a setting is a change too.
    over = load_config_now(ws.config_dir, env={"THIMBLEBY__WORKSPACE__NAME": "From the environment"})
    assert over.workspace.name == "From the environment"


def test_settings_that_cannot_be_read_are_never_held(tmp_path):
    import pytest

    from engine.config.loader import ConfigError

    ws, cfg, store = make(tmp_path)
    good = load_config_now(ws.config_dir, env={})
    path = ws.config_dir / "workspace.yaml"
    kept = path.read_text()
    path.write_text("name: [unclosed\n")
    with pytest.raises(ConfigError):
        load_config_now(ws.config_dir, env={})
    path.write_text(kept)
    assert load_config_now(ws.config_dir, env={}).workspace.name == good.workspace.name


# ---- installed programs are looked up once, in the background ---------------------------------------------------


def test_the_look_for_installed_programs_runs_once_and_not_inside_each_request(tmp_path, monkeypatch):
    ws, cfg, store = make(tmp_path)
    looked = []
    monkeypatch.setattr(setup_steps.shutil, "which", lambda name: looked.append(name) or None)
    setup_steps.forget_programs()
    c, api = client(ws, cfg, store)
    setup_steps.wait_for_programs()  # the one look-up, started by the app when it was made
    once = list(looked)
    assert once and len(set(once)) == len(once)
    for _ in range(5):
        assert c.get(f"{api}/ai/endpoints").status_code == 200
    assert looked == once


def test_check_looks_again_and_a_program_installed_meanwhile_is_found(tmp_path, monkeypatch):
    ws, cfg, store = make(tmp_path)
    found: dict[str, str] = {}
    monkeypatch.setattr(setup_steps.shutil, "which", lambda name: found.get(name))
    setup_steps.forget_programs()
    c, api = client(ws, cfg, store)
    setup_steps.wait_for_programs()
    agent = next(k for k in c.get(f"{api}/ai/endpoints").json() if k["installed"] is False)
    found[next(e["program"] for e in setup_steps.known_endpoints() if e["id"] == agent["id"])] = "/bin/x"
    assert next(k for k in c.get(f"{api}/ai/endpoints").json() if k["id"] == agent["id"])["installed"] is False
    again = c.get(f"{api}/ai/endpoints", params={"recheck": "true"}).json()
    assert next(k for k in again if k["id"] == agent["id"])["installed"] is True


# ---- a setup step's save says which screens to read again ---------------------------------------------------------


def test_events_say_which_screens_a_change_touched_and_an_unnamed_change_touches_all():
    events = Events()
    start = events.version
    events.changed("setup")
    events.changed("today", "setup")
    assert events.touched_since(start) == {"setup", "today"}
    events.changed()
    assert events.touched_since(start) is None  # one change named nothing, so the screens read everything
    assert events.touched_since(events.version) == set()


def test_a_setup_skip_tells_every_screen_to_read_again(tmp_path):
    """A step of setup changes what several screens show (the step list, its recap, Today's setup line), and the
    walkthrough reads its own steps from the stream: naming only some screens left the recap on "Skipped" where "No one
    added" was due."""
    ws, cfg, store = make(tmp_path)
    c, api = client(ws, cfg, store)
    app_events = c.app.state.events
    before = app_events.version
    assert c.post(f"{api}/setup/backup/skip").status_code == 200
    assert app_events.version > before
    assert app_events.touched_since(before) is None
