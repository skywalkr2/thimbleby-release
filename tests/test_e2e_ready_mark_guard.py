"""A browser test opens a screen by the page's own ready mark (`openScreen`, `screenReady`), never by a `goto`
followed by a wait for the first heading with the default wait: a busy machine draws the heading late, and the wait
then fails for a reason that is not the app's. A journey that changes its server's state takes no automatic re-run,
which would start from the used server."""

from __future__ import annotations

import re
from pathlib import Path

E2E = Path(__file__).resolve().parents[1] / "web" / "e2e"
GOTO = re.compile(r"page\.goto\(")
FIRST_HEADING = re.compile(r'getByRole\("heading", \{ level: 1[^}]*\}\)\.first\(\)\)\.toBeVisible\(\)')
NO_RE_RUN = "test.describe.configure({ retries: 0 })"


def test_no_goto_is_followed_by_a_first_heading_wait_with_the_default_wait():
    found = []
    for spec in sorted(E2E.glob("*.ts")):
        lines = spec.read_text().splitlines()
        for i, line in enumerate(lines):
            if GOTO.search(line) and any(FIRST_HEADING.search(nxt) for nxt in lines[i + 1 : i + 4]):
                found.append(f"{spec.name}:{i + 1}")
    assert not found, f"open these by openScreen (web/e2e/open-screen.ts): {found}"


def test_every_journey_that_changes_its_server_takes_no_re_run():
    missing = []
    for spec in sorted(E2E.glob("journeys*.spec.ts")):
        text = spec.read_text()
        if "test.describe.serial(" in text and NO_RE_RUN not in text:
            missing.append(spec.name)
    assert not missing, f"a journey's re-run starts from its used server; mark it `{NO_RE_RUN}`: {missing}"


CONFIG = E2E.parent / "playwright.config.ts"


def test_the_servers_of_the_projects_that_read_the_weekday_start_on_a_monday_inside_the_process():
    """Today shows the Monday briefing on its weekly day only, so a project that tests what it holds or a side's filter
    over it starts its server on a Monday (`--clock-at`, time-machine), whatever day the run is on."""
    text = CONFIG.read_text()
    lines = [line for line in text.splitlines() if "tests.e2e_server" in line]
    for flag in ("--review-r3", "--review-r4"):
        assert any(flag in line and "--clock-at ${mondayAt}" in line for line in lines), flag
    assert any("--sides --plain-stages --clock-at ${mondayAt}" in line for line in lines)
    assert "faketime" not in text
