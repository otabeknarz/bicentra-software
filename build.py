"""
Build Bicentra Desktop as a distributable binary.

    python build.py macos                   # full pipeline → dist/bicentra-desktop-<ver>.dmg
    python build.py macos --skip-slim       # skip the lipo/strip pass (keeps universal binary)
    python build.py macos --skip-dmg        # stop after the slimmed .app
    python build.py windows                 # → dist/bicentra-desktop-<ver>.exe

The macOS pipeline:
  1. `flet build macos` with the arch/version flags baked in.
  2. Slim pass — walk the .app, run `lipo -thin arm64` on every Mach-O fat
     binary found, then `strip -SXx` the main executable. Cuts the bundle
     roughly in half because Flet always ships x86_64 alongside arm64.
  3. `hdiutil create -format UDBZ` — bzip2 compression, ~10-20% smaller than
     the UDZO default hdiutil produces.

Version comes from `config.APP_VERSION` — bump that in one place, both the
Info.plist and the DMG filename pick it up automatically.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.resolve()

# Read version from config.py without importing (avoids Flet import at build time)
_config_src = (REPO / "config.py").read_text()
APP_VERSION = next(
    line.split("=")[1].strip().strip('"').strip("'")
    for line in _config_src.splitlines()
    if line.startswith("APP_VERSION")
)

APP_NAME = "Bicentra Desktop"
PRODUCT = APP_NAME
ORG = "ai.bicentra"
DESCRIPTION = "AI-powered pharmacy PMS automation agent"


# ─────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def _die(msg: str, code: int = 1) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)
    sys.exit(code)


def _human_size(path: Path) -> str:
    """Best-effort file/dir size in MB. Dir walks are fine for .app bundles
    (a few hundred MB) — anything bigger you'd notice being slow anyway."""
    if path.is_file():
        n = path.stat().st_size
    else:
        n = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return f"{n / 1024 / 1024:.0f} MB"


def _is_macho(p: Path) -> bool:
    """Cheap Mach-O check via the file(1) command — matches both fat and
    thin Mach-O variants, skips resource files and shell scripts."""
    try:
        out = subprocess.check_output(["file", "-b", str(p)], text=True)
    except subprocess.CalledProcessError:
        return False
    return "Mach-O" in out


def _fvm_flutter_on_path() -> None:
    """If the repo pins Flutter via fvm, prepend that SDK's bin dir to PATH
    so `flet build` picks it up. Flet 0.25.2 needs Flutter 3.24.x — the
    system-wide flutter is often newer and breaks the theme API compile."""
    fvm_sdk = REPO / ".fvm" / "flutter_sdk" / "bin"
    if fvm_sdk.exists():
        os.environ["PATH"] = f"{fvm_sdk}:{os.environ.get('PATH', '')}"
        print(f"  Using fvm-pinned Flutter at {fvm_sdk}")


# ─────────────────────────────────────────────────────────────────
# macOS pipeline
# ─────────────────────────────────────────────────────────────────

APP_BUILD_PATH = REPO / "build" / "macos" / f"{APP_NAME}.app"


# Directories inside the repo that must NOT end up inside the packaged
# Python app. Without an explicit exclude list, `flet build` snapshots
# the entire working tree — that includes our previous DMG in dist/,
# the fvm-managed Flutter SDK under .fvm/ (~700 MB), the git history,
# and the pip build cache. Left unchecked, every rebuild inflates the
# next .app by the size of the last one; two rebuilds in a row and
# the .app crosses 4 GB.
_PACKAGING_EXCLUDES = [
    "build",           # Flet's own workspace + prior .app bundles
    "dist",            # our packaged DMGs
    ".fvm",            # pinned Flutter SDK (~700 MB)
    ".git",            # repo history
    "__pypackages__",  # pip build cache
    ".vscode",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".DS_Store",
]


def _flet_build_macos() -> None:
    _fvm_flutter_on_path()
    cmd = [
        "flet", "build", "macos",
        "--arch", "arm64",
        "--clear-cache",
        "--build-version", APP_VERSION,
        "--product", PRODUCT,
        "--description", DESCRIPTION,
        "--org", ORG,
        "--skip-flutter-doctor",
        "--exclude", *_PACKAGING_EXCLUDES,
    ]
    _run(cmd)
    if not APP_BUILD_PATH.exists():
        _die(f"flet build succeeded but no .app at {APP_BUILD_PATH}")
    print(f"  ✓ .app built ({_human_size(APP_BUILD_PATH)})")


