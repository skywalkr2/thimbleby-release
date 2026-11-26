"""The app's log file (S-0285): full errors for a bug report, never what the person gave the app; the settings that
shape it; and the one place the version is written."""

import logging
import re
from importlib.metadata import version
from pathlib import Path

import pytest

import engine
from engine import app_log
from engine.config import ConfigError
from tests.test_problems import KEY, PACKET_TEXT, RESOLVED, address, api, home, person, project  # noqa: F401,F811


@pytest.fixture
def logged(api):  # noqa: F811
    """The same app, with its log started the way `cockpit serve` starts it."""
    client, store, worker, ws, cfg, name = api
    handler = app_log.install(ws, cfg, store)
    try:
        yield client, ws
    finally:
        for h in logging.getLogger().handlers:
            h.flush()
        app_log.remove(handler)


def read(ws) -> str:
    return app_log.log_path(ws).read_text(encoding="utf-8")


def test_an_error_leaves_its_traceback_in_the_log_and_never_on_the_screen(logged):
    client, ws = logged
    r = client.get("/api/boom")
    assert r.status_code == 500
    assert "Traceback" not in r.text and "boom" not in r.text and "RuntimeError" not in r.text
    text = read(ws)
    assert "Traceback (most recent call last)" in text
    assert "in boom" in text and "RuntimeError" in text
    assert "api/" in text or "engine/" in text  # a frame's place, from its package on
    assert str(ws.root) not in text and str(Path.home()) not in text


def test_the_log_holds_no_secret_address_name_or_text_the_person_gave(logged):
    client, ws = logged
    who = person()
    assert client.post("/api/handin", json={"note": PACKET_TEXT, "pasted": ""}).status_code == 200
    logging.getLogger("engine.test").warning("a read said %s for %s <%s>", KEY, who["full_name"], address())
    logging.getLogger("engine.test").error("kept %s in %s", RESOLVED, project()["name"])
    assert client.get("/api/boom").status_code == 500
    text = read(ws)
    for hidden in (
        KEY,
        RESOLVED,
        address(),
        who["full_name"],
        *who["full_name"].split(),
        *who["aliases"],
        project()["name"],
        PACKET_TEXT,
    ):
        assert hidden not in text, (hidden, text)
    assert "<secret>" in text and "<address>" in text and "<name>" in text


def test_words_the_assistant_said_go_to_the_content_log_masked_and_never_to_the_app_log(api):  # noqa: F811
    """The content log keeps what can hold the assistant's words in its own private file, masked like the app's log;
    the app's log, whose end a report offers to send, never holds it (the #68 re-check, N-3)."""
    from engine import content_log, report_send

    client, store, worker, ws, cfg, name = api
    handler = app_log.install(ws, cfg, store)
    try:
        content_log.keep("the agent was stopped", f"I'll write to {address()} about the move to the new room")
        logging.getLogger("engine.test").warning("an ordinary line")
    finally:
        app_log.remove(handler)
    kept = app_log.content_path(ws).read_text(encoding="utf-8")
    assert "the move to the new room" in kept and address() not in kept and "<address>" in kept
    assert content_log.said_in(kept) and "the move to the new room" in content_log.said_in(kept)[0]
    assert "the move to the new room" not in read(ws) and "an ordinary line" in read(ws)
    assert "the move to the new room" not in report_send.details_for(ws, store, cfg)


def test_the_level_is_a_setting_and_a_quieter_one_leaves_out_what_a_louder_one_keeps(api):  # noqa: F811
    client, store, worker, ws, cfg, name = api
    quiet = ws.config(env={}, flags={"server.log_level": "error", "storage.backups.automatic": False})
    handler = app_log.install(ws, quiet, store)
    try:
        logging.getLogger("engine.test").warning("a handled thing")
        logging.getLogger("engine.test").error("a failure")
        handler.flush()
    finally:
        app_log.remove(handler)
    text = read(ws)
    assert "a failure" in text and "a handled thing" not in text


def test_the_file_rotates_at_its_size_and_keeps_only_the_files_asked_for(api):  # noqa: F811
    client, store, worker, ws, cfg, name = api
    cfg = ws.config(env={}, flags={"server.log_files": 2, "storage.backups.automatic": False})
    handler = app_log.install(ws, cfg, store, max_bytes=400)
    try:
        for i in range(60):
            logging.getLogger("engine.test").warning("line number %d with some padding to fill the file", i)
    finally:
        app_log.remove(handler)
    names = sorted(p.name for p in app_log.log_path(ws).parent.iterdir())
    assert names == ["thimbleby.log", "thimbleby.log.1"]


def test_a_folder_that_cant_be_written_never_stops_the_app(api, tmp_path):  # noqa: F811
    client, store, worker, ws, cfg, name = api
    blocker = tmp_path / "file"
    blocker.write_text("x")

    class Gone:
        private_dir = blocker  # a file where the folder should be

    assert app_log.install(Gone(), cfg, store) is None


def test_the_settings_have_bounds():
    from engine.config.schema import ServerFile

    with pytest.raises(ValueError):
        ServerFile(log_max_mb=0)
    with pytest.raises(ValueError):
        ServerFile(log_level="chatty")
    assert ServerFile().log_level == "warning"
    assert ConfigError  # the config loader raises it for the same refusals


def test_the_version_is_the_packages_own_and_written_nowhere_by_hand():
    assert engine.__version__ == version("thimbleby")
    source = (Path(engine.__file__)).read_text(encoding="utf-8")
    assert not re.search(r'__version__\s*=\s*"\d+\.\d', source)


def test_the_runtime_config_reports_that_version(api):  # noqa: F811
    client, *_ = api
    assert client.get("/api/runtime-config").json()["version"] == version("thimbleby")
