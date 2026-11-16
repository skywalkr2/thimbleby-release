"""The public tracking page of a parcel's carrier (design 7.7, "Deliveries").

The carriers the app knows are a shipped list (`engine/defaults/delivery_carriers.yaml`): each has the words of its
name as a mail writes it and its public tracking page, with the tracking number's place marked. A workspace adds
carriers of its own (`ui.today.delivery_carriers_extra`, an entry with a shipped id replacing it). A delivery whose
carrier is in the list gets a link to that page; the tracking number is only ever inside that address, never shown as
text. Nothing here names a carrier: the names are the file's."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from engine.yaml_load import load_yaml

CARRIERS_FILE = Path(__file__).parent / "defaults" / "delivery_carriers.yaml"
NUMBER = "{number}"
_WORDS = re.compile(r"[^\W_]+")


def shipped() -> list[Any]:
    """The app's own list of carriers."""
    from engine.config.schema import CarrierPage

    data = load_yaml(CARRIERS_FILE.read_text(encoding="utf-8")) or {}
    return [CarrierPage.model_validate(entry) for entry in data.get("carriers", [])]


def known(cfg: Any) -> list[Any]:
    """Every carrier with a tracking page: the shipped ones (one the workspace gave an entry for is replaced in place),
    then the workspace's own."""
    own = {c.id: c for c in cfg.ui.today.delivery_carriers_extra}
    return [*(own.pop(c.id, c) for c in shipped()), *own.values()]


def _words(text: str) -> set[str]:
    return {w.casefold() for w in _WORDS.findall(text)}


def page_for(cfg: Any, carrier: str | None, tracking: str | None) -> str | None:
    """The carrier's tracking page for this parcel, or None when the carrier is unknown or there is no number. The
    number is trimmed and made safe for a web address."""
    number = (tracking or "").strip()
    if not carrier or not number:
        return None
    spoken = _words(carrier)
    for entry in known(cfg):
        wanted = {w.casefold() for w in entry.words if w.strip()}
        if entry.page and wanted and wanted <= spoken:
            return "https://" + entry.page.replace(NUMBER, quote(number, safe=""))
    return None
