"""The core's notice template (design 7.19): the subject and body of a notice that goes by mail to the person
themselves, from a data file whose version is the hash of its text.

The shipped file is `defaults/notice_template.yaml`; a workspace's own `templates/notice.yaml` replaces it, which
changes the version. A notice act is rendered only from this template, and the person's standing yes names the version
they saw. Everything here reads."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.yaml_load import load_yaml

#: The template's name, as a notice act and a standing yes carry it.
NAME = "notice"
SHIPPED = Path(__file__).parent / "defaults" / "notice_template.yaml"
FORMS = ("count", "titles", "test")
PARTS = ("subject", "body")


class TemplateError(ValueError):
    """The template file is missing a form or a part, or can't be read."""


def source(root: Path | None) -> Path:
    """The file the template is read from: the workspace's own when it has one, else the shipped one."""
    own = root / "templates" / "notice.yaml" if root is not None else None
    return own if own is not None and own.is_file() else SHIPPED


def version(root: Path | None) -> str:
    """The version of the template as it stands: a hash of the text of the file in use."""
    return hashlib.sha256(source(root).read_text(encoding="utf-8").encode()).hexdigest()[:16]


def load(root: Path | None) -> dict[str, Any]:
    """The template as data, checked to hold every form with both parts."""
    found = load_yaml(source(root).read_text(encoding="utf-8")) or {}
    forms = found.get("forms") or {}
    for form in FORMS:
        for part in PARTS:
            if not str((forms.get(form) or {}).get(part, "")).strip():
                raise TemplateError(f"the notice template has no {part} in its {form} form")
    return found


class _Placeholders(dict):
    """The values a template's placeholders take; a placeholder it doesn't know stays as written."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(frozen=True)
class Rendered:
    subject: str
    body: str


def render(root: Path | None, *, form: str, message: str, app: str, titles: list[str] | None = None) -> Rendered:
    """The notice in `form` ("count", "titles" or "test"). `message` is the count line; `titles` fill the titles form,
    one to a line, and are never put in any other."""
    if form not in FORMS:
        raise TemplateError(f"there is no {form} form of the notice")
    chosen = load(root)["forms"][form]
    values = _Placeholders(
        message=" ".join(message.split()),
        app=app,
        titles="\n".join(f"- {' '.join(t.split())}" for t in (titles or [])) if form == "titles" else "",
    )
    return Rendered(**{part: str(chosen[part]).format_map(values) for part in PARTS})
