"""Build a single-file binary for the current platform with PyInstaller.

PyInstaller cannot cross-compile — run on each OS you want a binary for.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENTRY = HERE / "widget.py"
DIST = HERE / "dist"
BUILD_TMP = HERE / "build"
SPEC = HERE / "claude-widget.spec"


def _platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _write_icon() -> Path:
    import mascot
    if sys.platform.startswith("win"):
        path = HERE / "claude-widget.ico"
        path.write_bytes(mascot.to_ico_bytes())
    elif sys.platform == "darwin":
        path = HERE / "claude-widget.icns"
        try:
            mascot.build(512).save(path, format="ICNS")
        except (OSError, KeyError):
            path = HERE / "claude-widget.png"
            mascot.build(512).save(path, format="PNG")
    else:
        path = HERE / "claude-widget.png"
        mascot.build(512).save(path, format="PNG")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", action="store_true", help="show console window (debug builds)")
    parser.add_argument("--clean", action="store_true", help="wipe build/ dist/ first")
    args = parser.parse_args()

    if args.clean:
        for p in (DIST, BUILD_TMP, SPEC):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                p.unlink(missing_ok=True)

    icon_path = _write_icon()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name", "claude-widget",
        "--icon", str(icon_path),
        "--distpath", str(DIST),
        "--workpath", str(BUILD_TMP),
        "--specpath", str(HERE),
    ]
    for mod in (
        "test", "pydoc_data", "unittest", "lib2to3",
        "pytest", "setuptools", "pip", "wheel",
        "numpy", "scipy", "pandas", "matplotlib", "IPython", "tornado",
    ):
        cmd.extend(["--exclude-module", mod])
    # pystray's per-OS backend is dynamically imported; declare it for PyInstaller
    cmd.extend(["--collect-submodules", "pystray"])
    backend = {
        "win32": "pystray._win32",
        "darwin": "pystray._darwin",
    }.get(sys.platform, "pystray._appindicator")
    cmd.extend(["--hidden-import", backend])
    if not args.console:
        cmd.append("--windowed")
    cmd.append(str(ENTRY))

    print("> " + " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(HERE))
    if rc != 0:
        print(f"\nbuild failed with exit code {rc}", file=sys.stderr)
        return rc

    target = DIST / ("claude-widget.exe" if sys.platform.startswith("win") else "claude-widget")
    if target.exists():
        size_mb = target.stat().st_size / (1024 * 1024)
        print(f"\nbuilt {target}  ({size_mb:.1f} MB, platform={_platform_name()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
