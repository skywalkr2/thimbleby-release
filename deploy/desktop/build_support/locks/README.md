The hashed dependency locks the desktop build installs with `pip install --require-hashes`: one per build target
(`macos-arm64.txt`, `macos-x86_64.txt`, `windows-x64.txt`), and `linux-x64.txt`, which is only for trying the frozen start on a
Linux computer (see the folder above's README). Each holds the app's runtime libraries, the `desktop` extra (tray and
icon), the build backend the source install needs, PyInstaller at its pin, `dmgbuild` (Mac locks only; it lays out the disk image window), and every library they need, at exact versions with
SHA-256 hashes. A lock is made for its own system and for Python 3.13 (the workflow's pinned interpreter); each carries the
command that made it. Make them again, from the repository root, after changing `pyproject.toml`'s dependencies or
`requirements-build.in`:

```text
uv pip compile pyproject.toml deploy/desktop/build_support/requirements-build.in --extra desktop --generate-hashes \
  --python-version 3.13 --python-platform <target> -o deploy/desktop/build_support/locks/<name>.txt
```

with `<target>` and `<name>`: `aarch64-apple-darwin` and `macos-arm64`; `x86_64-apple-darwin` and `macos-x86_64`;
`x86_64-pc-windows-msvc` and `windows-x64`; `x86_64-unknown-linux-gnu` and `linux-x64`.
