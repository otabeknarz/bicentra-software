"""
Bicentra Desktop — shared UI primitives.

Centralized design tokens (colors, spacing, typography) and helper functions
for common widgets (cards, chips, headings, empty states, etc.). Every
screen in main.py should reach for these instead of inlining colour strings
and padding numbers — that's how we keep the desktop app visually
consistent without a real component library.

Inspired by the same "balanced dense" design language we use in the web
dashboard: white surfaces, gray-200 borders, one blue accent, no shadows
or gradients.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

import flet as ft


# ─────────────────────────────────────────────────────────────────────────────
# Color tokens
# ─────────────────────────────────────────────────────────────────────────────

# Surfaces
BG = "#f8fafc"            # page background (very light slate)
SURFACE = "#ffffff"       # card / panel background
SURFACE_SUBTLE = "#f9fafb"  # subtle gray surface (input bg, etc.)
SURFACE_HOVER = "#f3f4f6"   # hover background

# Borders
BORDER = "#e5e7eb"         # default border
BORDER_STRONG = "#d1d5db"  # emphasized border
BORDER_SUBTLE = "#f1f5f9"  # very subtle divider

# Text
TEXT_PRIMARY = "#111827"   # gray-900 — headings, body
TEXT_SECONDARY = "#4b5563"  # gray-600 — secondary
TEXT_MUTED = "#6b7280"     # gray-500 — captions, labels
TEXT_DISABLED = "#9ca3af"  # gray-400 — disabled, placeholders

# Accents
ACCENT = "#2563eb"         # blue-600 — primary action
ACCENT_HOVER = "#1d4ed8"   # blue-700 — pressed
ACCENT_SUBTLE = "#eff6ff"  # blue-50 — soft backgrounds

# Status
SUCCESS = "#16a34a"
SUCCESS_BG = "#f0fdf4"
WARNING = "#d97706"
WARNING_BG = "#fffbeb"
ERROR = "#dc2626"
ERROR_BG = "#fef2f2"
INFO = "#2563eb"
INFO_BG = "#eff6ff"


# ─────────────────────────────────────────────────────────────────────────────
# Spacing tokens (use these, not raw numbers)
# ─────────────────────────────────────────────────────────────────────────────

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24
SPACE_8 = 32

RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 10
RADIUS_FULL = 999


# ─────────────────────────────────────────────────────────────────────────────
# Typography
# ─────────────────────────────────────────────────────────────────────────────

FONT_XS = 11
FONT_SM = 12
FONT_BASE = 13
FONT_MD = 14
FONT_LG = 16
FONT_XL = 18
FONT_2XL = 22


def heading(
    text: str,
    size: str = "lg",
    color: str = TEXT_PRIMARY,
) -> ft.Text:
    """A page or section heading."""
    sizes = {"sm": FONT_MD, "md": FONT_LG, "lg": FONT_XL, "xl": FONT_2XL}
    return ft.Text(
        text,
        size=sizes.get(size, FONT_XL),
        weight=ft.FontWeight.W_600,
        color=color,
    )


def body(
    text: str,
    size: int = FONT_BASE,
    color: str = TEXT_PRIMARY,
    weight: ft.FontWeight = ft.FontWeight.NORMAL,
) -> ft.Text:
    """Body text."""
    return ft.Text(text, size=size, color=color, weight=weight)


def muted(text: str, size: int = FONT_BASE) -> ft.Text:
    """Muted text — captions, descriptions."""
    return ft.Text(text, size=size, color=TEXT_MUTED)


def caption(text: str) -> ft.Text:
    """Tiny uppercase tracking-wider label (section dividers)."""
    return ft.Text(
        text.upper(),
        size=FONT_XS,
        color=TEXT_MUTED,
        weight=ft.FontWeight.W_600,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Surfaces & layout helpers
# ─────────────────────────────────────────────────────────────────────────────

def card(
    content: ft.Control,
    padding: int = SPACE_4,
    bg: str = SURFACE,
    border_color: str = BORDER,
) -> ft.Container:
    """Standard card surface — white bg, light border, no shadow."""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=bg,
        border=ft.border.all(1, border_color),
        border_radius=RADIUS_MD,
    )


def section_header(
    title: str,
    description: Optional[str] = None,
    trailing: Optional[ft.Control] = None,
) -> ft.Control:
    """
    Section header with optional muted description and optional trailing
    action (e.g., a refresh button).
    """
    left = ft.Column(
        [caption(title)],
        spacing=SPACE_1,
        tight=True,
    )
    if description:
        left.controls.append(muted(description, size=FONT_BASE))
    if trailing:
        return ft.Row(
            [left, trailing],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )
    return left


# ─────────────────────────────────────────────────────────────────────────────
# Chips, badges, status
# ─────────────────────────────────────────────────────────────────────────────

_CHIP_VARIANTS = {
    "neutral": ("#f3f4f6", TEXT_SECONDARY),
    "success": (SUCCESS_BG, SUCCESS),
    "warning": (WARNING_BG, WARNING),
    "error": (ERROR_BG, ERROR),
    "info": (INFO_BG, INFO),
    "accent": (ACCENT_SUBTLE, ACCENT),
}


def chip(
    text: str,
    variant: str = "neutral",
    icon: Optional[str] = None,
) -> ft.Container:
    """Small inline label — used for PMS names, status counts, etc."""
    bg, fg = _CHIP_VARIANTS.get(variant, _CHIP_VARIANTS["neutral"])
    controls: list[ft.Control] = []
    if icon:
        controls.append(ft.Icon(icon, size=11, color=fg))
    controls.append(
        ft.Text(text, size=FONT_XS, weight=ft.FontWeight.W_600, color=fg)
    )
    return ft.Container(
        content=ft.Row(controls, spacing=4, tight=True),
        padding=ft.padding.symmetric(horizontal=6, vertical=2),
        bgcolor=bg,
        border_radius=RADIUS_SM,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Buttons
# ─────────────────────────────────────────────────────────────────────────────

_BUTTON_RADIUS = RADIUS_MD


def primary_button(
    text: str,
    on_click: Callable,
    icon: Optional[str] = None,
    disabled: bool = False,
    expand: bool = False,
) -> ft.ElevatedButton:
    return ft.ElevatedButton(
        text=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        expand=expand,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: ACCENT,
                ft.ControlState.HOVERED: ACCENT_HOVER,
                ft.ControlState.DISABLED: SURFACE_HOVER,
            },
            color={
                ft.ControlState.DEFAULT: "#ffffff",
                ft.ControlState.DISABLED: TEXT_DISABLED,
            },
            shape=ft.RoundedRectangleBorder(radius=_BUTTON_RADIUS),
            padding=ft.padding.symmetric(horizontal=SPACE_4, vertical=SPACE_3),
            text_style=ft.TextStyle(
                size=FONT_MD, weight=ft.FontWeight.W_500
            ),
            elevation=0,
        ),
    )


def secondary_button(
    text: str,
    on_click: Callable,
    icon: Optional[str] = None,
    disabled: bool = False,
    expand: bool = False,
) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        text=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        expand=expand,
        style=ft.ButtonStyle(
            bgcolor=SURFACE,
            color=TEXT_PRIMARY,
            side={
                ft.ControlState.DEFAULT: ft.BorderSide(1, BORDER),
                ft.ControlState.HOVERED: ft.BorderSide(1, BORDER_STRONG),
            },
            overlay_color=SURFACE_HOVER,
            shape=ft.RoundedRectangleBorder(radius=_BUTTON_RADIUS),
            padding=ft.padding.symmetric(horizontal=SPACE_4, vertical=SPACE_3),
            text_style=ft.TextStyle(
                size=FONT_MD, weight=ft.FontWeight.W_500
            ),
        ),
    )


def ghost_button(
    text: str,
    on_click: Callable,
    icon: Optional[str] = None,
    disabled: bool = False,
    color: str = TEXT_SECONDARY,
) -> ft.TextButton:
    return ft.TextButton(
        text=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            color=color,
            overlay_color=SURFACE_HOVER,
            shape=ft.RoundedRectangleBorder(radius=_BUTTON_RADIUS),
            padding=ft.padding.symmetric(horizontal=SPACE_3, vertical=SPACE_2),
            text_style=ft.TextStyle(
                size=FONT_MD, weight=ft.FontWeight.W_500
            ),
        ),
    )


def destructive_button(
    text: str,
    on_click: Callable,
    icon: Optional[str] = None,
    disabled: bool = False,
) -> ft.ElevatedButton:
    return ft.ElevatedButton(
        text=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: ERROR,
                ft.ControlState.HOVERED: "#b91c1c",
            },
            color="#ffffff",
            shape=ft.RoundedRectangleBorder(radius=_BUTTON_RADIUS),
            padding=ft.padding.symmetric(horizontal=SPACE_4, vertical=SPACE_3),
            text_style=ft.TextStyle(
                size=FONT_MD, weight=ft.FontWeight.W_500
            ),
            elevation=0,
        ),
    )


def icon_button(
    icon: str,
    on_click: Callable,
    tooltip: Optional[str] = None,
    size: int = 18,
    color: str = TEXT_SECONDARY,
) -> ft.IconButton:
    """Compact icon-only button."""
    return ft.IconButton(
        icon=icon,
        on_click=on_click,
        tooltip=tooltip,
        icon_size=size,
        icon_color=color,
        style=ft.ButtonStyle(
            overlay_color=SURFACE_HOVER,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            padding=ft.padding.all(SPACE_2),
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Form fields
# ─────────────────────────────────────────────────────────────────────────────

def text_field(
    label: Optional[str] = None,
    hint: Optional[str] = None,
    value: str = "",
    password: bool = False,
    multiline: bool = False,
    min_lines: int = 1,
    max_lines: int = 1,
    on_change: Optional[Callable] = None,
    autofocus: bool = False,
    prefix_icon: Optional[str] = None,
    height: Optional[int] = None,
    width: Optional[int] = None,
) -> ft.TextField:
    """
    Consistent text field — light border, focused blue accent.

    For multiline text, pass multiline=True and adjust min/max_lines.
    """
    return ft.TextField(
        label=label,
        hint_text=hint,
        value=value,
        password=password,
        can_reveal_password=password,
        multiline=multiline,
        min_lines=min_lines,
        max_lines=max_lines if multiline else 1,
        on_change=on_change,
        autofocus=autofocus,
        prefix_icon=prefix_icon,
        height=height if not multiline else None,
        width=width,
        border_color=BORDER,
        focused_border_color=ACCENT,
        bgcolor=SURFACE,
        text_size=FONT_MD,
        text_style=ft.TextStyle(color=TEXT_PRIMARY),
        label_style=ft.TextStyle(color=TEXT_MUTED, size=FONT_BASE),
        hint_style=ft.TextStyle(color=TEXT_DISABLED, size=FONT_MD),
        content_padding=ft.padding.symmetric(horizontal=SPACE_3, vertical=SPACE_3),
        cursor_color=ACCENT,
        cursor_width=1,
        border_radius=RADIUS_MD,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Empty state
# ─────────────────────────────────────────────────────────────────────────────

def empty_state(
    icon: str,
    title: str,
    description: Optional[str] = None,
    action: Optional[ft.Control] = None,
) -> ft.Container:
    """Standard empty state — icon chip + title + optional description + CTA."""
    controls: list[ft.Control] = [
        ft.Container(
            content=ft.Icon(icon, size=20, color=TEXT_DISABLED),
            width=44,
            height=44,
            border_radius=RADIUS_FULL,
            bgcolor=SURFACE_HOVER,
            alignment=ft.alignment.center,
        ),
        ft.Container(height=SPACE_3),
        ft.Text(
            title,
            size=FONT_MD,
            weight=ft.FontWeight.W_600,
            color=TEXT_PRIMARY,
            text_align=ft.TextAlign.CENTER,
        ),
    ]
    if description:
        controls.append(ft.Container(height=SPACE_1))
        controls.append(
            ft.Text(
                description,
                size=FONT_BASE,
                color=TEXT_MUTED,
                text_align=ft.TextAlign.CENTER,
            )
        )
    if action:
        controls.append(ft.Container(height=SPACE_4))
        controls.append(action)

    return ft.Container(
        content=ft.Column(
            controls,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        padding=ft.padding.symmetric(horizontal=SPACE_5, vertical=SPACE_8),
        alignment=ft.alignment.center,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Loading state
# ─────────────────────────────────────────────────────────────────────────────

def loading_state(text: str = "Loading…") -> ft.Container:
    """Centered progress ring with caption."""
    return ft.Container(
        content=ft.Column(
            [
                ft.ProgressRing(width=20, height=20, stroke_width=2, color=ACCENT),
                ft.Container(height=SPACE_2),
                muted(text, size=FONT_BASE),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        padding=ft.padding.symmetric(vertical=SPACE_8),
        alignment=ft.alignment.center,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Divider
# ─────────────────────────────────────────────────────────────────────────────

def divider(vertical: bool = False) -> ft.Container:
    if vertical:
        return ft.Container(width=1, bgcolor=BORDER)
    return ft.Container(height=1, bgcolor=BORDER)
