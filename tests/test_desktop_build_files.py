"""The installers' build files (TB2): the version rules, the folders a frozen app carries, the entry that starts the
app, both specs, the installer's policy, the pinned tools and the one release workflow. These are structural checks;
the frozen start itself is proved by `deploy/desktop/build_support/smoke_frozen.py`, which the workflow runs on every
build."""

import importlib.metadata
import json
import re
import runpy
import sys
import types
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "deploy" / "desktop" / "build_support"
sys.path.insert(0, str(BUILD))

import release_tools  # noqa: E402
from build_model import BUNDLED_FOLDERS, bundled_data, release_versions  # noqa: E402


@pytest.mark.parametrize(
    "tag,display,numeric",
    [
        ("v1.2.3", "1.2.3", "1.2.3"),
        ("v0.1.0rc1", "0.1.0rc1", "0.1.0"),
        ("v1.2.3a2", "1.2.3a2", "1.2.3"),
        ("v1.2.3.post1", "1.2.3.post1", "1.2.3"),
    ],
)
def test_release_versions(tag, display, numeric):
    assert release_versions(tag) == (display, numeric)


@pytest.mark.parametrize(
    "tag", ["1.2.3", "v1.2", "v1.2.3.4", "v1.2.3+local", "v1!1.2.3", "v1.2.3\nX=bad", "v65536.0.0", "vnext", ""]
)
def test_invalid_tags(tag):
    with pytest.raises(ValueError):
        release_versions(tag)


@pytest.mark.parametrize("root", [PurePosixPath("/fictional/repo"), PureWindowsPath(r"C:\fictional\repo")])
def test_data_folder_layout(root):
    result = bundled_data(root)
    assert tuple(destination for _, destination in result) == BUNDLED_FOLDERS
    assert all(source == str(root / destination) for source, destination in result)


def test_every_bundled_folder_is_in_the_repository_and_nothing_made_up_is_bundled():
    for folder in BUNDLED_FOLDERS:
        if folder != "web/dist":  # built before a freeze
            assert (REPO / folder).is_dir() and any((REPO / folder).rglob("*")), folder
    assert not any(f.startswith(("workspaces", "plugins/example")) for f in BUNDLED_FOLDERS)
    # The parcels add-on ships in the installed app, with its data files (carriers, prompts, guidance).
    assert "plugins/parcels" in BUNDLED_FOLDERS
    # The folders of non-code files inside `engine/` are all there, so no data file is missing in a frozen app.
    holding = {
        path.parent.relative_to(REPO).parts[:3]
        for path in (REPO / "engine").rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".md", ".json"} and "__pycache__" not in path.parts
    }
    bundled = {tuple(f.split("/")) for f in BUNDLED_FOLDERS if f.startswith("engine/")}
    assert all(any(h[: len(b)] == b for b in bundled) for h in holding), sorted(holding)


def test_opened_with_nothing_typed_the_frozen_entry_starts_the_app_and_with_arguments_runs_the_command(monkeypatch):
    calls = []
    engine = types.ModuleType("engine")
    cli = types.ModuleType("engine.cli")
    desktop = types.ModuleType("engine.desktop")
    cli.main = lambda: calls.append("command") or 37
    desktop.main = lambda: calls.append("desktop") or 0
    engine.cli, engine.desktop = cli, desktop
    for name, module in (("engine", engine), ("engine.cli", cli), ("engine.desktop", desktop)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr("multiprocessing.freeze_support", lambda: calls.append("freeze_support"))
    for argv, code, ran in (
        (["Thimbleby"], 0, "desktop"),
        (["Thimbleby", "--at-login"], 0, "desktop"),
        (["Thimbleby", "serve", "-w", "x"], 37, "command"),
    ):
        calls.clear()
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(BUILD / "launcher.py"), run_name="__main__")
        assert result.value.code == code and calls == ["freeze_support", ran]


