"""Where add-ons installed from the app are kept on this computer, and putting them on the import path at start.

The folder is outside the Python environment the app runs in, so rebuilding that environment (a source checkout's
`uv sync`, a reinstall of the app) never removes an add-on. It is in the app's own data place for the system
(`engine/app_dirs.py`) unless `server.addons_dir` (or `THIMBLEBY__SERVER__ADDONS_DIR`) names another folder."""

from __future__ import annotations

import logging
import os
import platform
import sys
from collections.abc import Mapping
from pathlib import Path

from engine.legacy_names import APP_NAME as CURRENT_APP_NAME
from engine.legacy_names import app_name, env_setting

#: The folder the app's data place is named by.
APP_NAME = CURRENT_APP_NAME
#: Inside the add-ons folder: the packages themselves, one folder for pure Python and compiled libraries alike.
SITE = "site"

#: The environment variable that names the folder, the same name every setting has (`server.addons_dir`).
ENV_ADDONS_DIR = "THIMBLEBY__SERVER__ADDONS_DIR"
log = logging.getLogger(__name__)

_active: Path | None = None


def default_folder(env: Mapping[str, str] | None = None) -> Path:
    """The add-ons folder in this computer's app data place, by the system's own convention."""
    from engine.app_dirs import app_dirs

    env = os.environ if env is None else env
    system, home = platform.system() or "Linux", Path.home()
    args = (system, env, home, app_name(system, env, home))
    try:
        return Path(app_dirs(*args, install_dir=Path(__file__).resolve().parents[1]).addons)
    except ValueError:
        # No place outside the app's own folder was found (a home folder inside it): use the plain place.
        return Path(app_dirs(*args).addons)


def resolve(configured: str | None = None) -> Path:
    """The add-ons folder by the settings: the one given, else the environment's, else the app data place."""
    if configured:
        return Path(configured).expanduser()
    named = (env_setting("SERVER__ADDONS_DIR") or "").strip()
    return Path(named).expanduser() if named else default_folder()


def folder() -> Path:
    """The add-ons folder in use: the one activated at start, or the one the settings name before that."""
    return _active if _active is not None else resolve()


def site_folder() -> Path:
    """The folder packages are unpacked into, and the one put on the import path."""
    return folder() / SITE


def _from(module: object, place: Path) -> bool:
    """Whether a loaded module's file is inside the add-ons folder."""
    where = getattr(module, "__file__", None)
    if not where:
        return False
    try:
        return Path(where).resolve().is_relative_to(place.resolve())
    except (OSError, ValueError):
        return False


def activate(configured: str | None = None) -> Path:
    """Put the add-ons folder on the import path (and so on the path add-on entry points are found on), and move any
    add-on installed the old way, into the Python environment, here. Called once at start before add-ons are
    discovered; calling it again with the same folder changes nothing. Returns the folder holding the packages."""
    global _active
    root = resolve(configured)
    _active = root
    place = root / SITE
    try:
        place.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        log.warning("The add-ons folder %s can't be made (%s); add-ons installed from the app won't load.", place, err)
        return place
    # An app built again in the same process (an add-on installed, updated or removed) imports its add-ons afresh: the
    # previous app has stopped, so modules it loaded from this folder are dropped and an updated add-on's new files are
    # the ones used.
    for module in [n for n, m in sys.modules.items() if _from(m, place)]:
        del sys.modules[module]
    if str(place) not in sys.path:
        # Appended, so the app's own packages win. Never `site.addsitedir`: it runs the `import` lines of every `.pth`
        # file in the folder, and installing an add-on must not run anything.
        sys.path.append(str(place))
    import importlib

    importlib.invalidate_caches()
    from engine import pack_install

    try:
        moved = pack_install.move_old_installs(place)
    except OSError as err:
        log.warning("Add-ons installed in the app's own folders couldn't be moved to %s: %s", place, err)
        moved = []
    for line in moved:
        log.info("Moved the add-on %s from the app's own packages to %s.", line, place)
    if moved:
        importlib.invalidate_caches()
    return place
