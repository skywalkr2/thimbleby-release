# The desktop builds

Unsigned Windows and macOS installers, made by `.github/workflows/release.yml`. A person who opens the installed app gets the
tray or menu-bar item and the app on their own workspace in the app-data folder, not the command line (`engine/desktop.py`).

## What is built

A `v*` tag, or **Run workflow** on the workflow's page in the repository's Actions tab, runs two jobs:

1. `package` (Linux): the lint, the tests and the self-check, the web screens, the wheel and its constraints, and the demo
   smoke test. For a tag only, it then attaches them to a release (as it did before). It keeps the screens and the filled
   `catalog/product.yaml` as an artifact for the next job.
2. `desktop` (one native runner each), only after `package` passed:

| Runner | Python architecture | Output |
| --- | --- | --- |
| `macos-15` | arm64 | `Thimbleby-VERSION-macos-arm64.dmg` containing `Thimbleby.app` |
| `macos-15-intel` | x64 | `Thimbleby-VERSION-macos-x86_64.dmg` containing `Thimbleby.app` |
| `windows-2022` | x64 | `Thimbleby-VERSION-windows-x64-setup.exe` |

Each job installs its hashed lock, installs the source package (`--no-deps --no-build-isolation`), freezes the app with
PyInstaller (one folder, windowed), **starts the frozen app on an empty home folder** (`build_support/smoke_frozen.py`: it
must make its workspace, serve the screens on this computer only, refuse a visit with no sign-in link, and let a second start
only bring the first forward), and only then makes the disk image or the installer. Each uploads its installer and
`SHA256SUMS.txt` as a download of the run (14 days). Nothing is published, no one is told, and nothing is installed for a
tester. Hashes detect changed bytes; they do not say who made the file.

**To make one by hand:** Actions tab, *release*, *Run workflow*, pick the branch. With no tag the version is the package's own
(`pyproject.toml`); with a tag it must equal the tag without the `v` (`v0.1.0`, `v0.1.0rc1`, `v0.1.0.post1`; numbers up to
65535). The downloads are on the run's page, under Artifacts.

## What the installers look like

Both follow the product's installer design and its mockups; the pictures are drawn at build time from the brand's own mark
(`engine/installer_art.py`), never kept as files.

- **Mac disk image** (`release_tools.py dmg`, `build_support/dmg_settings.py`): a 620 x 340 window that opens by itself, cream, with
  a brass arrow from the app to the Applications alias and two lines under them; the volume is "Thimbleby VERSION". The layout is
  written by `dmgbuild` (in the Mac locks): it writes the Finder's own window settings straight into the image, so no Finder
  scripting and no logged-in desktop is needed to build it. The background is made at 1x and 2x.
- **Windows setup** (`build_support/windows.iss`): Inno Setup in modern style with the brand side image (164 x 314, and 328 x 628)
  from `release_tools.py wizard-art`. Three pages: Welcome (three facts), A couple of choices (desktop shortcut ticked, start at
  sign-in not ticked, the folder as text, the button reads Install) and Installed ("Open Thimbleby now" ticked). No licence, folder,
  Start-menu-group or ready page. "Start at sign-in" writes the same run key and value as the app's own switch
  (`engine/login_item.py`). The uninstaller says what stays and how to delete it too, and never deletes the work.
- **Pictures:** each desktop job adds pictures to the run's downloads beside the window pictures: the Mac's `dmg-window.png`
  (`build_support/dmg_picture.py`) and the Windows setup's pages and the uninstaller's (`build_support/setup_pictures.ps1`, which sends
  Enter between pages). These steps do not fail the build; a page the runner could not reach is missing from the folder.

## What the app does when opened

`build_support/launcher.py` is the frozen entry. With nothing typed it calls `engine.desktop.main`: it makes the workspace
(first time, no template) in the app-data folder (`<data>/thimbleby/workspace`; `THIMBLEBY_WORKSPACE` names another), then starts
the app on it (`engine/launcher.py`, `engine/appwindow.py`): the server on loopback, the starting window, then the app in
its own window once the server answers, one instance per workspace (a second open shows the running window), and the
menu-bar or tray item's menu (see "The window, the menu-bar item and the check in a desktop session"). With arguments it is the `thimbleby` command. A start that fails
writes why to `desktop.log` in the logs folder. Resources are read from the frozen folder; data, logs and add-ons are in the
user folders, never inside the app.

## What is bundled

The folders listed in `build_support/build_model.py` (`BUNDLED_FOLDERS`), at their repository paths under the frozen
resource root, where `engine/shipped.py` and `engine/plugin_host.py` look: the built screens, the starting templates, the
catalog, the non-code folders of `engine/`, and `plugins/kit`. The engine, API, the kit, the web server and the tray
library are collected by name (`freeze_common.py`). **Not bundled:** the fictional workspaces and the example plugin (nothing
made-up ships). A missing folder, or missing screens, fails the build.

## Choices

1. **Native per architecture:** PyInstaller doesn't cross-compile, so each chip and Windows has its own runner and lock.
   macOS 15 is the declared minimum (`MACOSX_DEPLOYMENT_TARGET`); lower it only after testing older systems.
2. **One folder, no UPX, no stripping.** The macOS folder becomes the bundle; the Windows folder is copied whole.
3. **Windowed**, with a runtime hook giving null streams to libraries that inspect them.
4. **Per user on Windows:** `PrivilegesRequired=lowest`, default folder `{localappdata}\Programs\Thimbleby`; the installer
   removes the old `_internal` before replacing it, and uninstall deletes no user data.
5. **Unsigned.** No signing identity, notarization or signing command; PyInstaller's ad-hoc macOS signature is all. Testers
   see the systems' warnings. Signing is batch TB4 and waits for the signing accounts.
