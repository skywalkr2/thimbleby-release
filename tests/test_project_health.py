"""What the app sees beside a project's typed status (design 7.13): when a status that says all is well disagrees with
overdue to-dos, a quiet project or a passed target, and when it does not."""

from __future__ import annotations

from datetime import date

import pytest

from engine import project_health

TODAY = date(2026, 11, 23)


def read(meaning, *, overdue=0, last_change="2026-11-20T10:00:00+00:00", target=None, weeks=4):
    return project_health.read(
        meaning=meaning, overdue=overdue, last_change=last_change, target=target, today=TODAY, quiet_after_weeks=weeks
    )


def test_on_track_beside_overdue_todos_and_a_quiet_project_disagrees():
    found = read("open", overdue=6, last_change="2026-10-12T10:00:00+00:00")
    assert found.disagrees and found.overdue == 6 and found.quiet_weeks == 6


@pytest.mark.parametrize("meaning", ["open", "not_started"])
def test_each_status_that_says_all_is_well_can_disagree(meaning):
    assert read(meaning, overdue=1).disagrees


@pytest.mark.parametrize("meaning", ["at_risk", "blocked", "done", None])
def test_a_status_that_already_says_trouble_or_is_finished_or_unset_never_disagrees(meaning):
    assert not read(meaning, overdue=3, target="2026-01-01").disagrees


def test_a_recent_project_with_nothing_overdue_agrees():
    found = read("open", target="2027-01-01")
    assert not found.disagrees and found.quiet_weeks == 0 and not found.target_passed


def test_a_passed_target_or_a_quiet_stretch_alone_disagrees_and_the_weeks_are_the_setting():
    assert read("open", target="2026-11-01").disagrees
    assert read("open", last_change="2026-10-26T00:00:00+00:00", weeks=4).disagrees
    assert not read("open", last_change="2026-10-26T00:00:00+00:00", weeks=5).disagrees


def test_the_projects_list_marks_a_status_that_says_all_is_well_beside_an_overdue_to_do():
    """Through the API: the status the person typed stays, and the counts behind the mark come with it."""
    import tempfile
    from datetime import UTC, datetime
    from pathlib import Path

    from fastapi.testclient import TestClient

    from api.app import create_app
    from engine.today import zone
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B
    from tests.test_corrections import pm_of

    with tempfile.TemporaryDirectory() as tmp:
        ws = init_workspace(Path(tmp) / "ws", template=DEMO_B, git=False)
        cfg = ws.config(env={}, flags={"storage.backups.automatic": False})
        app = create_app(ws, cfg, "t", ui_dist=Path(tmp) / "no-ui", start_worker=False)
        with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
            now = datetime.now(zone(cfg)).astimezone(UTC)
            app.state.store.clock = lambda: now.isoformat()
            before = {p["id"]: p for p in client.get("/api/projects").json()}
            target = next(p for p in before.values() if p["status_meaning"] == "open" and not p["side"])
            made = client.post(
                "/api/todos",
                json={"text": "Late thing", "when": "2020-01-02", "owners": [pm_of(cfg)], "project": target["id"]},
            )
            assert made.status_code == 200, made.text
            row = next(p for p in client.get("/api/projects").json() if p["id"] == target["id"])
            assert row["status"] == target["status"]
            assert row["overdue_actions"] >= 1 and row["status_disagrees"] is True
