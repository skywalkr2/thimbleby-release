"""Validate explicit build inputs without accessing external state."""

import re
from pathlib import PurePath

from packaging.version import Version


def release_versions(tag: str) -> tuple[str, str]:
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?", tag):
        raise ValueError("Use a vMAJOR.MINOR.PATCH tag, optionally with a prerelease or post-release suffix")
    version = Version(tag[1:])
    if any(part > 65535 for part in version.release):
        raise ValueError("Version components exceed the installer version limit")
    numeric = ".".join(str(part) for part in version.release)
    return str(version), numeric


#: The folders of the checkout the frozen app reads, at the same place under the frozen resource root as they are in the
#: checkout (`engine/shipped.py` and `engine/plugin_host.py` find them from the modules' own location): the built
#: screens, the starting templates, the AI endpoint catalog, the folders of non-code files inside `engine/`, and the
#: kit for defining one's own plugin. The fictional workspaces and the example plugin are not here: nothing made-up
#: ships in an installed app.
BUNDLED_FOLDERS = (
    "web/dist",
    "templates",
    "catalog",
    "engine/defaults",
    "engine/guide",
    "engine/prompts",
    "engine/playbook",
    "engine/ai/adapters",
    "plugins/kit",
    "plugins/parcels",
    "web/src/assets/brand",
)


def bundled_data(root: PurePath) -> tuple[tuple[str, str], ...]:
    return tuple((str(root / folder), folder) for folder in BUNDLED_FOLDERS)
