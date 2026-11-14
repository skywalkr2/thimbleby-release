"""The guide check (design 6.25; story S-0108): the user guide is held to what the app has.

Ask answers "how do I" from the guide alone, so a screen, a Settings page or an add-on's person action the guide never
names is one Ask can't help with, and a guide that names one the app doesn't have sends the person looking for it.

- **Main screens:** the entries of the side menu (the names `web/src/shell/nav.ts` takes from the wording sheet) and the
  screens it doesn't list (Quality, Ask). The guide's list of screens has a `- Name:` line for each, and for nothing
  else.
- **Settings pages:** every `settings.section.*` name of the wording sheet is in the guide's Settings section, and the
  pages that section lists ("The pages are ...") are all real.
- **Person actions:** each action the add-ons of the fictional workspaces register is named in the guide or in that
  add-on's own help, which Ask reads with the guide.
- **Setting codes:** a dotted name in backticks in the guide is a setting that exists.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from engine.config import ConfigError, load_config
from engine.help import Section, guide_sections
from engine.selfcheck.scans import REPO, Finding

WEB = REPO / "web" / "src"
GUIDE = "engine/guide/guide.md"
#: Screens that are not entries of the side menu: the quality screen is opened from the menu under the person's
#: initials, and Ask is the question box.
EXTRA_SCREENS = ("Quality", "Ask")


def _found(message: str) -> Finding:
    return Finding("guide", GUIDE, 0, message)


def screen_names() -> set[str]:
    """Every screen's name as the side menu shows it, read from the navigation code and the wording sheet."""
    words = json.loads((WEB / "wording" / "en.json").read_text(encoding="utf-8"))
    keys = re.findall(r't\("(nav\.[a-z]+)"\)', (WEB / "shell" / "nav.ts").read_text(encoding="utf-8"))
    return {words[k] for k in keys} | set(EXTRA_SCREENS)


def settings_pages() -> set[str]:
    """The names of Settings' pages, from the wording sheet."""
    words = json.loads((WEB / "wording" / "en.json").read_text(encoding="utf-8"))
    return {v for k, v in words.items() if k.startswith("settings.section.")}


def _screens_in(sections: list[Section]) -> set[str]:
    listed = next((s for s in sections if s.title.startswith("The screens")), None)
    return set(re.findall(r"^- ([^:\n]+):", listed.text, re.M)) if listed is not None else set()


def _pages_in(sections: list[Section]) -> tuple[set[str], str]:
    """The pages the guide's Settings section lists, and its text."""
    found = next((s for s in sections if s.title == "Settings"), None)
    if found is None:
        return set(), ""
    text = " ".join(found.text.split())
    sentence = re.search(r"The pages are (.+?) \(only", text)
    names = sentence.group(1).split(", ") if sentence else []
    if names:
        # The last two are joined by "and"; an "and" inside a page's own name ("AI and spending") is never the last.
        names[-1:] = names[-1].rsplit(" and ", 1)
    return {n.strip() for n in names if n.strip()}, text


def check_sections(
    sections: list[Section],
    screens: set[str],
    pages: set[str],
    actions: dict[str, list[str]] | None = None,
    help_text: dict[str, str] | None = None,
    settings: set[str] | None = None,
) -> list[Finding]:
    """The findings for a guide held against the screens, the Settings pages, the add-ons' actions (by add-on, with each
    add-on's help text) and the setting keys that exist. Each part is checked only when it is given."""
    findings: list[Finding] = []
    listed = _screens_in(sections)
    for name in sorted(screens - listed):
        findings.append(_found(f'the screen "{name}" has no "- {name}:" line in the guide\'s list of screens'))
    for name in sorted(listed - screens):
        findings.append(_found(f'the guide lists a screen "{name}", which the app does not have'))
    named, settings_text = _pages_in(sections)
    for name in sorted(pages):
        if name not in settings_text:
            findings.append(_found(f'the Settings page "{name}" is not named in the guide\'s Settings section'))
    for name in sorted(named - pages):
        findings.append(_found(f'the guide\'s Settings section lists a page "{name}", which the app does not have'))
    everything = "\n".join(f"{s.title}\n{s.text}" for s in sections)
    for plugin, labels in sorted((actions or {}).items()):
        for label in labels:
            if label not in everything and label not in (help_text or {}).get(plugin, ""):
                findings.append(
                    _found(f'the action "{label}" of the add-on {plugin} is named in neither the guide nor its help')
                )
    if settings is not None:
        for code in sorted(set(re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", everything)) - settings):
            findings.append(_found(f"the guide names the setting `{code}`, which does not exist"))
    return findings


def _fictional_workspaces() -> list[Path]:
    from engine.selfcheck import FIXTURES

    return list(FIXTURES)


def add_on_actions(workspaces: list[Path] | None = None) -> tuple[dict[str, list[str]], dict[str, str]]:
    """The labels of the actions each add-on registers in the fictional workspaces, and each add-on's help text."""
    from engine.storage import Store, StoreError

    actions: dict[str, list[str]] = {}
    help_text: dict[str, str] = {}
    for root in workspaces or _fictional_workspaces():
        try:
            cfg = load_config(root / "config", env={})
        except ConfigError:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                store = Store(Path(tmp) / "guide.db", cfg=cfg)
            except StoreError:
                continue
            try:
                for name, registrar in sorted(store.plugins.registrars.items()):
                    if not store.plugins.active(name):
                        continue
                    labels = [a.label for a in registrar.actions.values() if a.label]
                    actions[name] = sorted({*actions.get(name, []), *labels})
                    help_text[name] = "\n".join(
                        s.text for s in store.plugins.help_sections() if s.title.startswith(f"{name}: ")
                    )
            finally:
                store.close()
    return actions, help_text


def check_guide() -> list[Finding]:
    """The guide held to the app: every main screen, Settings page and add-on action named, nothing named that isn't
    there."""
    from engine import settings as config_screens

    try:
        cfg = load_config(_fictional_workspaces()[0] / "config", env={})
        keys = {item.key for item in config_screens.describe(cfg)}
    except ConfigError as err:
        return [_found(f"the settings couldn't be read to check the guide: {err}")]
    actions, help_text = add_on_actions()
    return check_sections(guide_sections(), screen_names(), settings_pages(), actions, help_text, keys)
