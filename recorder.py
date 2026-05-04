"""
Records mouse + keyboard input, then converts them into a flow.

Smart aggregation:
- Rapid character typing → single `type` step
- Single special keys (tab, enter, esc, arrows) → `key` step
- Modifier + key (ctrl+s, cmd+shift+p) → `hotkey` step
- Left clicks → `click_pct`
- Right clicks → `right_click_pct`
- Two consecutive clicks at same position within DOUBLE_CLICK_WINDOW → `double_click_pct`
- Mouse wheel scrolls → `scroll`, consecutive scrolls aggregate
- Long pauses (>1.5s) between actions → optional `wait` step
"""

import time
import threading
from dataclasses import dataclass
from typing import Callable

import pyautogui
from pynput import mouse, keyboard

import windows as win_mod


SPECIAL_KEYS = {
    keyboard.Key.tab: "tab",
    keyboard.Key.enter: "enter",
    keyboard.Key.esc: "esc",
    keyboard.Key.space: "space",
    keyboard.Key.backspace: "backspace",
    keyboard.Key.delete: "delete",
    keyboard.Key.up: "up",
    keyboard.Key.down: "down",
    keyboard.Key.left: "left",
    keyboard.Key.right: "right",
    keyboard.Key.home: "home",
    keyboard.Key.end: "end",
    keyboard.Key.page_up: "pageup",
    keyboard.Key.page_down: "pagedown",
    keyboard.Key.f1: "f1", keyboard.Key.f2: "f2", keyboard.Key.f3: "f3",
    keyboard.Key.f4: "f4", keyboard.Key.f5: "f5", keyboard.Key.f6: "f6",
    keyboard.Key.f7: "f7", keyboard.Key.f8: "f8", keyboard.Key.f9: "f9",
    keyboard.Key.f10: "f10", keyboard.Key.f11: "f11", keyboard.Key.f12: "f12",
}

MODIFIER_KEYS = {
    keyboard.Key.ctrl: "ctrl", keyboard.Key.ctrl_l: "ctrl", keyboard.Key.ctrl_r: "ctrl",
    keyboard.Key.shift: "shift", keyboard.Key.shift_l: "shift", keyboard.Key.shift_r: "shift",
    keyboard.Key.alt: "alt", keyboard.Key.alt_l: "alt", keyboard.Key.alt_r: "alt",
    keyboard.Key.cmd: "cmd", keyboard.Key.cmd_l: "cmd", keyboard.Key.cmd_r: "cmd",
}

# Stop recording with cmd/ctrl+shift+esc
STOP_HOTKEY_KEYS = {"cmd", "shift"}
STOP_TRIGGER_KEY = keyboard.Key.esc

# Two clicks within this window → double-click
DOUBLE_CLICK_WINDOW = 0.35  # seconds
DOUBLE_CLICK_PIXEL_TOLERANCE = 6  # px

# Aggregate consecutive scrolls within this gap
SCROLL_AGGREGATE_WINDOW = 0.6  # seconds


@dataclass
class RecordedEvent:
    timestamp: float
    kind: str   # 'click' | 'right_click' | 'double_click' | 'type' | 'key' | 'hotkey' | 'scroll'
    data: dict


