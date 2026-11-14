from engine.selfcheck.file_names import check_name_case


def test_a_module_that_differs_from_another_only_in_capitals_is_found(tmp_path):
    ui = tmp_path / "web" / "src" / "ui"
    ui.mkdir(parents=True)
    (ui / "Sheet.tsx").write_text("")
    (ui / "sheet.ts").write_text("")
    (ui / "Sheet.module.css").write_text("")
    found = check_name_case(tmp_path)
    assert [f.path for f in found] == ["web/src/ui/sheet.ts"]


def test_names_that_differ_beyond_capitals_pass(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    for name in ("Sheet.tsx", "inSheet.ts", "Sheet.module.css", "words.test.ts", "words.test.tsx", "words.ts"):
        (ui / name).write_text("")
    assert check_name_case(tmp_path) == []


def test_the_repository_has_no_such_names():
    assert check_name_case() == []


def test_an_unresolved_merge_conflict_is_found_and_a_clean_tree_passes(tmp_path):
    from engine.selfcheck.file_names import check_conflict_markers

    doc = tmp_path / "docs" / "plan.md"
    doc.parent.mkdir()
    doc.write_text("intro\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n", encoding="utf-8")
    found = [(f.path, f.line) for f in check_conflict_markers(tmp_path)]
    assert found == [("docs/plan.md", 2), ("docs/plan.md", 6)]
    doc.write_text("intro\nresolved\n", encoding="utf-8")
    assert check_conflict_markers(tmp_path) == []


def test_the_repository_has_no_unresolved_merge_conflict():
    from engine.selfcheck.file_names import check_conflict_markers

    assert check_conflict_markers() == []
