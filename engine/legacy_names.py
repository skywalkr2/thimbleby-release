"""The names the product used before it was called Thimbleby, read in one place.

A new workspace, backup or setting uses the current names. What an earlier version wrote is still opened and read, in
place: the workspace's private folder and database keep the names they have, the old environment prefix is still read,
and an add-on installed under the old entry-point group is still found. Nothing else in the code spells an old name
(`tests/test_legacy_names.py` checks the folder, the files, the settings and the backups of a new workspace)."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from importlib.metadata import EntryPoint, PackageNotFoundError, entry_points
from importlib.metadata import version as installed_version
from pathlib import Path

log = logging.getLogger(__name__)

DISTRIBUTION = "thimbleby"
PRIVATE_DIR = ".thimbleby"
DB_NAME = "thimbleby.db"
ENV_PREFIX = "THIMBLEBY__"
ENV_WORKSPACE = "THIMBLEBY_WORKSPACE"
ENTRY_POINT_GROUP = "thimbleby.plugins"
#: Names of an earlier version, read only here.
OLD_DISTRIBUTION = "pm-cockpit"
OLD_PRIVATE_DIR = ".cockpit"
OLD_DB_NAME = "cockpit.db"
OLD_ENV_PREFIX = "COCKPIT__"
OLD_ENV_WORKSPACE = "COCKPIT_WORKSPACE"
OLD_ENTRY_POINT_GROUP = "pm_cockpit.plugins"
OLD_TEMP_SUFFIX = ".cockpit-tmp"
OLD_CHECK_TEXT = b"cockpit backup key check"
#: The folder name in the system's app-data place, and the per-person folder (last workspace, kept packages) in the home
#: folder, as they were before the rename.
APP_NAME = "thimbleby"
OLD_APP_NAME = "cockpit"
PERSON_DIR = ".thimbleby"
OLD_PERSON_DIR = ".pm-cockpit"
ENV_PACKAGES = "THIMBLEBY_PACKAGES"
OLD_ENV_PACKAGES = "COCKPIT_PACKAGES"
OLD_DB_SUFFIXES = ("", "-wal", "-shm")
_told: set[str] = set()


def private_dir(root: Path) -> Path:
    """The folder for files that never leave this computer: the one the workspace already has, else the current name."""
    old = Path(root) / OLD_PRIVATE_DIR
    new = Path(root) / PRIVATE_DIR
    return old if old.is_dir() and not new.exists() else new


def db_file(root: Path) -> Path:
    """The workspace's database: the one it already has, else the current name. Never two copies."""
    old = Path(root) / OLD_DB_NAME
    new = Path(root) / DB_NAME
    return old if old.exists() and not new.exists() else new


def db_names() -> tuple[str, ...]:
    """Every name a database file (with its journal files) may have in a workspace or backup folder, current first."""
    return tuple(f"{base}{s}" for base in (DB_NAME, OLD_DB_NAME) for s in OLD_DB_SUFFIXES)


def backup_database(folder: Path) -> Path:
    """The database file inside a backup folder, whichever name the backup was written with."""
    old = Path(folder) / OLD_DB_NAME
    new = Path(folder) / DB_NAME
    return old if old.exists() and not new.exists() else new


def app_name(system: str, env: Mapping[str, str], home: str | Path) -> str:
    """The name of the app's folder in the system's app-data place: the one this computer already has, else the current
    name. Never two folders."""
    from engine.app_dirs import app_dirs

    try:
        old = Path(app_dirs(system, env, home, OLD_APP_NAME).data)
        new = Path(app_dirs(system, env, home, APP_NAME).data)
    except ValueError:
        return APP_NAME
    return OLD_APP_NAME if old.is_dir() and not new.exists() else APP_NAME


