"""The copy this computer keeps for itself (design 6.13): a daily one from the first day, a fixed number kept, one
before every update and every change to how records are saved, a stop when that copy can't be made, a restore from
Settings, and Today's line until a folder off this computer is chosen."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from engine import backup, updating
from engine.backup import local_folder, run_local
from engine.config.schema import BackupTarget
from engine.storage import Store, StoreError
from engine.storage import migrations as m
from engine.workspace import init_workspace
from tests.test_first_backup import make
from tests.test_follow_up_lines import backing_up, env  # noqa: F401  (the promise lines' workspace fixture)
from tests.test_promise_lines import NOW as TODAY_NOW
from tests.test_promise_lines import lines
from tests.test_record_migrations import earlier_workspace, rename_display_name
from tests.test_setup import client

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def copies(ws) -> list[Path]:
    folder = local_folder(ws, ws.config().storage.backups)
    return sorted(p for p in folder.iterdir() if backup.is_copy_of(p.name, ws.root.name)) if folder.is_dir() else []


def blocked_folder(tmp_path: Path, ws) -> None:
    """Make the local folder impossible to create: a file sits where its parent folder should be."""
    (tmp_path / "file").write_text("x")
    from engine.config.yaml_edit import set_key

    path = ws.config_dir / "storage.yaml"
    path.write_text(
        set_key(path.read_text(encoding="utf-8"), ["backups", "local_folder"], str(tmp_path / "file" / "inside")),
        encoding="utf-8",
    )


def test_a_fresh_workspace_has_a_local_copy_after_its_first_day_with_no_folder_chosen(tmp_path):
    ws, cfg, store = make(tmp_path)
    from engine.worker import Events, Worker

    worker = Worker(ws, store, cfg, Events())
    assert cfg.storage.backups.targets == [] and copies(ws) == []
    worker.backup_if_due()
    [one] = copies(ws)
    assert (one / "thimbleby.db").is_file() and (one / "config").is_dir()
    assert not one.resolve().is_relative_to(ws.root.resolve())
    worker.backup_if_due()  # the same day: nothing more
    assert len(copies(ws)) == 1


def test_the_fifteenth_day_leaves_fourteen(tmp_path):
    ws, cfg, store = make(tmp_path)
    settings = cfg.storage.backups
    assert settings.local_keep == 14
    for day in range(15):
        now = NOW + timedelta(days=day)
        assert backup.local_due(ws, settings, now)
        run_local(ws, settings, now)
    names = [p.name for p in copies(ws)]
    assert len(names) == 14 and names[0].endswith("20261010-140000") and names[-1].endswith("20261023-140000")
    assert not backup.local_due(ws, settings, NOW + timedelta(days=14, hours=3))


def test_a_local_folder_inside_the_workspace_is_refused_and_says_why(tmp_path):
    ws, cfg, store = make(tmp_path)
    cfg.storage.backups.local_folder = str(ws.root / "copies")
    entry = run_local(ws, cfg.storage.backups, NOW)
    assert "inside the workspace" in entry["last_error"] and not (ws.root / "copies").exists()


def test_an_update_makes_a_copy_first_even_when_the_daily_one_ran_that_day(tmp_path):
    ws, cfg, store = make(tmp_path)
    run_local(ws, cfg.storage.backups, NOW)
    assert len(copies(ws)) == 1
    updating.backup(ws, "abc1234", NOW)  # the same moment: still a copy of its own
    assert len(copies(ws)) == 2 and updating.note(ws)["version"] == "abc1234"


def test_a_failed_local_copy_stops_the_update_with_a_plain_reason(tmp_path):
    ws, cfg, store = make(tmp_path)
    blocked_folder(tmp_path, ws)
    with pytest.raises(updating.UpdateError, match="Nothing was changed, because the copy kept on this computer"):
        updating.backup(ws, "abc1234", NOW)
    assert updating.note(ws) is None  # the update's own copy was never started


def test_a_change_to_how_records_are_saved_makes_a_copy_first_and_a_failed_copy_stops_it(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration("person", "rename-display-name", 2, rename_display_name)])
    ws = earlier_workspace(tmp_path)
    assert copies(ws) == []
    blocked_folder(tmp_path, ws)
    with pytest.raises(StoreError, match="Nothing was changed, because the copy kept on this computer"):
        Store(ws.db_path)
    # The workspace is as it was: opening it again with the copy possible migrates it, after one copy.
    (ws.config_dir / "storage.yaml").write_text(
        (ws.config_dir / "storage.yaml").read_text(encoding="utf-8").replace(str(tmp_path / "file" / "inside"), ""),
        encoding="utf-8",
    )
    Store(ws.db_path).close()
    [one] = copies(ws)
    import sqlite3

    kept = sqlite3.connect(one / "thimbleby.db")
    try:
        assert kept.execute("SELECT data FROM records WHERE kind='person' LIMIT 1").fetchone()[0].count("display_name")
    finally:
        kept.close()


def test_a_new_workspace_makes_no_copy_for_a_migration_it_does_not_need(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration("person", "rename-display-name", 2, rename_display_name)])
    ws = init_workspace(tmp_path / "fresh", git=False)
    Store(ws.db_path).close()
    assert copies(ws) == []


def test_settings_backups_lists_the_local_copy_and_restores_from_it(tmp_path):
    ws, cfg, store = make(tmp_path)
    c, api = client(ws, cfg, store)
    run_local(ws, cfg.storage.backups, NOW)
    body = c.get(f"{api}/backups").json()
    assert body["targets"] == [] and body["local_last_success"] and body["local_last_error"] is None
    [copy] = body["copies"]
    assert copy["local"] is True and copy["encrypted"] is False
    staged = c.post(f"{api}/backups/restore", json={"path": copy["path"]})
    assert staged.status_code == 200 and staged.json()["pending"]["kind"] == "backup"
    assert (ws.private_dir / "restore-pending").is_dir()


def test_todays_line_stays_while_only_the_local_copy_exists_and_leaves_with_a_folder(env, tmp_path):  # noqa: F811
    ws, cfg, _ = env
    run_local(ws, cfg.storage.backups, TODAY_NOW)
    (line,) = backing_up(env, target=False)
    assert (line.group, line.state) == ("setup", "unset")
    cfg.storage.backups.targets = [BackupTarget(path=str(tmp_path / "drive"))]
    (tmp_path / "drive").mkdir()
    backup.run_backup(ws, cfg, TODAY_NOW)
    assert [x for x in lines(env) if x.kind == "backup"] == []


def test_the_nudge_can_be_put_off_and_a_failed_copy_still_shows(env):  # noqa: F811
    """The nudge stays until a folder is chosen or it is put off; a failed copy is never put off with it."""
    from engine import suggestions

    ws, cfg, store = env
    run_local(ws, cfg.storage.backups, TODAY_NOW)
    (line,) = backing_up(env, target=False)
    assert line.state == "unset"
    suggestions.put_off(store, cfg, line, TODAY_NOW)
    assert [x for x in lines(env) if x.kind == "backup"] == []
    # The local copy fails: another state, so the line comes back as the risk it is.
    cfg.storage.backups.local_folder = str(ws.root / "inside")  # a folder inside the workspace is refused
    run_local(ws, cfg.storage.backups, TODAY_NOW + timedelta(days=3))
    shown = [x for x in lines(env) if x.kind == "backup"]
    assert shown and shown[0].state != "unset"


def test_the_nudge_put_off_comes_back_after_its_days_while_there_is_still_no_folder(env):  # noqa: F811
    """The owner: a tester who taps Not now in week one is reminded once more that a lost laptop means lost data."""
    from engine import suggestions
    from engine.today_queue import queue

    ws, cfg, store = env
    assert cfg.storage.backups.nudge_again_days == 14
    run_local(ws, cfg.storage.backups, TODAY_NOW)
    (line,) = backing_up(env, target=False)
    suggestions.put_off(store, cfg, line, TODAY_NOW)

    def nudged(days: int) -> bool:
        at = TODAY_NOW + timedelta(days=days)
        run_local(ws, cfg.storage.backups, at)  # the daily copy keeps running, so only the nudge is in question
        return any(x.kind == "backup" for x in queue(ws, store, cfg, at))

    assert not nudged(13)
    assert nudged(15)


def test_the_local_copy_is_included_in_what_deleting_the_workspace_lists(tmp_path):
    from engine import erase

    ws, cfg, store = make(tmp_path)
    run_local(ws, cfg.storage.backups, NOW)
    plan = erase.plan(ws, cfg)
    assert any(i.kind == erase.BACKUP for i in plan.items)


def test_the_state_says_this_computer_only_and_warns_only_for_a_failed_or_old_copy(tmp_path):
    ws, cfg, _ = make(tmp_path)
    settings = cfg.storage.backups
    assert settings.warn_after_hours == 48
    run_local(ws, settings, NOW)
    fresh = backup.state(ws, cfg, NOW + timedelta(hours=3))
    assert (fresh.configured, fresh.needs_attention, fresh.folder, fresh.newest_hours) == (False, False, None, 3.0)
    three_days = backup.state(ws, cfg, NOW + timedelta(days=3))
    assert (three_days.needs_attention, three_days.problem, three_days.newest_hours) == (True, "overdue", 72.0)
    blocked_folder(tmp_path, ws)
    failed_cfg = ws.config()
    run_local(ws, failed_cfg.storage.backups, NOW + timedelta(hours=1))
    failed = backup.state(ws, failed_cfg, NOW + timedelta(hours=2))
    assert (failed.needs_attention, failed.problem) == (True, "failed") and failed.last_error


def test_a_folder_off_the_computer_is_named_and_a_fresh_copy_there_is_quiet(tmp_path):
    ws, cfg, _ = make(tmp_path)
    drive = tmp_path / "drive"
    drive.mkdir()
    cfg.storage.backups.targets = [BackupTarget(path=str(drive))]
    backup.run_backup(ws, cfg, NOW)
    kept = backup.state(ws, cfg, NOW + timedelta(hours=2))
    assert (kept.configured, kept.needs_attention, kept.folder, kept.newest_hours) == (True, False, "drive", 2.0)


def test_the_status_route_sends_the_folder_and_the_age_of_the_newest_copy(tmp_path):
    ws, cfg, store = make(tmp_path)
    run_local(ws, cfg.storage.backups, datetime.now(UTC))
    c, base = client(ws, cfg, store)
    sent = c.get(f"{base}/status").json()["backup"]
    assert sent["configured"] is False and sent["folder"] == "" and sent["needs_attention"] is False
    assert 0 <= sent["newest_hours"] < 1


def test_with_no_folder_the_local_copy_is_due_again_the_next_day_and_back_up_now_makes_it(tmp_path):
    """S-0794: the automatic switch covers the local copy, so day two makes one with no folder; Back up now too."""
    ws, cfg, store = make(tmp_path)
    settings = cfg.storage.backups
    assert settings.automatic and settings.targets == []
    run_local(ws, settings, NOW)
    assert not backup.local_due(ws, settings, NOW + timedelta(hours=3))
    assert backup.local_due(ws, settings, NOW + timedelta(hours=25))
    c, base = client(ws, cfg, store)
    assert c.post(f"{base}/backup").status_code == 200
    assert len(copies(ws)) == 2
    assert c.get(f"{base}/backups").json()["schedule"] is True


def test_a_copy_never_made_warns_after_warn_after_hours_counted_from_the_first_day(tmp_path):
    """S-0794: with the daily job never run, the header doesn't promise a copy that doesn't exist."""
    ws, cfg, _ = make(tmp_path)
    assert backup.state(ws, cfg, NOW).needs_attention is False  # nothing noted yet: quiet, as before
    backup.note_started(ws, NOW)
    backup.note_started(ws, NOW + timedelta(days=9))  # only the first day counts
    assert backup.state(ws, cfg, NOW + timedelta(hours=47)).needs_attention is False
    late = backup.state(ws, cfg, NOW + timedelta(hours=49))
    assert (late.needs_attention, late.problem) == (True, "never")
    run_local(ws, cfg.storage.backups, NOW + timedelta(hours=50))
    assert backup.state(ws, cfg, NOW + timedelta(hours=51)).needs_attention is False


def _missing_folder(tmp_path):
    ws, cfg, store = make(tmp_path)
    run_local(ws, cfg.storage.backups, NOW)
    cfg.storage.backups.targets = [BackupTarget(path=str(tmp_path / "Account" / "cloud"), label="cloud folder")]
    backup.run_backup(ws, cfg, NOW + timedelta(hours=1))  # the folder isn't there: refused, never created
    return ws, cfg, store


def test_only_the_folder_missing_is_one_state_with_one_set_of_words_and_no_full_path(tmp_path):
    """S-0795, S-0796: the header, the popover, Today and /api/backups say "Backup folder missing"; the copy kept on
    this computer is named; the full path (it holds the account's name) is nowhere in them."""
    ws, cfg, store = _missing_folder(tmp_path)
    at = NOW + timedelta(hours=2)
    kept = backup.state(ws, cfg, at)
    assert (kept.configured, kept.needs_attention, kept.problem) == (True, True, "folder_missing")
    assert kept.message.startswith("Backup folder missing: 'cloud folder' not found.")
    assert "on this computer" in kept.message and "No successful backup" not in kept.message
    assert kept.folder == "cloud folder" and kept.newest_at is not None
    assert "Account" not in (kept.last_error or "") and "Account" not in kept.message
    from engine.today_queue import queue

    (line,) = [x for x in queue(ws, store, cfg, at) if x.kind == "backup"]
    assert (line.state, line.subject, line.group) == ("folder_missing", "cloud folder", "risk")
    assert line.since == kept.newest_at and line.age_hours == 2.0


def test_the_routes_never_send_the_full_path_and_the_path_is_behind_details(tmp_path):
    ws, cfg, store = _missing_folder(tmp_path)
    c, base = client(ws, cfg, store)
    sent = c.get(f"{base}/status").json()["backup"]
    assert sent["folder"] == "cloud folder" and sent["problem"] == "folder_missing"
    assert "Account" not in str(sent) and str(tmp_path) not in str(sent)
    body = c.get(f"{base}/backups").json()
    assert "No successful backup yet" not in body["message"] and body["state"]["problem"] == "folder_missing"
    assert "Account" not in body["message"] and str(tmp_path) not in str(body["state"])
    assert str(tmp_path) not in str([t["last_error"] for t in body["targets"]])
    assert body["local_path"] and body["targets"][0]["path"].endswith("cloud")  # for the page's Details only


def test_a_folder_with_no_label_is_named_by_its_own_name_not_its_path(tmp_path):
    ws, cfg, _ = make(tmp_path)
    run_local(ws, cfg.storage.backups, NOW)
    cfg.storage.backups.targets = [BackupTarget(path=str(tmp_path / "Account" / "lantern-backups"))]
    backup.run_backup(ws, cfg, NOW + timedelta(hours=1))
    kept = backup.state(ws, cfg, NOW + timedelta(hours=2))
    assert kept.folder == "lantern-backups" and "Account" not in kept.message


def test_not_now_on_the_folder_nudge_answers_with_the_day_it_comes_back(tmp_path):
    """S-0801: Not now's toast says "Back on Today on <day>", so the answer gives that day (`nudge_again_days` on)."""
    ws, cfg, store = make(tmp_path)
    run_local(ws, cfg.storage.backups, datetime.now(UTC))
    c, base = client(ws, cfg, store)
    put = c.post(f"{base}/suggestions/not-now", json={"key": "backup"})
    assert put.status_code == 200, put.text
    again = datetime.fromisoformat(put.json()["until"])
    days = (again - datetime.now(UTC)).total_seconds() / 86400
    assert abs(days - cfg.storage.backups.nudge_again_days) < 0.1


def test_one_demo_has_the_weeks_goals_and_no_backup_folder_so_all_good_and_the_nudge_show(tmp_path):
    """S-0801: one demo is seeded with the week's goals and an unset backup."""
    from engine.shipped import demo

    ws = init_workspace(tmp_path / "demo", template=demo("demo-a"), history=True)
    cfg = ws.config()
    assert cfg.storage.backups.targets == []
    store = Store(ws.db_path, cfg=cfg)
    plans = store.read().list("week_plan")
    assert len(plans) == 1 and len(plans[0].data["goals"]) >= 2 and plans[0].data["confirmed_at"]


def test_a_failed_try_into_a_folder_that_is_there_is_still_failed_not_missing(tmp_path):
    ws, cfg, _ = make(tmp_path)
    drive = tmp_path / "drive"
    drive.mkdir()
    cfg.storage.backups.targets = [BackupTarget(path=str(drive), label="drive")]
    backup.run_backup(ws, cfg, NOW)
    status = backup._load(ws)
    status[str(drive)]["last_error"] = "no space left on the disk"
    backup._save(ws, status)
    kept = backup.state(ws, cfg, NOW + timedelta(hours=30))
    assert (kept.problem, kept.needs_attention) == ("failed", True)
