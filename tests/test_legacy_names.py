"""The names the product used before it was called Thimbleby (S-0296): a new workspace, backup and setting carry none
of them, and what an earlier version made is still opened, restored and read."""

import base64
import logging
import os
import shutil
import sys
from importlib.metadata import entry_points
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from engine import backup, backup_crypto, cli, legacy_names
from engine.backup import restore_backup, run_backup
from engine.storage import Store
from engine.workspace import init_workspace, resolve
from tests.conftest import DEMO_A
from tests.test_update_restore import NOW, counts

OLD = ("cockpit",)


def old_made(tmp_path: Path) -> Path:
    """A workspace as the earlier version made it: the old private folder and database names."""
    ws = init_workspace(tmp_path / "old", template=DEMO_A, git=False)
    ws.install_token()
    ws.db_path.rename(ws.root / "cockpit.db")
    ws.private_dir.rename(ws.root / ".cockpit")
    return ws.root


def names_with_old(root: Path) -> list[str]:
    return [p.relative_to(root).as_posix() for p in root.rglob("*") if any(o in p.name.lower() for o in OLD)]


def test_an_old_workspace_opens_in_place_with_its_data_and_settings(tmp_path):
    root = old_made(tmp_path)
    ws = resolve(root)
    assert ws.db_path == root / "cockpit.db" and ws.private_dir == root / ".cockpit"
    token_before = (root / ".cockpit" / "token").read_text(encoding="utf-8").strip()
    assert ws.install_token() == token_before
    store = Store(ws.db_path, cfg=ws.config())
    try:
        assert store.read().list("person")
    finally:
        store.close()
    assert ws.config().server  # its settings load
    # Read in place: never a second database or a second private folder.
    assert not (root / "thimbleby.db").exists() and not (root / ".thimbleby").exists()
    assert not list(root.glob("thimbleby.db*"))


def test_a_new_workspace_has_none_of_the_old_names(tmp_path):
    ws = init_workspace(tmp_path / "new", template=DEMO_A, git=True)
    ws.install_token()
    assert ws.db_path.name == "thimbleby.db" and ws.private_dir.name == ".thimbleby"
    assert names_with_old(ws.root) == []
    for path in ws.root.rglob("*"):
        if path.is_file() and ".git" not in path.relative_to(ws.root).parts:
            assert b"cockpit.db" not in path.read_bytes() and b".cockpit" not in path.read_bytes(), path
    ignored = (ws.root / ".gitignore").read_text(encoding="utf-8")
    assert "cockpit" not in ignored and "thimbleby.db" in ignored and ".thimbleby/" in ignored


def test_a_new_workspaces_backup_has_none_of_the_old_names_and_restores(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_A, git=False)
    offsite = tmp_path / "offsite"
    offsite.mkdir()
    cfg = ws.config(env={}, flags={"storage.backups.targets": [{"path": str(offsite), "label": "test"}]})
    run_backup(ws, cfg, NOW)
    (folder,) = list(offsite.iterdir())
    assert names_with_old(folder) == [] and (folder / "thimbleby.db").is_file()
    restored = tmp_path / "restored"
    restore_backup(folder, restored)
    assert counts(restored / "thimbleby.db") == counts(ws.db_path)
    assert names_with_old(restored) == []


def test_a_backup_made_with_the_old_names_still_restores(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_A, git=False)
    folder = tmp_path / "old-backup"
    folder.mkdir()
    backup._database_copy(ws, folder / "cockpit.db")
    for name in backup.BACKUP_FOLDERS:
        if (ws.root / name).is_dir():
            shutil.copytree(ws.root / name, folder / name)
    restored = tmp_path / "restored"
    restore_backup(folder, restored)
    assert counts(restored / "thimbleby.db") == counts(ws.db_path)
    assert not (restored / "cockpit.db").exists()


def test_an_encrypted_backup_made_with_the_old_names_and_check_bytes_still_restores(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_crypto, "KDF", {"n": 2**4, "r": 1, "p": 1})
    monkeypatch.setattr(backup_crypto, "_CHECK", legacy_names.OLD_CHECK_TEXT)
    monkeypatch.setattr(backup, "DB_NAME", "cockpit.db")
    ws = init_workspace(tmp_path / "ws", template=DEMO_A, git=False)
    key = tmp_path / "key"
    key.write_text("a long phrase only the person knows\n", encoding="utf-8")
    offsite = tmp_path / "offsite"
    offsite.mkdir()
    flags = {
        "storage.backups.targets": [{"path": str(offsite), "label": "t"}],
        "storage.backups.encrypt": f"file:{key}",
    }
    run_backup(ws, ws.config(env={}, flags=flags), NOW)
    (folder,) = list(offsite.iterdir())
    assert (folder / "cockpit.db").is_file()
    monkeypatch.undo()
    monkeypatch.setattr(backup_crypto, "KDF", {"n": 2**4, "r": 1, "p": 1})
    restored = tmp_path / "restored"
    restore_backup(folder, restored, "a long phrase only the person knows")
    assert counts(restored / "thimbleby.db") == counts(ws.db_path)