def person_file(home: Path, *names: str) -> Path:
    """A file in the per-person folder of the home folder: the one an earlier version wrote when the current name has
    none, else the current name (where it is written)."""
    new = Path(home).joinpath(PERSON_DIR, *names)
    old = Path(home).joinpath(OLD_PERSON_DIR, *names)
    return old if old.exists() and not new.exists() else new


def packages_folder(home: Path, env: Mapping[str, str] | None = None) -> Path:
    """Where the installer keeps the packages it installed: the folder the environment names (either name, the current
    one first), else the per-person folder's `packages`. `deploy/install.sh` and `install.ps1` choose the same way."""
    source = os.environ if env is None else env
    named = source.get(ENV_PACKAGES) or source.get(OLD_ENV_PACKAGES)
    if named:
        return Path(named)
    new = Path(home) / PERSON_DIR / "packages"
    old = Path(home) / OLD_PERSON_DIR / "packages"
    return old if old.is_dir() and not new.exists() else new


def workspace_from_env(env: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if env is None else env
    return source.get(ENV_WORKSPACE) or source.get(OLD_ENV_WORKSPACE) or None


def env_setting(name: str, env: Mapping[str, str] | None = None) -> str | None:
    """A setting given by an environment variable whose name after the prefix is `name` (e.g. `SERVER__ADDONS_DIR`)."""
    source = os.environ if env is None else env
    return merged_env(source).get(ENV_PREFIX + name)


def merged_env(env: Mapping[str, str]) -> dict[str, str]:
    """The settings variables of `env` under the current prefix. A variable under the old prefix counts only when the
    current one isn't set; when both are, the current one wins and the log says the old one was ignored."""
    out = {k: v for k, v in env.items() if k.startswith(ENV_PREFIX)}
    for key, value in env.items():
        if not key.startswith(OLD_ENV_PREFIX):
            continue
        new = ENV_PREFIX + key[len(OLD_ENV_PREFIX) :]
        if new in out:
            if key not in _told:
                _told.add(key)
                log.warning("%s is ignored: %s is set and wins", key, new)
        else:
            out[new] = value
    return out


def addon_entry_points(*, log_old: bool = True) -> list[EntryPoint]:
    """The installed add-ons' entry points: the current group, then any only found under the old group (one log line
    for each, so the add-on's maker is asked to move it)."""
    found = list(entry_points(group=ENTRY_POINT_GROUP))
    known = {ep.name for ep in found}
    for ep in entry_points(group=OLD_ENTRY_POINT_GROUP):
        if ep.name in known:
            continue
        known.add(ep.name)
        found.append(ep)
        if log_old and ep.name not in _told:
            _told.add(ep.name)
            log.warning(
                "the add-on %s is registered under the old entry-point group %s; its maker should use %s",
                ep.name,
                OLD_ENTRY_POINT_GROUP,
                ENTRY_POINT_GROUP,
            )
    return found


def check_texts(current: bytes) -> tuple[bytes, ...]:
    return (current, OLD_CHECK_TEXT)


def canonical_distribution(name: str) -> str:
    """The distribution a requirement names: the earlier name of the app means the app, so an add-on that still depends
    on it is met by the installed core, and never looked up in a package index."""
    plain = name.strip().lower().replace("_", "-").replace(".", "-")
    return DISTRIBUTION if plain == OLD_DISTRIBUTION else name


def distribution_version(name: str) -> str:
    """The installed version of a distribution, reading the app's own under its current name and, for an install made
    before the rename, under the earlier one. Raises `PackageNotFoundError` like `importlib.metadata.version`."""
    wanted = canonical_distribution(name)
    try:
        return installed_version(wanted)
    except PackageNotFoundError:
        if wanted == DISTRIBUTION:
            return installed_version(OLD_DISTRIBUTION)
        raise


def installer_marks() -> tuple[str, ...]:
    """What an installed add-on's `INSTALLER` file may say to count as installed from the Add-ons screen: the current
    name, and the earlier one for add-ons installed before the rename."""
    return (DISTRIBUTION, OLD_DISTRIBUTION)
