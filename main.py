"""
Bicentra Desktop — AI-powered pharmacy PMS automation agent (Flet GUI).

Cross-platform: Windows, macOS, Linux.

Usage:
    python main.py
"""

import json
import os
import threading
import time
import flet as ft

import config
from config import logger

# Local store for remembering last-used input values per flow
_INPUT_STORE_PATH = os.path.join(os.path.expanduser("~"), ".bicentra", "input_values.json")


def _load_input_store() -> dict:
    try:
        with open(_INPUT_STORE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_input_store(store: dict):
    try:
        os.makedirs(os.path.dirname(_INPUT_STORE_PATH), exist_ok=True)
        with open(_INPUT_STORE_PATH, "w") as f:
            json.dump(store, f)
    except Exception:
        pass
from api_client import BicentraAPI
from automation import take_screenshot_bytes, execute_action
from video import build_slideshow
from recorder import Recorder
import windows as win_mod
import system_info as sysinfo
import settings_store
import ui

PMS_OPTIONS = [
    ("pioneer_rx", "PioneerRx"),
    ("best_rx", "BestRx"),
    ("framework_ltc", "Framework LTC"),
    ("liberty", "Liberty Software"),
    ("prime_rx", "PrimeRx"),
]


def main(page: ft.Page):
    page.title = "Bicentra Desktop"
    page.window.width = 600
    page.window.height = 820
    page.window.min_width = 500
    page.window.min_height = 700
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = "#f8fafc"

    # Shared state (bag of references)
    state = {"api": None, "view": None}

    # ─────────────────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────────────────
    def go_login():
        page.controls.clear()
        page.add(LoginView(page, on_login))
        page.update()

    def go_main():
        page.controls.clear()
        main_view = MainView(page, state["api"], on_logout=go_login)
        state["view"] = main_view
        page.add(main_view.build())
        page.update()
        main_view.load_flows_async()

    def on_login(api: BicentraAPI):
        state["api"] = api
        go_main()

    # ─────────────────────────────────────────────────────────
    # Startup — try restore session
    # ─────────────────────────────────────────────────────────
    splash = ft.Container(
        content=ft.Column(
            [
                ft.Text("Bicentra Desktop", size=24, weight=ft.FontWeight.BOLD),
                ft.ProgressRing(width=24, height=24, stroke_width=2),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
        ),
        alignment=ft.alignment.center,
        expand=True,
    )
    page.add(splash)
    page.update()

    def try_restore():
        api = BicentraAPI()
        try:
            restored = api.restore_session()
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            restored = False

        if restored:
            state["api"] = api
            go_main()
        else:
            go_login()

    threading.Thread(target=try_restore, daemon=True).start()


# ════════════════════════════════════════════════════════════
# Login
# ════════════════════════════════════════════════════════════

class LoginView(ft.Container):
    def __init__(self, page: ft.Page, on_login):
        super().__init__()
        self.page = page
        self.on_login = on_login

        self.email_field = ft.TextField(
            label="Email", hint_text="you@pharmacy.com",
            border_radius=8, height=48,
        )
        self.password_field = ft.TextField(
            label="Password", password=True, can_reveal_password=True,
            border_radius=8, height=48,
            on_submit=lambda e: self._login(),
        )
        self.error_text = ft.Text("", color="#dc2626", size=12)
        self.login_btn = ft.ElevatedButton(
            "Sign In", on_click=lambda e: self._login(),
            height=44, expand=True,
            style=ft.ButtonStyle(
                bgcolor="#2563eb", color="white",
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        mode = "BETA" if config.DEBUG else "PRODUCTION"

        self.content = ft.Column(
            [
                ft.Container(height=40),
                ft.Text("Bicentra Desktop", size=28, weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER),
                ft.Text("AI Pharmacy PMS Automation", size=13, color="#6b7280",
                        text_align=ft.TextAlign.CENTER),
                ft.Container(height=30),
                ft.Container(
                    content=ft.Column([
                        self.email_field,
                        ft.Container(height=8),
                        self.password_field,
                        ft.Container(height=16),
                        ft.Row([self.login_btn]),
                        ft.Container(height=6),
                        self.error_text,
                    ]),
                    padding=ft.padding.symmetric(horizontal=40),
                ),
                ft.Container(expand=True),
                ft.Text(f"{mode}  •  {config.API_BASE_URL}",
                        size=10, color="#9ca3af", text_align=ft.TextAlign.CENTER),
                ft.Container(height=16),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        )
        self.expand = True
        self.bgcolor = "white"

    def _login(self):
        email = self.email_field.value.strip() if self.email_field.value else ""
        password = self.password_field.value.strip() if self.password_field.value else ""
        if not email or not password:
            self.error_text.value = "Please enter email and password"
            self.update()
            return

        self.login_btn.disabled = True
        self.login_btn.text = "Signing in..."
        self.error_text.value = ""
        self.update()

        def do_login():
            api = BicentraAPI()
            if api.login(email, password):
                self.on_login(api)
            else:
                self.login_btn.disabled = False
                self.login_btn.text = "Sign In"
                self.error_text.value = "Invalid email or password"
                self.update()

        threading.Thread(target=do_login, daemon=True).start()


# ════════════════════════════════════════════════════════════
# Main view (tabs: Run / Record)
# ════════════════════════════════════════════════════════════

class MainView:
    def __init__(self, page: ft.Page, api: BicentraAPI, on_logout):
        self.page = page
        self.api = api
        self.on_logout = on_logout

        # Navigation
        self._active_page = "run"
        # Sidebar is fully hidden by default — hamburger reveals it
        self._sidebar_open = False

        # State for flows
        self.flows: list[dict] = []
        self.flow_search_text = ""
        self.selected_flow: dict | None = None
        self.running = False
        self.session_id: str | None = None
        # In-memory cache of (step_number, png_bytes) for slideshow video
        self._step_screenshots: list[tuple[int, bytes]] = []
        self._max_screenshots = 200

        # Recording state
        self.recording = False
        self.recorder: Recorder | None = None

        # Manage state
        self.managed_flows: list[dict] = []

        # History state
        self.history_sessions: list[dict] = []
        self.history_page: int = 1
        self.history_page_size: int = 25
        self.history_total: int = 0
        self.history_has_next: bool = False
        self.history_has_prev: bool = False
        self.history_filter_status: str = ""
        self.history_filter_flow: str = ""
        self.history_query: str = ""
        self._history_search_handle = None

        # AI Workflow state (chat-style)
        self.workflow: dict | None = None     # latest workflow detail dict
        self.workflow_readonly: bool = False  # True when viewing a past workflow
        self.ai_running: bool = False         # is a workflow currently executing
        self._workflow_sse_thread = None      # background SSE consumer
        self._workflow_step_threads: list = []  # background run_flow runners
        self._ai_step_bubbles: dict[str, ft.Container] = {}  # step_id -> live bubble
        # Conversation widgets
        self.ai_input: ft.TextField | None = None
        self.ai_send_btn = None
        self.ai_stop_btn = None
        self.ai_recent_btn = None
        self.ai_new_chat_btn = None
        self.ai_conversation: ft.ListView | None = None
        self.ai_header_indicator: ft.Container | None = None  # "Bicentra is thinking…"

        # ── Widgets (will build on build()) ──
        # Header / sidebar
        self.sidebar_container: ft.Container | None = None
        self.nav_buttons: dict[str, ft.Container] = {}
        # Page containers
        self.ai_container: ft.Container | None = None
        self.run_container: ft.Container | None = None
        self.record_container: ft.Container | None = None
        self.manage_container: ft.Container | None = None
        self.manage_list: ft.Column | None = None
        self.manage_status: ft.Text | None = None
        # History tab widgets
        self.history_container: ft.Container | None = None
        self.history_list: ft.Column | None = None
        self.history_status: ft.Text | None = None
        self.history_search: ft.TextField | None = None
        self.history_status_dropdown: ft.Dropdown | None = None
        self.history_pagination_label: ft.Text | None = None
        self.history_prev_btn: ft.IconButton | None = None
        self.history_next_btn: ft.IconButton | None = None
        # Settings tab widgets
        self.settings_container: ft.Container | None = None
        self.settings_tier_dropdown: ft.Dropdown | None = None
        self.settings_status: ft.Text | None = None
        self._about_copy_btn: ft.OutlinedButton | None = None

        # Run tab widgets
        self.flow_search_field: ft.TextField | None = None
        self.flow_list_column: ft.Column | None = None  # search results
        self.flow_form_panel: ft.Container | None = None  # selected flow form
        self.inputs_column: ft.Column | None = None
        self.input_fields: dict[str, ft.Control] = {}  # any widget with .value
        self.run_btn: ft.ElevatedButton | None = None
        self.stop_btn: ft.ElevatedButton | None = None
        self.status_text: ft.Text | None = None
        self.log_view: ft.ListView | None = None
        self.copy_btn: ft.IconButton | None = None
        self.run_idle_view: ft.Container | None = None  # shown when no flow selected
        self.run_active_view: ft.Container | None = None  # shown when flow selected

        # Record tab widgets
        self.rec_pms: ft.Dropdown | None = None  # PMS picker lives inside Record tab now
        self.rec_pms_value: str = PMS_OPTIONS[0][0] if PMS_OPTIONS else "pioneer_rx"
        self.rec_name: ft.TextField | None = None
        self.rec_display: ft.TextField | None = None
        self.rec_desc: ft.TextField | None = None
        self.rec_btn: ft.ElevatedButton | None = None
        self.rec_status: ft.Text | None = None
        self.rec_event_count: ft.Text | None = None

    # ─────────────────────────────────────────────────────────
    # Build
    # ─────────────────────────────────────────────────────────
    def build(self) -> ft.Control:
        header = self._build_header()
        self.sidebar_container = self._build_sidebar()

        # Build all page contents (only the active one is visible at a time)
        self.ai_container = self._build_ai_tab()
        self.run_container = self._build_run_tab()
        self.record_container = self._build_record_tab()
        self.manage_container = self._build_manage_tab()
        self.history_container = self._build_history_tab()
        self.settings_container = self._build_settings_tab()
        # Initial visibility — Run is the home page
        self.ai_container.visible = False
        self.record_container.visible = False
        self.manage_container.visible = False
        self.history_container.visible = False
        self.settings_container.visible = False

        body_content = ft.Container(
            content=ft.Column(
                [
                    self.ai_container,
                    self.run_container,
                    self.record_container,
                    self.manage_container,
                    self.history_container,
                    self.settings_container,
                ],
                spacing=0,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
            padding=ft.padding.symmetric(horizontal=ui.SPACE_5, vertical=ui.SPACE_4),
            expand=True,
            bgcolor=ui.BG,
        )

        # Header sits at the top; sidebar + content sit in a row below it
        main_row = ft.Row(
            [self.sidebar_container, body_content],
            spacing=0,
            expand=True,
        )

        return ft.Column([header, main_row], spacing=0, expand=True)

    # ─────────────────────────────────────────────────────────
    # Header
    # ─────────────────────────────────────────────────────────
    def _build_header(self) -> ft.Container:
        hamburger = ui.icon_button(
            icon=ft.Icons.MENU,
            on_click=lambda e: self._toggle_sidebar(),
            tooltip="Toggle menu",
            size=20,
            color=ui.TEXT_SECONDARY,
        )
        logo = ft.Image(
            src="/bicentra-logo.svg",
            height=24,
            fit=ft.ImageFit.CONTAIN,
            error_content=ft.Text(
                "Bicentra",
                size=ui.FONT_LG,
                weight=ft.FontWeight.W_700,
                color=ui.TEXT_PRIMARY,
            ),
        )

        email_text = ft.Text(
            self.api.email or "",
            size=ui.FONT_BASE,
            color=ui.TEXT_MUTED,
        )

        logout_btn = ui.ghost_button(
            text="Logout",
            on_click=lambda e: self._confirm_logout(),
            icon=ft.Icons.LOGOUT,
            color=ui.TEXT_SECONDARY,
        )

        return ft.Container(
            content=ft.Row(
                [
                    hamburger,
                    ft.Container(width=ui.SPACE_2),
                    logo,
                    ft.Container(expand=True),
                    email_text,
                    ft.Container(width=ui.SPACE_3),
                    logout_btn,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=ui.SPACE_4, vertical=ui.SPACE_2),
            bgcolor=ui.SURFACE,
            border=ft.border.only(bottom=ft.BorderSide(1, ui.BORDER)),
        )

    # ─────────────────────────────────────────────────────────
    # Sidebar
    # ─────────────────────────────────────────────────────────
    _NAV_ITEMS = [
        ("ai", "AI Workflow", ft.Icons.AUTO_AWESOME_OUTLINED),
        ("run", "Run", ft.Icons.PLAY_ARROW_OUTLINED),
        ("record", "Record", ft.Icons.FIBER_MANUAL_RECORD_OUTLINED),
        ("manage", "Manage", ft.Icons.LIST_ALT_OUTLINED),
        ("history", "History", ft.Icons.HISTORY),
        ("settings", "Settings", ft.Icons.SETTINGS_OUTLINED),
    ]

    def _build_sidebar(self) -> ft.Container:
        items = []
        for key, label, icon in self._NAV_ITEMS:
            btn = self._build_nav_item(key, label, icon)
            self.nav_buttons[key] = btn
            items.append(btn)

        return ft.Container(
            content=ft.Column(
                items,
                spacing=ui.SPACE_1,
                expand=True,
            ),
            padding=ft.padding.symmetric(horizontal=ui.SPACE_2, vertical=ui.SPACE_3),
            width=220,
            bgcolor=ui.SURFACE,
            border=ft.border.only(right=ft.BorderSide(1, ui.BORDER)),
            visible=self._sidebar_open,
        )

    def _build_nav_item(self, key: str, label: str, icon: str) -> ft.Container:
        is_active = key == self._active_page
        bg = ui.ACCENT_SUBTLE if is_active else "transparent"
        fg = ui.ACCENT if is_active else ui.TEXT_SECONDARY

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=18, color=fg),
                    ft.Text(
                        label,
                        size=ui.FONT_MD,
                        color=fg,
                        weight=ft.FontWeight.W_500 if is_active else ft.FontWeight.W_400,
                    ),
                ],
                spacing=ui.SPACE_3,
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=ui.SPACE_3, vertical=ui.SPACE_3),
            bgcolor=bg,
            border_radius=ui.RADIUS_MD,
            on_click=lambda e, k=key: self._on_nav_change(k),
            ink=True,
        )

    def _refresh_sidebar(self):
        """Re-render sidebar contents in place (after toggle or nav change)."""
        if not self.sidebar_container:
            return
        # Rebuild nav buttons so the active highlight follows _active_page
        self.nav_buttons.clear()
        items = []
        for key, label, icon in self._NAV_ITEMS:
            btn = self._build_nav_item(key, label, icon)
            self.nav_buttons[key] = btn
            items.append(btn)
        self.sidebar_container.content = ft.Column(
            items,
            spacing=ui.SPACE_1,
            expand=True,
        )
        self.sidebar_container.visible = self._sidebar_open
        self.page.update()

    def _toggle_sidebar(self):
        self._sidebar_open = not self._sidebar_open
        self._refresh_sidebar()

    def _on_nav_change(self, key: str):
        self._active_page = key
        # Toggle visibility
        self.ai_container.visible = key == "ai"
        self.run_container.visible = key == "run"
        self.record_container.visible = key == "record"
        self.manage_container.visible = key == "manage"
        self.history_container.visible = key == "history"
        self.settings_container.visible = key == "settings"
        # Auto-close the sidebar after navigation so it doesn't linger
        self._sidebar_open = False
        # Flush visibility + sidebar state to the UI in one update before any
        # lazy loader runs — without this, the lazy loader's page.update() can
        # race with the visibility flip and the new tab renders empty.
        self._refresh_sidebar()
        # Lazy loads per page (after visibility has been committed). The AI
        # tab is self-contained — its history lives in a button-triggered
        # dialog so opening the tab is instant.
        if key == "manage":
            self._load_managed_flows()
        elif key == "history":
            self._load_history_async()
        elif key == "settings":
            self._refresh_settings_status()

    # ─────────────────────────────────────────────────────────
    # AI Workflow tab — chat-style: prompt at bottom, conversation
    # feed in the middle, plan auto-runs once Gemini returns it
    # ─────────────────────────────────────────────────────────
    def _build_ai_tab(self) -> ft.Container:
        # ── Header (title + working indicator + recent + new-chat) ──
        self.ai_recent_btn = ui.icon_button(
            icon=ft.Icons.HISTORY,
            on_click=lambda e: self._show_recent_workflows(),
            tooltip="Recent workflows",
            color=ui.TEXT_SECONDARY,
        )
        self.ai_new_chat_btn = ui.icon_button(
            icon=ft.Icons.ADD,
            on_click=lambda e: self._on_ai_new_chat(),
            tooltip="New chat",
            color=ui.TEXT_SECONDARY,
        )
        self.ai_header_indicator = ft.Container(
            content=ft.Row(
                [
                    ft.ProgressRing(
                        width=12, height=12, stroke_width=2, color=ui.ACCENT,
                    ),
                    ft.Text(
                        "Bicentra is working…",
                        size=ui.FONT_XS,
                        color=ui.ACCENT,
                    ),
                ],
                spacing=ui.SPACE_2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=False,
        )
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        "Bicentra AI",
                        size=ui.FONT_LG,
                        weight=ft.FontWeight.W_700,
                        color=ui.TEXT_PRIMARY,
                    ),
                    ft.Container(width=ui.SPACE_3),
                    self.ai_header_indicator,
                    ft.Container(expand=True),
                    self.ai_recent_btn,
                    self.ai_new_chat_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(bottom=ui.SPACE_2),
            border=ft.border.only(bottom=ft.BorderSide(1, ui.BORDER)),
        )

        # ── Conversation feed (scrolls; auto-scrolls to bottom) ─────
        self.ai_conversation = ft.ListView(
            spacing=ui.SPACE_3,
            expand=True,
            auto_scroll=True,
            padding=ft.padding.symmetric(horizontal=ui.SPACE_2, vertical=ui.SPACE_3),
        )
        self.ai_conversation.controls.append(self._build_welcome_bubble())

        # ── Input area at bottom ────────────────────────────────────
        self.ai_input = ft.TextField(
            hint_text="Ask Bicentra AI to do something…",
            multiline=True,
            min_lines=1,
            max_lines=4,
            border_radius=ui.RADIUS_LG,
            border_color=ui.BORDER,
            focused_border_color=ui.ACCENT,
            bgcolor=ui.SURFACE,
            text_size=ui.FONT_MD,
            content_padding=ft.padding.symmetric(
                horizontal=ui.SPACE_3, vertical=ui.SPACE_3,
            ),
            expand=True,
            on_submit=lambda e: self._on_ai_send(),
        )
        self.ai_send_btn = ui.icon_button(
            icon=ft.Icons.ARROW_UPWARD,
            on_click=lambda e: self._on_ai_send(),
            tooltip="Send",
            color="white",
        )
        self._ai_send_btn_wrap = ft.Container(
            content=self.ai_send_btn,
            bgcolor=ui.ACCENT,
            border_radius=ui.RADIUS_FULL,
            width=40,
            height=40,
            alignment=ft.alignment.center,
        )
        self.ai_stop_btn = ui.icon_button(
            icon=ft.Icons.STOP_CIRCLE,
            on_click=lambda e: self._on_ai_stop(),
            tooltip="Stop",
            color=ui.ERROR,
            size=24,
        )
        self._ai_stop_btn_wrap = ft.Container(
            content=self.ai_stop_btn,
            width=40, height=40,
            alignment=ft.alignment.center,
            visible=False,
        )

        input_row = ft.Container(
            content=ft.Row(
                [self.ai_input, self._ai_send_btn_wrap, self._ai_stop_btn_wrap],
                spacing=ui.SPACE_2,
                vertical_alignment=ft.CrossAxisAlignment.END,
            ),
            padding=ft.padding.only(top=ui.SPACE_3, bottom=ui.SPACE_1),
        )

        return ft.Container(
            content=ft.Column(
                [header, self.ai_conversation, input_row],
                spacing=0,
                expand=True,
            ),
            expand=True,
        )

    # ── Bubble builders ──────────────────────────────────────────

    def _build_welcome_bubble(self) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.AUTO_AWESOME, size=32, color=ui.ACCENT,
                        ),
                        width=56, height=56,
                        bgcolor=ui.ACCENT_SUBTLE,
                        border_radius=28,
                        alignment=ft.alignment.center,
                    ),
                    ft.Container(height=ui.SPACE_2),
                    ft.Text(
                        "Bicentra AI",
                        size=ui.FONT_XL,
                        weight=ft.FontWeight.W_700,
                        color=ui.TEXT_PRIMARY,
                    ),
                    ft.Text(
                        "Ask me to find a patient, run a recorded PMS flow, "
                        "place an AI call, or send an SMS.",
                        size=ui.FONT_BASE,
                        color=ui.TEXT_MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            padding=ft.padding.symmetric(vertical=ui.SPACE_8),
            alignment=ft.alignment.center,
        )

    def _user_bubble(self, text: str) -> ft.Row:
        return ft.Row(
            [
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Text(
                        text,
                        color="white",
                        size=ui.FONT_MD,
                        selectable=True,
                    ),
                    bgcolor=ui.ACCENT,
                    border_radius=14,
                    padding=ft.padding.symmetric(
                        horizontal=ui.SPACE_4, vertical=ui.SPACE_3,
                    ),
                ),
            ],
            alignment=ft.MainAxisAlignment.END,
        )

    def _ai_avatar(self) -> ft.Container:
        return ft.Container(
            content=ft.Icon(ft.Icons.AUTO_AWESOME, color=ui.ACCENT, size=18),
            width=32, height=32,
            bgcolor=ui.ACCENT_SUBTLE,
            border_radius=16,
            alignment=ft.alignment.center,
        )

    def _ai_message_bubble(self, *body_controls: ft.Control) -> ft.Row:
        """An assistant-attributed bubble — avatar + Column of body controls."""
        return ft.Row(
            [
                self._ai_avatar(),
                ft.Column(
                    list(body_controls),
                    spacing=ui.SPACE_1,
                    tight=True,
                    expand=True,
                ),
            ],
            spacing=ui.SPACE_2,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def _typing_bubble(self, label: str = "Thinking…") -> ft.Row:
        return self._ai_message_bubble(
            ft.Row(
                [
                    ft.ProgressRing(
                        width=14, height=14, stroke_width=2, color=ui.ACCENT,
                    ),
                    ft.Text(label, size=ui.FONT_BASE, color=ui.TEXT_MUTED),
                ],
                spacing=ui.SPACE_2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

    def _plan_bubble(self, plan: dict) -> ft.Row:
        summary = plan.get("summary") or "(no summary)"
        steps = plan.get("steps") or []
        return self._ai_message_bubble(
            ft.Text(
                "Plan",
                size=ui.FONT_XS,
                color=ui.TEXT_MUTED,
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(summary, size=ui.FONT_MD, color=ui.TEXT_PRIMARY),
            ft.Text(
                f"{len(steps)} step{'s' if len(steps) != 1 else ''} · running automatically",
                size=ui.FONT_XS,
                color=ui.TEXT_MUTED,
            ),
        )

    _STEP_ICON = {
        "pending": (ft.Icons.RADIO_BUTTON_UNCHECKED, "#9ca3af"),
        "running": (ft.Icons.HOURGLASS_TOP, ui.ACCENT),
        "completed": (ft.Icons.CHECK_CIRCLE, ui.SUCCESS),
        "failed": (ft.Icons.CANCEL, ui.ERROR),
        "skipped": (ft.Icons.REMOVE_CIRCLE_OUTLINE, ui.TEXT_MUTED),
        "desktop": (ft.Icons.DESKTOP_WINDOWS, ui.WARNING),
    }

    def _step_bubble(self, event: dict, status: str) -> ft.Row:
        idx = event.get("index", "?")
        tool = event.get("tool", "?")
        reason = event.get("reason") or ""
        result = event.get("result") or {}
        error = event.get("error") or ""
        icon, color = self._STEP_ICON.get(status, self._STEP_ICON["running"])

        head = ft.Row(
            [
                ft.Icon(icon, size=18, color=color),
                ft.Text(
                    f"Step {idx} · {tool}",
                    size=ui.FONT_BASE,
                    weight=ft.FontWeight.W_600,
                    color=ui.TEXT_PRIMARY,
                ),
            ],
            spacing=ui.SPACE_2,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        body_children: list[ft.Control] = [head]
        if reason:
            body_children.append(
                ft.Text(reason, size=ui.FONT_BASE, color=ui.TEXT_SECONDARY)
            )

        if status == "completed" and isinstance(result, dict):
            preview = ", ".join(
                f"{k}={str(v)[:32]}" for k, v in list(result.items())[:3]
                if not k.startswith("_")
            )
            if preview:
                body_children.append(
                    ft.Text(preview, size=ui.FONT_XS, color=ui.TEXT_MUTED)
                )
        elif status == "failed" and error:
            body_children.append(
                ft.Text(f"⚠ {error[:240]}", size=ui.FONT_BASE, color=ui.ERROR)
            )
        elif status == "desktop":
            body_children.append(
                ft.Text(
                    "Running on the desktop…",
                    size=ui.FONT_XS,
                    color=ui.WARNING,
                )
            )
        elif status == "running":
            body_children.append(
                ft.Row(
                    [
                        ft.ProgressRing(
                            width=12, height=12, stroke_width=2, color=ui.ACCENT,
                        ),
                        ft.Text("Working…", size=ui.FONT_XS, color=ui.TEXT_MUTED),
                    ],
                    spacing=ui.SPACE_2,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )

        return self._ai_message_bubble(
            ft.Container(
                content=ft.Column(body_children, spacing=ui.SPACE_1, tight=True),
                padding=ft.padding.symmetric(
                    horizontal=ui.SPACE_3, vertical=ui.SPACE_3,
                ),
                bgcolor=ui.SURFACE,
                border=ft.border.all(1, ui.BORDER),
                border_radius=ui.RADIUS_MD,
            )
        )

    def _final_bubble(self, status: str, error: str = "") -> ft.Row:
        if status == "completed":
            return self._ai_message_bubble(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=ui.SUCCESS, size=18),
                        ft.Text(
                            "All done.",
                            size=ui.FONT_MD,
                            color=ui.SUCCESS,
                            weight=ft.FontWeight.W_600,
                        ),
                    ],
                    spacing=ui.SPACE_2,
                )
            )
        if status == "cancelled":
            return self._ai_message_bubble(
                ft.Text(
                    "Workflow cancelled.",
                    size=ui.FONT_MD,
                    color=ui.TEXT_MUTED,
                )
            )
        return self._ai_message_bubble(
            ft.Row(
                [
                    ft.Icon(ft.Icons.CANCEL, color=ui.ERROR, size=18),
                    ft.Column(
                        [
                            ft.Text(
                                "Workflow failed.",
                                size=ui.FONT_MD,
                                color=ui.ERROR,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(
                                error[:300] if error else "",
                                size=ui.FONT_BASE,
                                color=ui.TEXT_SECONDARY,
                            ),
                        ],
                        spacing=ui.SPACE_1,
                        tight=True,
                        expand=True,
                    ),
                ],
                spacing=ui.SPACE_2,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )

    # ── Lifecycle helpers ────────────────────────────────────────

    def _ai_show_indicator(self, on: bool, label: str = "Bicentra is working…"):
        if not self.ai_header_indicator:
            return
        self.ai_header_indicator.visible = on
        if on:
            label_widget = self.ai_header_indicator.content.controls[1]
            label_widget.value = label

    def _ai_set_input_state(self, running: bool):
        self.ai_running = running
        if self.ai_input:
            self.ai_input.disabled = running
        if self._ai_send_btn_wrap and self._ai_stop_btn_wrap:
            self._ai_send_btn_wrap.visible = not running
            self._ai_stop_btn_wrap.visible = running

    def _on_ai_send(self):
        if self.ai_running:
            return
        prompt = (self.ai_input.value or "").strip()
        if len(prompt) < 3:
            return
        # Append user message + typing indicator, clear input, lock controls
        self.ai_conversation.controls.append(self._user_bubble(prompt))
        typing = self._typing_bubble("Planning…")
        self.ai_conversation.controls.append(typing)
        self.ai_input.value = ""
        self._ai_set_input_state(running=True)
        self._ai_show_indicator(True, "Planning…")
        self.page.update()

        def go():
            workflow, error = self.api.create_workflow(prompt)
            # Drop the typing indicator
            if typing in self.ai_conversation.controls:
                self.ai_conversation.controls.remove(typing)

            if not workflow:
                self.ai_conversation.controls.append(
                    self._final_bubble(
                        "failed", f"Couldn't plan: {error or 'unknown error'}"
                    )
                )
                self._ai_set_input_state(running=False)
                self._ai_show_indicator(False)
                self.page.update()
                return

            self.workflow = workflow
            plan = workflow.get("plan") or {}
            self.ai_conversation.controls.append(self._plan_bubble(plan))
            self._ai_show_indicator(True, "Running…")
            self.page.update()

            # Auto-approve so the executor kicks in immediately — user already
            # described what they want; the plan card above documents it.
            updated, err = self.api.approve_workflow(workflow["id"])
            if not updated:
                self.ai_conversation.controls.append(
                    self._final_bubble(
                        "failed", f"Couldn't start: {err or 'unknown error'}"
                    )
                )
                self._ai_set_input_state(running=False)
                self._ai_show_indicator(False)
                self.page.update()
                return
            self.workflow = updated
            self._start_workflow_event_stream(workflow["id"])

        threading.Thread(target=go, daemon=True).start()

    def _on_ai_stop(self):
        if not self.workflow:
            return
        self._ai_show_indicator(True, "Stopping…")
        self.page.update()

        def go():
            self.api.cancel_workflow(self.workflow["id"])
            # The workflow_cancelled SSE event drives the rest of the cleanup.

        threading.Thread(target=go, daemon=True).start()

    def _on_ai_new_chat(self):
        if self.ai_running:
            return  # block until current run finishes or is cancelled
        self.workflow = None
        self.workflow_readonly = False
        self._ai_step_bubbles.clear()
        self.ai_conversation.controls.clear()
        self.ai_conversation.controls.append(self._build_welcome_bubble())
        self.ai_input.value = ""
        self._ai_set_input_state(running=False)
        self._ai_show_indicator(False)
        self.page.update()

    _AI_TERMINAL_KINDS = {
        "workflow_completed", "workflow_failed", "workflow_cancelled",
    }

    def _start_workflow_event_stream(self, workflow_id: str):
        """Open the SSE stream in a daemon thread, breaking on terminal."""

        def consume():
            logger.info(f"workflow SSE: opening stream for {workflow_id}")
            stream = self.api.stream_workflow_events(workflow_id)
            event_count = 0
            try:
                for event in stream:
                    event_count += 1
                    try:
                        self._handle_workflow_event(workflow_id, event)
                    except Exception as exc:
                        logger.error(
                            f"workflow event handler crashed: {exc}", exc_info=True
                        )
                    if event.get("kind") in self._AI_TERMINAL_KINDS:
                        break
            finally:
                logger.info(
                    f"workflow SSE: stream for {workflow_id} closed "
                    f"after {event_count} events"
                )
                try:
                    stream.close()
                except Exception:
                    pass

        self._workflow_sse_thread = threading.Thread(target=consume, daemon=True)
        self._workflow_sse_thread.start()

    def _handle_workflow_event(self, workflow_id: str, event: dict):
        kind = event.get("kind")
        is_replay = bool(event.get("replay"))
        logger.info(
            f"workflow event: {kind} idx={event.get('index')} replay={is_replay}"
        )

        if kind == "hello":
            return  # connection confirmed — no bubble change
        if kind == "workflow_started":
            self._ai_show_indicator(True, "Running…")
            self.page.update()
            return

        if kind in (
            "step_started",
            "step_completed",
            "step_failed",
            "step_skipped",
            "desktop_action_required",
        ):
            status_for_kind = {
                "step_started": "running",
                "step_completed": "completed",
                "step_failed": "failed",
                "step_skipped": "skipped",
                "desktop_action_required": "desktop",
            }[kind]
            self._upsert_step_bubble(event, status_for_kind)
            if kind == "desktop_action_required" and not is_replay:
                self._handle_desktop_action(workflow_id, event)
            self.page.update()
            return

        if kind == "workflow_completed":
            self.ai_conversation.controls.append(self._final_bubble("completed"))
            self._ai_finish_run(local_status="completed")
            self.page.update()
            return
        if kind == "workflow_failed":
            err = event.get("error") or "Unknown error"
            self.ai_conversation.controls.append(self._final_bubble("failed", err))
            self._ai_finish_run(local_status="failed")
            self.page.update()
            return
        if kind == "workflow_cancelled":
            self.ai_conversation.controls.append(self._final_bubble("cancelled"))
            self._ai_finish_run(local_status="cancelled")
            self.page.update()
            return

        logger.debug(f"Unhandled workflow event: {kind}")

    def _upsert_step_bubble(self, event: dict, status: str):
        """Create a step bubble the first time we see this step_id, or replace
        the existing one in place on subsequent events so a single row
        progresses through running → completed/failed instead of stacking."""
        step_id = event.get("step_id")
        new_bubble = self._step_bubble(event, status)

        existing = self._ai_step_bubbles.get(step_id) if step_id else None
        if existing is not None and existing in self.ai_conversation.controls:
            i = self.ai_conversation.controls.index(existing)
            self.ai_conversation.controls[i] = new_bubble
        else:
            self.ai_conversation.controls.append(new_bubble)

        if step_id:
            self._ai_step_bubbles[step_id] = new_bubble

    def _ai_finish_run(self, local_status: str):
        if self.workflow is not None:
            self.workflow["status"] = local_status
        self._ai_set_input_state(running=False)
        self._ai_show_indicator(False)

    # ── Recent workflows dialog ──────────────────────────────────

    _WORKFLOW_STATUS_COLOR = {
        "completed": ui.SUCCESS,
        "failed": ui.ERROR,
        "cancelled": ui.TEXT_MUTED,
        "running": ui.ACCENT,
        "planning": ui.WARNING,
        "planned": ui.WARNING,
    }

    def _show_recent_workflows(self):
        if self.ai_running:
            return
        loading = ft.ProgressRing(width=24, height=24, stroke_width=2)
        body = ft.Container(
            content=loading,
            width=520, height=320,
            alignment=ft.alignment.center,
        )

        def close_dlg(_=None):
            self.page.close(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Recent workflows"),
            content=body,
            actions=[ft.TextButton("Close", on_click=close_dlg)],
        )
        self.page.open(dlg)

        def fetch():
            data = self.api.list_workflows(page=1, page_size=10)
            rows = data.get("results") or []
            list_view = ft.ListView(spacing=ui.SPACE_2, height=320, padding=0)
            if not rows:
                list_view.controls.append(
                    ui.muted("No past workflows yet.", size=ui.FONT_BASE)
                )
            else:
                for wf in rows:
                    list_view.controls.append(self._build_recent_row(wf, close_dlg))
            body.content = list_view
            self.page.update()

        threading.Thread(target=fetch, daemon=True).start()

    def _build_recent_row(self, wf: dict, close_dlg) -> ft.Container:
        prompt = (wf.get("prompt") or "").strip().replace("\n", " ")
        if len(prompt) > 90:
            prompt = prompt[:87] + "…"
        status = wf.get("status") or ""
        when = (wf.get("created_at") or "")[:19].replace("T", " ")
        steps_n = wf.get("step_count") or 0
        color = self._WORKFLOW_STATUS_COLOR.get(status, ui.TEXT_MUTED)

        def open_it(_=None):
            close_dlg()
            self._open_recent_workflow(wf)

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                prompt or "(empty prompt)",
                                size=ui.FONT_BASE,
                                color=ui.TEXT_PRIMARY,
                                weight=ft.FontWeight.W_500,
                                expand=True,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ui.chip(status, variant="neutral"),
                        ],
                        spacing=ui.SPACE_2,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        f"{when} · {steps_n} step{'s' if steps_n != 1 else ''}",
                        size=ui.FONT_XS,
                        color=color,
                    ),
                ],
                spacing=ui.SPACE_1,
                tight=True,
            ),
            padding=ui.SPACE_3,
            bgcolor=ui.SURFACE,
            border=ft.border.all(1, ui.BORDER),
            border_radius=ui.RADIUS_MD,
            on_click=open_it,
            ink=True,
        )

    def _open_recent_workflow(self, wf: dict):
        workflow_id = wf.get("id")
        if not workflow_id:
            return
        self._ai_step_bubbles.clear()
        self.ai_conversation.controls.clear()
        self.workflow_readonly = True
        self.page.update()

        def fetch():
            detail = self.api.get_workflow(workflow_id)
            if not detail:
                self.ai_conversation.controls.append(self._build_welcome_bubble())
                self.page.update()
                return
            self.workflow = detail
            prompt = detail.get("prompt") or ""
            self.ai_conversation.controls.append(self._user_bubble(prompt))
            plan = detail.get("plan") or {}
            self.ai_conversation.controls.append(self._plan_bubble(plan))
            status_map = {
                "completed": "completed",
                "failed": "failed",
                "skipped": "skipped",
                "awaiting_desktop": "desktop",
                "running": "running",
                "pending": "running",
            }
            for step in detail.get("steps") or []:
                fake_event = {
                    "step_id": str(step.get("id")),
                    "index": step.get("index"),
                    "tool": step.get("tool_name"),
                    "reason": step.get("reason", ""),
                    "result": step.get("result") or {},
                    "error": step.get("error") or "",
                }
                self._upsert_step_bubble(
                    fake_event,
                    status_map.get(step.get("status"), "completed"),
                )
            status = detail.get("status") or ""
            if status in ("completed", "failed", "cancelled"):
                self.ai_conversation.controls.append(
                    self._final_bubble(status, detail.get("error_message") or "")
                )
            self.page.update()

        threading.Thread(target=fetch, daemon=True).start()
    def _handle_desktop_action(self, workflow_id: str, event: dict):
        """Backend asked us to run a flow. Spin off the existing flow runner
        but POST its result back to the workflow callback when it finishes."""
        tool = event.get("tool")
        if tool != "run_flow":
            logger.warning(f"Unsupported desktop_action_required tool: {tool}")
            return
        step_id = event.get("step_id")
        pms = event.get("pms")
        flow_name = event.get("flow_name")
        flow_inputs = event.get("inputs") or {}
        desktop_session_id = event.get("desktop_session_id")
        if not all([step_id, pms, flow_name, desktop_session_id]):
            logger.warning(f"desktop_action_required missing fields: {event}")
            return

        # Run the desktop flow in a worker thread (reuses the existing
        # session-based runner but with the pre-created session_id).
        t = threading.Thread(
            target=self._run_workflow_flow_step,
            args=(workflow_id, step_id, pms, flow_name, flow_inputs, desktop_session_id),
            daemon=True,
        )
        t.start()
        self._workflow_step_threads.append(t)

    def _read_clipboard(self) -> str | None:
        """Read the system clipboard. Returns None on any error (no clipboard
        manager, permission denied, etc.) so callers can treat 'no value'
        the same as 'failed to read'."""
        try:
            import pyperclip
            return pyperclip.paste()
        except Exception as exc:
            logger.debug(f"clipboard read failed: {exc}")
            return None

    def _run_workflow_flow_step(
        self,
        workflow_id: str,
        step_id: str,
        pms: str,
        flow_name: str,
        flow_inputs: dict,
        desktop_session_id: str,
    ):
        """Run a pre-created DesktopSession to completion (reuses the same
        next_step → execute_action loop the Run tab uses) and report the
        outcome back to the workflow API.

        Also captures the clipboard before and after the flow so that flows
        ending with a copy action (e.g. Sheets search + Ctrl+C) can hand
        their output back to the backend agent as `result.clipboard` —
        the agent then chains it into `extract_data` to pull structured
        fields without us hard-coding output schemas per flow.
        """
        import pyautogui

        screen_w, screen_h = pyautogui.size()
        # Baseline so we only return the clipboard if the flow actually changed
        # it — random text the operator had copied earlier shouldn't leak in.
        clipboard_baseline = self._read_clipboard()
        result: dict = {"steps_executed": 0, "session_id": desktop_session_id}
        step = 0

        def _attach_clipboard() -> None:
            """Mutate `result` to include the flow's clipboard output, if any."""
            final = self._read_clipboard()
            if final and final != clipboard_baseline:
                result["clipboard"] = final

        try:
            while True:
                step += 1
                api_result = self.api.next_step(
                    desktop_session_id, screen_width=screen_w, screen_height=screen_h
                )
                if api_result is None:
                    raise RuntimeError("next_step returned None — session may have ended")

                action_type = api_result.get("action_type", "failed")
                if action_type == "done":
                    result["steps_executed"] = step - 1
                    result["final_reason"] = api_result.get("reason", "")
                    _attach_clipboard()
                    self.api.post_workflow_step_result(
                        workflow_id, step_id, "completed", result=result
                    )
                    return
                if action_type == "failed":
                    _attach_clipboard()
                    self.api.post_workflow_step_result(
                        workflow_id, step_id, "failed",
                        result=result,
                        error=api_result.get("reason", "Flow failed"),
                    )
                    return

                try:
                    execute_action(api_result)
                except Exception as exc:
                    _attach_clipboard()
                    self.api.post_workflow_step_result(
                        workflow_id, step_id, "failed",
                        result={**result, "steps_executed": step},
                        error=f"execute_action: {exc}",
                    )
                    return

                if step >= config.MAX_STEPS:
                    self.api.cancel_session(desktop_session_id)
                    _attach_clipboard()
                    self.api.post_workflow_step_result(
                        workflow_id, step_id, "failed",
                        result={**result, "steps_executed": step},
                        error="Max steps reached",
                    )
                    return
                time.sleep(config.SCREENSHOT_INTERVAL)
        except Exception as exc:
            logger.error(f"workflow flow step runner crashed: {exc}", exc_info=True)
            _attach_clipboard()
            self.api.post_workflow_step_result(
                workflow_id, step_id, "failed",
                result=result,
                error=f"Runner crashed: {exc}",
            )

    # ─────────────────────────────────────────────────────────
    # Run tab — search-based flow selector + form
    # ─────────────────────────────────────────────────────────
    def _build_run_tab(self) -> ft.Container:
        # Search field
        self.flow_search_field = ui.text_field(
            hint="Search flows by name or description…",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._on_flow_search_change,
            height=44,
        )

        # Empty state placeholder for the list area
        self.flow_list_column = ft.Column(spacing=ui.SPACE_2)

        # Idle view: shown when no flow selected
        self.run_idle_view = ft.Container(
            content=ft.Column(
                [
                    self.flow_search_field,
                    ft.Container(height=ui.SPACE_3),
                    self.flow_list_column,
                ],
                spacing=0,
            ),
            visible=True,
        )

        # Active view widgets (form + run controls) — built lazily on flow select
        self.inputs_column = ft.Column(spacing=ui.SPACE_3)

        self.run_btn = ui.primary_button(
            "Run flow",
            on_click=lambda e: self._start_run(),
            icon=ft.Icons.PLAY_ARROW,
            expand=True,
        )
        self.stop_btn = ui.destructive_button(
            "Stop",
            on_click=lambda e: self._stop_run(),
            icon=ft.Icons.STOP,
            disabled=True,
        )

        self.status_text = ft.Text("Ready", size=ui.FONT_BASE, color=ui.TEXT_MUTED)
        self.log_view = ft.ListView(
            spacing=2,
            height=200,
            auto_scroll=True,
            padding=ft.padding.all(ui.SPACE_2),
        )
        self.copy_btn = ft.IconButton(
            icon=ft.Icons.CONTENT_COPY,
            tooltip="Copy logs",
            on_click=lambda e: self._copy_logs(),
            visible=config.DEBUG,
            icon_size=16,
            icon_color=ui.TEXT_MUTED,
        )

        # The active view is built by _render_active_flow_view() — start empty
        self.flow_form_panel = ft.Column(spacing=0)
        self.run_active_view = ft.Container(
            content=self.flow_form_panel,
            visible=False,
        )

        return ft.Container(
            content=ft.Column(
                [
                    self.run_idle_view,
                    self.run_active_view,
                ],
                spacing=0,
            ),
        )

    def _render_flow_list(self):
        """Re-render the flow list based on the current search query."""
        if not self.flow_list_column:
            return
        self.flow_list_column.controls.clear()

        if not self.flows:
            # Empty state — no flows at all
            self.flow_list_column.controls.append(
                ui.empty_state(
                    icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
                    title="No flows yet",
                    description="Record a flow in the Record tab to get started.",
                )
            )
            self.page.update()
            return

        # Filter by search text
        q = (self.flow_search_text or "").lower().strip()
        if q:
            matching = [
                f for f in self.flows
                if q in (f.get("display_name") or "").lower()
                or q in (f.get("name") or "").lower()
                or q in (f.get("description") or "").lower()
            ]
        else:
            matching = list(self.flows)

        if not matching:
            self.flow_list_column.controls.append(
                ui.empty_state(
                    icon=ft.Icons.SEARCH_OFF,
                    title="No matches",
                    description=f"No flows match \"{self.flow_search_text}\".",
                )
            )
            self.page.update()
            return

        for flow in matching:
            self.flow_list_column.controls.append(self._build_flow_card(flow))
        self.page.update()

    def _build_flow_card(self, flow: dict) -> ft.Container:
        """A single clickable flow card in the search list."""
        name = flow.get("display_name") or flow.get("name") or "Untitled flow"
        desc = flow.get("description") or ""
        pms = flow.get("pms") or flow.get("pms_software") or ""
        step_count = flow.get("step_count") or len(flow.get("steps", []))
        source = flow.get("source", "")

        chips_row = ft.Row(spacing=ui.SPACE_2)
        if pms:
            pms_label = dict(PMS_OPTIONS).get(pms, pms)
            chips_row.controls.append(ui.chip(pms_label, variant="info"))
        if step_count:
            chips_row.controls.append(
                ui.chip(f"{step_count} step{'s' if step_count != 1 else ''}", variant="neutral")
            )
        if source == "yaml":
            chips_row.controls.append(ui.chip("YAML", variant="accent"))

        content_col = ft.Column(
            [
                ft.Text(
                    name,
                    size=ui.FONT_MD,
                    weight=ft.FontWeight.W_600,
                    color=ui.TEXT_PRIMARY,
                ),
            ],
            spacing=ui.SPACE_1,
            tight=True,
        )
        if desc:
            content_col.controls.append(
                ft.Text(
                    desc,
                    size=ui.FONT_BASE,
                    color=ui.TEXT_MUTED,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                )
            )
        content_col.controls.append(chips_row)

        return ft.Container(
            content=content_col,
            padding=ui.SPACE_3,
            bgcolor=ui.SURFACE,
            border=ft.border.all(1, ui.BORDER),
            border_radius=ui.RADIUS_MD,
            on_click=lambda e, f=flow: self._select_flow(f),
            ink=True,
        )

    def _on_flow_search_change(self, e):
        self.flow_search_text = e.control.value or ""
        self._render_flow_list()

    def _select_flow(self, flow: dict):
        """Activate a flow — show its form, hide the search list."""
        self.selected_flow = flow
        self.input_fields = {}
        self._build_active_flow_form()
        self.run_idle_view.visible = False
        self.run_active_view.visible = True
        self.page.update()

    def _back_to_flows(self):
        """Return to the search/list view (only allowed when not running)."""
        if self.running:
            return
        self.selected_flow = None
        self.run_idle_view.visible = True
        self.run_active_view.visible = False
        self.page.update()

    def _build_active_flow_form(self):
        """Build the form panel for the currently selected flow."""
        flow = self.selected_flow
        if not flow:
            return

        name = flow.get("display_name") or flow.get("name") or "Untitled flow"
        desc = flow.get("description") or ""

        # Header row: back button + name + chips
        back_btn = ui.icon_button(
            icon=ft.Icons.ARROW_BACK,
            on_click=lambda e: self._back_to_flows(),
            tooltip="Back to flows",
            size=18,
            color=ui.TEXT_SECONDARY,
        )

        chips_row = ft.Row(spacing=ui.SPACE_2)
        pms = flow.get("pms") or flow.get("pms_software") or ""
        if pms:
            chips_row.controls.append(
                ui.chip(dict(PMS_OPTIONS).get(pms, pms), variant="info")
            )

        # Rebuild input fields
        self.inputs_column.controls.clear()
        store = _load_input_store()
        flow_key = f"{pms}::{flow.get('name', '')}"
        last_values = store.get(flow_key, {})

        inputs = flow.get("inputs", []) or []
        if not inputs:
            self.inputs_column.controls.append(
                ui.muted("This flow has no input variables.", size=ui.FONT_BASE)
            )
        else:
            for inp in inputs:
                self.inputs_column.controls.append(
                    self._build_input_widget(inp, last_values)
                )

        controls_row = ft.Row([self.run_btn, self.stop_btn], spacing=ui.SPACE_2)

        self.flow_form_panel.controls.clear()
        self.flow_form_panel.controls.extend(
            [
                ft.Row(
                    [
                        back_btn,
                        ft.Column(
                            [
                                ft.Text(
                                    name,
                                    size=ui.FONT_XL,
                                    weight=ft.FontWeight.W_600,
                                    color=ui.TEXT_PRIMARY,
                                ),
                                chips_row if chips_row.controls else ft.Container(),
                            ],
                            spacing=ui.SPACE_1,
                            tight=True,
                            expand=True,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=ui.SPACE_2,
                ),
                ft.Container(height=ui.SPACE_3),
                ft.Text(desc, size=ui.FONT_BASE, color=ui.TEXT_SECONDARY)
                if desc
                else ft.Container(),
                ft.Container(height=ui.SPACE_4),
                ui.caption("Inputs"),
                ft.Container(height=ui.SPACE_2),
                self.inputs_column,
                ft.Container(height=ui.SPACE_4),
                controls_row,
                ft.Container(height=ui.SPACE_2),
                self.status_text,
                ft.Container(height=ui.SPACE_3),
                ft.Row(
                    [
                        ui.caption("Logs"),
                        ft.Container(expand=True),
                        self.copy_btn,
                    ]
                ),
                ft.Container(height=ui.SPACE_1),
                ft.Container(
                    content=self.log_view,
                    bgcolor=ui.SURFACE_SUBTLE,
                    border_radius=ui.RADIUS_MD,
                    border=ft.border.all(1, ui.BORDER),
                ),
            ]
        )

    def _build_input_widget(self, inp: dict, last_values: dict) -> ft.Control:
        """Build a single input widget from a flow input schema entry."""
        name = inp.get("name", "")
        label = inp.get("label", name)
        placeholder = inp.get("placeholder", "")
        required = inp.get("required", False)
        inp_type = inp.get("type", "string")
        default = inp.get("default", "")
        initial = last_values.get(name, default)
        label_text = f"{label}{' *' if required else ''}"

        widget: ft.Control
        if inp_type == "choice":
            choices = inp.get("choices", []) or []
            widget = ft.Dropdown(
                label=label_text,
                value=initial if initial in choices else (choices[0] if choices else None),
                options=[ft.dropdown.Option(key=c, text=c) for c in choices],
                border_radius=ui.RADIUS_MD,
                border_color=ui.BORDER,
                focused_border_color=ui.ACCENT,
                bgcolor=ui.SURFACE,
                text_size=ui.FONT_MD,
                content_padding=ft.padding.symmetric(horizontal=ui.SPACE_3, vertical=ui.SPACE_3),
            )
        elif inp_type == "longtext":
            widget = ui.text_field(
                label=label_text,
                hint=placeholder,
                value=str(initial) if initial else "",
                multiline=True,
                min_lines=2,
                max_lines=5,
            )
        elif inp_type == "number":
            widget = ui.text_field(
                label=label_text,
                hint=placeholder,
                value=str(initial) if initial else "",
                height=44,
            )
        else:  # string
            widget = ui.text_field(
                label=label_text,
                hint=placeholder,
                value=str(initial) if initial else "",
                height=44,
            )

        self.input_fields[name] = widget
        return widget

    # ─────────────────────────────────────────────────────────
    # Record tab
    # ─────────────────────────────────────────────────────────
    def _build_record_tab(self) -> ft.Container:
        self.rec_pms = ft.Dropdown(
            label="PMS Software",
            value=self.rec_pms_value,
            options=[ft.dropdown.Option(key=k, text=label) for k, label in PMS_OPTIONS],
            on_change=self._on_rec_pms_change,
            border_radius=ui.RADIUS_MD,
            border_color=ui.BORDER,
            focused_border_color=ui.ACCENT,
            bgcolor=ui.SURFACE,
            text_size=ui.FONT_MD,
            content_padding=ft.padding.symmetric(horizontal=ui.SPACE_3, vertical=ui.SPACE_3),
        )
        self.rec_name = ft.TextField(
            label="Flow Name (slug)",
            hint_text="create_patient",
            border_radius=8, height=48,
        )
        self.rec_display = ft.TextField(
            label="Display Name",
            hint_text="Create Patient Profile",
            border_radius=8, height=48,
        )
        self.rec_desc = ft.TextField(
            label="Description",
            multiline=True,
            min_lines=2, max_lines=4,
            border_radius=8,
        )

        warning = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.WARNING_AMBER, color="#92400e", size=16),
                    ft.Text(
                        "Do not type passwords or sensitive data during recording.",
                        color="#92400e", size=11, expand=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
                spacing=8,
            ),
            padding=8,
            bgcolor="#fef3c7",
            border_radius=6,
            border=ft.border.all(1, "#fcd34d"),
        )

        self.rec_btn = ft.ElevatedButton(
            "● Start Recording",
            on_click=lambda e: self._toggle_recording(),
            height=40, expand=True,
            style=ft.ButtonStyle(
                bgcolor="#dc2626", color="white",
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self.rec_status = ft.Text("Ready to record", size=12, color="#6b7280")
        self.rec_event_count = ft.Text("", size=11, color="#9ca3af")

        return ft.Container(
            content=ft.Column([
                ft.Text("Record a Flow", size=14, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Click Start, then perform the task in your PMS. "
                    "Press ⌘+Shift+Esc or click Stop when done.",
                    size=11, color="#6b7280",
                ),
                ft.Container(height=8),
                self.rec_pms,
                ft.Container(height=4),
                self.rec_name,
                ft.Container(height=4),
                self.rec_display,
                ft.Container(height=4),
                self.rec_desc,
                ft.Container(height=8),
                warning,
                ft.Container(height=8),
                ft.Row([self.rec_btn]),
                ft.Container(height=6),
                self.rec_status,
                self.rec_event_count,
            ], spacing=0),
        )

    def _on_rec_pms_change(self, e):
        self.rec_pms_value = e.control.value

    # ─────────────────────────────────────────────────────────
    # Manage tab
    # ─────────────────────────────────────────────────────────
    def _build_manage_tab(self) -> ft.Container:
        self.manage_list = ft.Column(spacing=6)
        self.manage_status = ft.Text("Loading your flows...", size=12, color="#6b7280")
        refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH, tooltip="Refresh",
            on_click=lambda e: self._load_managed_flows(),
        )
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("Your Flows", size=14, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    refresh_btn,
                ]),
                ft.Text(
                    "Flows your organization has recorded or created.",
                    size=11, color="#6b7280",
                ),
                ft.Container(height=8),
                self.manage_status,
                self.manage_list,
            ], spacing=0),
        )

    def _load_managed_flows(self):
        self.manage_status.value = "Loading..."
        self.manage_status.color = "#6b7280"
        self.manage_list.controls.clear()
        self.page.update()

        def fetch():
            try:
                flows = self.api.list_my_flows()
            except Exception as e:
                logger.error(f"list_my_flows failed: {e}")
                flows = []
            self._render_managed_flows(flows)

        threading.Thread(target=fetch, daemon=True).start()

    def _render_managed_flows(self, flows: list[dict]):
        self.managed_flows = flows
        self.manage_list.controls.clear()

        if not flows:
            self.manage_status.value = "No saved flows yet. Record one in the Record tab."
            self.manage_status.color = "#6b7280"
            self.page.update()
            return

        pms_labels = {k: label for k, label in PMS_OPTIONS}

        self.manage_status.value = f"{len(flows)} flow{'s' if len(flows) != 1 else ''}"
        for flow in flows:
            pms = flow.get("pms_software", "")
            pms_label = pms_labels.get(pms, pms)
            step_count = len(flow.get("steps", []))
            input_count = len(flow.get("inputs", []))
            verified = flow.get("is_verified", False)

            tags_row = [
                ft.Container(
                    content=ft.Text(pms_label, size=10, color="#1e40af"),
                    bgcolor="#dbeafe", border_radius=4,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                ),
                ft.Container(
                    content=ft.Text(f"{step_count} steps", size=10, color="#6b7280"),
                    bgcolor="#f3f4f6", border_radius=4,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                ),
            ]
            if input_count > 0:
                tags_row.append(
                    ft.Container(
                        content=ft.Text(f"{input_count} inputs", size=10, color="#6b7280"),
                        bgcolor="#f3f4f6", border_radius=4,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    )
                )
            if verified:
                tags_row.append(
                    ft.Container(
                        content=ft.Text("✓ verified", size=10, color="#15803d"),
                        bgcolor="#dcfce7", border_radius=4,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    )
                )

            row = ft.Container(
                content=ft.Row([
                    ft.Column([
                        ft.Text(
                            flow.get("display_name") or flow.get("name"),
                            size=13, weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            flow.get("description", "") or f"({flow.get('name')})",
                            size=11, color="#6b7280", max_lines=2,
                        ),
                        ft.Row(tags_row, spacing=4, wrap=True),
                    ], spacing=3, expand=True),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE, icon_color="#dc2626",
                        tooltip="Delete flow",
                        on_click=lambda e, f=flow: self._confirm_delete(f),
                    ),
                ], alignment=ft.MainAxisAlignment.START),
                padding=10,
                bgcolor="white",
                border=ft.border.all(1, "#e5e7eb"),
                border_radius=8,
            )
            self.manage_list.controls.append(row)

        self.page.update()

    def _confirm_delete(self, flow: dict):
        name = flow.get("display_name") or flow.get("name")

        def on_delete(e):
            self.page.close(dlg)
            threading.Thread(target=self._do_delete, args=(flow,), daemon=True).start()

        def close_dlg(e):
            self.page.close(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete flow?"),
            content=ft.Text(
                f"Are you sure you want to delete \"{name}\"?\n"
                "This removes it from the Run tab for everyone in your org."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=close_dlg),
                ft.ElevatedButton(
                    "Delete", on_click=on_delete,
                    style=ft.ButtonStyle(bgcolor="#dc2626", color="white"),
                ),
            ],
        )
        self.page.open(dlg)

    def _do_delete(self, flow: dict):
        flow_id = flow.get("id")
        if not flow_id:
            return
        ok = self.api.delete_flow(flow_id)
        if ok:
            self._load_managed_flows()
            # Refresh the Run search list too (in case it was deleted from there)
            self.load_flows_async()

    # ─────────────────────────────────────────────────────────
    # History tab
    # ─────────────────────────────────────────────────────────
    def _build_history_tab(self) -> ft.Container:
        self.history_search = ft.TextField(
            label="Search",
            hint_text="Flow name, task description, or session id",
            border_radius=8, height=40,
            on_change=self._on_history_search_change,
        )
        self.history_status_dropdown = ft.Dropdown(
            label="Status",
            value="",
            options=[
                ft.dropdown.Option(key="", text="All"),
                ft.dropdown.Option(key="active", text="Active"),
                ft.dropdown.Option(key="completed", text="Completed"),
                ft.dropdown.Option(key="failed", text="Failed"),
                ft.dropdown.Option(key="cancelled", text="Cancelled"),
            ],
            on_change=self._on_history_status_change,
            width=160,
            height=40,
            border_radius=8,
        )
        refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH, tooltip="Refresh",
            on_click=lambda e: self._load_history_async(),
        )
        self.history_status = ft.Text("", size=11, color="#6b7280")
        self.history_list = ft.Column(spacing=6)
        self.history_pagination_label = ft.Text("", size=11, color="#6b7280")
        self.history_prev_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT, tooltip="Previous page", disabled=True,
            on_click=lambda e: self._history_change_page(-1),
        )
        self.history_next_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT, tooltip="Next page", disabled=True,
            on_click=lambda e: self._history_change_page(1),
        )

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("Run History", size=14, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    refresh_btn,
                ]),
                ft.Text(
                    "Past flow runs for your organization. Click a row to inspect.",
                    size=11, color="#6b7280",
                ),
                ft.Container(height=8),
                ft.Row([self.history_search, self.history_status_dropdown], spacing=8),
                ft.Container(height=4),
                self.history_status,
                self.history_list,
                ft.Container(height=4),
                ft.Row([
                    self.history_pagination_label,
                    ft.Container(expand=True),
                    self.history_prev_btn,
                    self.history_next_btn,
                ]),
            ], spacing=0),
        )

    def _on_history_search_change(self, e):
        # Debounce: cancel previous timer
        if self._history_search_handle is not None:
            try:
                self._history_search_handle.cancel()
            except Exception:
                pass
        val = (e.control.value or "").strip()

        def fire():
            self.history_query = val
            self.history_page = 1
            self._load_history_async()

        self._history_search_handle = threading.Timer(0.4, fire)
        self._history_search_handle.daemon = True
        self._history_search_handle.start()

    def _on_history_status_change(self, e):
        self.history_filter_status = e.control.value or ""
        self.history_page = 1
        self._load_history_async()

    def _history_change_page(self, delta: int):
        new_page = self.history_page + delta
        if new_page < 1:
            return
        self.history_page = new_page
        self._load_history_async()

    def _load_history_async(self):
        if self.history_status:
            self.history_status.value = "Loading..."
            self.history_status.color = "#6b7280"
            self.history_list.controls.clear()
            self.page.update()

        def fetch():
            try:
                data = self.api.list_sessions(
                    page=self.history_page,
                    page_size=self.history_page_size,
                    status=self.history_filter_status or None,
                    flow_name=self.history_filter_flow or None,
                    q=self.history_query or None,
                )
            except Exception as exc:
                logger.error(f"list_sessions failed: {exc}")
                data = {"results": [], "count": 0, "next": None, "previous": None}
            self._render_history(data)

        threading.Thread(target=fetch, daemon=True).start()

    def _render_history(self, data: dict):
        results = data.get("results") or []
        self.history_sessions = results
        self.history_total = data.get("count") or len(results)
        self.history_has_next = bool(data.get("next"))
        self.history_has_prev = bool(data.get("previous"))

        self.history_list.controls.clear()

        if not results:
            self.history_status.value = "No sessions yet — run a flow to see history here."
            self.history_status.color = "#6b7280"
            self.history_pagination_label.value = ""
            self.history_prev_btn.disabled = True
            self.history_next_btn.disabled = True
            self.page.update()
            return

        self.history_status.value = f"{self.history_total} session{'s' if self.history_total != 1 else ''}"
        self.history_pagination_label.value = (
            f"Page {self.history_page} of "
            f"{max(1, (self.history_total + self.history_page_size - 1) // self.history_page_size)}"
        )
        self.history_prev_btn.disabled = not self.history_has_prev
        self.history_next_btn.disabled = not self.history_has_next

        status_color = {
            "active": "#2563eb",
            "completed": "#16a34a",
            "failed": "#dc2626",
            "cancelled": "#6b7280",
        }

        pms_labels = {k: label for k, label in PMS_OPTIONS}

        for session in results:
            sid = session.get("id", "")
            display = session.get("flow_display_name") or session.get("flow_name") or "Untitled flow"
            pms = pms_labels.get(session.get("pms_software", ""), session.get("pms_software", ""))
            status = session.get("status", "")
            duration_ms = session.get("duration_ms")
            duration_str = (
                f"{duration_ms / 1000:.1f}s" if duration_ms else "—"
            )
            started = session.get("started_at") or session.get("created_at") or ""
            steps = session.get("step_count", 0)
            has_video = session.get("has_video")
            err = session.get("error_message")

            tags = [
                ft.Container(
                    content=ft.Text(pms, size=10, color="#1e40af"),
                    bgcolor="#dbeafe", border_radius=4,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                ),
                ft.Container(
                    content=ft.Text(status, size=10, color=status_color.get(status, "#374151")),
                    bgcolor="#f3f4f6", border_radius=4,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                ),
                ft.Container(
                    content=ft.Text(f"{steps} steps", size=10, color="#6b7280"),
                    bgcolor="#f3f4f6", border_radius=4,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                ),
                ft.Container(
                    content=ft.Text(duration_str, size=10, color="#6b7280"),
                    bgcolor="#f3f4f6", border_radius=4,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                ),
            ]
            if has_video:
                tags.append(ft.Container(
                    content=ft.Text("🎬 video", size=10, color="#7c3aed"),
                    bgcolor="#ede9fe", border_radius=4,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                ))

            row_main_col = ft.Column([
                ft.Text(display, size=13, weight=ft.FontWeight.BOLD),
                ft.Text(
                    started[:19].replace("T", " "),
                    size=11, color="#6b7280",
                ),
                ft.Row(tags, spacing=4, wrap=True),
            ], spacing=3, expand=True)

            if err:
                row_main_col.controls.insert(2, ft.Text(
                    err[:120], size=10, color="#dc2626",
                ))

            row = ft.Container(
                content=ft.Row([
                    row_main_col,
                    ft.IconButton(
                        icon=ft.Icons.CHEVRON_RIGHT,
                        on_click=lambda e, s=sid: self._open_session_detail(s),
                    ),
                ], alignment=ft.MainAxisAlignment.START),
                padding=10, bgcolor="white",
                border=ft.border.all(1, "#e5e7eb"), border_radius=8,
                ink=True,
                on_click=lambda e, s=sid: self._open_session_detail(s),
            )
            self.history_list.controls.append(row)

        self.page.update()

    def _open_session_detail(self, session_id: str):
        SessionDetailDialog(
            page=self.page,
            api=self.api,
            session_id=session_id,
            on_deleted=self._load_history_async,
        ).show()

    # (Tab switching is now handled by _on_nav_change above.)

    # ─────────────────────────────────────────────────────────
    # Settings tab
    # ─────────────────────────────────────────────────────────
    def _build_settings_tab(self) -> ft.Container:
        # Hardware info card
        info = sysinfo.detect_system()
        recommended = sysinfo.recommend_tier(info)
        hw_h264 = sysinfo.has_hardware_h264()

        hw_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.MEMORY, size=16, color="#6b7280"),
                    ft.Text("Detected hardware", size=12, weight=ft.FontWeight.BOLD, color="#6b7280"),
                ], spacing=6),
                ft.Container(height=4),
                ft.Text(info.label(), size=12),
                ft.Text(
                    f"Hardware H.264 encoder: {'available' if hw_h264 else 'not available'}",
                    size=11, color="#6b7280",
                ),
                ft.Text(f"Recommended tier: {recommended}", size=11, color="#16a34a"),
            ], spacing=2),
            padding=12,
            bgcolor="white",
            border=ft.border.all(1, "#e5e7eb"),
            border_radius=8,
        )

        # Video tier dropdown
        current = settings_store.load().get("video_tier", "auto")
        self.settings_tier_dropdown = ft.Dropdown(
            label="Recording mode",
            value=current if current in ("auto",) + tuple(sysinfo.ALL_TIERS) else "auto",
            options=[
                ft.dropdown.Option(key="auto", text=f"Auto (recommended: {recommended})"),
                ft.dropdown.Option(key="off", text="Off — no screenshots, no video"),
                ft.dropdown.Option(key="low", text="Low — 1 fps, 854×480 (lightweight)"),
                ft.dropdown.Option(key="medium", text="Medium — 2 fps, 1280×720 (default)"),
                ft.dropdown.Option(key="high", text="High — 3 fps, 1600×900 (best detail)"),
            ],
            on_change=self._on_tier_change,
            border_radius=8, height=48,
        )

        self.settings_status = ft.Text(
            self._tier_status_label(current, recommended),
            size=11, color="#6b7280",
        )

        explainer = ft.Container(
            content=ft.Column([
                ft.Text("How recording works", size=12, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "After each step, Bicentra captures a screenshot. When the flow ends, "
                    "the screenshots are stitched into an MP4 slideshow and uploaded so you "
                    "can replay it later in History or in the web dashboard.",
                    size=11, color="#6b7280",
                ),
                ft.Text(
                    "• Off uses zero CPU, zero bandwidth — and you'll have no replay.",
                    size=11, color="#6b7280",
                ),
                ft.Text(
                    "• Low / Medium / High change the slideshow's frame rate and resolution. "
                    "Higher tiers use a bit more CPU + RAM during the brief encoding step.",
                    size=11, color="#6b7280",
                ),
                ft.Text(
                    "• Auto picks the best tier for this machine each time the app starts.",
                    size=11, color="#6b7280",
                ),
            ], spacing=4),
            padding=12,
            bgcolor="#f9fafb",
            border=ft.border.all(1, "#e5e7eb"),
            border_radius=8,
        )

        # ── About card (version, user, API) ─────────────────
        env_label = "BETA" if config.DEBUG else "PRODUCTION"
        env_color = "#7c3aed" if config.DEBUG else "#16a34a"
        user_email = (self.api.email if self.api and self.api.email else "—")

        self._about_copy_btn = ft.OutlinedButton(
            text="📋 Copy app info",
            on_click=lambda e: self._copy_app_info(info),
        )

        about_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=16, color="#6b7280"),
                    ft.Text("About", size=12, weight=ft.FontWeight.BOLD, color="#6b7280"),
                ], spacing=6),
                ft.Container(height=4),
                ft.Row([
                    ft.Text("Bicentra Desktop", size=14, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        content=ft.Text(f"v{config.APP_VERSION}", size=10, color="#1e40af"),
                        bgcolor="#dbeafe", border_radius=4,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    ),
                ], spacing=8),
                ft.Container(height=2),
                ft.Text(f"Signed in as {user_email}", size=11, color="#6b7280"),
                ft.Row([
                    ft.Text(config.API_BASE_URL, size=11, color="#6b7280", selectable=True),
                    ft.Container(
                        content=ft.Text(env_label, size=10, color=env_color),
                        bgcolor="#f3f4f6", border_radius=4,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    ),
                ], spacing=6, wrap=True),
                ft.Container(height=8),
                self._about_copy_btn,
            ], spacing=2),
            padding=12,
            bgcolor="white",
            border=ft.border.all(1, "#e5e7eb"),
            border_radius=8,
        )

        return ft.Container(
            content=ft.Column([
                ft.Text("Settings", size=14, weight=ft.FontWeight.BOLD),
                ft.Container(height=4),
                hw_card,
                ft.Container(height=12),
                ft.Text("Recording", size=12, weight=ft.FontWeight.BOLD),
                self.settings_tier_dropdown,
                self.settings_status,
                ft.Container(height=12),
                explainer,
                ft.Container(height=12),
                about_card,
            ], spacing=2),
        )

    def _copy_app_info(self, info):
        """Copy a one-shot diagnostics snapshot to the clipboard."""
        env_label = "BETA" if config.DEBUG else "PRODUCTION"
        user_email = self.api.email if self.api and self.api.email else "—"
        text = (
            f"Bicentra Desktop v{config.APP_VERSION}\n"
            f"User: {user_email}\n"
            f"API: {config.API_BASE_URL} ({env_label})\n"
            f"Platform: {info.label()}"
        )
        try:
            self.page.set_clipboard(text)
        except Exception:
            return
        if self._about_copy_btn is None:
            return
        self._about_copy_btn.text = "✓ Copied!"
        self.page.update()
        # Revert to original label after 1.5s
        def revert():
            try:
                if self._about_copy_btn is not None:
                    self._about_copy_btn.text = "📋 Copy app info"
                    self.page.update()
            except Exception:
                pass
        threading.Timer(1.5, revert).start()

    def _tier_status_label(self, choice: str, recommended: str) -> str:
        if choice == "auto":
            params = sysinfo.tier_settings(recommended)
            if recommended == sysinfo.TIER_OFF:
                return "Auto: recording disabled."
            return (
                f"Auto-resolved to {recommended} — "
                f"{params['fps']} fps, "
                f"{params['max_size'][0]}×{params['max_size'][1]}, "
                f"max {params['max_frames']} frames."
            )
        if choice == sysinfo.TIER_OFF:
            return "Recording is off. No screenshots or video will be uploaded."
        params = sysinfo.tier_settings(choice)
        return (
            f"Manual: {choice} — "
            f"{params['fps']} fps, "
            f"{params['max_size'][0]}×{params['max_size'][1]}, "
            f"max {params['max_frames']} frames."
        )

    def _on_tier_change(self, e):
        new_value = e.control.value or "auto"
        s = settings_store.load()
        s["video_tier"] = new_value
        settings_store.save(s)
        self._refresh_settings_status()

    def _refresh_settings_status(self):
        if not self.settings_status or not self.settings_tier_dropdown:
            return
        choice = self.settings_tier_dropdown.value or "auto"
        recommended = sysinfo.recommend_tier()
        self.settings_status.value = self._tier_status_label(choice, recommended)
        self.settings_status.color = "#6b7280"
        self.page.update()

    # ─────────────────────────────────────────────────────────
    # Logout
    # ─────────────────────────────────────────────────────────
    def _confirm_logout(self):
        """Open a confirmation dialog before actually logging out."""
        if self.running or self.recording:
            # Don't allow logout mid-run; show a small dialog
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Can't sign out right now", size=ui.FONT_LG, weight=ft.FontWeight.W_600),
                content=ft.Text(
                    "A flow is currently active. Stop it first, then try again.",
                    size=ui.FONT_BASE,
                    color=ui.TEXT_SECONDARY,
                ),
                actions=[
                    ui.ghost_button("OK", lambda e: self._close_dialog(dlg)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            self.page.open(dlg)
            return

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Sign out?", size=ui.FONT_LG, weight=ft.FontWeight.W_600),
            content=ft.Text(
                "You'll need to enter your email and password again to sign back in.",
                size=ui.FONT_BASE,
                color=ui.TEXT_SECONDARY,
            ),
            actions=[
                ui.ghost_button("Cancel", lambda e: self._close_dialog(dlg)),
                ui.destructive_button("Sign out", lambda e: self._do_logout(dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _close_dialog(self, dlg):
        self.page.close(dlg)

    def _do_logout(self, dlg):
        self.page.close(dlg)
        self.api.logout()
        self.on_logout()

    # Back-compat alias (used in a couple of older code paths)
    def _logout(self):
        self._confirm_logout()

    # ─────────────────────────────────────────────────────────
    # Flow loading
    # ─────────────────────────────────────────────────────────
    def load_flows_async(self):
        """Load every available flow across every PMS.

        The backend's `/api/desktop/flows/?pms=X` endpoint returns the
        combined "available flows for PMS X" (system YAML flows + the org's
        DB-saved flows scoped to that PMS), so we fan out across every PMS
        we know about and dedupe by (name, pms). That way the Run page
        shows the union of all flows the user could ever pick from.
        """
        if self.flow_list_column:
            self.flow_list_column.controls.clear()
            self.flow_list_column.controls.append(ui.loading_state("Loading flows…"))
            self.page.update()

        def fetch_all():
            all_flows: list[dict] = []
            seen: set[tuple] = set()
            for pms_key, _label in PMS_OPTIONS:
                try:
                    chunk = self.api.list_flows(pms_key) or []
                except Exception as e:
                    logger.error(f"list_flows({pms_key}) failed: {e}")
                    chunk = []
                for flow in chunk:
                    # Backend may omit `pms` on individual rows; backfill it.
                    if not flow.get("pms"):
                        flow["pms"] = pms_key
                    key = (flow.get("name"), flow.get("pms") or pms_key)
                    if key in seen:
                        continue
                    seen.add(key)
                    all_flows.append(flow)
            all_flows.sort(
                key=lambda f: (f.get("display_name") or f.get("name") or "").lower()
            )
            self.flows = all_flows
            self._render_flow_list()

        threading.Thread(target=fetch_all, daemon=True).start()

    def _selected_flow(self) -> dict | None:
        return self.selected_flow

    # ─────────────────────────────────────────────────────────
    # Running a flow
    # ─────────────────────────────────────────────────────────
    def _collect_inputs(self) -> tuple[dict, str | None]:
        flow = self._selected_flow()
        if not flow:
            return {}, "No flow selected"

        values = {}
        for inp in flow.get("inputs", []):
            name = inp.get("name", "")
            inp_type = inp.get("type", "string")
            label = inp.get("label", name)
            widget = self.input_fields.get(name)
            raw = getattr(widget, "value", None)
            val = (raw if isinstance(raw, str) else (str(raw) if raw is not None else "")).strip()

            if inp.get("required") and not val:
                return {}, f"Required: {label}"

            if inp_type == "number" and val:
                try:
                    float(val)  # validate parseable
                except ValueError:
                    return {}, f"{label} must be a number"

            values[name] = val

        # Save as last-used for next time
        store = _load_input_store()
        flow_key = f"{flow.get('pms', '')}::{flow.get('name', '')}"
        store[flow_key] = values
        _save_input_store(store)

        return values, None

    def _log(self, text: str):
        self.log_view.controls.append(
            ft.Text(text, size=11, font_family="Courier", selectable=True)
        )
        self.page.update()

    def _debug_log(self, text: str):
        if config.DEBUG:
            self._log(f"  [DEBUG] {text}")

    def _copy_logs(self):
        content = "\n".join(
            c.value for c in self.log_view.controls if hasattr(c, "value")
        )
        self.page.set_clipboard(content)

    def _status(self, text: str, color: str = "#6b7280"):
        self.status_text.value = text
        self.status_text.color = color
        self.page.update()

    def _start_run(self):
        flow = self._selected_flow()
        if not flow:
            self._status("Please select a flow", "#dc2626")
            return
        inputs, err = self._collect_inputs()
        if err:
            self._status(err, "#dc2626")
            return

        # Show app picker before running
        self._show_app_picker(flow, inputs)

    def _show_app_picker(self, flow: dict, inputs: dict):
        """Ask the user which app the flow should target before running."""
        # Suggested target from the flow itself
        suggested = flow.get("target_app_name", "") or ""

        # Get current app list
        apps = win_mod.list_apps()
        app_names = [a["name"] for a in apps]

        # If suggested app isn't in the list right now, warn but allow user to refresh
        warning_text = ""
        if suggested and suggested not in app_names:
            warning_text = f"⚠ Recommended app '{suggested}' isn't running. Open it first."

        # Pre-select suggested if available, otherwise first
        default_value = suggested if suggested in app_names else (app_names[0] if app_names else "")

        if not app_names:
            app_dropdown = ft.Text("No apps found. Make sure your PMS is open.", color="#dc2626")
            value_holder = {"value": ""}
        else:
            value_holder = {"value": default_value}

            def on_change(e):
                value_holder["value"] = e.control.value

            app_dropdown = ft.Dropdown(
                label="Target App",
                value=default_value,
                options=[ft.dropdown.Option(key=n, text=n) for n in app_names],
                on_change=on_change,
                border_radius=8, height=48,
            )

        warning_widget = ft.Text(
            warning_text, color="#92400e", size=11,
        ) if warning_text else ft.Container()

        suggestion_text = (
            f"Recommended: {suggested}" if suggested else
            "No recommended app saved with this flow."
        )

        def on_continue(e):
            chosen_app = value_holder.get("value", "").strip()
            if not chosen_app:
                return
            self.page.close(picker_dlg)
            self._actually_start_run(flow, inputs, chosen_app)

        def on_refresh(e):
            new_apps = win_mod.list_apps()
            new_names = [a["name"] for a in new_apps]
            if hasattr(app_dropdown, "options"):
                app_dropdown.options = [ft.dropdown.Option(key=n, text=n) for n in new_names]
                # Re-pick suggested if it appeared
                if suggested and suggested in new_names:
                    app_dropdown.value = suggested
                    value_holder["value"] = suggested
                self.page.update()

        def on_cancel(e):
            self.page.close(picker_dlg)

        picker_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Which app should the flow run in?"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(suggestion_text, size=12, color="#6b7280"),
                    warning_widget,
                    ft.Container(height=8),
                    app_dropdown,
                    ft.Container(height=8),
                    ft.Text(
                        "Bicentra will focus the chosen app, then start the flow.",
                        size=11, color="#6b7280",
                    ),
                ], spacing=4, tight=True),
                width=400,
            ),
            actions=[
                ft.TextButton("Refresh", on_click=on_refresh),
                ft.TextButton("Cancel", on_click=on_cancel),
                ft.ElevatedButton(
                    "Continue", on_click=on_continue,
                    style=ft.ButtonStyle(
                        bgcolor="#16a34a", color="white",
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self.page.open(picker_dlg)

    def _actually_start_run(self, flow: dict, inputs: dict, target_app: str):
        """Called after user confirms target app."""
        self.running = True
        self.run_btn.disabled = True
        self.stop_btn.disabled = False
        self.log_view.controls.clear()
        self._status(f"Focusing {target_app}...", "#2563eb")
        self._log(f"Flow: {flow.get('display_name')}")
        self._log(f"Target app: {target_app}")
        if inputs:
            self._log(f"Inputs: {inputs}")
        self._log("")

        # Focus the chosen app
        ok = win_mod.focus_app(target_app)
        if ok:
            self._log(f"✓ Focused {target_app}")
        else:
            self._log(f"⚠ Could not focus {target_app} — flow will run on current screen")

        pms_software = flow.get("pms") or flow.get("pms_software") or ""
        threading.Thread(
            target=self._run_loop,
            args=(pms_software, flow["name"], inputs),
            daemon=True,
        ).start()

    def _stop_run(self):
        self.running = False
        self._status("Stopping...", "#f59e0b")
        if self.session_id:
            threading.Thread(
                target=self.api.cancel_session, args=(self.session_id,), daemon=True
            ).start()

    def _reset_run_ui(self):
        self.running = False
        self.session_id = None
        self.run_btn.disabled = False
        self.stop_btn.disabled = True
        self.page.update()

    def _fire_and_forget(self, fn, *args, **kwargs):
        """Run a callable in a daemon thread. Errors are swallowed (logged)."""
        def runner():
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.error(f"background task failed: {fn.__name__}: {e}")
        threading.Thread(target=runner, daemon=True).start()

    def _stash_screenshot(self, step_number: int, png_bytes: bytes):
        """Cap memory: drop oldest if over budget."""
        self._step_screenshots.append((step_number, png_bytes))
        if len(self._step_screenshots) > self._max_screenshots:
            self._step_screenshots.pop(0)

    def _finalize_session_video(self, session_id: str, tier: str):
        """Build a slideshow MP4 from cached frames, upload, then clear cache."""
        frames = self._step_screenshots
        if not frames or tier == sysinfo.TIER_OFF:
            self._step_screenshots = []
            return
        params = sysinfo.tier_settings(tier)
        fps = params.get("fps") or 2
        max_size = params.get("max_size") or (1280, 720)
        try:
            t0 = time.monotonic()
            mp4 = build_slideshow(frames, fps=fps, max_size=max_size)
            duration_ms = int(len(frames) * 1000 / max(1, fps))
            logger.debug(
                f"Built slideshow video [{tier}]: {len(mp4)} bytes from "
                f"{len(frames)} frames in {int((time.monotonic() - t0) * 1000)} ms"
            )
            if mp4:
                self.api.upload_session_video(session_id, mp4, duration_ms=duration_ms)
        except Exception as e:
            logger.error(f"Failed to build/upload session video: {e}")
        finally:
            self._step_screenshots = []

    def _run_loop(self, pms_key, flow_name, inputs):
        import pyautogui
        screen_w, screen_h = pyautogui.size()
        self._debug_log(f"Screen size: {screen_w}x{screen_h}")

        # Resolve recording tier from settings (per-machine).
        active_tier = settings_store.get_video_tier()
        tier_params = sysinfo.tier_settings(active_tier)
        record_enabled = active_tier != sysinfo.TIER_OFF
        self._max_screenshots = tier_params.get("max_frames", 200) or 200
        self._debug_log(
            f"Recording tier: {active_tier} "
            f"(fps={tier_params.get('fps')}, "
            f"max_size={tier_params.get('max_size')}, "
            f"max_frames={self._max_screenshots})"
        )

        # Reset frame buffer for this run
        self._step_screenshots = []

        session, error = self.api.create_session(
            pms_software=pms_key, flow_name=flow_name, flow_inputs=inputs,
        )
        if not session:
            self._status("Failed to create session", "#dc2626")
            self._log(f"✗ Failed:\n  {error}")
            self._reset_run_ui()
            return

        self.session_id = session["id"]
        self._log(f"Session: {self.session_id}\n")

        step = 0
        while self.running:
            step += 1
            self._status(f"Step {step}...", "#2563eb")

            # Capture a screenshot up-front so we can both upload it
            # for this step and add it to the slideshow video.
            # Skipped entirely when recording is OFF (saves CPU + bandwidth).
            png_bytes: bytes = b""
            if record_enabled:
                try:
                    png_bytes, _, _ = take_screenshot_bytes()
                except Exception as e:
                    logger.error(f"screenshot failed: {e}")
                    png_bytes = b""

            # Always send screen size so backend converts pct -> pixels
            result = self.api.next_step(
                self.session_id,
                screen_width=screen_w, screen_height=screen_h,
            )
            if not self.running or result is None:
                break

            action_type = result.get("action_type", "failed")
            reason = result.get("reason", "")
            action_id = result.get("id")
            action_step = result.get("step_number") or step

            # Upload screenshot for this action (fire-and-forget)
            if action_id and png_bytes:
                self._fire_and_forget(
                    self.api.upload_action_screenshot,
                    self.session_id, action_id, png_bytes,
                )
                self._stash_screenshot(action_step, png_bytes)

            line = f"Step {step}: {action_type}"
            if action_type in ("click", "double_click", "right_click"):
                line += f" at ({result.get('x')}, {result.get('y')})"
            if action_type == "type":
                line += f' "{result.get("text", "")[:40]}"'
            if action_type == "hotkey":
                line += f" {'+'.join(result.get('keys', []))}"
            if action_type == "key":
                line += f" {result.get('key', '')}"
            self._log(line)
            if reason:
                self._log(f"  → {reason[:120]}")

            if action_type == "done":
                self._status(f"✓ {reason[:60]}", "#16a34a")
                self._log("\n✓ Completed!")
                break
            if action_type == "failed":
                self._status(f"✗ {reason[:60]}", "#dc2626")
                self._log(f"\n✗ Failed: {reason}")
                break

            self._status(f"Step {step} — {action_type}", "#f59e0b")

            # Time the actual execution + report it
            t_exec = time.monotonic()
            exec_status, exec_error = "executed", ""
            try:
                execute_action(result)
            except Exception as e:
                exec_status, exec_error = "failed", str(e)
                logger.error(f"execute_action failed at step {step}: {e}")

            if action_id:
                self._fire_and_forget(
                    self.api.report_action_executed,
                    self.session_id, action_id,
                    None,
                    int((time.monotonic() - t_exec) * 1000),
                    exec_status,
                    exec_error,
                )

            time.sleep(config.SCREENSHOT_INTERVAL)

            if step >= config.MAX_STEPS:
                self._log("\n⚠ Max steps reached")
                self.api.cancel_session(self.session_id)
                break

        # Finalize: build slideshow video and upload (background thread).
        # Even if run was cancelled or stopped, capture what we have.
        session_id_at_finalize = self.session_id
        if session_id_at_finalize and record_enabled:
            self._fire_and_forget(
                self._finalize_session_video, session_id_at_finalize, active_tier,
            )
        else:
            # Drop any cached frames if recording is disabled
            self._step_screenshots = []

        self._reset_run_ui()

    # ─────────────────────────────────────────────────────────
    # Recording
    # ─────────────────────────────────────────────────────────
    def _toggle_recording(self):
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        name = (self.rec_name.value or "").strip()
        display = (self.rec_display.value or "").strip()

        if not name or not display:
            self.rec_status.value = "Name and Display Name are required"
            self.rec_status.color = "#dc2626"
            self.page.update()
            return

        if not name.replace("_", "").isalnum():
            self.rec_status.value = "Name must be letters, numbers, underscores only"
            self.rec_status.color = "#dc2626"
            self.page.update()
            return

        self.recorder = Recorder(on_stop=self._on_recorder_stopped)
        self.recorder.start()
        self.recording = True
        self._finalize_lock = threading.Lock()

        self.rec_btn.text = "■  Stop Recording"
        self.rec_btn.style = ft.ButtonStyle(
            bgcolor="#6b7280", color="white",
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        self.rec_status.value = "● RECORDING — switch to your PMS and perform the task"
        self.rec_status.color = "#dc2626"
        self.page.update()
        # Start a polling loop that updates event count AND waits for recorder to stop
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _stop_recording(self):
        if self.recorder:
            self.recorder.stop()

    def _on_recorder_stopped(self):
        """Called from recorder thread when stop is triggered (button or hotkey)."""
        self._finalize_recording()

    def _poll_loop(self):
        """Polls in a single background thread — updates event count live."""
        while self.recording and self.recorder and self.recorder.running:
            try:
                self.rec_event_count.value = f"Captured: {len(self.recorder.events)} events"
                self.page.update()
            except Exception:
                pass
            time.sleep(0.3)
        # Recorder has stopped (via hotkey) but we may not have finalized yet
        if self.recording:
            self._finalize_recording()

    def _finalize_recording(self):
        # Thread-safe: only the first caller wins
        lock = getattr(self, "_finalize_lock", None)
        if lock:
            if not lock.acquire(blocking=False):
                return
        try:
            if not self.recording:
                return
            self.recording = False
        finally:
            if lock:
                lock.release()

        self.rec_btn.text = "● Start Recording"
        self.rec_btn.style = ft.ButtonStyle(
            bgcolor="#dc2626", color="white",
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        self.rec_status.value = "Recording stopped"
        self.rec_status.color = "#6b7280"
        try:
            self.page.update()
        except Exception as e:
            logger.error(f"page.update failed: {e}")

        if not self.recorder:
            return
        steps = self.recorder.get_flow_steps()
        logger.debug(f"Recorded {len(steps)} steps")

        if not steps:
            self.rec_status.value = "No actions were captured — try again."
            self.rec_status.color = "#f59e0b"
            self.rec_event_count.value = ""
            self.page.update()
            return

        metadata = {
            "name": (self.rec_name.value or "").strip(),
            "display_name": (self.rec_display.value or "").strip(),
            "description": (self.rec_desc.value or "").strip(),
            "pms_software": self.rec_pms_value,
            "screen_width": self.recorder.screen_width,
            "screen_height": self.recorder.screen_height,
            "target_app_name": self.recorder.target_app_name,
        }
        try:
            self._open_review_dialog(metadata, steps)
        except Exception as e:
            logger.error(f"Failed to open review dialog: {e}", exc_info=True)
            self.rec_status.value = f"Error opening review: {e}"
            self.rec_status.color = "#dc2626"
            self.page.update()

    def _show_snackbar(self, message: str, color: str = "#2563eb"):
        snack = ft.SnackBar(
            content=ft.Text(message, color="white"),
            bgcolor=color,
        )
        self.page.open(snack)

    # ─────────────────────────────────────────────────────────
    # Review dialog
    # ─────────────────────────────────────────────────────────
    def _open_review_dialog(self, metadata: dict, steps: list[dict]):
        ReviewDialog(
            page=self.page,
            api=self.api,
            metadata=metadata,
            steps=steps,
            on_saved=self._on_flow_saved,
        ).show()

    def _on_flow_saved(self):
        # Clear form, switch to Run tab, reload flows
        self.rec_name.value = ""
        self.rec_display.value = ""
        self.rec_desc.value = ""
        self.rec_status.value = "✓ Flow saved"
        self.rec_status.color = "#16a34a"
        self.rec_event_count.value = ""
        # Switch to Run page (new sidebar nav)
        self._on_nav_change("run")
        self.page.update()
        self.load_flows_async()


# ════════════════════════════════════════════════════════════
# Review dialog
# ════════════════════════════════════════════════════════════

class ReviewDialog:
    def __init__(self, page: ft.Page, api: BicentraAPI, metadata: dict, steps: list[dict], on_saved):
        self.page = page
        self.api = api
        self.metadata = metadata
        self.steps = steps
        self.on_saved = on_saved
        self.inputs_schema: list[dict] = []
        self.dialog: ft.AlertDialog | None = None
        self.steps_column: ft.Column | None = None
        self.inputs_text: ft.Text | None = None
        self.save_btn: ft.ElevatedButton | None = None
        self.error_text: ft.Text | None = None

    def show(self):
        self.steps_column = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=360)
        self.inputs_text = ft.Text("Inputs: (none — flow has no variables)",
                                    size=11, color="#6b7280")
        self.error_text = ft.Text(
            "", size=11, color="#dc2626", visible=False, selectable=True,
        )
        # Render steps AFTER inputs_text exists (it accesses inputs_text.value)
        self._render_steps()

        self.save_btn = ft.ElevatedButton(
            "💾 Save Flow",
            on_click=lambda e: self._save(),
            style=ft.ButtonStyle(
                bgcolor="#16a34a", color="white",
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        target_app = self.metadata.get("target_app_name") or "(no target app captured)"
        title_lines = [
            ft.Text(self.metadata["display_name"], size=18, weight=ft.FontWeight.BOLD),
            ft.Text(f"{len(self.steps)} steps captured — review and save",
                    size=11, color="#6b7280"),
            ft.Text(f"Target app: {target_app}",
                    size=11, color="#1e40af"),
        ]
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Column(title_lines, spacing=2, tight=True),
            content=ft.Container(
                content=ft.Column([
                    ft.Container(
                        content=self.steps_column,
                        border=ft.border.all(1, "#e5e7eb"),
                        border_radius=8,
                        padding=8,
                    ),
                    ft.Container(height=8),
                    self.inputs_text,
                    ft.Container(height=4),
                    self.error_text,
                ], spacing=0),
                width=600,
            ),
            actions=[
                ft.TextButton(
                    "Cancel",
                    on_click=lambda e: self._close(),
                ),
                self.save_btn,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(self.dialog)

    def _close(self):
        if self.dialog:
            self.page.close(self.dialog)

    def _render_steps(self):
        self.steps_column.controls.clear()
        for i, step in enumerate(self.steps):
            row_controls: list[ft.Control] = [
                ft.Text(f"{i + 1}.", width=28, size=11, weight=ft.FontWeight.BOLD, color="#9ca3af"),
                ft.Text(self._step_description(step), size=11, expand=True),
            ]
            if step.get("action") == "type" and not step.get("_is_variable"):
                row_controls.append(
                    ft.TextButton(
                        "→ Variable",
                        on_click=lambda e, idx=i: self._parameterize(idx),
                        style=ft.ButtonStyle(color="#1e40af"),
                    )
                )
            row_controls.append(
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=16,
                    icon_color="#dc2626",
                    on_click=lambda e, idx=i: self._delete_step(idx),
                )
            )
            self.steps_column.controls.append(
                ft.Container(
                    content=ft.Row(row_controls, alignment=ft.MainAxisAlignment.START),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    bgcolor="#f9fafb",
                    border_radius=6,
                )
            )
        self._update_inputs_label()
        try:
            self.page.update()
        except Exception:
            pass

    def _step_description(self, step: dict) -> str:
        action = step.get("action", "?")
        x_pct = step.get("x", 0) * 100
        y_pct = step.get("y", 0) * 100
        if action == "click_pct":
            return f"CLICK at ({x_pct:.1f}%, {y_pct:.1f}%)"
        if action == "double_click_pct":
            return f"DOUBLE-CLICK at ({x_pct:.1f}%, {y_pct:.1f}%)"
        if action == "right_click_pct":
            return f"RIGHT-CLICK at ({x_pct:.1f}%, {y_pct:.1f}%)"
        if action == "scroll":
            amt = step.get("scroll_amount", 0)
            direction = "up" if amt > 0 else "down"
            return f"SCROLL {direction} ({abs(amt)}) at ({x_pct:.1f}%, {y_pct:.1f}%)"
        if action == "type":
            text = step.get("text", "")
            if step.get("_is_variable"):
                return f"TYPE variable: {text}"
            return f'TYPE "{text[:60]}"'
        if action == "key":
            return f"KEY {step.get('key', '')}"
        if action == "hotkey":
            return f"HOTKEY {'+'.join(step.get('keys', []))}"
        if action == "wait":
            return f"WAIT {step.get('delay', 0)}s"
        return action.upper()

    def _parameterize(self, idx: int):
        step = self.steps[idx]
        current_text = step.get("text", "")

        name_field = ft.TextField(
            label="Variable name (slug)",
            hint_text="first_name",
            autofocus=True,
        )
        label_field = ft.TextField(
            label="Display label",
            hint_text="First Name",
        )
        type_dropdown = ft.Dropdown(
            label="Type",
            value="string",
            options=[
                ft.dropdown.Option(key="string", text="Single line text"),
                ft.dropdown.Option(key="longtext", text="Multi-line text"),
                ft.dropdown.Option(key="number", text="Number"),
                ft.dropdown.Option(key="choice", text="Choice (dropdown)"),
            ],
        )
        default_field = ft.TextField(
            label="Default value (optional)",
            value=current_text,
        )
        choices_field = ft.TextField(
            label="Choices (one per line, only for Choice type)",
            multiline=True,
            min_lines=2, max_lines=4,
            visible=False,
        )

        def on_type_change(e):
            choices_field.visible = type_dropdown.value == "choice"
            self.page.update()
        type_dropdown.on_change = on_type_change

        def on_ok(e):
            name = (name_field.value or "").strip().replace(" ", "_").lower()
            if not name or not name.replace("_", "").isalnum():
                name_field.error_text = "Letters, numbers, underscores only"
                self.page.update()
                return

            label = (label_field.value or "").strip() or name.replace("_", " ").title()
            var_type = type_dropdown.value or "string"
            default = (default_field.value or "").strip()

            choices: list[str] = []
            if var_type == "choice":
                raw = (choices_field.value or "").strip()
                choices = [c.strip() for c in raw.split("\n") if c.strip()]
                if len(choices) < 2:
                    choices_field.error_text = "Provide at least 2 choices"
                    self.page.update()
                    return

            step["text"] = "{{" + name + "}}"
            step["_is_variable"] = True
            step["_variable_name"] = name
            step["_original_text"] = current_text

            # Replace existing input definition or add new
            self.inputs_schema = [i for i in self.inputs_schema if i.get("name") != name]
            input_def = {
                "name": name,
                "label": label,
                "type": var_type,
                "placeholder": current_text[:50],
                "required": True,
                "default": default,
            }
            if var_type == "choice":
                input_def["choices"] = choices
            self.inputs_schema.append(input_def)

            self.page.close(var_dlg)
            self._render_steps()

        def close_var(e):
            self.page.close(var_dlg)

        var_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Make Variable"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f'Replace "{current_text[:50]}" with a variable.', size=12),
                    ft.Container(height=8),
                    name_field,
                    label_field,
                    type_dropdown,
                    default_field,
                    choices_field,
                ], tight=True, scroll=ft.ScrollMode.AUTO),
                width=420,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=close_var),
                ft.ElevatedButton("OK", on_click=on_ok),
            ],
        )
        self.page.open(var_dlg)

    def _delete_step(self, idx: int):
        del self.steps[idx]
        self._render_steps()

    def _update_inputs_label(self):
        if self.inputs_schema:
            names = ", ".join(i["name"] for i in self.inputs_schema)
            self.inputs_text.value = f"Inputs: {names}"
        else:
            self.inputs_text.value = "Inputs: (none — flow has no variables)"

    def _save(self):
        logger.info(f"ReviewDialog._save: name={self.metadata.get('name')!r}")
        clean_steps = []
        for s in self.steps:
            clean = {k: v for k, v in s.items() if not k.startswith("_")}
            clean_steps.append(clean)
        if clean_steps and clean_steps[-1].get("action") != "done":
            clean_steps.append({"action": "done", "reason": "Flow completed"})

        payload = {
            "name": self.metadata["name"],
            "display_name": self.metadata["display_name"],
            "description": self.metadata["description"],
            "pms_software": self.metadata["pms_software"],
            "inputs": self.inputs_schema,
            "steps": clean_steps,
            "recorded_screen_width": self.metadata["screen_width"],
            "recorded_screen_height": self.metadata["screen_height"],
            "target_app_name": self.metadata.get("target_app_name", ""),
        }

        self.save_btn.disabled = True
        self.save_btn.text = "Saving..."
        self._set_error("")
        self.page.update()

        def show_error(msg: str):
            """Re-enable Save, surface the error inline on the dialog so
            the operator can fix the issue and click Save again."""
            try:
                self.save_btn.disabled = False
                self.save_btn.text = "💾 Save Flow"
                self._set_error(msg)
                self.page.update()
            except Exception as exc:
                logger.error(f"show_error itself crashed: {exc}", exc_info=True)

        def do_save():
            try:
                flow, error = self.api.create_flow(payload)
            except Exception as exc:
                # api_client.create_flow should never raise — but if a future
                # regression creeps in, this guard makes sure the user sees
                # something instead of a stuck "Saving…" button.
                logger.error(f"create_flow unexpected exception: {exc}", exc_info=True)
                show_error(f"Unexpected error: {exc}")
                return

            if flow:
                logger.info(f"Flow saved: id={flow.get('id')} name={flow.get('name')!r}")
                try:
                    self._close()
                except Exception as exc:
                    logger.error(f"_close after save crashed: {exc}", exc_info=True)
                try:
                    self.on_saved()
                except Exception as exc:
                    logger.error(f"on_saved callback crashed: {exc}", exc_info=True)
            else:
                logger.warning(f"create_flow rejected: {error}")
                show_error(error or "Unknown save failure")

        threading.Thread(target=do_save, daemon=True).start()

    def _set_error(self, msg: str):
        """Show/hide the inline error label inside the review dialog."""
        if not getattr(self, "error_text", None):
            return
        self.error_text.value = msg
        self.error_text.visible = bool(msg)


# ════════════════════════════════════════════════════════════
# Session detail dialog (history viewer)
# ════════════════════════════════════════════════════════════

PMS_LABELS_LOOKUP = {k: label for k, label in PMS_OPTIONS}


def _format_dt(s: str | None) -> str:
    if not s:
        return "—"
    return s[:19].replace("T", " ")


def _format_duration(ms: int | None) -> str:
    if not ms:
        return "—"
    if ms < 1000:
        return f"{ms} ms"
    return f"{ms / 1000:.1f}s"


class SessionDetailDialog:
    """Modal dialog showing a single session's full step timeline."""

    def __init__(self, page: ft.Page, api: BicentraAPI, session_id: str, on_deleted=None):
        self.page = page
        self.api = api
        self.session_id = session_id
        self.on_deleted = on_deleted
        self.dialog: ft.AlertDialog | None = None
        self.detail: dict | None = None

    def show(self):
        # Show a quick "loading" dialog, fetch in background, then swap content
        loading = ft.ProgressRing(width=24, height=24, stroke_width=2)
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Loading session..."),
            content=ft.Container(content=loading, width=400, height=80,
                                 alignment=ft.alignment.center),
            actions=[ft.TextButton("Cancel", on_click=lambda e: self._close())],
        )
        self.page.open(self.dialog)

        def fetch():
            try:
                self.detail = self.api.get_session_detail(self.session_id)
            except Exception as exc:
                logger.error(f"get_session_detail failed: {exc}")
                self.detail = None
            self._render()

        threading.Thread(target=fetch, daemon=True).start()

    def _close(self):
        if self.dialog:
            self.page.close(self.dialog)

    def _render(self):
        if not self.detail:
            self.dialog.title = ft.Text("Failed to load session")
            self.dialog.content = ft.Text("Could not fetch session details. Check your connection.")
            self.dialog.actions = [ft.TextButton("Close", on_click=lambda e: self._close())]
            self.page.update()
            return

        d = self.detail
        sid = d.get("id", "")
        display = d.get("flow_display_name") or d.get("flow_name") or "Untitled flow"
        pms = PMS_LABELS_LOOKUP.get(d.get("pms_software", ""), d.get("pms_software", ""))
        status = d.get("status", "")
        status_color = {
            "active": "#2563eb", "completed": "#16a34a",
            "failed": "#dc2626", "cancelled": "#6b7280",
        }.get(status, "#374151")
        started = _format_dt(d.get("started_at"))
        ended = _format_dt(d.get("ended_at"))
        duration = _format_duration(d.get("duration_ms"))
        steps = d.get("step_count", 0)
        err = d.get("error_message")
        video_url = d.get("video_url")
        actions = d.get("actions") or []

        # Header section
        header_rows = [
            ft.Row([
                ft.Text(display, size=18, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Text(status, size=11, color=status_color, weight=ft.FontWeight.BOLD),
                    bgcolor="#f3f4f6", border_radius=4,
                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                ),
            ]),
            ft.Text(f"Session id: {sid}", size=10, color="#9ca3af", selectable=True),
            ft.Row([
                ft.Text(f"PMS: {pms}", size=11, color="#6b7280"),
                ft.Text(f"  •  {steps} steps", size=11, color="#6b7280"),
                ft.Text(f"  •  {duration}", size=11, color="#6b7280"),
            ]),
            ft.Text(f"Started: {started}    Ended: {ended}", size=11, color="#6b7280"),
        ]
        if err:
            header_rows.append(ft.Container(
                content=ft.Text(err, size=11, color="#7f1d1d", selectable=True),
                bgcolor="#fef2f2", border=ft.border.all(1, "#fecaca"),
                border_radius=6, padding=8,
            ))

        # Video section (if present)
        body_children: list[ft.Control] = list(header_rows)
        body_children.append(ft.Container(height=10))
        if video_url:
            body_children.append(ft.Text("Recording", size=12, weight=ft.FontWeight.BOLD))
            try:
                video_widget = ft.Video(
                    playlist=[ft.VideoMedia(video_url)],
                    autoplay=False,
                    show_controls=True,
                    width=560, height=320,
                )
                body_children.append(video_widget)
            except Exception:
                # Fallback: link button if Flet's Video isn't available
                body_children.append(ft.TextButton(
                    "Open video", icon=ft.Icons.PLAY_CIRCLE,
                    on_click=lambda e, u=video_url: self.page.launch_url(u),
                ))
            body_children.append(ft.Container(height=10))

        # Steps timeline
        body_children.append(ft.Text(f"Steps ({len(actions)})", size=12, weight=ft.FontWeight.BOLD))
        steps_col = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=320)
        for a in actions:
            step_n = a.get("step_number")
            atype = a.get("action_type", "")
            obs = a.get("ai_observation") or ""
            reason = a.get("reason") or ""
            ss_url = a.get("screenshot_url")
            dur_ms = a.get("duration_ms")
            status_str = a.get("status") or ""
            err_str = a.get("error") or ""

            line_text = f"{step_n}. {atype}"
            if atype in ("click", "double_click", "right_click"):
                line_text += f"  ({a.get('x')}, {a.get('y')})"
            elif atype == "type":
                line_text += f'  "{(a.get("text") or "")[:60]}"'
            elif atype == "hotkey":
                line_text += f"  {'+'.join(a.get('keys') or [])}"
            elif atype == "key":
                line_text += f"  {a.get('key', '')}"

            row_left = ft.Column([
                ft.Text(line_text, size=11, weight=ft.FontWeight.BOLD),
                *([ft.Text(f"👁 {obs[:140]}", size=10, color="#6b7280")] if obs else []),
                *([ft.Text(f"→ {reason[:120]}", size=10, color="#6b7280")] if reason else []),
                *([ft.Text(f"⚠ {err_str[:120]}", size=10, color="#dc2626")] if err_str else []),
                ft.Row([
                    ft.Text(_format_duration(dur_ms), size=10, color="#9ca3af"),
                    ft.Text(f"  •  {status_str}", size=10, color="#9ca3af"),
                ]),
            ], spacing=2, expand=True)

            row_children: list[ft.Control] = [row_left]
            if ss_url:
                row_children.append(ft.Image(
                    src=ss_url, width=80, height=50, fit=ft.ImageFit.COVER,
                    border_radius=4,
                ))

            steps_col.controls.append(ft.Container(
                content=ft.Row(row_children, alignment=ft.MainAxisAlignment.START, spacing=8),
                padding=8, bgcolor="#f9fafb", border_radius=6,
            ))
        body_children.append(ft.Container(
            content=steps_col, border=ft.border.all(1, "#e5e7eb"),
            border_radius=8, padding=4,
        ))

        # Build action buttons
        share_btn = ft.TextButton(
            "Share link", icon=ft.Icons.LINK,
            on_click=lambda e: self._share(),
        )
        export_btn = ft.TextButton(
            "Export JSON", icon=ft.Icons.DOWNLOAD,
            on_click=lambda e: self._export(),
        )
        delete_btn = ft.TextButton(
            "Delete", icon=ft.Icons.DELETE_OUTLINE,
            on_click=lambda e: self._delete(),
            style=ft.ButtonStyle(color="#dc2626"),
        )
        close_btn = ft.TextButton("Close", on_click=lambda e: self._close())

        self.dialog.title = ft.Text("Session detail", size=14, weight=ft.FontWeight.BOLD)
        self.dialog.content = ft.Container(
            content=ft.Column(body_children, spacing=4, scroll=ft.ScrollMode.AUTO),
            width=620,
        )
        self.dialog.actions = [share_btn, export_btn, delete_btn, close_btn]
        self.dialog.actions_alignment = ft.MainAxisAlignment.SPACE_BETWEEN
        self.page.update()

    def _share(self):
        def do_share():
            try:
                resp = self.api.share_session(self.session_id)
                url = (resp or {}).get("url", "")
                if url:
                    try:
                        self.page.set_clipboard(url)
                    except Exception:
                        pass
                    info = ft.AlertDialog(
                        modal=True,
                        title=ft.Text("Share link copied"),
                        content=ft.Container(
                            content=ft.Column([
                                ft.Text(
                                    "Anyone with this link can view this session (read-only).",
                                    size=11, color="#6b7280",
                                ),
                                ft.Container(height=6),
                                ft.TextField(value=url, read_only=True),
                            ], tight=True),
                            width=480,
                        ),
                        actions=[ft.TextButton(
                            "OK",
                            on_click=lambda e: self.page.close(info),
                        )],
                    )
                    self.page.open(info)
            except Exception as exc:
                logger.error(f"share_session failed: {exc}")

        threading.Thread(target=do_share, daemon=True).start()

    def _export(self):
        def do_export():
            try:
                data = self.api.export_session(self.session_id)
                if data is None:
                    return
                home = os.path.expanduser("~")
                downloads = os.path.join(home, "Downloads")
                target_dir = downloads if os.path.isdir(downloads) else home
                target = os.path.join(target_dir, f"session_{self.session_id}.json")
                with open(target, "w") as f:
                    json.dump(data, f, indent=2, default=str)
                info = ft.AlertDialog(
                    modal=True,
                    title=ft.Text("Exported"),
                    content=ft.Text(f"Saved to: {target}", size=11, selectable=True),
                    actions=[ft.TextButton(
                        "OK",
                        on_click=lambda e: self.page.close(info),
                    )],
                )
                self.page.open(info)
            except Exception as exc:
                logger.error(f"export_session failed: {exc}")

        threading.Thread(target=do_export, daemon=True).start()

    def _delete(self):
        def do_confirm_delete(e):
            self.page.close(confirm)

            def do_delete():
                try:
                    if self.api.delete_session(self.session_id):
                        self._close()
                        if self.on_deleted:
                            self.on_deleted()
                except Exception as exc:
                    logger.error(f"delete_session failed: {exc}")

            threading.Thread(target=do_delete, daemon=True).start()

        def cancel_delete(e):
            self.page.close(confirm)

        confirm = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete this session?"),
            content=ft.Text("This will hide the session from the History tab. You can restore it from admin."),
            actions=[
                ft.TextButton("Cancel", on_click=cancel_delete),
                ft.ElevatedButton(
                    "Delete", on_click=do_confirm_delete,
                    style=ft.ButtonStyle(bgcolor="#dc2626", color="white"),
                ),
            ],
        )
        self.page.open(confirm)


if __name__ == "__main__":
    ft.app(target=main, assets_dir="assets")
