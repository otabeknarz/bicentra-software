"""
Build Bicentra Desktop as a standalone app.

Usage:
    python build.py          # Build for current platform
    python build.py --clean  # Clean build artifacts first
"""

import subprocess
import sys
import platform
import shutil
import os

APP_NAME = "Bicentra Desktop"
ENTRY = "main.py"
ICON_WIN = "icon.ico"   # Place icon.ico for Windows builds
ICON_MAC = "icon.icns"  # Place icon.icns for macOS builds


def clean():
    for d in ("build", "dist"):
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"  Cleaned {d}/")
    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)
            print(f"  Cleaned {f}")


def build():
    system = platform.system()
    print(f"  Building for {system}...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--add-data", f"config.py{os.pathsep}.",
    ]

    # Platform-specific icon
    if system == "Windows" and os.path.exists(ICON_WIN):
        cmd += ["--icon", ICON_WIN]
    elif system == "Darwin" and os.path.exists(ICON_MAC):
        cmd += ["--icon", ICON_MAC]

    # Hidden imports that PyInstaller might miss
    cmd += [
        "--hidden-import", "customtkinter",
        "--hidden-import", "pyautogui",
        "--hidden-import", "PIL",
    ]

    # Collect customtkinter data files
    cmd += [
        "--collect-all", "customtkinter",
    ]

    cmd.append(ENTRY)

    print(f"  Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        if system == "Windows":
            print(f"\n  ✓ Built: dist/{APP_NAME}.exe")
        elif system == "Darwin":
            print(f"\n  ✓ Built: dist/{APP_NAME}.app")
        else:
            print(f"\n  ✓ Built: dist/{APP_NAME}")
    else:
        print(f"\n  ✗ Build failed (exit code {result.returncode})")
        sys.exit(1)


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean()
    build()
