"""Opening a workspace an earlier installer made (the configuration compatibility policy): known settings and renamed
settings load, a setting no version knows is refused and named on the start screen, and nothing the person has is
changed by opening it."""

import sqlite3
from pathlib import Path

import pytest
import yaml

from engine import desktop
from engine.config import loader
from engine.config.loader import ConfigError
from engine.storage import Store
from engine.workspace import init_workspace, resolve
from tests.conftest import DEMO_A
from tests.test_desktop import Shell, env_for


def previous_installer_workspace(tmp_path: Path) -> Path:
    """A workspace with records, a ledger and settings as the earlier installer wrote them, the setting that build
    added to the dispatch file included."""
    ws = init_workspace(tmp_path / "old", template=DEMO_A, git=False)
    path = ws.root / "config" / "dispatch.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    data = data or {}
    data.setdefault("knowledge", {})["apply_guesses"] = False
    path.write_text(yaml.safe_dump(data))
    return ws.root


def tables(db: Path) -> dict[str, list]:
    conn = sqlite3.connect(db)
    try:
        names = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        return {n: sorted(map(repr, conn.execute(f'SELECT * FROM "{n}"'))) for n in names}
    finally:
        conn.close()


def test_a_workspace_from_the_previous_installer_opens_with_its_settings_and_all_its_data(tmp_path):
    root = previous_installer_workspace(tmp_path)
    ws = resolve(root)
    before_files = {p: p.read_bytes() for p in (root / "config").rglob("*.yaml")}
    before_db = tables(ws.db_path)
    assert before_db["records"] and before_db["ledger"]
    cfg = ws.config()
    assert cfg.dispatch.knowledge.apply_guesses is False
    assert cfg.retired == [] and cfg.deprecated == {}
    store = Store(ws.db_path, cfg=cfg)
    store.close()
    assert tables(ws.db_path) == before_db
    assert {p: p.read_bytes() for p in (root / "config").rglob("*.yaml")} == before_files


def test_a_stored_mail_reach_past_fourteen_days_is_kept_and_the_file_is_not_rewritten(tmp_path):
    root = previous_installer_workspace(tmp_path)
    path = root / "config" / "watch.yaml"
    data = yaml.safe_load(path.read_text())
    data["look_back_choices"] = [30, 90, 365]
    data["full_read_choices"] = [14, 30, 90]
    data["first_headers_days"] = 365
    data["full_read_max_items"] = 5000
    source = data["sources"][0]
    source["first_run_days"] = 30
    path.write_text(yaml.safe_dump(data))
    kept = path.read_bytes()
    cfg = resolve(root).config()
    assert cfg.watch.look_back_choices == [30, 90, 365]
    assert cfg.watch.full_read_choices == [14, 30, 90]
    assert cfg.watch.first_headers_days == 365
    assert cfg.watch.full_read_max_items == 5000
    assert cfg.watch.sources[0].first_run_days == 30
    assert not hasattr(cfg, "adjusted")
    assert path.read_bytes() == kept


def test_a_renamed_setting_is_read_under_its_new_name_and_reported(tmp_path):
    root = previous_installer_workspace(tmp_path)
    path = root / "config" / "ui.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    data = data or {}
    data.get("followups", {}).pop("question_after_days", None)
    data.setdefault("today", {})["nudge_after_days"] = 9
    path.write_text(yaml.safe_dump(data))
    cfg = resolve(root).config()
    assert cfg.ui.followups.question_after_days == 9
    assert cfg.deprecated == {"ui.today.nudge_after_days": "ui.followups.question_after_days"}


def test_a_retired_setting_is_set_aside_and_listed_never_silently_dropped(tmp_path, monkeypatch):
    root = previous_installer_workspace(tmp_path)
    path = root / "config" / "dispatch.yaml"
    data = yaml.safe_load(path.read_text())
    data["knowledge"]["gone_setting"] = True
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError) as err:
        resolve(root).config()
    assert err.value.unknown == ["dispatch.knowledge.gone_setting"]
    monkeypatch.setattr(loader, "RETIRED_KEYS", ("dispatch.knowledge.gone_setting",))
    cfg = resolve(root).config()
    assert cfg.retired == ["dispatch.knowledge.gone_setting"]
    assert "gone_setting" in path.read_text()


def test_a_setting_no_version_knows_stops_the_start_with_a_screen_that_names_it_and_changes_nothing(tmp_path):
    root = previous_installer_workspace(tmp_path)
    path = root / "config" / "dispatch.yaml"
    data = yaml.safe_load(path.read_text())
    data["knowledge"]["from_a_newer_version"] = 1
    path.write_text(yaml.safe_dump(data))
    before_files = {p: p.read_bytes() for p in (root / "config").rglob("*.yaml")}
    before_db = tables(resolve(root).db_path)
    shell = Shell()
    env = env_for(tmp_path)
    assert desktop.run(root, tmp_path / "logs", shell, environ=env, launch=lambda *a, **k: None) == 1
    ((kind, _),) = shell.problems
    assert kind == "config"
    assert "dispatch.knowledge.from_a_newer_version" in shell.words["desktop.problem.config.text"]
    assert {p: p.read_bytes() for p in (root / "config").rglob("*.yaml")} == before_files
    assert tables(resolve(root).db_path) == before_db
