"""
Build a slideshow MP4 from per-step PNG screenshots.

Uses imageio + imageio-ffmpeg (ships a static ffmpeg binary cross-platform).
"""

import io
import logging
import tempfile
import os
from typing import Iterable

import imageio.v2 as imageio
from PIL import Image
import numpy as np

logger = logging.getLogger("bicentra.video")


def _resize_keep_aspect(img: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    max_w, max_h = max_size
    if img.width <= max_w and img.height <= max_h:
        return img
    img = img.copy()
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img


def _pad_to_size(img: Image.Image, size: tuple[int, int], fill=(0, 0, 0)) -> Image.Image:
    """Center the image on a black canvas of the target size."""
    target_w, target_h = size
    if img.width == target_w and img.height == target_h:
        return img.convert("RGB")
    bg = Image.new("RGB", size, fill)
    x = (target_w - img.width) // 2
    y = (target_h - img.height) // 2
    bg.paste(img.convert("RGB"), (x, y))
    return bg


def build_slideshow(
    frames: Iterable[tuple[int, bytes]],
    fps: int = 2,
    max_size: tuple[int, int] = (1280, 720),
) -> bytes:
    """
    Build an MP4 slideshow where each PNG frame appears for `1/fps` seconds.

    Returns raw MP4 bytes. May raise on encoding errors.
    """
    frames = list(frames)
    if not frames:
        return b""

    # First pass: determine the canvas size based on the first frame after resize.
    first_img = Image.open(io.BytesIO(frames[0][1]))
    first_resized = _resize_keep_aspect(first_img, max_size)
    canvas_size = (first_resized.width, first_resized.height)
    # Make sure dimensions are even (h.264 requirement)
    canvas_size = (canvas_size[0] - (canvas_size[0] % 2), canvas_size[1] - (canvas_size[1] % 2))

    # Write to a temp file because imageio-ffmpeg's writer typically streams to disk.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        writer = imageio.get_writer(
            tmp_path,
            fps=fps,
            codec="libx264",
            quality=7,
            macro_block_size=1,
        )
        try:
            for _, png_bytes in frames:
                try:
                    img = Image.open(io.BytesIO(png_bytes))
                except Exception as e:
                    logger.warning(f"Skipping unreadable frame: {e}")
                    continue
                img = _resize_keep_aspect(img, max_size)
                img = _pad_to_size(img, canvas_size)
                arr = np.asarray(img)
                writer.append_data(arr)
        finally:
            writer.close()

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
