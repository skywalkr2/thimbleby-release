#!/bin/sh
# Installs or updates Thimbleby from a downloaded package file, then tells you how to start.
# Usage: sh install.sh thimbleby-<version>-py3-none-any.whl [constraints.txt]
# Needs uv (the Python package tool). Running it again with a newer file updates the app; workspaces are untouched
# except that an update first copies the records and, if it fails, puts the version and the records back.
# The libraries are the exact versions the release was tested with, from the constraints file that comes with it
# (by default the one beside the package file).
set -eu
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ] || [ ! -f "$1" ]; then
  echo "Usage: sh install.sh <the downloaded .whl file> [the downloaded constraints.txt]" >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "This needs uv, the Python package tool. Install it from its documentation, open a new terminal, and run this again." >&2
  exit 1
fi
package="$1"
constraints="${2:-$(dirname "$package")/constraints.txt}"
if [ ! -f "$constraints" ]; then
  echo "The constraints file that comes with this release isn't beside the package file. Download constraints.txt from the same release, put it next to the package file, and run this again." >&2
  exit 2
fi
# The packages already installed are kept here, so a failed update can put the one before back.
# The same choice as engine/legacy_names.py: the environment's folder (THIMBLEBY_PACKAGES, else the earlier name
# COCKPIT_PACKAGES), else the per-person folder, or the one an earlier version made when there is no new one.
store="${THIMBLEBY_PACKAGES:-${COCKPIT_PACKAGES:-}}"
if [ -z "$store" ]; then
  store="$HOME/.thimbleby/packages"
  if [ -d "$HOME/.pm-cockpit/packages" ] && [ ! -e "$store" ]; then store="$HOME/.pm-cockpit/packages"; fi
fi
mkdir -p "$store"
before=""
if [ -f "$store/current" ]; then before="$(cat "$store/current")"; fi
# The program already installed, which makes the copy of the records first: `thimbleby`, or `cockpit` for a version
# from before the rename. Checking and putting the records back are done by the new program, once it is installed.
installed=""
if command -v thimbleby >/dev/null 2>&1; then installed=thimbleby
elif command -v cockpit >/dev/null 2>&1; then installed=cockpit; fi
had_cockpit=no
if [ -n "$installed" ]; then had_cockpit=yes; fi

if [ "$had_cockpit" = yes ]; then
  version="$(uv tool list 2>/dev/null | awk '$1 == "thimbleby" || $1 == "pm-cockpit" { print $2; exit }')"
  if ! "$installed" update-step backup --version "${version:-unknown}"; then
    echo "Nothing was changed: the copy of your records made first couldn't be made, or the app is open. Close it, then run this again." >&2
    exit 1
  fi
fi

checked=no
if uv tool install --force --python 3.12 --constraints "$constraints" "$package" \
  && { [ "$had_cockpit" = no ] || { checked=yes; thimbleby update-step check; }; }; then
  name="$(basename "$package")"
  cp "$package" "$store/$name"
  cp "$constraints" "$store/$name.constraints.txt"
  echo "$name" > "$store/current"
  # A copy installed before the package was renamed is a second tool with the same commands. Its folder is removed here
  # directly, because `uv tool uninstall` would also remove the commands the new copy now owns.
  tool_dir="$(uv tool dir 2>/dev/null || true)"
  if [ -n "$tool_dir" ] && [ -d "$tool_dir/pm-cockpit" ]; then rm -rf "$tool_dir/pm-cockpit"; fi
else
  echo "The update didn't work, so it was not kept." >&2
  if [ "$checked" = yes ]; then
    thimbleby update-step restore && echo "Put back the copy of your records made before updating." >&2
  fi
  if [ -n "$before" ] && [ -f "$store/$before" ]; then
    echo "Putting back the version you had ($before)." >&2
    uv tool install --force --python 3.12 --constraints "$store/$before.constraints.txt" "$store/$before" >/dev/null
  fi
  exit 1
fi
uv tool update-shell >/dev/null 2>&1 || true
echo
echo "Installed. Open a new terminal, then:"
echo "  thimbleby demo                    try it on made-up data"
echo "  thimbleby                         start your workspace (made the first time) and open it"
echo "To update later, run this script again with the newer file."
