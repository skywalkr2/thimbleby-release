"""Whether an agent program is older than the versions the catalog says were tested, said as one line of advice.

The catalog entry of a kind of account may carry `tested_versions` ({oldest, newest}) and an `update_hint`; the
program's own version line is read as numbers and compared with them. Advice only: an older program still passes its
check when it works, and a version in the range, a newer one or one that can't be read says nothing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: The line shown for an older program: its name and version, the oldest tested version and how to update.
OLDER_PLAIN = "{name} {version} is older than the tested {oldest}: update it with {hint}."

_NUMBERS = re.compile(r"\d+(?:\.\d+)+")


def read_version(line: str | None) -> tuple[str, tuple[int, ...]] | None:
    """The first dotted version in the program's version line, as its text and its numbers; None when there is none."""
    found = _NUMBERS.search(line or "")
    if found is None:
        return None
    return found.group(0), tuple(int(part) for part in found.group(0).split("."))


def _padded(numbers: tuple[int, ...], size: int) -> tuple[int, ...]:
    return numbers + (0,) * (size - len(numbers))


def cleaned_tested(raw: Any) -> dict[str, str]:
    """The catalog's `tested_versions` as {"oldest": text, "newest": text}; empty unless both read as versions."""
    if not isinstance(raw, Mapping):
        return {}
    found = {key: str(raw.get(key) or "").strip() for key in ("oldest", "newest")}
    if any(read_version(v) is None or read_version(v)[0] != v for v in found.values()):  # type: ignore[index]
        return {}
    return found


def older_note(entry: Mapping[str, Any] | None, version_line: str | None) -> str | None:
    """The advice line when the program's version is older than the entry's oldest tested one, else None."""
    if not entry:
        return None
    tested = cleaned_tested(entry.get("tested_versions"))
    hint = str(entry.get("update_hint") or "").strip()
    seen = read_version(version_line)
    if not tested or not hint or seen is None:
        return None
    oldest = read_version(tested["oldest"])
    assert oldest is not None
    size = max(len(seen[1]), len(oldest[1]))
    if _padded(seen[1], size) >= _padded(oldest[1], size):
        return None
    return OLDER_PLAIN.format(
        name=str(entry.get("name") or "The program"), version=seen[0], oldest=tested["oldest"], hint=hint
    )
