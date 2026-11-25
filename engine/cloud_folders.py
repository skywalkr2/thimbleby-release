"""Cloud-drive folders on this computer, offered as the place for backups (design 7.8).

Which drives to look for, and where each keeps its folder on each system, is a setting (`storage.backups.cloud_folders`,
with the app's own list in `engine/defaults/cloud_folders.yaml`); nothing here names a drive. A drive is found when one
of its places on this system exists inside the home folder. The first found that is not a work account's is the one the
guide recommends.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from engine.yaml_load import load_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable

    from engine.config.schema import CloudFolder

DEFAULTS = Path(__file__).parent / "defaults" / "cloud_folders.yaml"
#: What joins the folders of a path shown to the person.
ARROW = " › "


@dataclass(frozen=True)
class Found:
    name: str  # the drive's name, as the entry gives it
    root: Path  # the drive's folder on this computer
    account: str = ""  # the account the folder is named after, when its name has one ("" for a plain folder)
    work: bool = False  # the folder belongs to an account that is not one of the drive's personal ones


def system_name() -> str:
    """Which of the three places an entry lists applies on this computer: "macos", "windows" or "linux"."""
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def shipped() -> list[CloudFolder]:
    """The app's own list of drives to look for."""
    from engine.config.schema import CloudFolder

    data = load_yaml(DEFAULTS.read_text(encoding="utf-8")) or {}
    return [CloudFolder.model_validate(entry) for entry in data.get("folders", [])]


def _account(place: str, root: Path, home: Path) -> str:
    """The account a drive's folder is named after: the part of its name that the place's `*` matched ("OneDrive - Acme"
    on a place "OneDrive - *" gives "Acme"). Empty when the place has no `*`."""
    parts = Path(place).parts
    shown = root.relative_to(home).parts if root.is_relative_to(home) else ()
    for pattern, name in zip(parts, shown, strict=False):
        if "*" in pattern:
            found = re.fullmatch(re.escape(pattern).replace(r"\*", "(.*)"), name)
            return found.group(1).strip(" -_") if found else ""
    return ""


def found(drives: Iterable[CloudFolder], home: Path, system: str | None = None) -> list[Found]:
    """The drives whose folder exists on this computer, in the order of the list, each with the first of its places that
    is a folder. A place may use `*` to match any characters in a name. A folder named after an account says
    which; it is `work` unless the account is one the drive lists as personal (a match at the end of its name)."""
    here = system or system_name()
    out: list[Found] = []
    for drive in drives:
        for place in getattr(drive, here, []):
            root = next((p for p in sorted(home.glob(place)) if p.is_dir()), None)
            if root is not None:
                account = _account(place, root, home)
                personal = any(account.lower().endswith(x.lower()) for x in drive.personal if x.strip())
                out.append(Found(drive.name, root, account, bool(account) and not personal))
                break
    return out


def recommended(drives: list[Found]) -> int | None:
    """The index of the drive the guide recommends: the first that is not a work account's, so a personal workspace is
    never one click from an employer's drive. None when every drive found is a work one."""
    return next((n for n, d in enumerate(drives) if not d.work), None)


def shown(parts: Iterable[str]) -> str:
    """A path of folders as the person reads it: plain names joined with arrows."""
    return ARROW.join(parts)


def make_backup_folder(root: Path, parts: Iterable[str]) -> Path:
    """The folder for backups inside a drive's folder, made when it isn't there yet."""
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    return folder