@pytest.mark.parametrize("filename,system", [("thimbleby_macos.spec", "darwin"), ("thimbleby_windows.spec", "win32")])
def test_specs_preserve_resources_and_disable_console(monkeypatch, filename, system):
    observed = {}
    data = list(bundled_data(REPO))
    common = types.ModuleType("freeze_common")

    def inputs(actual_root, actual_system):
        assert actual_root == REPO and actual_system == system
        return {
            "datas": data,
            "hiddenimports": ["engine.cli"],
            "architecture": "arm64",
            "version": "0.1.0",
            "numeric_version": "0.1.0",
            "icon": "the-icon-file",
        }

    common.freeze_inputs = inputs
    monkeypatch.setitem(sys.modules, "freeze_common", common)
    monkeypatch.setattr(sys, "path", list(sys.path))

    def analysis(*args, **kwargs):
        observed["analysis"] = (args, kwargs)
        return types.SimpleNamespace(pure=(), scripts=(), binaries=(), datas=data)

    def executable(*args, **kwargs):
        observed["exe"] = kwargs
        return object()

    def bundle(*args, **kwargs):
        observed["bundle"] = kwargs
        return object()

    runpy.run_path(
        str(BUILD / filename),
        init_globals={
            "SPECPATH": str(BUILD),
            "Analysis": analysis,
            "PYZ": lambda *args: object(),
            "EXE": executable,
            "COLLECT": lambda *args, **kwargs: object(),
            "BUNDLE": bundle,
        },
    )
    args, kwargs = observed["analysis"]
    assert kwargs["datas"] == data
    assert args[0] == [str(BUILD / "launcher.py")] and (BUILD / "launcher.py").is_file()
    assert all(Path(hook).is_file() for hook in kwargs["runtime_hooks"])
    assert observed["exe"]["console"] is False
    assert observed["exe"]["exclude_binaries"] is True
    assert observed["exe"]["upx"] is False
    assert observed["exe"]["name"] == "Thimbleby"
    assert observed["exe"]["icon"] == "the-icon-file"
    if system == "darwin":
        assert observed["exe"]["target_arch"] == "arm64"
        assert observed["exe"]["codesign_identity"] is None
        assert observed["bundle"]["name"] == "Thimbleby.app"
        assert observed["bundle"]["icon"] == "the-icon-file"
        assert observed["bundle"]["bundle_identifier"] == "app.thimbleby.desktop"
    else:
        assert observed["exe"]["contents_directory"] == "_internal"


def test_the_freeze_looks_for_the_thimbleby_command_and_collects_what_is_loaded_by_name():
    text = (BUILD / "freeze_common.py").read_text()
    assert 'name="thimbleby"' in text and 'name="cockpit"' not in text
    for package in ("api", "plugins.kit", "plugins.parcels", "uvicorn", "pystray", "webview"):
        assert f'"{package}"' in text
    assert "plugins.example" not in text
    # The window library's script files, which put the bridge into each page: without them, nothing in the page can
    # reach the app on the Mac, and the build refuses to go on.
    assert 'collect_data_files("webview", includes=["js/**/*"])' in text
    assert "script files were not found" in text


def test_the_build_files_carry_the_new_names_only():
    for path in [*BUILD.glob("*.spec"), BUILD / "windows.iss"]:
        assert "cockpit" not in path.read_text().lower(), path.name
    assert not list(BUILD.glob("cockpit_*"))
    assert "AppId={{8B79A062-067C-46D5-94D7-A27CBAA00C33}" in (BUILD / "windows.iss").read_text()


def workflow():
    return yaml.safe_load((REPO / ".github" / "workflows" / "release.yml").read_text())


