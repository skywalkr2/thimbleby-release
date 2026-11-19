"""The app's own window and its menu-bar item (engine/appwindow.py), run with no display: a fake window loop owns the
test's thread, and every call the shell makes to the window or the item records which thread it came from."""

import contextlib
import queue
import threading
from pathlib import Path

import pytest

from engine import appwindow
from engine.appwindow import AppShell, MenuLine, PageApi, menu_lines
from engine.appwindow_backends import closing_handler
from engine.sides import words_sheet

WORDS = {k: str(v) for k, v in words_sheet().items() if k.startswith("desktop.")}


class FakeWindow:
    """A window loop on the thread that calls run; posted calls run there."""

    def __init__(self):
        self.calls = []
        self.queue = queue.Queue()
        self.closing = None
        self.done = threading.Event()

    def _note(self, name, *args):
        self.calls.append((name, args, threading.current_thread() is threading.main_thread()))

    def post(self, call):
        self.queue.put(call)

    def create(self, title, html, api, on_closing, on_quit):
        self._note("create", title)
        self.html, self.closing, self.quit_requested = html, on_closing, on_quit

    def run(self, worker):
        threading.Thread(target=worker).start()
        while not self.done.is_set():
            with contextlib.suppress(queue.Empty):
                self.queue.get(timeout=0.05)()

    def show(self):
        self._note("show")

    def hide(self):
        self._note("hide")

    def load_url(self, url):
        self._note("load_url", url)

    def load_html(self, html):
        self._note("load_html")

    def script(self, code):
        self._note("script", code)

    def page_state(self):
        return {"address": "http://127.0.0.1:1/", "drawn": True}

    def destroy(self):
        self._note("destroy")
        self.done.set()


class FakeTray:
    def __init__(self, window):
        self.window = window
        self.started = threading.Event()

    def start(self, lines, act, title):
        self.window._note("tray.start")
        self.lines, self.act = lines, act
        self.started.set()

    def refresh(self):
        self.window._note("tray.refresh")

    def dock(self, shown):
        self.window._note("tray.dock", shown)

    def stop(self):
        self.window._note("tray.stop")


def make(system="Darwin", **options):
    window = FakeWindow()
    tray = FakeTray(window)
    return AppShell(window, tray, dict(WORDS), system=system, **options), window, tray


def test_no_window_or_menu_call_leaves_the_main_thread():
    """The Mac stops an app that touches a status item from another thread, so every call from the server's threads,
    the menu's actions and the restart loop reaches the toolkit on the loop's own thread."""
    shell, window, _ = make()

    def work():
        shell.show_starting()
        shell.step(1)
        shell.show_app("http://127.0.0.1:1/")
        shell.set_state("restarting")
        shell.set_state("live")
        shell.bring_forward("#setup")
        shell.quit()
        return 0

    assert shell.run(work) == 0
    off = [name for name, _, on_main in window.calls if not on_main]
    assert off == [] and len(window.calls) > 8


def test_menu_lines_state_choices_and_login_wording_per_system():
    mac = menu_lines(WORDS, "Darwin", "live", restart_on=False, login_on=True)
    assert [line.key for line in mac] == ["state", "open", "update", "restart", "login", "help", "quit"]
    assert [line.text for line in mac] == [
        "All good",
        "Open Thimbleby",
        "Check for a new version",
        "Restart",
        "Open at login",
        "Help",
        "Quit",
    ]
    assert not mac[0].enabled and not mac[3].enabled and mac[4].checked is True and mac[1].default
    windows = menu_lines(WORDS, "Windows", "restart", restart_on=True, login_on=False)
    assert windows[0].text == "Restart to finish" and windows[3].enabled
    assert windows[4] == MenuLine("login", "Start when I sign in", checked=False, separator_before=True)
    assert menu_lines(WORDS, "Darwin", "starting", restart_on=False, login_on=False)[0].text == "Starting"