6. **Locked dependencies:** `build_support/locks/<target>.txt` (see its README), installed with `--require-hashes`.

## What each pin was checked against (2026-11-14)

| Pin | Value | Checked against |
| --- | --- | --- |
| `actions/checkout` | `3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1) | the repository's tags (`git ls-remote`): v7.0.1 is that commit; its `action.yml` has the inputs used |
| `actions/setup-python` | `5fda3b95a4ea91299a34e894583c3862153e4b97` (v7.0.0) | tags: v7.0.0 is that commit; `action.yml` has `architecture` and `pip-version` (v7.1.0 exists; not taken, not needed) |
| `actions/upload-artifact` | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` (v7.0.2) | tags: v7.0.2 is that commit; inputs `if-no-files-found`, `compression-level`, `retention-days` exist |
| `actions/download-artifact` | `9000827ccba6bdab643e8b6fd33ac0654aef8333` (v8.0.2) | tags: v8.0.2 is that commit; inputs `name`, `path` exist |
| `astral-sh/setup-uv` | `d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86` (v5.4.2) | tags: the last v5 release, the line the workflow used before |
| `actions/setup-node` | `49933ea5288caeca8642d1e84afbd3f7d6820020` (v4.4.0) | tags: the last v4 release, the line the workflow used before |
| Python | **3.13.17** | the hosted runners' Python manifest (`actions/python-versions`): it has macOS (arm64, x64) and Windows (x64) builds of 3.13.17. **The draft's 3.12.15 was wrong:** 3.12.11 and later have no macOS or Windows build there (3.12.10 is the last), so the draft would have failed to install it |
| pip | 25.2 | PyPI: the release exists (2025-07-30); `setup-python` takes it through `pip-version` |
| PyInstaller | 6.22.3 | PyPI: the release exists (2026-09-12) and is the latest; the freeze runs on it (below) |
| Runner labels | `macos-15` (arm64), `macos-15-intel` (x64), `windows-2022` (x64) | the runner images' own README table |
| Inno Setup | 6.4.3, `https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/innosetup-6.4.3.exe`, SHA-256 `f3c42116542c4cc57263c5ba6c4feabfc49fe771f2f98a79d2f7628b8762723b` | downloaded: the address answers, and `sha256sum` of the file is that value. Newer releases exist (6.7.x); 6.4.3 is kept as pinned |

## Proving the frozen start on Linux

The same freeze code runs on Linux with `build_support/thimbleby_linux.spec` (not shipped), on a computer with no display. The
window and tray need a display, so the proof freezes with stand-in `webview` and `pystray` modules (`deploy/desktop/proof/stub/`) put first on `PYTHONPATH` (the names the launcher
uses; the icon waits until stopped). Everything else is the app's own:

```sh
uv venv --python 3.13 /tmp/try/venv
uv pip install --python /tmp/try/venv/bin/python --require-hashes -r deploy/desktop/build_support/locks/linux-x64.txt
uv pip install --python /tmp/try/venv/bin/python --no-deps --no-build-isolation .
APP_VERSION=0.1.0 PYTHONPATH=deploy/desktop/proof/stub /tmp/try/venv/bin/python -m PyInstaller --noconfirm --clean \
  --distpath /tmp/try/dist --workpath /tmp/try/build deploy/desktop/build_support/thimbleby_linux.spec
/tmp/try/venv/bin/python deploy/desktop/build_support/smoke_frozen.py /tmp/try/dist/Thimbleby/Thimbleby
```

## The window, the menu-bar item and the check in a desktop session

The app opens in its own window (pywebview: WebKit on the Mac, WebView2 on Windows; `engine/appwindow.py`, the real classes in
`engine/appwindow_backends.py`). Mac: one loop, the window's, on the main thread, and the menu-bar item is a native status item
made on that thread through PyObjC (pystray's Mac backend builds its menu once, draws no template picture and touches AppKit
from any caller's thread). Windows: pystray's tray in its own thread. Every window or item call goes through `MainThread`.
The icon pictures are drawn when the app starts from the brand's SVG (`web/src/assets/brand/`, bundled) by
`engine/brandmark.py`; nothing about the shape is in code. Not in the menu yet: "Check for a new version" (S-0152) and
"Hand something in...".

After the smoke start, the workflow runs `build_support/session_check.py` on each runner: it opens the app as a person does
(`open` on the Mac under Apple's main-thread checker with `MTC_CRASH_ON_REPORT=1`; `Start-Process` on Windows), waits for it to
answer, takes `window.png` (and, on the Mac when the session lets the script click the item, `menu-open.png`), checks the app
is still running after a minute and that no crash report was written, then quits it through the menu's code path (the
loopback quit) and checks that it exits. The pictures are the run's `Thimbleby-window-pictures-<target>` downloads. The Linux
proof's `deploy/desktop/proof/stub/` also stands in for `webview`.

## Not done here

- **The fresh-install test from the built app** (S-0459) and the target's captures by day and at night with a cold score
  (S-0460).
- **The Windows uninstaller's "Remove the app" button and its folder link** (S-0456), and the Mac's "Removing" card (S-0457).
- **The Intel Mac build** runs only at a tag (`targets.json`, `tag_only`).
- **Signing and notarizing** (S-0461): unsigned through 1.0.
- **The identifiers are permanent:** bundle id `app.thimbleby.desktop` (`thimbleby_macos.spec`) and Windows AppId
  `{8B79A062-067C-46D5-94D7-A27CBAA00C33}` (`windows.iss`).
- **The numeric installer version** uses the three release numbers; prerelease and post-release suffixes stay in the file names
  only. Decide a monotonic build number before relying on automatic upgrades between such builds.
- **Updating** (S-0152) and the update, failed-update and earlier-workspace (S-0458) messages of the starting window.
