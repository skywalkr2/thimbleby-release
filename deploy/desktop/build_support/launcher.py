"""The frozen app's entry. Opened with nothing typed (a double click, the Start menu, the Applications folder), it
starts the person's workspace in the app-data folder behind the tray or menu-bar item (`engine/desktop.py`). Started at
sign-in (`--at-login`) it opens quietly. Given other arguments (a command run from a terminal), it is the `thimbleby`
command."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] and sys.argv[1:] != ["--at-login"]:
        from engine.cli import main
    else:
        from engine.desktop import main

    raise SystemExit(main())