def test_the_menu_reads_the_current_state_each_time_it_is_asked():
    shell, _, _ = make()
    shell.restart_enabled = lambda: False
    assert shell.lines()[3].enabled is False
    shell.restart_enabled = lambda: True
    shell.set_state("restart")
    assert shell.lines()[0].text == "Restart to finish" and shell.lines()[3].enabled
    with pytest.raises(ValueError):
        shell.set_state("unknown")


def test_closing_the_window_hides_it_and_the_app_keeps_running():
    shell, window, _ = make()

    def work():
        shell.show_app("http://127.0.0.1:1/")
        assert shell.window.closing() is False
        shell.bring_forward()
        return 0

    shell.run(work)
    names = [name for name, _, _ in window.calls]
    assert "hide" in names and names[-1] == "destroy"
    assert shell._quitting  # only the end of the run lets the window close


def test_every_quit_path_ends_the_app_through_quit_and_closing_the_window_does_not():
    """The menu-bar item's Quit, the control listener's quit and the system's own Quit (application menu, its
    shortcut, the Dock) each set the quit event; the window's close only hides."""
    paths = {
        "menu item": lambda shell, tray: tray.act("quit"),
        "control listener": lambda shell, tray: shell.quit_from_menu(),
        "system quit": lambda shell, tray: shell.window.quit_requested(),
    }
    for name, path in paths.items():
        shell, window, tray = make()
        seen = {}

        def work(shell=shell, tray=tray, path=path, seen=seen):
            assert tray.started.wait(5)
            shell.show_app("http://127.0.0.1:1/")
            assert not shell.quit_event.is_set()
            path(shell, tray)
            seen["quit"] = shell.quit_event.is_set()
            return 0

        shell.run(work)
        assert seen == {"quit": True}, name
    shell, window, tray = make()

    def close_only():
        shell.show_app("http://127.0.0.1:1/")
        assert shell.window.closing() is False
        assert not shell.quit_event.is_set()
        return 0

    shell.run(close_only)


def test_the_window_librarys_quit_is_told_from_a_close_by_the_call_that_asked():
    quits, closes = [], []
    handle = closing_handler(lambda: closes.append(1) or False, lambda: quits.append(1))
    assert handle() is False and closes == [1] and quits == []

    def applicationShouldTerminate_():  # noqa: N802 (the window library's own name for the Mac's Quit)
        return handle()

    assert applicationShouldTerminate_() is False and quits == [1] and closes == [1]


def test_the_dock_icon_shows_with_the_window_and_not_without_it():
    shell, window, _ = make()

    def work():
        shell.show_starting()
        shell.quit()
        return 0

    shell.run(work)
    docks = [args[0] for name, args, _ in window.calls if name == "tray.dock"]
    assert docks[:1] == [True] and docks[-1] is False


def test_started_at_login_it_shows_nothing_until_the_person_opens_it():
    shell, window, _ = make(quiet=True)

    def work():
        shell.show_starting()
        shell.show_app("http://127.0.0.1:1/")
        assert "show" not in [name for name, _, _ in window.calls]
        shell.bring_forward()
        return 0

    shell.run(work)
    assert [name for name, _, _ in window.calls].count("show") == 1


def test_a_second_open_with_a_place_moves_the_app_there():
    shell, window, _ = make()

    def work():
        shell.show_app("http://127.0.0.1:1/")
        shell.bring_forward("#setup")
        return 0

    shell.run(work)
    assert ("script", ("location.hash = '#setup'",), True) in window.calls


def test_a_link_to_another_address_goes_to_the_browser_never_the_window():
    opened = []
    shell, window, _ = make(external=opened.append)
    api = PageApi(shell)
    assert api.open_external("http://192.0.2.1/page") and api.open_external("mailto:a@example.com")
    assert not api.open_external("file:///etc/passwd") and not api.open_external("javascript:alert(1)")
    assert not api.open_external(None)
    assert opened == ["http://192.0.2.1/page", "mailto:a@example.com"]
    assert "load_url" not in [name for name, _, _ in window.calls]


