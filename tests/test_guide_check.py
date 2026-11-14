"""The guide is held to the app (design 6.25; S-0108): every main screen, Settings page and add-on action is named in
it, and nothing is named that isn't there. Ask answers "how do I" from the guide alone, so a gap is a question it can't
help with."""

from __future__ import annotations

from engine.help import Section, guide_sections
from engine.selfcheck.guide import add_on_actions, check_guide, check_sections, screen_names, settings_pages

SCREENS = {"Today", "Schedule"}
PAGES = {"You", "AI and spending", "Advanced"}


def guide(screens=("Today", "Schedule"), pages="You, AI and spending and Advanced", extra=""):
    listed = "\n".join(f"- {s}: what it is." for s in screens)
    return [
        Section("The screens: the side menu", listed),
        Section(
            "Settings", f"Settings has pages. The pages are {pages} (only those that apply to you are listed). {extra}"
        ),
    ]


def messages(findings):
    return [f.message for f in findings]


def test_the_guide_in_the_repository_names_every_screen_page_and_action_and_nothing_that_isnt_there():
    assert check_guide() == []
    # What it is held to is read from the app: the side menu, the wording sheet's pages and the add-ons' actions.
    assert {"Today", "Schedule", "Settings", "Quality", "Ask"} <= screen_names()
    assert {"Connections", "Add-ons", "Advanced"} <= settings_pages()
    actions, _ = add_on_actions()
    assert any(labels for labels in actions.values())


def test_a_screen_with_no_line_in_the_guide_fails_and_so_does_a_screen_the_app_does_not_have():
    found = messages(check_sections(guide(screens=("Today",)), SCREENS, PAGES))
    assert found == ['the screen "Schedule" has no "- Schedule:" line in the guide\'s list of screens']
    found = messages(check_sections(guide(screens=("Today", "Schedule", "Gadgets")), SCREENS, PAGES))
    assert found == ['the guide lists a screen "Gadgets", which the app does not have']


def test_a_settings_page_the_guide_does_not_name_fails_and_so_does_one_it_lists_that_is_not_there():
    found = messages(check_sections(guide(pages="You and Advanced"), SCREENS, PAGES))
    assert found == ['the Settings page "AI and spending" is not named in the guide\'s Settings section']
    found = messages(check_sections(guide(pages="You, AI and spending, Moods and Advanced"), SCREENS, PAGES))
    assert found == ['the guide\'s Settings section lists a page "Moods", which the app does not have']


def test_an_add_on_action_named_in_neither_the_guide_nor_its_help_fails():
    sections = guide(extra="Press Make a note from this file.")
    actions = {"example": ["Make a note from this file", "Build the thing"]}
    found = messages(check_sections(sections, SCREENS, PAGES, actions, {"example": ""}))
    assert found == ['the action "Build the thing" of the add-on example is named in neither the guide nor its help']
    assert check_sections(sections, SCREENS, PAGES, actions, {"example": "Build the thing makes it."}) == []


def test_a_setting_the_guide_names_in_backticks_must_exist():
    sections = guide(extra="Change `ask.nothing` or `storage.backups.keep`.")
    found = messages(check_sections(sections, SCREENS, PAGES, settings={"storage.backups.keep"}))
    assert found == ["the guide names the setting `ask.nothing`, which does not exist"]


def test_the_guide_has_a_section_for_every_screen_it_lists():
    assert guide_sections()  # the repository's own guide loads and has sections
