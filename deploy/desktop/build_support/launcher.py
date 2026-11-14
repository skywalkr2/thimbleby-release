"""The frozen app's entry. Opened with nothing typed (a double click, the Start menu, the Applications folder), it
starts the person's workspace in the app-data folder behind the tray or menu-bar item (`engine/desktop.py`). Given
arguments (a command run from a terminal), it is the `thimbleby` command."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1:
        from engine.cli import main
    else:
        from engine.desktop import main

    raise SystemExit(main())