def test_one_release_workflow_builds_the_package_and_the_three_installers_from_a_tag_or_by_hand():
    flow = workflow()
    # YAML reads `on` as true. The private repository starts it only by hand and the public release repository's copy
    # also on a tag (tests/private/test_export.py checks each); the release step needs a tag.
    assert "workflow_dispatch" in flow[True]
    assert flow["permissions"] == {"contents": "read"}
    assert flow["jobs"]["package"]["permissions"] == {"contents": "write"}
    assert "permissions" not in flow["jobs"]["desktop"]  # a build never writes to the repository
    assert flow["jobs"]["desktop"]["needs"] == "package"
    # The targets live in one file; the Intel Mac is built only for a tag, and the package job hands the chosen ones on.
    assert flow["jobs"]["desktop"]["strategy"]["matrix"] == "${{ fromJSON(needs.package.outputs.targets) }}"
    matrix = json.loads((BUILD / "targets.json").read_text())["include"]
    assert {(item["target"], item["runner"], item["python_arch"], item.get("tag_only", False)) for item in matrix} == {
        ("macos-arm64", "macos-15", "arm64", False),
        ("macos-x86_64", "macos-15-intel", "x64", True),
        ("windows-x64", "windows-2022", "x64", False),
    }
    assert all((REPO / item["spec"]).is_file() for item in matrix)
    checks = next(step for step in flow["jobs"]["package"]["steps"] if step.get("name") == "Checks")
    assert checks["if"] == "github.ref_type == 'tag'"
    # Publishing is never part of a build: a tag makes a draft release that a person publishes by hand, the package job
    # starts it, and the attach job adds the installers to it, for a tag only.
    steps = flow["jobs"]["package"]["steps"]
    release = next(step for step in steps if "gh release create" in step.get("run", ""))
    assert release["if"] == "github.ref_type == 'tag'" and "--draft" in release["run"]
    attach = flow["jobs"]["attach"]
    assert attach["if"] == "github.ref_type == 'tag'" and attach["needs"] == ["package", "desktop"]
    assert not any("release create" in step.get("run", "") or "edit" in step.get("run", "") for step in attach["steps"])
    assert not any("gh release" in step.get("run", "") for step in flow["jobs"]["desktop"]["steps"])
    assert any("smoke_frozen.py" in step.get("run", "") for step in flow["jobs"]["desktop"]["steps"])


def test_every_action_in_the_workflow_is_pinned_by_commit_hash():
    uses = [step["uses"] for job in workflow()["jobs"].values() for step in job["steps"] if "uses" in step]
    assert uses
    for action in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[a-f0-9]{40}", action), action


def test_the_pinned_python_is_one_the_runners_can_install_and_the_locks_were_made_for_it():
    version = workflow()["env"]["PYTHON_VERSION"]
    assert re.fullmatch(r"3\.\d+\.\d+", version)
    for lock in (BUILD / "locks").glob("*.txt"):
        assert f"--python-version {'.'.join(version.split('.')[:2])} " in lock.read_text(), lock.name


@pytest.mark.parametrize("target", ["macos-arm64", "macos-x86_64", "windows-x64", "linux-x64"])
def test_each_lock_is_complete_and_hashed(target):
    text = (BUILD / "locks" / f"{target}.txt").read_text()
    blocks = re.split(r"\n(?=[A-Za-z0-9][\w.-]*==)", text)
    pinned = [b for b in blocks if re.match(r"[A-Za-z0-9][\w.-]*==", b)]
    assert pinned
    for block in pinned:
        assert "--hash=sha256:" in block, block.splitlines()[0]
    names = {b.split("==")[0].lower() for b in pinned}
    # The app's own libraries, the tray, the build backend the source install needs, and the freezer, at its pin.
    assert {"fastapi", "uvicorn", "pillow", "hatchling", "pyinstaller"} <= names
    # The window is the system's web view on the Mac and Windows; the Mac's menu-bar item is made with PyObjC and the
    # Windows tray is pystray (a Linux lock only tries the frozen start, with a stand-in window).
    assert ("pywebview" in names) == (target != "linux-x64")
    assert ("pystray" in names) == (not target.startswith("macos"))
    assert ("pyobjc-framework-cocoa" in names) == target.startswith("macos")
    assert "pyinstaller==6.22.3" in text and "thimbleby" not in names
    assert (target.startswith("windows")) == ("pywin32-ctypes" in names)
    assert (target.startswith("macos")) == ("macholib" in names)
    # The disk image's window is laid out by this library, which only the Mac builds use.
    assert (target.startswith("macos")) == ("dmgbuild" in names)


