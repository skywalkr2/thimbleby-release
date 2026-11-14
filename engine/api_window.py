"""The window across one minor plugin API release (design 3.3): which of a pack's declared ranges the core serves."""

from __future__ import annotations

from typing import Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from engine.plugin_api import PLUGIN_API_COMPAT, PLUGIN_API_VERSION

#: The note a pack in the window carries on its row and in Add-ons.
EARLIER_NOTE = "Built for an earlier version: ask its maker for an update"

Served = Literal["current", "earlier", "outside"]


def served(plugin_api: str, version: str = PLUGIN_API_VERSION, compat: str = PLUGIN_API_COMPAT) -> Served:
    """`current` when the range includes this core's version; `earlier` when it instead reaches the end of the earlier
    minor version the core still serves; `outside` otherwise, including a range that can't be read."""
    try:
        spec = SpecifierSet(plugin_api)
        if spec.contains(version, prereleases=True):
            return "current"
        # A pack made for the earlier minor works on any of its releases; its newest is above any patch number in use.
        if compat and spec.contains(Version(f"{compat}.9999"), prereleases=True):
            return "earlier"
    except InvalidSpecifier:
        pass
    return "outside"