def test_a_failure_becomes_one_message_with_try_again_and_copy_details():
    copied = []
    shell, window, _ = make(copy=copied.append)
    outcome = []

    def work():
        threading.Timer(0.1, lambda: (PageApi(shell).copy_details(), PageApi(shell).retry())).start()
        outcome.append(shell.problem("disk_full", "Traceback: the disk"))
        return 0

    shell.run(work)
    assert outcome == [True] and copied == ["Traceback: the disk"]
    scripts = [args[0] for name, args, _ in window.calls if name == "script"]
    assert any("Your disk is full" in code and "50 MB" in code for code in scripts)
    assert not any("Traceback" in code for code in scripts)  # raw text is never on screen


def test_quitting_while_a_message_waits_ends_it_without_trying_again():
    shell, _, _ = make()
    outcome = []

    def work():
        threading.Timer(0.1, shell.quit).start()
        outcome.append(shell.problem("other", "details"))
        return 1

    assert shell.run(work) == 1 and outcome == [False]


def test_the_menus_quit_ends_the_loop_and_its_other_choices_run_off_the_menu_thread():
    shell, _, tray = make()
    ran = []

    def work():
        assert tray.started.wait(5)
        shell.on("help", lambda: ran.append(threading.current_thread() is threading.main_thread()))
        tray.act("help")
        threading.Event().wait(0.2)
        tray.act("quit")
        assert shell.quit_event.is_set()
        return 0

    shell.run(work)
    assert ran == [False]


def test_copy_text_uses_the_systems_clipboard_program(monkeypatch):
    seen = []
    monkeypatch.setattr(appwindow.subprocess, "run", lambda command, **kw: seen.append((command, kw["input"])))
    appwindow.copy_text("hi", "darwin")
    appwindow.copy_text("hi", "win32")
    assert seen[0] == (["pbcopy"], b"hi") and seen[1][0] == ["clip"]


def test_the_tray_menu_builds_with_the_tray_library_and_each_line_runs_its_own_action():
    """pystray counts an action's arguments, defaults included; lambdas with bound defaults stopped the Windows tray."""
    import importlib.util

    found = importlib.util.find_spec("pystray")
    if found is None or not found.submodule_search_locations:
        pytest.skip("pystray is in the desktop extra")
    # The library's menu classes alone: importing the package picks a desktop backend, which a test machine has none of.
    spec = importlib.util.spec_from_file_location(
        "pystray_menu_classes", Path(found.submodule_search_locations[0]) / "_base.py"
    )
    pystray = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pystray)
    from engine.appwindow import MenuLine
    from engine.appwindow_backends import tray_items

    class Lib:  # the two names tray_items uses, from the real library
        Menu = pystray.Menu
        MenuItem = pystray.MenuItem

    ran = []
    lines = [
        MenuLine(key="open", text="Open Thimbleby", default=True),
        MenuLine(key="login", text="Start when I sign in", checked=True, separator_before=True),
    ]
    items = [i for i in tray_items(Lib, lines, ran.append) if i is not pystray.Menu.SEPARATOR]
    assert [i.text for i in items] == ["Open Thimbleby", "Start when I sign in"]
    for item in items:
        item(None)  # pystray calls an item with the icon
    assert ran == ["open", "login"] and items[1].checked is True


@pytest.mark.parametrize(
    "screen,size",
    [((1024, 768), (921, 691)), ((1440, 900), (1280, 810)), ((2560, 1440), (1280, 860))],
)
def test_the_window_fits_the_screen_it_opens_on(screen, size):
    """On a 1024 by 768 screen the window was wider than the screen and its right side was out of reach."""
    fit = appwindow.fit_window(screen)
    assert (fit.width, fit.height) == size
    assert fit.width <= screen[0] * 0.9 and fit.height <= screen[1] * 0.9
    assert fit.min_width <= fit.width and fit.min_height <= fit.height
    assert fit.x == (screen[0] - fit.width) // 2 and fit.y == (screen[1] - fit.height) // 2