def _slim_macos_app(app_path: Path) -> None:
    """Walk every Mach-O file in the bundle and `lipo -thin arm64` it. Flet's
    --arch flag only affects the Python side of the build; the Flutter engine
    and third-party dylibs still ship universal, which nearly doubles the
    bundle. Strip the main executable's debug + local symbols on top."""

    thinned = 0
    thin_bytes_before = 0
    thin_bytes_after = 0
    skipped = 0

    for path in app_path.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if not _is_macho(path):
            continue
        try:
            arches = subprocess.check_output(
                ["lipo", "-archs", str(path)], text=True, stderr=subprocess.DEVNULL,
            ).split()
        except subprocess.CalledProcessError:
            continue
        if len(arches) < 2:
            # Already single-arch — nothing to trim.
            skipped += 1
            continue
        if "arm64" not in arches:
            print(f"    ! {path.name}: no arm64 slice, skipping")
            continue
        before = path.stat().st_size
        subprocess.run(
            ["lipo", "-thin", "arm64", str(path), "-output", str(path)],
            check=True,
        )
        after = path.stat().st_size
        thinned += 1
        thin_bytes_before += before
        thin_bytes_after += after

    saved_mb = (thin_bytes_before - thin_bytes_after) / 1024 / 1024
    print(
        f"  ✓ lipo: thinned {thinned} Mach-O files "
        f"({skipped} already single-arch), saved {saved_mb:.0f} MB"
    )

    # Strip debug + local symbols from the main executable. -S removes debug,
    # -X removes local, -x removes non-globals. Safe for a distributed app;
    # gdb won't attach either way once codesigned.
    main_exe = app_path / "Contents" / "MacOS" / APP_NAME
    if main_exe.exists():
        subprocess.run(["strip", "-SXx", str(main_exe)])
        print(f"  ✓ strip: {main_exe.name}")


def _build_dmg(app_path: Path) -> Path:
    dist = REPO / "dist"
    dist.mkdir(exist_ok=True)
    dmg = dist / f"bicentra-desktop-{APP_VERSION}.dmg"
    if dmg.exists():
        dmg.unlink()
    # UDBZ = bzip2. Slower to compress but ~10–20% smaller than UDZO (default).
    # For a 500+ MB payload that's a real difference to end users on hotel wifi.
    _run([
        "hdiutil", "create",
        "-volname", "Bicentra Desktop",
        "-srcfolder", str(app_path),
        "-ov",
        "-format", "UDBZ",
        str(dmg),
    ])
    print(f"  ✓ DMG created ({_human_size(dmg)})")
    return dmg


def build_macos(skip_slim: bool, skip_dmg: bool) -> None:
    _flet_build_macos()
    if skip_slim:
        print("  ⚠ --skip-slim: keeping universal binary + unstripped symbols")
    else:
        _slim_macos_app(APP_BUILD_PATH)
        print(f"  ✓ slimmed .app ({_human_size(APP_BUILD_PATH)})")
    if skip_dmg:
        print(f"\n  ✓ Done. .app at: {APP_BUILD_PATH}")
        return
    dmg = _build_dmg(APP_BUILD_PATH)
    print(f"\n  ✓ Done. DMG at: {dmg}  ({_human_size(dmg)})")


# ─────────────────────────────────────────────────────────────────
# Windows pipeline
# ─────────────────────────────────────────────────────────────────

def build_windows() -> None:
    _fvm_flutter_on_path()
    if platform.system() != "Windows":
        print("  ⚠ Not running on Windows — this will call flet build")
        print("    but the actual compile step requires Visual Studio 2022")
        print("    with the C++ workload installed. Cross-compilation is")
        print("    not supported by Flet 0.25.")
    cmd = [
        "flet", "build", "windows",
        "--arch", "x86_64",
        "--clear-cache",
        "--build-version", APP_VERSION,
        "--product", PRODUCT,
        "--description", DESCRIPTION,
        "--org", ORG,
        "--skip-flutter-doctor",
        "--exclude", *_PACKAGING_EXCLUDES,
    ]
    _run(cmd)
    exe = REPO / "build" / "windows" / f"{APP_NAME}.exe"
    if exe.exists():
        print(f"\n  ✓ Done. .exe at: {exe}  ({_human_size(exe)})")
    else:
        _die(f"flet build finished but no .exe at {exe}")


# ─────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────

def clean() -> None:
    for d in ("build", "dist"):
        p = REPO / d
        if p.exists():
            shutil.rmtree(p)
            print(f"  Cleaned {d}/")


# ─────────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Bicentra Desktop (Flet-based)",
    )
    parser.add_argument(
        "target",
        choices=["macos", "windows", "clean"],
        help="build target or 'clean' to wipe build/ and dist/",
    )
    parser.add_argument(
        "--skip-slim",
        action="store_true",
        help="macOS only: skip the lipo/strip pass (keeps ~2x size)",
    )
    parser.add_argument(
        "--skip-dmg",
        action="store_true",
        help="macOS only: stop after the .app, don't package a DMG",
    )
    args = parser.parse_args()

    print(f"  Bicentra Desktop v{APP_VERSION}")
    print(f"  Target: {args.target}\n")

    if args.target == "clean":
        clean()
    elif args.target == "macos":
        build_macos(skip_slim=args.skip_slim, skip_dmg=args.skip_dmg)
    elif args.target == "windows":
        build_windows()


if __name__ == "__main__":
    main()
