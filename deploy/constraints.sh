#!/bin/sh
# Writes the exact versions of every library the app needs, as the tests ran on them, from the lock file.
# Usage: sh deploy/constraints.sh <where to write the constraints file>
# The release build runs this and attaches the file beside the package; install.sh and install.ps1 pass it to uv.
set -eu
if [ "$#" -ne 1 ]; then
  echo "Usage: sh deploy/constraints.sh <output file>" >&2
  exit 2
fi
uv export --frozen --no-hashes --no-emit-project --no-dev -o "$1" >/dev/null