def test_the_window_state_names_the_menu_state_and_the_page():
    shell, _, _ = make()
    assert shell.window_state() == {
        "state": "starting",
        "shown": False,
        "address": "http://127.0.0.1:1/",
        "drawn": True,
    }


def test_a_window_call_never_runs_on_the_loop_thread_that_made_it():
    """The Mac's web view waits for a reply only the loop's thread can give, so a script or page load made on that
    thread never returned and the window stayed blank. The real window makes each such call on its own worker."""
    from engine.appwindow_backends import WebviewWindow

    seen = {}
    done = threading.Event()

    class Page:
        def load_url(self, url):
            seen["load_url"] = threading.current_thread()

        def evaluate_js(self, code):
            seen["script"] = threading.current_thread()
            done.set()

    window = WebviewWindow()
    window.window = Page()
    window.load_url("http://127.0.0.1:1/")
    window.script("1")
    assert done.wait(10)
    assert set(seen) == {"load_url", "script"}
    assert all(thread is not threading.current_thread() for thread in seen.values())


def test_the_page_saying_it_has_drawn_counts_as_drawn_even_when_a_script_cannot_be_read(monkeypatch):
    """On the Mac a script run in the window from outside came back with nothing although the page showed Welcome."""
    shell, window, _ = make()
    monkeypatch.setattr(window, "page_state", lambda: {"address": "http://127.0.0.1:1/#setup", "drawn": False})
    assert shell.window_state()["drawn"] is False
    shell.api.page_drawn()
    assert shell.window_state()["drawn"] is True
    shell.show_app("http://127.0.0.1:1/")  # a new page has to say so again
    assert shell.window_state()["drawn"] is False


def test_the_question_about_earlier_work_shows_the_path_and_what_it_holds_and_returns_the_answer():
    shell, window, _ = make()
    outcome = []

    def work():
        threading.Timer(0.1, lambda: PageApi(shell).choose("use")).start()
        outcome.append(shell.ask_earlier("~/Work", 2, 48, 3, "Nov 2"))
        return 0

    shell.run(work)
    assert outcome == [True]
    scripts = [args[0] for name, args, _ in window.calls if name == "script"]
    asked = next(code for code in scripts if code.startswith("choice("))
    for text in ("Use the work you already have?", "~/Work", "Sides 2", "To-dos 48", "People 3", "Nov 2"):
        assert text in asked
    assert "ockpit" not in asked  # the earlier name is never in what the window says


def test_start_fresh_answers_false_and_quitting_while_it_waits_answers_none():
    shell, _, _ = make()
    outcome = []

    def work():
        threading.Timer(0.1, lambda: PageApi(shell).choose("fresh")).start()
        outcome.append(shell.ask_earlier("~/Work", 1, 0, 0, "Nov 2"))
        PageApi(shell).choose("anything else")  # not an answer: ignored
        threading.Timer(0.1, shell.quit).start()
        outcome.append(shell.ask_earlier("~/Work", 1, 0, 0, "Nov 2"))
        return 0

    shell.run(work)
    assert outcome == [False, None]


class StuckWindow(FakeWindow):
    """A window loop that doesn't return when its window is destroyed, as a Mac's does when no event follows a Quit."""

    def destroy(self):
        self._note("destroy")


def test_a_quit_whose_window_loop_never_returns_still_ends_the_app_once_the_work_is_done():
    window = StuckWindow()
    shell = AppShell(window, FakeTray(window), dict(WORDS), system="Darwin")
    shell.end_grace_seconds = 0.05
    exits = []

    def exit_now(code):
        exits.append(code)
        window.done.set()  # the process ending is what ends a stuck loop

    shell._exit = exit_now

    def work():
        shell.show_app("http://127.0.0.1:1/")
        shell.quit()
        return 0

    assert shell.run(work) == 0
    assert exits == [0]