def test_new_backups_write_the_new_key_check_bytes_and_old_ones_are_accepted():
    key = os.urandom(32)
    sealer = backup_crypto.Sealer(key)
    raw = base64.b64decode(sealer.check_value())
    assert AESGCM(key).decrypt(raw[:12], raw[12:], b"check") == b"thimbleby backup key check"
    nonce = os.urandom(12)
    old = base64.b64encode(nonce + AESGCM(key).encrypt(nonce, b"cockpit backup key check", b"check")).decode()
    assert sealer.accepts(old) and sealer.accepts(sealer.check_value())
    other = base64.b64encode(nonce + AESGCM(key).encrypt(nonce, b"something else", b"check")).decode()
    assert not sealer.accepts(other)


def test_both_settings_prefixes_are_read_and_the_new_one_wins(caplog):
    from engine.config import load_config

    ws_cfg = Path(DEMO_A) / "config"
    only_new = load_config(ws_cfg, env={"THIMBLEBY__SERVER__PORT": "8123"})
    only_old = load_config(ws_cfg, env={"COCKPIT__SERVER__PORT": "8124"})
    assert only_new.server.port == 8123 and only_old.server.port == 8124
    legacy_names._told.clear()
    with caplog.at_level(logging.WARNING, logger="engine.legacy_names"):
        both = load_config(ws_cfg, env={"THIMBLEBY__SERVER__PORT": "8123", "COCKPIT__SERVER__PORT": "8124"})
    assert both.server.port == 8123
    assert "COCKPIT__SERVER__PORT is ignored" in caplog.text and "THIMBLEBY__SERVER__PORT" in caplog.text


def test_the_workspace_variable_has_both_names(monkeypatch, tmp_path):
    monkeypatch.delenv("THIMBLEBY_WORKSPACE", raising=False)
    monkeypatch.setenv("COCKPIT_WORKSPACE", "old")
    assert legacy_names.workspace_from_env() == "old"
    monkeypatch.setenv("THIMBLEBY_WORKSPACE", "new")
    assert legacy_names.workspace_from_env() == "new"


def make_addon_dist(folder: Path, name: str, group: str) -> None:
    info = folder / f"{name}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n", encoding="utf-8")
    (info / "entry_points.txt").write_text(f"[{group}]\n{name} = {name}:register\n", encoding="utf-8")


