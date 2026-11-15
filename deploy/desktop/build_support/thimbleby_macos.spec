# Build a native application bundle with its read-only resources.
import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)
from freeze_common import freeze_inputs

root = Path(SPECPATH).parents[2]  # the repository root: this folder is deploy/desktop/build_support
inputs = freeze_inputs(root, "darwin")
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
    console=False,
    target_arch=inputs["architecture"],
    codesign_identity=None,
    entitlements_file=None,
    icon=inputs["icon"],
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Thimbleby")
app = BUNDLE(
    collection,
    name="Thimbleby.app",
    icon=inputs["icon"],
    bundle_identifier="app.thimbleby.desktop",
    info_plist={
        "CFBundleName": "Thimbleby",
        "CFBundleDisplayName": "Thimbleby",
        "CFBundleShortVersionString": inputs["numeric_version"],
        "CFBundleVersion": inputs["numeric_version"],
        "CFBundleGetInfoString": "Thimbleby " + inputs["version"],
        "LSMinimumSystemVersion": "15.0",
        "NSHighResolutionCapable": True,
        # The window shows the app served on this computer's own address.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
