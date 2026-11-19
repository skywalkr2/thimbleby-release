"""Which build of the app this is: its number and commit, stamped when the installer is built, and the rule for which
of two copies is newer.

The release build's prepare step writes `catalog/build.yaml` (`number`, `commit`) before the app is frozen. A copy run
from source has no such file, says so, and is never taken to be newer than a copy that has a number."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from engine.shipped import shipped
from engine.yaml_load import load_yaml

BUILD_FILE = "build.yaml"


@dataclass(frozen=True)
class Build:
    """The version the package says, and the build's number and commit (None and empty for a source run)."""

    version: str
    number: int | None = None
    commit: str = ""

    def identity(self) -> dict[str, Any]:
        """What a running copy publishes about itself for a second open to read."""
        return {"version": self.version, "build": self.number, "commit": self.commit}


def stamp(catalog: Path | None = None) -> tuple[int | None, str]:
    """The number and commit written at build time; (None, "") when this is not a stamped build."""
    folder = catalog if catalog is not None else shipped("catalog")
    try:
        data = load_yaml((folder / BUILD_FILE).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    number, commit = data.get("number"), data.get("commit")
    return (
        number if type(number) is int and number > 0 else None,
        commit.strip()[:12] if isinstance(commit, str) else "",
    )


def current(catalog: Path | None = None) -> Build:
    from engine import __version__

    number, commit = stamp(catalog)
    return Build(__version__, number, commit)


def from_published(details: dict[str, Any] | None) -> Build | None:
    """A running copy's published identity; None when it published none (a copy older than the stamp)."""
    if not details or not isinstance(details.get("version"), str):
        return None
    number, commit = details.get("build"), details.get("commit")
    return Build(
        details["version"],
        number if type(number) is int and number > 0 else None,
        commit if isinstance(commit, str) else "",
    )


def is_newer(new: Build, running: Build | None) -> bool:
    """Whether `new` should take over from `running`: a copy that published no identity is older than any stamped build;
    otherwise the higher package version wins, and at the same version the higher build number, when both have one. The
    same, an older and an unnumbered (source) copy never take over."""
    from packaging.version import InvalidVersion, Version

    if running is None:
        return new.number is not None
    try:
        if Version(new.version) != Version(running.version):
            return Version(new.version) > Version(running.version)
    except InvalidVersion:
        return False
    return new.number is not None and running.number is not None and new.number > running.number
