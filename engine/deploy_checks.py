"""Deploy checks (design 11.5): conditions a hosted install must meet before it serves. Each check returns the problems
it found, in words for the screen; an empty list means it passed. Local mode runs none of them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.problems import _config_values

SECRETS_FOLDER = "secrets"


def secrets_dir(ws: Any, cfg: Any) -> Path:
    """The folder a hosted install's secret files must be in: the configured one, else the secrets folder inside the
    workspace's private folder."""
    chosen = cfg.server.secrets_dir
    return Path(chosen).expanduser() if chosen else ws.private_dir / SECRETS_FOLDER


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except (ValueError, OSError, RuntimeError):
        return False
    return True


def file_secret_problems(ws: Any, cfg: Any) -> list[str]:
    """Every setting that reads a secret from a file outside the secrets folder. A path that leaves the folder by `..`
    or through a link counts as outside."""
    folder = secrets_dir(ws, cfg)
    problems: list[str] = []
    for name, model in getattr(cfg, "files", {}).items():
        try:
            data = model.model_dump(mode="json")
        except Exception:  # a file's model that can't be shown holds no reference this can name
            continue
        for value in _config_values(data):
            scheme, _, where = value.partition(":")
            if scheme != "file" or not where:
                continue
            if not _inside(Path(where).expanduser(), folder):
                problems.append(
                    f"A setting in {name} reads a secret from a file that isn't in the secrets folder ({folder}). "
                    "Move the file there and point the setting at it."
                )
    return problems


def run(ws: Any, cfg: Any) -> list[str]:
    """Every deploy check; the problems of all of them, in the order the design lists them."""
    return file_secret_problems(ws, cfg)
