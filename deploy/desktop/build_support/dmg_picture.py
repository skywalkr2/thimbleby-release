"""Mount a built disk image, let the Finder open its window as a person sees it, and take a picture of the screen.

Usage: python dmg_picture.py <the .dmg> <folder for the picture>"""

from __future__ import annotations

import plistlib
import subprocess
import sys
import threading
from pathlib import Path

PICTURE = "dmg-window.png"
OPEN_SECONDS = 5


def mount_point(attach_plist: bytes) -> str:
    """The folder a mounted image appears at, from `hdiutil attach -plist`'s answer."""
    for entity in plistlib.loads(attach_plist).get("system-entities", []):
        if entity.get("mount-point"):
            return entity["mount-point"]
    raise SystemExit("The disk image did not mount")


def main(dmg: str, pictures_folder: str) -> None:
    pictures = Path(pictures_folder)
    pictures.mkdir(parents=True, exist_ok=True)
    attached = subprocess.run(["hdiutil", "attach", "-plist", dmg], capture_output=True, check=True).stdout
    mounted = mount_point(attached)
    try:
        # The window opens by itself from the image's own settings once the Finder shows the volume.
        subprocess.run(["open", mounted], check=True)
        threading.Event().wait(OPEN_SECONDS)
        subprocess.run(["screencapture", "-x", str(pictures / PICTURE)], check=True)
        print(f"took {PICTURE} of {mounted}")
    finally:
        subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to close every window'], capture_output=True, check=False
        )
        subprocess.run(["hdiutil", "detach", "-force", mounted], capture_output=True, check=False)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