def test_a_build_by_hand_takes_its_version_from_the_package_and_a_tag_from_the_tag(monkeypatch, tmp_path):
    env_file = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.setattr(sys, "argv", ["release_tools.py", "prepare"])
    own = importlib.metadata.version("thimbleby")
    monkeypatch.delenv("RELEASE_TAG", raising=False)
    release_tools.main()
    assert env_file.read_text().startswith(f"APP_VERSION={own}\n")
    env_file.write_text("")
    monkeypatch.setenv("RELEASE_TAG", "v1.2.3rc1")
    release_tools.main()
    assert env_file.read_text() == "APP_VERSION=1.2.3rc1\nWINDOWS_VERSION=1.2.3\n"


CHANGELOG = """# Changelog

## 0.2.0 (2026-12-01)

Newer.

## 0.1.0a1 (2026-11-14)

- First thing.
- Second thing.

## 0.0.9 (2026-10-01)

Older.
"""


def test_a_section_still_headed_unreleased_is_refused_until_its_date_is_the_tags_day():
    text = "# Changelog\n\n## 0.3.0 (unreleased)\n\n- Coming.\n"
    with pytest.raises(ValueError, match="unreleased"):
        release_tools.release_notes(text, "0.3.0")
    assert release_tools.release_notes(text.replace("unreleased", "2030-01-02"), "0.3.0") == "- Coming.\n"


def test_the_release_notes_are_the_tags_section_of_the_change_log():
    assert release_tools.release_notes(CHANGELOG, "0.1.0a1") == "- First thing.\n- Second thing.\n"
    assert release_tools.release_notes(CHANGELOG, "0.2.0") == "Newer.\n"
    assert release_tools.release_notes(CHANGELOG, "0.0.9") == "Older.\n"  # the last section runs to the end


@pytest.mark.parametrize("version", ["0.3.0", "0.1.0", "0.1.0rc1"])
def test_a_version_with_no_section_in_the_change_log_is_refused_saying_so(version):
    with pytest.raises(ValueError, match=f"no section for version {version}"):
        release_tools.release_notes(CHANGELOG, version)


def test_a_tag_with_no_section_fails_the_notes_step_before_the_release_is_made(monkeypatch, tmp_path):
    out = tmp_path / "notes.md"
    monkeypatch.setattr(sys, "argv", ["release_tools.py", "notes", "--out", str(out)])
    monkeypatch.setenv("RELEASE_TAG", "v99.0.0")
    with pytest.raises(SystemExit, match="no section for version 99.0.0"):
        release_tools.main()
    assert not out.exists()
    # The current version's own section: refused while it is still headed (unreleased), its notes once it is dated.
    own = importlib.metadata.version("thimbleby")
    monkeypatch.setenv("RELEASE_TAG", f"v{own}")
    if f"## {own} (unreleased)" in (REPO / "CHANGELOG.md").read_text():
        with pytest.raises(SystemExit, match="unreleased"):
            release_tools.main()
        assert not out.exists()
    else:
        release_tools.main()
        assert out.read_text().strip()


def test_installer_per_user_and_installs_the_whole_folder():
    text = (BUILD / "windows.iss").read_text()
    assert "PrivilegesRequired=lowest" in text
    assert "DefaultDirName={localappdata}\\Programs\\Thimbleby" in text
    assert "PrivilegesRequiredOverridesAllowed" not in text
    assert "recursesubdirs createallsubdirs" in text
    assert "[UninstallDelete]" not in text


def test_compiler_download_has_an_exact_version_and_hash():
    tool = json.loads((BUILD / "tool_downloads.yaml").read_text())["inno_setup"]
    assert tool["version"] == "6.4.3"
    assert tool["url"].endswith("/innosetup-6.4.3.exe")
    assert re.fullmatch(r"[a-f0-9]{64}", tool["sha256"])


def test_each_runner_opens_the_frozen_app_in_its_desktop_session_and_keeps_the_pictures():
    """A start that only proves the server runs let a crash in the menu-bar item through: the check opens the app as a
    person does, and the Mac run is under Apple's main-thread checker set to stop on any report."""
    # The release repository's copy has the same jobs (tests/private/test_export.py), so this file is enough.
    for path in (REPO / ".github" / "workflows" / "release.yml",):
        steps = yaml.safe_load(path.read_text())["jobs"]["desktop"]["steps"]
        assert any("session_check.py" in step.get("run", "") for step in steps), path
        assert any("window-pictures" in str(step.get("with", {}).get("name", "")) for step in steps), path
    script = (BUILD / "session_check.py").read_text()
    assert "MTC_CRASH_ON_REPORT" in script and "libMainThreadChecker.dylib" in script and "Start-Process" in script
    assert '"open"' in script and "screencapture" in script and "System.Drawing" in script


