"""
Detect machine resources and recommend a video-recording tier.

Tiers (slideshow MP4 of per-step screenshots):
- off       : no recording (no per-step screenshot upload, no MP4)
- low       : 1 fps, 854x480, max 60 frames
- medium    : 2 fps, 1280x720, max 200 frames
- high      : 3 fps, 1600x900, max 400 frames

Recommendation rules (rough but safe):
- < 4 GB RAM   → low
- < 8 GB RAM   → medium
- 8-15 GB RAM  → medium (high if Apple Silicon — hw codecs are cheap)
- 16 GB+ RAM   → high
- Apple Silicon → bumps the tier up by one level

These are conservative; users can override.
"""

import platform
import subprocess
from dataclasses import dataclass

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:
    psutil = None  # type: ignore
    _HAS_PSUTIL = False


TIER_OFF = "off"
TIER_LOW = "low"
TIER_MEDIUM = "medium"
TIER_HIGH = "high"

ALL_TIERS = [TIER_OFF, TIER_LOW, TIER_MEDIUM, TIER_HIGH]


def tier_settings(tier: str) -> dict:
    """Return dict with fps, max_size, max_frames."""
    if tier == TIER_LOW:
        return {"fps": 1, "max_size": (854, 480), "max_frames": 60}
    if tier == TIER_MEDIUM:
        return {"fps": 2, "max_size": (1280, 720), "max_frames": 200}
    if tier == TIER_HIGH:
        return {"fps": 3, "max_size": (1600, 900), "max_frames": 400}
    # Off (or unknown) → no recording
    return {"fps": 0, "max_size": (0, 0), "max_frames": 0}


@dataclass
class SystemInfo:
    cpu_cores: int
    total_ram_gb: float
    platform_name: str
    platform_version: str
    is_apple_silicon: bool

    def label(self) -> str:
        cpu = f"{self.cpu_cores}-core CPU"
        ram = f"{self.total_ram_gb:.1f} GB RAM"
        plat = self.platform_name
        if self.is_apple_silicon:
            plat += " (Apple Silicon)"
        return f"{plat} • {cpu} • {ram}"


def detect_system() -> SystemInfo:
    cpu = 0
    try:
        cpu = int(_HAS_PSUTIL and psutil.cpu_count(logical=True) or 0)
    except Exception:
        pass
    if not cpu:
        try:
            import os
            cpu = os.cpu_count() or 0
        except Exception:
            cpu = 0

    ram_gb = 0.0
    if _HAS_PSUTIL:
        try:
            ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        except Exception:
            ram_gb = 0.0

    sys_name = platform.system()
    sys_ver = platform.release() or platform.version()
    is_apple_silicon = (
        sys_name == "Darwin"
        and platform.machine().lower() in ("arm64", "aarch64")
    )

    return SystemInfo(
        cpu_cores=cpu or 0,
        total_ram_gb=ram_gb,
        platform_name=sys_name or "Unknown",
        platform_version=sys_ver,
        is_apple_silicon=is_apple_silicon,
    )


def _bump_tier(tier: str) -> str:
    order = [TIER_LOW, TIER_MEDIUM, TIER_HIGH]
    if tier not in order:
        return TIER_MEDIUM
    idx = order.index(tier)
    return order[min(idx + 1, len(order) - 1)]


def recommend_tier(info: SystemInfo | None = None) -> str:
    info = info or detect_system()

    if info.total_ram_gb <= 0:
        # Couldn't detect → assume low-end, be safe
        return TIER_LOW

    if info.total_ram_gb < 4:
        tier = TIER_LOW
    elif info.total_ram_gb < 8:
        tier = TIER_LOW if info.cpu_cores < 4 else TIER_MEDIUM
    elif info.total_ram_gb < 16:
        tier = TIER_MEDIUM
    else:
        tier = TIER_HIGH

    if info.is_apple_silicon and tier != TIER_HIGH:
        tier = _bump_tier(tier)

    return tier


def has_hardware_h264() -> bool:
    """Best-effort probe for whether ffmpeg can do hardware-accelerated H.264.

    We only use this for advisory text in Settings; actual encoding still
    falls back to libx264 (CPU) which is what imageio uses by default.
    """
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=4,
        ).stdout.lower()
        for token in ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf"):
            if token in out:
                return True
    except Exception:
        pass
    return False
