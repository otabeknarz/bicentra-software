"""Screen capture and mouse/keyboard automation."""

import base64
import io
import time
import platform

import pyautogui
from PIL import Image

# Safety: move mouse to top-left corner to abort
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1


def take_screenshot() -> tuple[str, int, int]:
    """Take a screenshot and return (base64_png, width, height)."""
    screenshot = pyautogui.screenshot()
    buffer = io.BytesIO()
    screenshot.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return b64, screenshot.width, screenshot.height


def get_active_window_title() -> str:
    """Get the title of the currently active window."""
    try:
        if platform.system() == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        elif platform.system() == "Darwin":
            from subprocess import run, PIPE
            result = run(
                ["osascript", "-e", 'tell application "System Events" to get name of first process whose frontmost is true'],
                capture_output=True, text=True,
            )
            return result.stdout.strip()
        else:
            return ""
    except Exception:
        return ""


def execute_action(action: dict) -> None:
    """Execute a single action from the backend."""
    action_type = action.get("action_type", "")
    delay = action.get("delay", 0.3)

    if delay > 0:
        time.sleep(delay)

    x = action.get("x")
    y = action.get("y")

    if action_type == "click":
        if x is not None and y is not None:
            pyautogui.click(x, y)

    elif action_type == "double_click":
        if x is not None and y is not None:
            pyautogui.doubleClick(x, y)

    elif action_type == "right_click":
        if x is not None and y is not None:
            pyautogui.rightClick(x, y)

    elif action_type == "type":
        # Click target first if coordinates provided
        if x is not None and y is not None:
            pyautogui.click(x, y)
            time.sleep(0.1)
        text = action.get("text", "")
        if text:
            pyautogui.typewrite(text, interval=0.02) if text.isascii() else pyautogui.write(text)

    elif action_type == "hotkey":
        keys = action.get("keys", [])
        if keys:
            pyautogui.hotkey(*keys)

    elif action_type == "scroll":
        scroll_amount = action.get("scroll_amount", 0)
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        pyautogui.scroll(scroll_amount)

    elif action_type == "wait":
        # Already waited via delay above
        pass

    elif action_type in ("done", "failed"):
        # Terminal states — nothing to execute
        pass