def test_the_app_and_its_installer_carry_the_mark_as_their_icon(tmp_path):
    """Without an icon file PyInstaller's own picture is the Dock, taskbar and title bar icon."""
    from PIL import Image

    from engine import brandmark

    ico = brandmark.write_ico(tmp_path / "x.ico")
    assert Image.open(ico).info["sizes"] >= {(16, 16), (32, 32), (256, 256)}
    icns = brandmark.write_icns(tmp_path / "x.icns")
    assert icns.read_bytes()[:4] == b"icns"
    assert 'brandmark.write_icns(icons / "Thimbleby.icns")' in (BUILD / "freeze_common.py").read_text()
    assert 'brandmark.write_ico(icons / "Thimbleby.ico")' in (BUILD / "freeze_common.py").read_text()
    assert "SetupIconFile={#IconFile}" in (BUILD / "windows.iss").read_text()
    # The release repository's copy has the same jobs (tests/private/test_export.py), so this file is enough.
    for path in (REPO / ".github" / "workflows" / "release.yml",):
        assert "/DIconFile=" in path.read_text() and "Thimbleby.ico" in path.read_text(), path


def test_the_session_check_fails_on_a_page_that_has_not_drawn():
    import session_check

    blank = {"address": "http://127.0.0.1:1/", "drawn": False}
    starting = {"address": "", "drawn": True}
    live = {"address": "http://127.0.0.1:1/", "drawn": True}
    assert not session_check.page_drawn(None) and not session_check.page_drawn(blank)
    assert not session_check.page_drawn(starting) and session_check.page_drawn(live)
    clock = iter(range(1000))
    answers = iter([blank, blank, live])
    assert session_check.wait_drawn(lambda: next(answers), 30, lambda: next(clock), lambda s: None) == live
    clock = iter(range(1000))
    assert session_check.wait_drawn(lambda: blank, 30, lambda: next(clock), lambda s: None) == blank


def test_the_disk_image_and_setup_pictures_are_drawn_at_the_stated_sizes(tmp_path):
    import dmg_settings
    from PIL import Image

    from engine import installer_art

    one, two = installer_art.write_dmg_background(tmp_path, dmg_settings.LINES)
    assert one.name == "dmg-background.png" and two.name == "dmg-background@2x.png"
    assert Image.open(one).size == (620, 340) and Image.open(two).size == (1240, 680)
    # The system joins the two by their resolution, so they must carry 72 and 144.
    assert round(Image.open(one).info["dpi"][0]) == 72 and round(Image.open(two).info["dpi"][0]) == 144
    assert Image.open(one).getpixel((2, 2)) == installer_art.CREAM
    # The arrow is brass, between the two icon places.
    arrow = Image.open(one).getpixel((300, installer_art.DMG_APP_CENTER[1] + 2))
    assert all(abs(a - b) <= 6 for a, b in zip(arrow, installer_art.BRASS, strict=True)), arrow

    made = installer_art.write_wizard_images(tmp_path / "wiz", "Name", "Version 1.2.3")
    sizes = {role: Image.open(path).size for role, path in made.items()}
    assert sizes == {"side": (164, 314), "side_large": (328, 628), "small": (55, 55), "small_large": (110, 106)}
    assert all(path.suffix == ".bmp" for path in made.values())
    assert Image.open(made["side"]).getpixel((2, 2)) == installer_art.BRAND


