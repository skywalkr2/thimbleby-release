"""The starting window's three views are drawn by the server side with no script: what a person sees while the app
updates itself, and the failed-update screen with its reason and its three choices (design 11.7)."""

import pytest

from engine import brandmark, startpage
from engine.sides import words_sheet

WORDS = {k: str(v) for k, v in words_sheet().items() if k.startswith("desktop.")}


def test_the_update_view_lists_the_five_steps_in_order_with_the_running_version():
    html = startpage.page(WORDS, "0.1.0", view="update")
    assert 'data-view="update"' in html and "Updating Thimbleby" in html and "Version 0.1.0" in html
    order = [html.index(WORDS[f"desktop.update.step.{n}"]) for n in ("copy", "download", "check", "install", "open")]
    assert order == sorted(order)


def test_the_failed_view_names_the_version_still_running_the_reason_and_three_choices():
    html = startpage.page(WORDS, "0.1.0", view="failed", reason="The download stopped <b>early</b>.")
    assert 'data-view="failed"' in html and "Still on 0.1.0" in html
    assert "The update didn&#x27;t finish, so nothing changed." in html or "didn't finish" in html
    assert "The download stopped &lt;b&gt;early&lt;/b&gt;." in html  # never raw markup
    for button in ("failed-copy", "failed-open", "failed-again"):
        assert f'id="{button}"' in html


def test_the_view_for_work_that_is_not_back_yet_shows_try_again_and_quit_and_hides_the_way_on_to_the_app():
    """H5-28, H2: the screen while the copy of the work can't be put back after a rolled-back update."""
    html = startpage.page(WORDS, "0.1.0", view="unrestored", reason=WORDS["desktop.update.unrestored.text"])
    assert 'data-view="unrestored"' in html and "Still on 0.1.0" in html
    assert html.count(">Quit</button>") == 1 and 'id="failed-quit"' in html and 'api().choose("quit")' in html
    assert 'body[data-view="unrestored"] #failed-open { display:none; }' in html
    assert 'body[data-view="unrestored"] #failed-quit { display:inline-block; }' in html
    assert "#failed-quit { display:none; }" in html  # and Quit is not on the failed-update screen
    for button in ("failed-copy", "failed-again"):
        assert f'id="{button}"' in html


def test_an_unknown_view_is_refused():
    with pytest.raises(ValueError):
        startpage.page(WORDS, view="other")


def test_the_dot_sits_in_the_top_right_corner_and_leaves_the_rest_of_the_mark_alone():
    plain = brandmark.render(brandmark.mark_svg(), 64, template=False)
    dotted = brandmark.with_dot(plain, template=False)
    assert dotted.size == plain.size and dotted.getpixel((56, 8)) != plain.getpixel((56, 8))
    assert dotted.getpixel((8, 56)) == plain.getpixel((8, 56))
    flat = brandmark.render(brandmark.mark_svg(), 44, template=True)
    marked = brandmark.with_dot(flat, template=True)
    assert marked.getpixel((38, 6))[3] > 200  # a solid dot in the template
