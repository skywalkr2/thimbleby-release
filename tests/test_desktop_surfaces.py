"""The pieces the installed app's window and item are made of: the mark's pictures from the brand file, the starting
page and what each way of not starting says, and the sign-in choice."""

import errno

import pytest

from engine import brandmark, login_item, startpage
from engine.handover import Refused
from engine.sides import words_sheet

WORDS = {k: str(v) for k, v in words_sheet().items() if k.startswith("desktop.")}


def test_the_menu_bar_picture_is_one_colour_with_the_bow_cut_out_and_the_tray_picture_is_the_mark_in_colour():
    svg = brandmark.mark_svg()
    template = brandmark.render(svg, 44, template=True)
    assert {pixel[:3] for pixel in template.getdata() if pixel[3]} == {(0, 0, 0)}
    assert template.getpixel((22, 2))[3] == 0  # nothing around the shape
    assert template.getpixel((22, 24))[3] == 255  # the thimble
    colour = brandmark.render(svg, 64, template=False)
    assert colour.getpixel((32, 14))[:3] == (255, 242, 216)  # the thimble's cream
    assert colour.getpixel((4, 32))[3] == 255 and colour.getpixel((4, 32))[:3] != (255, 242, 216)  # the ground


def test_the_picture_follows_the_brand_file_not_a_shape_in_code():
    changed = brandmark.render(brandmark.mark_svg().replace("#FFF2D8", "#00FF00"), 64, template=False)
    assert changed.getpixel((32, 14))[:3] == (0, 255, 0)


def test_a_path_command_the_reader_does_not_know_is_refused():
    with pytest.raises(ValueError):
        brandmark.flatten("M0 0 A5 5 0 0 1 10 10")


@pytest.mark.parametrize(
    "error,kind",
    [
        (OSError(errno.ENOSPC, "full"), "disk_full"),
        (OSError(errno.EADDRINUSE, "in use"), "held"),
        (Refused("held elsewhere"), "elsewhere"),
        (RuntimeError("anything else"), "other"),
    ],
)
def test_each_way_of_not_starting_has_its_own_message(error, kind):
    assert startpage.classify(error) == kind
    title, text = startpage.message(WORDS, kind)
    assert title and text and "Traceback" not in text


def test_a_cause_further_down_decides_the_message():
    try:
        try:
            raise OSError(errno.ENOSPC, "full")
        except OSError as inner:
            raise RuntimeError("could not start") from inner
    except RuntimeError as outer:
        assert startpage.classify(outer) == "disk_full"


def test_the_starting_page_has_the_mark_the_heading_three_steps_and_both_actions():
    page = startpage.page(WORDS, "0.1.0")
    assert "Starting Thimbleby" in page and "Version 0.1.0" in page and page.count("<li>") == 3
    assert "Your workspace is ready" in page and "Opening the screens" in page
    assert "<svg" in page and "Try again" in page and "Copy details" in page
    assert "You're offline" not in page and "{{" not in page
    assert page.count('id="d-ground"') == 1 and page.count('id="n-ground"') == 1  # the two marks share no ids


def test_every_wording_key_the_page_and_the_menu_use_is_in_the_sheet():
    for key in startpage.STEPS:
        assert WORDS[key]
    for kind in ("disk_full", "elsewhere", "held", "other"):
        assert all(startpage.message(WORDS, kind))


def test_signing_in_to_the_computer_is_set_up_only_when_chosen_and_removed_exactly(tmp_path):
    agent = login_item.mac_agent_path(tmp_path)
    assert not login_item.is_enabled("Darwin", tmp_path)
    assert login_item.toggle("Darwin", tmp_path) is True and agent.is_file()
    assert b"--at-login" in agent.read_bytes() and login_item.is_enabled("Darwin", tmp_path)
    assert login_item.toggle("Darwin", tmp_path) is False and not agent.exists()
    assert login_item.is_enabled("Linux") is False