def test_the_disk_image_names_its_volume_window_and_two_lines():
    import dmg_settings

    from engine import installer_art

    assert dmg_settings.volume_name("0.1.0") == "Thimbleby 0.1.0"
    assert dmg_settings.LINES == (
        "Drag Thimbleby into Applications",
        "Then open it from Applications or Launchpad",
    )
    chosen = dmg_settings.settings("Thimbleby.app", Path("x/dmg-background.png"))
    assert chosen["window_rect"][1] == (620, 340) == installer_art.DMG_WINDOW
    assert chosen["icon_size"] == 112 and chosen["default_view"] == "icon-view"
    assert chosen["symlinks"] == {"Applications": "/Applications"}
    assert set(chosen["icon_locations"]) == {"Thimbleby.app", "Applications"}
    # Both icons sit on the window's middle line, one each side of the arrow.
    (left_x, left_y), (right_x, right_y) = (chosen["icon_locations"][k] for k in ("Thimbleby.app", "Applications"))
    assert left_y == right_y and left_x < 310 < right_x
    assert not chosen.get("show_toolbar") and not chosen.get("show_sidebar")
    # The layout comes from the library, with no Finder scripting, and the build and its pictures are the steps' own.
    script = (BUILD / "release_tools.py").read_text()
    assert "dmgbuild.build_dmg" in script and "osascript" not in script and "hdiutil" not in script


def test_a_mounted_images_folder_is_read_from_the_systems_answer():
    import plistlib

    import dmg_picture

    answer = plistlib.dumps(
        {"system-entities": [{"dev-entry": "/dev/disk4"}, {"mount-point": "/Volumes/Thimbleby 0.1.0"}]}
    )
    assert dmg_picture.mount_point(answer) == "/Volumes/Thimbleby 0.1.0"
    with pytest.raises(SystemExit):
        dmg_picture.mount_point(plistlib.dumps({"system-entities": []}))


def test_the_setup_has_three_pages_in_the_targets_words_and_no_licence_folder_or_ready_page():
    text = (BUILD / "windows.iss").read_text()
    # Only the pages that say something: no licence, folder, Start-menu group or ready page.
    for line in ("DisableDirPage=yes", "DisableProgramGroupPage=yes", "DisableReadyPage=yes", "WizardStyle=modern"):
        assert line in text
    assert "LicenseFile" not in text and "DisableFinishedPage" not in text
    # The modern style hides the Welcome page unless it is asked for (the runner's pictures showed it missing).
    assert "DisableWelcomePage=no" in text
    assert "WizardImageFile={#ImageDir}\\side.bmp,{#ImageDir}\\side@2x.bmp" in text
    assert "CloseApplications=yes" in text and "PrivilegesRequired=lowest" in text
    # Welcome: three facts.
    for words in (
        "For you only. No administrator password.",
        "About a minute, and {#SizeMB} MB of space.",
        "Your work is kept in its own folder. Removing the app never deletes it.",
    ):
        assert words in text
    # A couple of choices: the desktop shortcut ticked, starting at sign-in not, the folder as text, and Install.
    assert 'Name: "desktopicon"; Description: "{cm:TaskDesktop}"; Flags: checkedonce' in text
    assert 'Name: "signin"; Description: "{cm:TaskSignIn}"; Flags: unchecked' in text
    assert "english.TaskDesktop=Put Thimbleby on the desktop" in text
    assert "english.TaskSignIn=Start Thimbleby when I sign in to Windows" in text
    assert "WizardSelectTasks=A couple of choices" in text and "ButtonInstall=Install" in text
    assert "WizardDirValue" in text and "msgButtonInstall" in text
    # Installed: "Open Thimbleby now", ticked (no `unchecked` flag), then Finish.
    assert "english.RunNow=Open Thimbleby now" in text
    run = next(line for line in text.splitlines() if line.startswith("Filename:") and "postinstall" in line)
    assert "unchecked" not in run and "{cm:RunNow}" in run
    assert "FinishedHeadingLabel=Thimbleby is installed" in text and "InstallingLabel=Installing Thimbleby" in text
    # Removing: says what stays and how to delete it too; never deletes the work.
    assert "Your work stays in AppData\\Local\\Thimbleby: your workspace, backups and saved keys." in text
    assert "Settings > Advanced > Delete this workspace" in text
    assert "[UninstallDelete]" not in text
    # The removal button reads "Remove the app", and the last page links the folder the work stays in.
    assert "ButtonYes=&Remove the app" in text and "ButtonNo=&Keep the app" in text
    assert "english.OpenWorkFolder=Open the folder" in text
    assert "usDone" in text and "{localappdata}\\Thimbleby" in text and "TaskDialogMsgBox" in text
    # Every line is in [Messages] or [CustomMessages], and the file is plain text the compiler reads without a mark.
    assert "[Messages]" in text and "[CustomMessages]" in text
    text.encode("ascii")