class Recorder:
    def __init__(self, on_stop: Callable | None = None):
        self.on_stop = on_stop
        self.events: list[RecordedEvent] = []
        self.running = False

        self._mouse_listener = None
        self._keyboard_listener = None

        self._active_modifiers: set[str] = set()
        self._pending_text: list[str] = []
        self._last_type_time = 0.0
        self._lock = threading.Lock()

        self.screen_width = 0
        self.screen_height = 0
        self.target_app_name = ""

    # ──────────── Public API ────────────
    def start(self):
        if self.running:
            return
        self.screen_width, self.screen_height = pyautogui.size()
        self.events = []
        self.running = True

        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self._flush_pending_text()
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        self._mouse_listener = None
        self._keyboard_listener = None
        if self.on_stop:
            try:
                self.on_stop()
            except Exception:
                pass

    def get_flow_steps(self) -> list[dict]:
        """Convert recorded events into a flow step list."""
        steps: list[dict] = []
        prev_time = None

        for ev in self.events:
            # Optional wait step for long gaps (>1.5s)
            if prev_time is not None and (ev.timestamp - prev_time) > 1.5:
                steps.append({
                    "action": "wait",
                    "delay": round(min(ev.timestamp - prev_time, 3.0), 2),
                })
            prev_time = ev.timestamp

            if ev.kind == "click":
                steps.append(self._click_step("click_pct", ev))
            elif ev.kind == "right_click":
                steps.append(self._click_step("right_click_pct", ev))
            elif ev.kind == "double_click":
                steps.append(self._click_step("double_click_pct", ev))
            elif ev.kind == "scroll":
                steps.append({
                    "action": "scroll",
                    "x": round(ev.data["x"] / self.screen_width, 4),
                    "y": round(ev.data["y"] / self.screen_height, 4),
                    "scroll_amount": ev.data["amount"],
                })
            elif ev.kind == "type":
                steps.append({"action": "type", "text": ev.data["text"]})
            elif ev.kind == "key":
                steps.append({"action": "key", "key": ev.data["key"]})
            elif ev.kind == "hotkey":
                steps.append({"action": "hotkey", "keys": ev.data["keys"]})

        return steps

    def _click_step(self, action: str, ev: RecordedEvent) -> dict:
        return {
            "action": action,
            "x": round(ev.data["x"] / self.screen_width, 4),
            "y": round(ev.data["y"] / self.screen_height, 4),
        }

    # ──────────── Mouse handlers ────────────
    def _on_click(self, x: int, y: int, button, pressed: bool):
        if not self.running or not pressed:
            return

        # Map button → kind
        if button == mouse.Button.left:
            kind = "click"
        elif button == mouse.Button.right:
            kind = "right_click"
        else:
            return  # ignore middle, etc.

        with self._lock:
            self._capture_target_app_if_needed()
            self._flush_pending_text()

            now = time.time()

            # Promote to double-click if last event was a left-click at almost the same place, recent
            if (
                kind == "click"
                and self.events
                and self.events[-1].kind == "click"
                and (now - self.events[-1].timestamp) < DOUBLE_CLICK_WINDOW
                and abs(self.events[-1].data["x"] - x) <= DOUBLE_CLICK_PIXEL_TOLERANCE
                and abs(self.events[-1].data["y"] - y) <= DOUBLE_CLICK_PIXEL_TOLERANCE
            ):
                # Replace previous click with a double_click at the same coords
                self.events[-1] = RecordedEvent(
                    timestamp=now, kind="double_click", data={"x": x, "y": y},
                )
                return

            self.events.append(RecordedEvent(
                timestamp=now, kind=kind, data={"x": x, "y": y},
            ))

    def _on_scroll(self, x: int, y: int, dx: int, dy: int):
        if not self.running:
            return
        # Vertical scroll only for v1; dy positive = up, negative = down
        if dy == 0:
            return
        with self._lock:
            self._capture_target_app_if_needed()
            self._flush_pending_text()

            now = time.time()
            # Aggregate consecutive scrolls at roughly the same place
            if (
                self.events
                and self.events[-1].kind == "scroll"
                and (now - self.events[-1].timestamp) < SCROLL_AGGREGATE_WINDOW
                and abs(self.events[-1].data["x"] - x) <= 50
                and abs(self.events[-1].data["y"] - y) <= 50
            ):
                self.events[-1].data["amount"] += dy
                self.events[-1].timestamp = now
                return

            self.events.append(RecordedEvent(
                timestamp=now, kind="scroll",
                data={"x": x, "y": y, "amount": dy},
            ))

    def _capture_target_app_if_needed(self):
        if not self.target_app_name:
            try:
                active = win_mod.get_active_app()
                if active and active != "Python":
                    self.target_app_name = active
            except Exception:
                pass

    # ──────────── Keyboard handlers ────────────
    def _on_press(self, key):
        if not self.running:
            return

        if key in MODIFIER_KEYS:
            self._active_modifiers.add(MODIFIER_KEYS[key])
            return

        with self._lock:
            # Global stop hotkey
            if (key == STOP_TRIGGER_KEY
                    and STOP_HOTKEY_KEYS.issubset(self._active_modifiers)):
                threading.Thread(target=self.stop, daemon=True).start()
                return

            if self._active_modifiers:
                self._capture_target_app_if_needed()
                self._flush_pending_text()
                key_name = self._key_to_string(key)
                if key_name:
                    combo = sorted(self._active_modifiers) + [key_name]
                    self.events.append(RecordedEvent(
                        timestamp=time.time(), kind="hotkey",
                        data={"keys": combo},
                    ))
                return

            if key in SPECIAL_KEYS:
                self._capture_target_app_if_needed()
                self._flush_pending_text()
                self.events.append(RecordedEvent(
                    timestamp=time.time(), kind="key",
                    data={"key": SPECIAL_KEYS[key]},
                ))
                return

            try:
                char = key.char
                if char is not None:
                    self._capture_target_app_if_needed()
                    if self._pending_text and (time.time() - self._last_type_time) > 2.0:
                        self._flush_pending_text()
                    self._pending_text.append(char)
                    self._last_type_time = time.time()
            except AttributeError:
                pass

    def _on_release(self, key):
        if key in MODIFIER_KEYS:
            self._active_modifiers.discard(MODIFIER_KEYS[key])

    # ──────────── Helpers ────────────
    def _flush_pending_text(self):
        if self._pending_text:
            text = "".join(self._pending_text)
            self.events.append(RecordedEvent(
                timestamp=self._last_type_time or time.time(),
                kind="type", data={"text": text},
            ))
            self._pending_text = []

    def _key_to_string(self, key) -> str | None:
        if key in SPECIAL_KEYS:
            return SPECIAL_KEYS[key]
        try:
            return key.char.lower() if key.char else None
        except AttributeError:
            return None