def test_a_quit_whose_window_loop_returns_never_ends_the_process():
    shell, window, _ = make()
    shell.end_grace_seconds = 0.05
    exits = []
    shell._exit = exits.append

    def work():
        shell.show_app("http://127.0.0.1:1/")
        shell.quit()
        return 0

    assert shell.run(work) == 0
    for guard in [t for t in threading.enumerate() if t.name == "end-guard"]:
        guard.join(5)
    assert exits == []


def test_the_menu_offers_the_update_only_while_a_newer_version_is_on_offer():
    plain = menu_lines(WORDS, "Darwin", "live", restart_on=False, login_on=False)
    assert "install" not in [line.key for line in plain]
    offered = menu_lines(WORDS, "Darwin", "live", restart_on=False, login_on=False, update="0.2.0")
    assert [line.key for line in offered][:4] == ["state", "open", "install", "update"]
    assert offered[2].text == "Update to 0.2.0 and restart" and offered[2].enabled


def test_the_dot_and_the_update_line_follow_the_offer_and_nothing_is_redrawn_when_it_is_unchanged():
    shell, window, tray = make()
    tray.badge = lambda on: window._note("tray.badge", on)

    def work():
        shell.set_update("0.2.0")
        shell.set_update("0.2.0")
        shell.set_update(None)
        shell.quit()
        return 0

    shell.run(work)
    assert [args for name, args, _ in window.calls if name == "tray.badge"] == [(True,), (False,)]
    assert shell.update_offered is None


def test_the_update_window_shows_its_steps_and_the_failed_screen_waits_for_the_persons_choice():
    shell, window, _ = make(version="0.1.0")
    result = []

    def work():
        shell.show_update("0.1.0")
        shell.update_step("download", 0.5, "12/40")
        threading.Timer(0.1, lambda: PageApi(shell).choose("again")).start()
        result.append(shell.update_failed("0.1.0", "It stopped.", "details"))
        threading.Timer(0.1, lambda: PageApi(shell).choose("open")).start()
        result.append(shell.update_failed("0.1.0", "It stopped.", "details"))
        shell.quit()
        return 0

    shell.run(work)
    assert result == ["again", "open"] and shell.details == "details"
    script = [args[0] for name, args, _ in window.calls if name == "script"]
    assert script == ['update_tick(1, 0.5, "12 of 40 MB")']
    assert [name for name, _, _ in window.calls].count("load_html") == 3  # the update view, then the screen twice


def test_the_screen_for_work_that_is_not_back_yet_offers_try_again_and_quit_and_no_way_on_to_the_app():
    """H5-28, H2: while the copy of the work can't be put back, the only answers are trying again and quitting."""
    shell, window, _ = make(version="0.1.0")
    result = []

    def work():
        threading.Timer(0.1, lambda: PageApi(shell).choose("again")).start()
        result.append(shell.restore_failed("0.1.0", "It couldn't be put back.", "details"))
        threading.Timer(0.1, lambda: PageApi(shell).choose("open")).start()  # not offered there: never a way on
        result.append(shell.restore_failed("0.1.0", "It couldn't be put back.", "details"))
        threading.Timer(0.1, lambda: PageApi(shell).choose("quit")).start()
        result.append(shell.restore_failed("0.1.0", "It couldn't be put back.", "details"))
        shell.quit()
        return 0

    shell.run(work)
    assert result == ["again", "", ""] and shell.details == "details"
    assert [name for name, _, _ in window.calls].count("load_html") == 3  # the screen, each time it was asked


def test_a_choice_the_page_does_not_offer_is_ignored():
    shell, _, _ = make()
    PageApi(shell).choose("delete everything")
    assert not shell.answer_event.is_set()
