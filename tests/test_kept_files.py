"""Opening a kept file from the installed app's window (Files): only a file this workspace keeps, saved under the
private folder first. A document or media kind is handed to the computer's program; any other kind is only shown in its
folder, never started."""

import pytest

from engine import kept_files
from engine.files import add_file
from engine.storage import Store
from tests.test_appwindow import make

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
LISTS = {
    "extensions": ["pdf", "png", "txt"],
    "types": ["application/pdf", "image/png", "text/plain"],
}


@pytest.fixture
def env(workspace):
    cfg = workspace.config(env={})
    store = Store(workspace.db_path, cfg=cfg)
    yield workspace, cfg, store
    store.close()


def run(env, name, media_type, **lists):
    ws, cfg, store = env
    kept = add_file(store, cfg, PNG, name=name, media_type=media_type, preserve_generic=True)
    started, shown = [], []
    result = kept_files.open_kept(store, ws.private_dir, kept.id, started.append, shown.append, **(lists or LISTS))
    return kept, result, started, shown


def test_a_document_is_saved_under_the_private_folder_and_handed_to_the_computer(env):
    ws, _, _ = env
    kept, result, started, shown = run(env, "../../evil/cover.png", "image/png")
    assert result == kept_files.OPENED and shown == []
    (path,) = started
    assert path.read_bytes() == PNG
    assert path.parent == ws.private_dir / kept_files.FOLDER / kept.id and path.name == "cover.png"


@pytest.mark.parametrize(
    ("name", "media_type"),
    [
        ("run.command", "image/png"),
        ("Tool.app", "application/pdf"),
        ("invoice.pdf.command", "application/pdf"),
        ("report.sh", "application/pdf"),  # the type claims a pdf; the name decides
        ("setup.exe", "text/plain"),
        ("noending", "image/png"),
        ("cover.png", "application/octet-stream"),  # the ending is listed but the stored type is not
    ],
)
def test_any_other_kind_is_shown_in_its_folder_and_never_started(env, name, media_type):
    _, result, started, shown = run(env, name, media_type)
    assert result == kept_files.SHOWN and started == [] and len(shown) == 1


def test_the_result_says_which_happened(env):
    assert run(env, "x.command", "image/png")[1] == kept_files.SHOWN


def test_the_default_settings_list_documents_and_never_scripts(env):
    _, cfg, _ = env
    files = cfg.storage.files
    for ending in ("pdf", "docx", "mp4", "mov", "md"):
        assert ending in files.open_extensions
    for ending in (
        "command",
        "sh",
        "app",
        "exe",
        "bat",
        "ps1",
        "jar",
        "scpt",
        "pkg",
        "dmg",
        "terminal",
        "webloc",
        "url",
    ):
        assert ending not in files.open_extensions


@pytest.mark.parametrize("asked", ["FILE-99999", "../../etc/passwd", "file:///etc/passwd", "ACT-1", "", None, 7])
def test_anything_but_a_kept_file_is_refused_and_nothing_is_saved_or_started(env, asked):
    ws, _, store = env
    started, shown = [], []
    assert kept_files.open_kept(store, ws.private_dir, asked, started.append, shown.append, **LISTS) is None
    assert started == [] and shown == [] and not (ws.private_dir / kept_files.FOLDER).exists()


def test_the_window_bridge_hands_the_id_to_the_apps_opener_and_says_what_happened(env):
    shell, _, _ = make()
    from engine.appwindow import PageApi

    api = PageApi(shell)
    assert api.open_file("FILE-1") == ""  # no workspace open yet
    asked = []
    shell.open_kept = lambda file_id: asked.append(file_id) or kept_files.SHOWN
    assert api.open_file("FILE-1") == "shown" and asked == ["FILE-1"]


def test_the_windows_opener_reads_the_workspace_store_not_the_start_up_status(env, monkeypatch):
    from engine.desktop import kept_opener

    ws, cfg, store = env
    kept = add_file(store, cfg, PNG, name="cover.png", media_type="image/png", preserve_generic=True)
    started = []
    monkeypatch.setattr(kept_files, "start_program", started.append)
    monkeypatch.setattr(kept_files.open_kept, "__defaults__", (started.append, kept_files.show_in_folder))
    assert kept_opener(ws, cfg)(kept.id) == kept_files.OPENED
    assert started and started[0].read_bytes() == PNG
    assert kept_opener(ws, cfg)("file-missing") is None
