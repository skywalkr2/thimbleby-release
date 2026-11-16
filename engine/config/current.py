"""The settings as the files hold them now, read again only when something they depend on changed.

Reading them parses every settings file and finds the installed add-ons, which is most of what a screen's answer
costs on a slow computer, and one answer asks several times. A read is kept while the files' contents, the
environment variables that override a setting and the workspace's own add-on manifests are as they were, and for a
short time at most, so an add-on installed meanwhile is found. A settings problem is never kept."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from engine.config.loader import Config, load_config
from engine.legacy_names import ENV_PREFIX, OLD_ENV_PREFIX

#: How long a read is kept at most when nothing it depends on changed.
KEEP_SECONDS = 5.0

_lock = threading.Lock()
_kept: dict[str, tuple[str, float, Config]] = {}


def _signature(config_dir: Path, env: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(config_dir.rglob("*.yaml")):
        digest.update(str(path.relative_to(config_dir)).encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"-")
    for key in sorted(k for k in env if k.startswith((ENV_PREFIX, OLD_ENV_PREFIX))):
        digest.update(f"{key}={env[key]}".encode())
    for path in sorted((config_dir.parent / "plugins").glob("*/plugin.yaml")):
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(f"{path.parent.name}:{stat.st_mtime_ns}:{stat.st_size}".encode())
    return digest.hexdigest()


def load_config_now(config_dir: Path, *, env: Mapping[str, str]) -> Config:
    """The effective settings, as `load_config` builds them, without building them again for an unchanged folder."""
    key = str(config_dir)
    signature = _signature(config_dir, env)
    now = time.monotonic()
    with _lock:
        held = _kept.get(key)
        if held and held[0] == signature and now - held[1] < KEEP_SECONDS:
            return held[2]
    cfg = load_config(config_dir, env=dict(env))
    with _lock:
        _kept[key] = (signature, now, cfg)
    return cfg
