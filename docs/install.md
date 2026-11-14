# Installing Thimbleby

Thimbleby runs on your own computer (Windows, macOS or Linux) and opens in your browser. It needs no Node and no
copy of the source code: one package file holds the app and its screens.

## The installers

Each version's three installers are downloads on its release, on the repository's Releases page. A build started by
hand from that repository's Actions tab keeps them with the run instead. They are unsigned, so the system asks you to
confirm the first open:

- **Mac:** opening it says Apple could not verify it. Open **System Settings › Privacy & Security**, scroll to the line
  about Thimbleby, and click **Open Anyway**, then **Open**. You do this once.
- **Windows:** the setup says "Windows protected your PC". Click **More info**, then **Run anyway**. You do this once.

| Download | For |
| --- | --- |
| `Thimbleby-<version>-macos-arm64.dmg` | a Mac with an Apple chip, macOS 15 or later |
| `Thimbleby-<version>-macos-x86_64.dmg` | a Mac with an Intel chip, macOS 15 or later |
| `Thimbleby-<version>-windows-x64-setup.exe` | Windows, installed for you alone, with no administrator password |

Each comes with `SHA256SUMS.txt`. Open the app: it starts in the background (a tray or menu-bar item with Open, Restart and
Quit), makes your workspace in the system's app-data folder the first time, and opens it in your browser. No Python, uv or
terminal is needed. To remove it, delete the app (Mac) or use Windows' app list; your workspace stays in the app-data folder
(`~/Library/Application Support/thimbleby` or `%LOCALAPPDATA%\thimbleby`) until you delete it inside the app. How they are
built is in `deploy/desktop/README.md`. The steps below are for the command-line install.

## What you need

- **uv**, the Python package tool. Install it from its documentation; it fetches the right Python for you.
- **A computer with a case-insensitive disk (macOS, Windows) is fine for the source too:** the repository holds no two
  file names that differ only in capitals, so a checkout never has one file overwrite another there. Keep it that way
  when adding files.
- **The package file**, `thimbleby-<version>-py3-none-any.whl`, the `constraints.txt` from the same release (the exact
  library versions the release was tested with), and the install script for your computer: `install.sh` (macOS, Linux) or
  `install.ps1` (Windows). Save them in one folder; the script finds `constraints.txt` beside the package file.

## Install or update

In a terminal, in the folder where you saved the files:

```sh
sh install.sh thimbleby-<version>-py3-none-any.whl                                  # macOS, Linux
powershell -ExecutionPolicy Bypass -File install.ps1 thimbleby-<version>-py3-none-any.whl   # Windows
```

Updating is the same command with the newer file. Your workspaces are separate folders. An update first copies the
records of the workspace you used last (close the app first; it refuses while the app is open), installs, and opens the
workspace once with the new version. If any of that fails, it puts the version you had back and the copy of your records,
and says so. A plain install touches no workspace.

## Start your own workspace

```sh
thimbleby
```

The first time, this makes your workspace in a `Thimbleby` folder in your home folder (a workspace an earlier version made in a `Cockpit` folder is kept in use) and
opens it; after that it reopens the workspace you used last. If your browser loses its sign-in while the app runs, `thimbleby open`
opens it signed in again; a browser stays signed in for `server.cookie_max_age_days` (30) days. `thimbleby erase` lists exactly what
a workspace holds and deletes the workspace, its history and its backups after you confirm. For a workspace elsewhere: `thimbleby init <folder>`, then `thimbleby serve -w <folder>`.

The workspace starts empty, and nothing in it needs a file edited. The first screen is the setup walkthrough: Welcome,
your name, what you will use it for (your own life, a job, a business), your AI account (with a test), your mail and
calendar, a backup folder and the people in your life, then Done (six steps in all; the first look back over your mail is
Today's Start line, which waits for your Start and shows its cost). Each step can
be skipped and done later from Settings. Keep workspaces in your home folder, not in a temporary folder.
[`getting-started.md`](getting-started.md) follows the same path step by step, with what each step costs.

## Update

- **A package install:** run the install step above again with the newer package file and its `constraints.txt`.
- **A source checkout:** run `thimbleby update` (with `uv run` in front when you run from the checkout; add `-w` for a
  workspace other than the one you used last). It copies the workspace's records first, pulls the newest version, brings
  the Python environment up to date from the lock without removing add-ons you installed from the screen, installs the
  web tools and rebuilds the screens, then opens the workspace once, printing each step. It stops at the first step that
  fails and names it with its exit code, goes back to the version you had and puts the copy back, and it refuses when you
  have changes of your own in the checkout or the app is open. It ends with the old and new
  version, or "Already up to date", and tells you that a running app shows **Restart now**. If Node isn't installed it
  skips the web steps and says the screens weren't rebuilt. On a package install it prints the install step instead.

## Add an add-on from its file

When an add-on's publisher gives you a package file (a `.whl`) instead of a listing with an Install button, run:

```
thimbleby install <the file>
```

From a source copy, use `uv run thimbleby install <the file>` in its folder. It installs the same way as the Add-ons
screen's Install button: only add-ons of pure Python whose needs the app already has. `thimbleby update` keeps it. Then
turn it on in the app (Add-ons, or the walkthrough's Mail and calendar step); it starts after a restart.

## Restore from a backup

Backups are dated folders in the backup folder you chose. **To go back to one in the app:** Settings, Backups, then
**Restore this copy** on the copy you want (a copy that is encrypted asks for its key). The app checks the copy and
stages it; nothing changes until you choose **Restart now**. At the next start the workspace as it is now is set aside in
`.thimbleby/before-restore/<time>/` (nothing is deleted) and the copy takes its place.

**To make a new workspace from one instead,** on the command line:

```sh
thimbleby restore --backup ~/Backups/cockpit-20261009-140000 ~/cockpit-restored
thimbleby serve -w ~/cockpit-restored
```

The command checks the backup's database first, then copies it, with the settings, sources, files and texts the backup
holds, into the new folder. It refuses a folder that already has files and never changes the backup or the workspace
you are running. The restored workspace is free to open on this computer even if the backup was made while another
computer had it open.

## Try an add-on on made-up data

```sh
thimbleby demo
```

This is a sandbox for trying an add-on (`thimbleby demo --plugin <its folder>`), not a place to start. It makes a demo
workspace in `~/thimbleby-demo` (a made-up small press with made-up people) and opens it in your browser. Every screen says
it is a demo. It works without an AI account: a stand-in answers instead, so you can see the whole loop.
`thimbleby demo --fresh` starts the demo over; `thimbleby demo --which demo-a` uses the other demo, the project office of a
made-up freight company. The two fictional workspaces are test fixtures; don't build real work in them.

## Uninstall

```sh
uv tool uninstall thimbleby
```

Your workspace folders stay where they are.
