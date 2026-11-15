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
    for package in ("api", "plugins.kit", "uvicorn", "pystray", "webview"):
        assert f'"{package}"' in text
    assert "plugins.example" not in text


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