def test_an_addon_under_the_old_group_still_loads_with_one_log_line(tmp_path, monkeypatch, caplog):
    make_addon_dist(tmp_path, "old_only_addon", "pm_cockpit.plugins")
    make_addon_dist(tmp_path, "new_addon", "thimbleby.plugins")
    make_addon_dist(tmp_path, "both_addon", "thimbleby.plugins")
    make_addon_dist(tmp_path, "both_addon_2", "pm_cockpit.plugins")
    (tmp_path / "both_addon-1.0.dist-info" / "entry_points.txt").write_text(
        "[thimbleby.plugins]\nboth_addon = both_addon:register\n"
        "[pm_cockpit.plugins]\nboth_addon = both_addon:register\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    legacy_names._told.clear()
    with caplog.at_level(logging.WARNING, logger="engine.legacy_names"):
        found = {ep.name for ep in legacy_names.addon_entry_points()}
        legacy_names.addon_entry_points()  # asked again: no second line
    assert {"old_only_addon", "new_addon", "both_addon", "both_addon_2"} <= found
    lines = [r.getMessage() for r in caplog.records if "old entry-point group" in r.getMessage()]
    assert sorted(line.split()[2] for line in lines) == ["both_addon_2", "old_only_addon"]
    assert all("thimbleby.plugins" in line for line in lines)
    assert [ep.name for ep in legacy_names.addon_entry_points(log_old=False)].count("both_addon") == 1


def test_the_apps_version_is_read_under_its_name_and_under_the_earlier_one(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    seen = []

    def only_old(name):
        seen.append(name)
        if name == "pm-cockpit":
            return "9.9.9"
        raise PackageNotFoundError(name)

    monkeypatch.setattr(legacy_names, "installed_version", only_old)
    assert legacy_names.distribution_version("thimbleby") == "9.9.9"
    assert legacy_names.distribution_version("pm_cockpit") == "9.9.9"
    assert seen[0] == "thimbleby"
    try:
        legacy_names.distribution_version("some-other-package")
    except PackageNotFoundError:
        pass
    else:
        raise AssertionError("another package is never read as the app")


def test_both_command_names_run_the_same_command():
    scripts = {ep.name: ep.value for ep in entry_points(group="console_scripts") if ep.dist.name == "thimbleby"}
    assert scripts["thimbleby"] == scripts["cockpit"] == "engine.cli:main"
    assert cli.COMMANDS == ("thimbleby", "cockpit")
    old_argv = sys.argv
    try:
        for name in cli.COMMANDS:
            sys.argv = [name]
            assert cli._parser().prog == "thimbleby"
    finally:
        sys.argv = old_argv
    assert {"thimbleby", "cockpit"} <= {p.name for p in Path(sys.executable).parent.iterdir()}


def test_the_private_folder_and_database_choose_the_existing_one(tmp_path):
    assert legacy_names.private_dir(tmp_path) == tmp_path / ".thimbleby"
    assert legacy_names.db_file(tmp_path) == tmp_path / "thimbleby.db"
    (tmp_path / ".cockpit").mkdir()
    (tmp_path / "cockpit.db").write_bytes(b"")
    assert legacy_names.private_dir(tmp_path) == tmp_path / ".cockpit"
    assert legacy_names.db_file(tmp_path) == tmp_path / "cockpit.db"
    (tmp_path / ".thimbleby").mkdir()
    (tmp_path / "thimbleby.db").write_bytes(b"")
    assert legacy_names.private_dir(tmp_path) == tmp_path / ".thimbleby"
    assert legacy_names.db_file(tmp_path) == tmp_path / "thimbleby.db"


def test_the_app_data_folder_and_the_per_person_files_are_read_under_the_old_names_when_the_new_are_absent(tmp_path):
    home = tmp_path / "home"
    share = {"XDG_DATA_HOME": str(tmp_path / "share")}
    # Nothing from before: the current name.
    assert legacy_names.app_name("Linux", share, home) == "thimbleby"
    # Only the old app-data folder: kept in use, never a second one beside it.
    (tmp_path / "share" / "cockpit").mkdir(parents=True)
    assert legacy_names.app_name("Linux", share, home) == "cockpit"
    (tmp_path / "share" / "thimbleby").mkdir()
    assert legacy_names.app_name("Linux", share, home) == "thimbleby"
    # The remembered workspace.
    old_file = home / ".pm-cockpit" / "last-workspace"
    old_file.parent.mkdir(parents=True)
    old_file.write_text("/somewhere\n")
    assert legacy_names.person_file(home, "last-workspace") == old_file
    new_file = home / ".thimbleby" / "last-workspace"
    new_file.parent.mkdir()
    new_file.write_text("/elsewhere\n")
    assert legacy_names.person_file(home, "last-workspace") == new_file
    # The packages the installer kept: the environment's folder under either name, else the per-person folder.
    assert legacy_names.packages_folder(home, {}) == home / ".thimbleby" / "packages"
    (home / ".pm-cockpit" / "packages").mkdir()
    assert legacy_names.packages_folder(home, {}) == home / ".pm-cockpit" / "packages"
    assert legacy_names.packages_folder(home, {"COCKPIT_PACKAGES": "/old-env"}) == Path("/old-env")
    assert legacy_names.packages_folder(home, {"COCKPIT_PACKAGES": "/old", "THIMBLEBY_PACKAGES": "/new"}) == Path(
        "/new"
    )


def test_the_workspace_remembered_under_the_old_folder_is_still_reopened(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "system_temp_roots", lambda: (tmp_path / "elsewhere",))
    (tmp_path / "home").mkdir()
    ws = init_workspace(tmp_path / "home" / "kept", git=False)
    old_file = tmp_path / "home" / ".pm-cockpit" / "last-workspace"
    old_file.parent.mkdir()
    old_file.write_text(f"{ws.root}\n")
    assert cli.last_workspace() == ws.root
    # Remembering writes the current name and leaves the old file alone.
    cli.remember_workspace(ws.root)
    assert (tmp_path / "home" / ".thimbleby" / "last-workspace").exists() and old_file.exists()
