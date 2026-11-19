"""Run explicit packaging steps in the build environment."""

import argparse
import hashlib
import importlib.metadata
import os
import platform
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from build_model import release_versions
from packaging.version import InvalidVersion, Version


def release_notes(changelog: str, version: str) -> str:
    """The text of a version's section of the change log: the lines under its `## <version> (<date>)` heading, up to the
    next `## ` heading. The versions are compared as versions, so `0.1.0a1` finds `## 0.1.0a1 (...)`. A version with no
    section, or an empty one, raises `ValueError` saying so, so a release is never made with empty notes. A section
    still headed `(unreleased)` is refused too: its date is set to the tag's day before the tag is made."""
    wanted = Version(version)
    found = False
    lines: list[str] = []
    for line in changelog.splitlines():
        heading = re.match(r"##\s+(\S+)(?:\s+\((.*)\))?\s*$", line)
        if heading:
            if found:
                break
            try:
                found = Version(heading.group(1)) == wanted
            except InvalidVersion:
                found = False
            if found and (heading.group(2) or "").strip().lower() == "unreleased":
                raise ValueError(
                    f"CHANGELOG.md's section for {wanted} is still headed (unreleased); set it to the tag's day first"
                )
            continue
        if found:
            lines.append(line)
    text = "\n".join(lines).strip()
    if not text:
        raise ValueError(
            f"CHANGELOG.md has no section for version {wanted}; add `## {wanted} (<date>)` and what changed"
        )
    return text + "\n"


def write_build_stamp(path: Path, env: Mapping[str, str]) -> bool:
    """Stamp the build's number and commit where the app reads them (`engine/build_info.py`), from the build service's
    run number and commit. A build with neither (one made by hand on a computer) is left unstamped, which About says."""
    number, commit = env.get("GITHUB_RUN_NUMBER", ""), env.get("GITHUB_SHA", "")
    if not number.isdigit() or int(number) < 1 or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        return False
    path.write_text(f"number: {int(number)}\ncommit: {commit[:7]}\n", encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("prepare", "notes", "dmg", "wizard-art", "hashes"))
    parser.add_argument("--out", help="notes: the file to write the release notes to")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]  # the repository root
    if args.step == "prepare":
        # A build started by hand from the Actions tab has no tag: it is the version the package says.
        tag = os.environ.get("RELEASE_TAG") or "v" + importlib.metadata.version("thimbleby")
        version, numeric = release_versions(tag)
        with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
            output.write(f"APP_VERSION={version}\nWINDOWS_VERSION={numeric}\n")
        write_build_stamp(root / "catalog" / "build.yaml", os.environ)
    elif args.step == "notes":
        # Runs before anything is built, so a tag with no section in the change log stops there.
        try:
            version, _ = release_versions(os.environ.get("RELEASE_TAG", ""))
            notes = release_notes((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
        except (ValueError, OSError) as error:
            raise SystemExit(str(error)) from error
        Path(args.out).write_text(notes, encoding="utf-8")
    elif args.step == "dmg":
        if platform.system() != "Darwin":
            raise SystemExit("Create a disk image on a native macOS builder")
        version, _ = release_versions("v" + os.environ["APP_VERSION"])
        architecture = platform.machine().lower()
        if architecture not in {"arm64", "x86_64"}:
            raise SystemExit("Unknown build architecture")
        app = root / "dist" / "Thimbleby.app"
        if not app.is_dir():
            raise SystemExit("The application bundle is missing")
        sys.path.insert(0, str(root))  # the checkout's own brand files, as the freeze does
        import dmg_settings
        import dmgbuild

        from engine import installer_art

        background, _ = installer_art.write_dmg_background(root / "build" / "dmg-art", dmg_settings.LINES)
        destination = root / "dist" / f"Thimbleby-{version}-macos-{architecture}.dmg"
        destination.unlink(missing_ok=True)
        dmgbuild.build_dmg(
            str(destination),
            dmg_settings.volume_name(version),
            settings={**dmg_settings.settings(app.name, background), "files": [str(app)]},
        )
    elif args.step == "wizard-art":
        sys.path.insert(0, str(root))
        from engine import installer_art

        version, _ = release_versions("v" + os.environ["APP_VERSION"])
        installer_art.write_wizard_images(root / "build" / "installer", "Thimbleby", f"Version {version}")
    else:
        artifacts = sorted(
            path for path in (root / "dist").iterdir() if path.suffix in {".dmg", ".exe"} and path.is_file()
        )
        if not artifacts:
            raise SystemExit("No installer artifacts were created")
        lines = []
        for artifact in artifacts:
            with artifact.open("rb") as payload:
                checksum = hashlib.file_digest(payload, "sha256").hexdigest()
            lines.append(f"{checksum}  {artifact.name}\n")
        (root / "dist" / "SHA256SUMS.txt").write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
