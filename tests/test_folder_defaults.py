"""A watched folder reads what its help says (S-0692): documents, spreadsheets, presentations and PDFs by default, and a
document it can't read is listed with why, never skipped quietly."""

from __future__ import annotations

from datetime import timedelta

from engine.connectors import FolderSettings
from tests.test_watch import NOW, make


def test_the_default_patterns_name_the_kinds_of_file_the_help_says():
    names = {"a.txt", "a.md", "a.docx", "a.xlsx", "a.pptx", "a.pdf"}
    from fnmatch import fnmatch

    assert {n for n in names if any(fnmatch(n, p) for p in FolderSettings(path="x").patterns)} == names


def test_a_docx_in_a_default_watched_folder_becomes_an_input(tmp_path):
    from engine.extract import fixtures
    from engine.watch import refresh

    folder = tmp_path / "shared"
    folder.mkdir()
    (folder / "plan.md").write_text("Line one\n")
    ws, cfg, store = make(
        tmp_path,
        [
            {
                "id": "shared",
                "connector": "folder",
                "label": "Docs",
                "first_run": "baseline",
                "settings": {"path": str(folder)},
            }
        ],
    )
    try:
        refresh(ws, store, cfg, "shared", NOW)
        (folder / "brief.docx").write_bytes(fixtures.document())
        result = refresh(ws, store, cfg, "shared", NOW + timedelta(hours=1))
        assert len(result.new) == 1
        assert [s.data["key"] for s in store.read().find("snapshot", {"source": "shared"})] == ["plan.md", "brief.docx"]
    finally:
        store.close()


def test_a_document_of_a_kind_that_cant_be_read_is_listed_with_why(tmp_path):
    from engine.watch import refresh

    folder = tmp_path / "shared"
    folder.mkdir()
    (folder / "old.doc").write_bytes(b"x")
    (folder / "plan.md").write_text("Line one\n")
    ws, cfg, store = make(
        tmp_path,
        [
            {
                "id": "shared",
                "connector": "folder",
                "label": "Docs",
                "first_run": "baseline",
                "settings": {"path": str(folder)},
            }
        ],
    )
    try:
        refresh(ws, store, cfg, "shared", NOW)
        last = [r for r in store.read().find("watch_run", {"source": "shared"})][-1]
        assert last.data["unreadable"] == [{"key": "old.doc", "reason": last.data["unreadable"][0]["reason"]}]
        assert "can't be read" in last.data["unreadable"][0]["reason"]
    finally:
        store.close()
