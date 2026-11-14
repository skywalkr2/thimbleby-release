# Build a Linux folder, to prove the frozen start on a Linux computer with the same freeze code. Not shipped.
import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)
from freeze_common import freeze_inputs

root = Path(SPECPATH).parents[2]  # the repository root: this folder is deploy/desktop/build_support
inputs = freeze_inputs(root, "linux")
a = Analysis(
    [str(Path(SPECPATH) / "launcher.py")],
    pathex=[str(root)],
    binaries=[],
    datas=inputs["datas"],
    hiddenimports=inputs["hiddenimports"],
    hookspath=[],
    runtime_hooks=[str(Path(SPECPATH) / "windowed_stdio.py")],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Thimbleby",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Thimbleby")