def test_the_setups_sign_in_choice_writes_what_the_apps_own_switch_writes():
    from engine import login_item

    text = (BUILD / "windows.iss").read_text()
    entry = next(line for line in text.splitlines() if line.startswith("Root: HKCU") and "signin" in line)
    assert f'Subkey: "{login_item.WINDOWS_KEY}"' in entry and f'ValueName: "{login_item.WINDOWS_VALUE}"' in entry
    # The value is the program and the flag, each in quotes, as the app writes it.
    written = " ".join(f'"{a}"' for a in login_item.command("{app}\\Thimbleby.exe"))
    assert 'ValueData: "' + written.replace('"', '""') + '"' in entry
    assert "uninsdeletevalue" in entry and "RegDeleteValue" in text


def test_each_runner_takes_a_picture_of_the_disk_image_and_of_every_setup_page():
    flow = workflow()["jobs"]["desktop"]["steps"]
    by_name = {step.get("name"): step for step in flow}
    mac = by_name["Mount the disk image and take a picture of its window"]
    assert "dmg_picture.py" in mac["run"] and mac["if"] == "runner.os == 'macOS'"
    assert (BUILD / "dmg_picture.py").read_text().count("dmg-window.png") == 1
    drawn = by_name["Draw the setup's side and header pictures"]["run"]
    assert "release_tools.py wizard-art" in drawn
    compile_step = by_name["Compile the per-user installer"]["run"]
    assert "/DImageDir=" in compile_step and "/DSizeMB=" in compile_step
    pictures = next(step for name, step in by_name.items() if name.startswith("Run the setup"))
    assert "setup_pictures.ps1" in pictures["run"]
    script = (BUILD / "setup_pictures.ps1").read_text()
    for page in (
        "setup-1-welcome",
        "setup-2-choices",
        "setup-3-progress",
        "setup-4-installed",
        "remove-1-first",
        "remove-3-folder",
    ):
        assert f"'{page}.png'" in script
    assert "WScript.Shell" in script and "{ENTER}" in script
    # The pictures are downloads of the run, beside the window pictures, after every step that adds one.
    names = [step.get("name") for step in flow]
    keep = next(i for i, n in enumerate(names) if n and n.startswith("Keep the pictures"))
    assert keep > names.index(pictures["name"]) > names.index("Compile the per-user installer")
    assert keep > names.index("Mount the disk image and take a picture of its window")
    assert flow[keep]["if"] == "always()"


def test_each_runner_tests_a_fresh_install_from_first_start_to_uninstall_after_the_installer_is_kept():
    """S-0459: the built installer is installed on an empty home, started, closed, started again, put over, and removed,
    with a browser test of the page on the first and the later visits. It runs after the installer is kept."""
    steps = workflow()["jobs"]["desktop"]["steps"]
    names = [step.get("name") for step in steps]
    check = next(i for i, step in enumerate(steps) if "fresh_install_check.py" in step.get("run", ""))
    assert check > names.index("Upload the installer and checksums")
    assert any("playwright install" in step.get("run", "") for step in steps[:check])
    assert steps[check + 1]["if"] == "always()" and "fresh-install" in steps[check + 1]["with"]["name"]
    script = (BUILD / "fresh_install_check.py").read_text()
    for visit in ('"first start"', '"start again"', '"after the update"'):
        assert visit in script
    # The uninstall removes the app and never the work; both systems do it.
    assert "unins000.exe" in script and "Removing the app removed the person's work" in script
    assert "hdiutil" in script and "/VERYSILENT" in script
    spec = (REPO / "web" / "e2e-install" / "fresh-install.spec.ts").read_text()
    assert "Getting started" in spec and "FRESH_INSTALL_VISIT" in spec
    assert "testMatch: /fresh-install\\.spec\\.ts/" in (REPO / "web" / "playwright.install.config.ts").read_text()
