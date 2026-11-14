"""The install script installs the tested library versions and comes back if an update fails (S-0301, design 11.7).
`uv`, `thimbleby` and `cockpit` are stand-ins that record what they were asked, so nothing is installed."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).parents[1] / "deploy"


@pytest.fixture
def box(tmp_path):
    """A folder of stand-in commands, the downloaded files, and the log of what the stand-ins were asked."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    fail = tmp_path / "fail"
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'echo "uv $*" >> "$LOG"\n'
        'if [ "$1 $2" = "tool list" ]; then echo "pm-cockpit v0.1.0"; exit 0; fi\n'
        'if [ "$1 $2" = "tool dir" ]; then echo "$TOOLDIR"; exit 0; fi\n'
        'if [ "$1 $2" = "tool install" ] && [ -e "$BIN/thimbleby.off" ]; then\n'
        '  mv "$BIN/thimbleby.off" "$BIN/thimbleby"\n'
        "fi\n"
        'if [ "$1 $2" = "tool install" ] && grep -qx "install" "$FAIL" 2>/dev/null; then\n'
        '  case "$*" in *new.whl*) exit 1;; esac\n'
        "fi\n"
        "exit 0\n"
    )
    for name in ("thimbleby", "cockpit"):
        command = bin_dir / name
        command.write_text(
            "#!/bin/sh\n"
            f'echo "{name} $*" >> "$LOG"\n'
            'step="$2"\n'
            'if grep -qx "$step" "$FAIL" 2>/dev/null; then exit 1; fi\n'
            "exit 0\n"
        )
        command.chmod(command.stat().st_mode | stat.S_IEXEC)
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "new.whl").write_text("new package")
    (downloads / "constraints.txt").write_text("fastapi==1.0.0\n")
    store = tmp_path / "store"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/bin:/bin",  # not the environment's own, which may hold the real commands
        "LOG": str(log),
        "FAIL": str(fail),
        "THIMBLEBY_PACKAGES": str(store),
        "BIN": str(bin_dir),
        "TOOLDIR": str(tmp_path / "tools"),
        "HOME": str(tmp_path),
    }
    env.pop("COCKPIT_PACKAGES", None)

    def run(*args, installed="thimbleby", fails=(), environment=None):
        """`installed` is the program the computer already has: `thimbleby`, `cockpit` (from before the rename; the
        new program appears when the install runs) or nothing."""
        fail.write_text("\n".join(fails) + "\n")
        log.write_text("")
        hidden = {"thimbleby": ("cockpit",), "cockpit": ("thimbleby",), None: ("thimbleby", "cockpit")}[
            installed or None
        ]
        for name in hidden:
            (bin_dir / name).rename(bin_dir / f"{name}.off")
        try:
            done = subprocess.run(
                ["sh", str(DEPLOY / "install.sh"), *args],
                env={**env, **(environment or {})},
                capture_output=True,
                text=True,
            )
        finally:
            for name in hidden:
                if (bin_dir / f"{name}.off").exists():
                    (bin_dir / f"{name}.off").rename(bin_dir / name)
        return done, log.read_text().splitlines()

    run.env = env
    return run, downloads, store


def test_a_first_install_passes_the_constraints_and_keeps_the_package_for_a_way_back(box):
    run, downloads, store = box
    done, calls = run(str(downloads / "new.whl"), installed=None)
    assert done.returncode == 0, done.stderr
    install = next(c for c in calls if c.startswith("uv tool install"))
    assert f"--constraints {downloads / 'constraints.txt'}" in install and install.endswith("new.whl")
    assert not any(c.startswith(("thimbleby", "cockpit")) for c in calls)  # nothing to copy or check on a first install
    assert (store / "new.whl").exists() and (store / "current").read_text().strip() == "new.whl"
    assert (store / "new.whl.constraints.txt").read_text() == "fastapi==1.0.0\n"


def test_without_the_constraints_file_nothing_is_installed(box):
    run, downloads, _ = box
    (downloads / "constraints.txt").unlink()
    done, calls = run(str(downloads / "new.whl"))
    assert done.returncode == 2 and "constraints" in done.stderr and calls == []


def test_an_update_copies_the_records_first_opens_the_workspace_after_and_keeps_what_worked(box):
    run, downloads, store = box
    store.mkdir()
    (store / "current").write_text("old.whl\n")
    done, calls = run(str(downloads / "new.whl"))
    assert done.returncode == 0, done.stderr
    kinds = [c.split()[0] + " " + " ".join(c.split()[1:3]) for c in calls]
    assert kinds[0] == "uv tool list" and "thimbleby update-step backup" in kinds[1]
    assert "--version v0.1.0" in calls[1]
    check = calls.index("thimbleby update-step check")
    assert calls[check - 1].startswith("uv tool install") and check > 1
    assert (store / "current").read_text().strip() == "new.whl"


def test_a_workspace_the_new_version_cannot_open_puts_the_records_and_the_version_back(box):
    run, downloads, store = box
    store.mkdir()
    (store / "old.whl").write_text("old package")
    (store / "old.whl.constraints.txt").write_text("fastapi==0.9.0\n")
    (store / "current").write_text("old.whl\n")
    done, calls = run(str(downloads / "new.whl"), fails=("check",))
    assert done.returncode == 1 and "was not kept" in done.stderr and "Put back the copy" in done.stderr
    assert "thimbleby update-step restore" in calls
    # The records are put back by the new program (which has the command) before the old one is installed again.
    assert calls.index("thimbleby update-step restore") < max(
        i for i, c in enumerate(calls) if c.startswith("uv tool install")
    )
    again = calls[-1]
    assert again.startswith("uv tool install") and again.endswith(f"{store / 'old.whl'}")
    assert f"--constraints {store / 'old.whl.constraints.txt'}" in again
    assert (store / "current").read_text().strip() == "old.whl"


