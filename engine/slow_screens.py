"""The main screens' time budget (design 6.13): each request's time is kept with its route, and a main screen whose
route is slower than `server.slow_screen_ms` on three loads in a row becomes one Today line, until three loads in a row
are fast again. The times live in this process only: a restart starts clean, and nothing here is written to the
workspace. A request's time says how long the app took, never what was in it, so the report drafted from it holds no
names."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: How many loads in a row make a screen slow, and how many make it fast again.
RUN = 3

#: Each main screen, and the route that loads its list. A route not named here is logged and never a screen.
SCREEN_ROUTES: dict[str, str] = {
    "/api/today/queue": "today",
    "/api/today/todo": "todos",
    "/api/open-items": "todos",
    "/api/people": "people",
    "/api/changes": "changes",
}
SCREENS = tuple(dict.fromkeys(SCREEN_ROUTES.values()))


@dataclass
class _Screen:
    recent: deque[float] = field(default_factory=lambda: deque(maxlen=RUN))
    showing: bool = False


class SlowScreens:
    """The recent load times of each main screen, and which are slow now."""

    def __init__(self, limit_ms: int):
        self.limit_ms = limit_ms
        self._lock = threading.Lock()
        self._screens: dict[str, _Screen] = {}

    def note(self, route: str, ms: float) -> None:
        """Keep one request's time. Logged for every route; a main screen's route also counts toward its screen."""
        log.info("request %s took %.0f ms", route, ms)
        screen = SCREEN_ROUTES.get(route)
        if screen is None:
            return
        with self._lock:
            state = self._screens.setdefault(screen, _Screen())
            state.recent.append(ms)
            if len(state.recent) < RUN:
                return
            if not state.showing and all(t > self.limit_ms for t in state.recent):
                state.showing = True
            elif state.showing and all(t <= self.limit_ms for t in state.recent):
                state.showing = False

    def slow(self) -> dict[str, float]:
        """The screens that are slow now, each with the seconds its latest load took."""
        with self._lock:
            return {name: s.recent[-1] / 1000 for name, s in self._screens.items() if s.showing and s.recent}


_by_workspace: dict[str, SlowScreens] = {}
_registry_lock = threading.Lock()


def for_workspace(root: Path | str, limit_ms: int | None = None) -> SlowScreens:
    """The one record of a workspace's load times in this process. `limit_ms` sets the limit when it is given."""
    with _registry_lock:
        found = _by_workspace.setdefault(str(root), SlowScreens(limit_ms if limit_ms is not None else 3000))
        if limit_ms is not None:
            found.limit_ms = limit_ms
        return found


def report_text(cfg: Any, store: Any, screen: str, seconds: float, limit_ms: int) -> tuple[str, str]:
    """A report for the product's maintainers about a slow screen, as a title and the text, for the person to read and
    send (the app sends nothing): the screen's name, how long it took, the limit, and how many records of each kind
    the workspace holds (counts only). Nothing in it names a person, project or file."""
    from engine.sides import word

    name = word(cfg, f"slow_screen.name.{screen}")
    held = ", ".join(f"{count} {kind}" for kind, count in counts_of(store).items())
    title = word(cfg, "slow_screen.report_title").format(screen=name)
    text = word(cfg, "slow_screen.report_text").format(
        screen=name, seconds=f"{seconds:.1f}", limit=f"{limit_ms / 1000:.1f}", held=held
    )
    return title, text


def counts_of(store: Any) -> dict[str, int]:
    """How many records of the kinds a main screen reads the workspace holds, as counts only."""
    view = store.read()
    return {kind: len(view.list(kind)) for kind in ("action", "person", "request", "changeset", "source")}
