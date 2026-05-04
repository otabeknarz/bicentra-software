"""
Cross-platform window/app enumeration and focus.

Public API:
    list_apps() -> list[dict]   # [{name, pid?}]
    focus_app(name) -> bool     # bring app to front
    get_active_app() -> str     # name of frontmost app
"""

import platform
import subprocess
import time

SYSTEM = platform.system()


# ─────────────────────────────────────────────────
# macOS
# ─────────────────────────────────────────────────

_LIST_APPS_OSASCRIPT = r'''
tell application "System Events"
    set procNames to name of every process whose background only is false
end tell
return procNames
'''

_GET_FRONTMOST_OSASCRIPT = r'''
tell application "System Events"
    return name of first process whose frontmost is true
end tell
'''


def _list_apps_macos() -> list[dict]:
    try:
        result = subprocess.run(
            ["osascript", "-e", _LIST_APPS_OSASCRIPT],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        # Output is comma-separated: "App1, App2, App3"
        names = [n.strip() for n in result.stdout.strip().split(",") if n.strip()]
        return [{"name": n} for n in sorted(set(names))]
    except Exception:
        return []


def _focus_app_macos(name: str) -> bool:
    try:
        # Escape quotes to avoid AppleScript injection
        safe_name = name.replace('"', '\\"')
        script = f'tell application "{safe_name}" to activate'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_active_app_macos() -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", _GET_FRONTMOST_OSASCRIPT],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────
# Windows
# ─────────────────────────────────────────────────

def _list_apps_windows() -> list[dict]:
    try:
        import pygetwindow as gw
    except ImportError:
        return []

    apps: dict[str, dict] = {}
    try:
        for w in gw.getAllWindows():
            title = (w.title or "").strip()
            if not title or not w.visible:
                continue
            # On Windows, the window title often is "AppName - DocName" or just "AppName"
            # We use the first segment as the app name heuristic
            key = title.split(" - ")[-1] or title  # keep most stable part
            apps[title] = {"name": title}
    except Exception:
        pass
    return sorted(apps.values(), key=lambda x: x["name"].lower())


def _focus_app_windows(name: str) -> bool:
    try:
        import pygetwindow as gw
    except ImportError:
        return False

    try:
        # Try exact match first
        wins = gw.getWindowsWithTitle(name)
        if not wins:
            # Fuzzy match
            for w in gw.getAllWindows():
                if name.lower() in (w.title or "").lower():
                    wins = [w]
                    break
        if not wins:
            return False
        w = wins[0]
        try:
            if w.isMinimized:
                w.restore()
        except Exception:
            pass
        w.activate()
        return True
    except Exception:
        return False


def _get_active_app_windows() -> str:
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


# ─────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────

def list_apps() -> list[dict]:
    """Return a list of running apps with visible windows."""
    if SYSTEM == "Darwin":
        return _list_apps_macos()
    if SYSTEM == "Windows":
        return _list_apps_windows()
    return []


def focus_app(name: str, wait_after: float = 0.4) -> bool:
    """Bring the specified app to the foreground. Returns True on success."""
    if not name:
        return False
    ok = False
    if SYSTEM == "Darwin":
        ok = _focus_app_macos(name)
    elif SYSTEM == "Windows":
        ok = _focus_app_windows(name)
    if ok and wait_after > 0:
        time.sleep(wait_after)  # give the window time to come forward
    return ok


def get_active_app() -> str:
    """Return the name of the currently frontmost app/window."""
    if SYSTEM == "Darwin":
        return _get_active_app_macos()
    if SYSTEM == "Windows":
        return _get_active_app_windows()
    return ""