def test_an_install_that_fails_puts_the_version_back_without_touching_the_records(box):
    run, downloads, store = box
    store.mkdir()
    (store / "old.whl").write_text("old package")
    (store / "old.whl.constraints.txt").write_text("fastapi==0.9.0\n")
    (store / "current").write_text("old.whl\n")
    done, calls = run(str(downloads / "new.whl"), fails=("install",))
    assert done.returncode == 1
    assert "thimbleby update-step restore" not in calls and "thimbleby update-step check" not in calls
    assert calls[-1].endswith(f"{store / 'old.whl'}")


def test_a_version_from_before_the_rename_makes_the_copy_and_the_new_program_checks_it(box):
    run, downloads, store = box
    done, calls = run(str(downloads / "new.whl"), installed="cockpit")
    assert done.returncode == 0, done.stderr
    assert any(c.startswith("cockpit update-step backup") for c in calls)
    assert "thimbleby update-step check" in calls and "cockpit update-step check" not in calls


def test_the_package_folder_is_read_under_the_old_name_when_the_new_one_is_absent(box, tmp_path):
    run, downloads, _ = box
    home = tmp_path / "person"
    environment = {"HOME": str(home), "THIMBLEBY_PACKAGES": "", "COCKPIT_PACKAGES": ""}
    old = home / ".pm-cockpit" / "packages"
    old.mkdir(parents=True)
    (old / "earlier.whl").write_text("earlier package")
    (old / "earlier.whl.constraints.txt").write_text("fastapi==0.9.0\n")
    (old / "current").write_text("earlier.whl\n")
    done, calls = run(str(downloads / "new.whl"), environment=environment)
    assert done.returncode == 0, done.stderr
    assert (old / "current").read_text().strip() == "new.whl" and not (home / ".thimbleby").exists()
    # The old environment variable still names the folder when the new one is not set.
    named = tmp_path / "named"
    done, _ = run(str(downloads / "new.whl"), environment={**environment, "COCKPIT_PACKAGES": str(named)})
    assert done.returncode == 0 and (named / "current").read_text().strip() == "new.whl"
    # With nothing from before, the current name is made.
    fresh = tmp_path / "fresh"
    done, _ = run(str(downloads / "new.whl"), environment={**environment, "HOME": str(fresh)})
    assert done.returncode == 0 and (fresh / ".thimbleby" / "packages" / "current").exists()


def test_a_copy_installed_under_the_old_package_name_is_taken_away_after_the_new_one_works(box, tmp_path):
    run, downloads, _ = box
    old_tool = tmp_path / "tools" / "pm-cockpit"
    old_tool.mkdir(parents=True)
    (old_tool / "uv-receipt.toml").write_text("")
    done, calls = run(str(downloads / "new.whl"), fails=("install",))
    assert done.returncode == 1 and old_tool.is_dir()  # a failed update leaves it as it was
    done, calls = run(str(downloads / "new.whl"))
    assert done.returncode == 0, done.stderr
    assert not old_tool.exists()
    assert not any(c.startswith("uv tool uninstall") for c in calls)  # that would remove the new copy's commands
    assert "thimbleby update-step backup --version v0.1.0" in calls  # the version is read from the old tool's name


def test_a_copy_that_cannot_be_made_stops_before_anything_is_installed(box):
    run, downloads, _ = box
    done, calls = run(str(downloads / "new.whl"), fails=("backup",))
    assert done.returncode == 1 and "Nothing was changed" in done.stderr
    assert not any(c.startswith("uv tool install") for c in calls)


def test_the_release_constraints_pin_every_library_in_the_lock(tmp_path):
    out = tmp_path / "constraints.txt"
    subprocess.run(["sh", str(DEPLOY / "constraints.sh"), str(out)], check=True, cwd=DEPLOY.parent)
    pinned = {
        line.split("==")[0].lower()
        for line in out.read_text().splitlines()
        if "==" in line and not line.startswith("#")
    }
    locked = {
        line.split('"')[1].lower()
        for line in (DEPLOY.parent / "uv.lock").read_text().splitlines()
        if line.startswith('name = "')
    }
    locked.discard("thimbleby")
    # Everything the app runs on is pinned; what the lock holds only for development is not needed in a release.
    for needed in ("fastapi", "pydantic", "uvicorn", "cryptography", "pyyaml"):
        assert needed in pinned and needed in locked
    assert "pytest" not in pinned and "ruff" not in pinned
    assert all("==" in line for line in out.read_text().splitlines() if line and not line.startswith(("#", " ")))
    workflow = (DEPLOY.parent / ".github" / "workflows" / "release.yml").read_text()
    assert (
        "deploy/constraints.sh dist/constraints.txt" in workflow and "pip install -c dist/constraints.txt" in workflow
    )
    for script in ("install.sh", "install.ps1"):
        assert "--constraints" in (DEPLOY / script).read_text()
