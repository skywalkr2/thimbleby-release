"""A new workspace starts with the add-ons the installer names turned on (design 4.0, `server.new_workspace_addons`)."""

from __future__ import annotations

import pytest

from engine.config.loader import ConfigError
from engine.workspace import init_workspace
from engine.yaml_load import load_yaml

ENV = "COCKPIT__SERVER__NEW_WORKSPACE_ADDONS"


def enabled(ws) -> list[str]:
    return list(
        (load_yaml((ws.config_dir / "workspace.yaml").read_text(encoding="utf-8")) or {})
        .get("plugins", {})
        .get("enabled", [])
    )


def test_a_new_workspace_starts_with_the_named_installed_add_ons_on(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, "[example, kit]")
    ws = init_workspace(tmp_path / "ws", git=False)
    assert enabled(ws) == ["example", "kit"]
    # The workspace still loads with them on.
    assert ws.config().workspace.plugins.enabled == ["example", "kit"]


def test_a_name_that_is_not_installed_is_skipped_not_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, "[example, nothing-called-this]")
    ws = init_workspace(tmp_path / "ws", git=False)
    assert enabled(ws) == ["example"]


def test_with_the_setting_empty_nothing_is_turned_on(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert enabled(init_workspace(tmp_path / "ws", git=False)) == []


def test_a_workspace_made_from_a_template_keeps_the_templates_own_add_ons(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, "[nothing-called-this]")
    from tests.conftest import DEMO_A

    own = load_yaml((DEMO_A / "config" / "workspace.yaml").read_text(encoding="utf-8"))["plugins"]["enabled"]
    assert enabled(init_workspace(tmp_path / "ws", template=DEMO_A, git=False)) == own


def test_a_setting_that_is_not_a_list_of_names_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, "{a: b}")
    with pytest.raises((ConfigError, ValueError)):
        init_workspace(tmp_path / "ws", git=False)
