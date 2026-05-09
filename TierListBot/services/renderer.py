from __future__ import annotations

import math
import textwrap
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from TierListBot.models import TierItem, TierList
from TierListBot.services.tierlist_service import LABEL_MAX_LINES, LABEL_WRAP_WIDTH

# ── palette ───────────────────────────────────────────────────────────────────

_DEFAULT_TIER_COLORS: dict[str, tuple[int, int, int]] = {
    "S": (255, 115, 115),   # salmon / coral
    "A": (255, 178, 115),   # peach
    "B": (255, 223, 107),   # golden yellow
    "C": (243, 241,  96),   # bright yellow
    "D": (142, 255, 128),   # lime green
}

_CUSTOM_PALETTE: list[tuple[int, int, int]] = [
    (160,  90, 255),
    (255,  90, 190),
    ( 64, 210, 210),
    (255, 170,  40),
    ( 60, 190, 110),
    (210,  90,  70),
]

# ── dark-mode colours ─────────────────────────────────────────────────────────

_BG         = (19,  19,  19)   # board background
_HEADER_BG  = (10,  10,  10)   # title bar
_ROW_BG     = (19,  19,  19)   # content-area background (matches template)
_DIVIDER    = (35,  35,  35)   # 1 px line between rows
_THUMB_BG   = (45,  45,  45)   # letterbox fill behind thumbnails
_WHITE      = (255, 255, 255)
_LABEL_TEXT = ( 20,  20,  20)  # dark label text (matches template)
_ITEM_TAG   = (  0,   0,   0)  # item-label overlay

# ── layout constants ──────────────────────────────────────────────────────────

_HEADER_H  = 44               # slim title bar
_ROW_H     = 114              # matches template row height
_LABEL_W   = 140              # wider label cell (matches template ~10% of width)
_CELL_W    = 114              # square thumbnail cell
_THUMB_PAD = 5                # padding around each thumbnail inside its cell
_ROW_GAP   = 1               # 1 px divider between rows
_MIN_COLS  = 5               # minimum empty columns shown on the board
_MAX_COLS  = 8               # wrap to a new sub-row after this many items


def _label_font(draw: ImageDraw.ImageDraw, text: str, max_px: int) -> ImageFont.ImageFont:
    for size in (32, 24, 17, 12):
        font = ImageFont.load_default(size=size)
        bb = draw.textbbox((0, 0), text, font=font)
        if bb[2] - bb[0] <= max_px:
            return font
    return ImageFont.load_default(size=12)


def _draw_tier_label(
    draw: ImageDraw.ImageDraw,
    text: str,
    cell_x: int,
    cell_y: int,
    cell_w: int,
    cell_h: int,
    color: tuple[int, int, int],
) -> None:
    """Draw a tier label, word-wrapping if it contains spaces."""
    lines = textwrap.wrap(text, LABEL_WRAP_WIDTH) or [text]
    lines = lines[:LABEL_MAX_LINES]

    widest = max(lines, key=len)
    font = _label_font(draw, widest, cell_w - 12)

    bb = draw.textbbox((0, 0), "Ag", font=font)
    line_h = bb[3] - bb[1] + 3
    total_h = line_h * len(lines)
    start_y = cell_y + (cell_h - total_h) // 2

    for i, line in enumerate(lines):
        _center_text(draw, line, font, cell_x, start_y + i * line_h, cell_w, line_h, color)


def _center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    cell_x: int,
    cell_y: int,
    cell_w: int,
    cell_h: int,
    color: tuple[int, int, int],
) -> None:
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text(
        (cell_x + (cell_w - tw) // 2 - bb[0], cell_y + (cell_h - th) // 2 - bb[1]),
        text,
        fill=color,
        font=font,
    )


class BoardRenderer:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._thumb_cache: dict[tuple[str, int], Image.Image] = {}

    def render(self, tier_list: TierList, items: list[TierItem], tier_labels: list[str]) -> Path:
        grouped: dict[str, list[TierItem]] = defaultdict(list)
        for item in items:
            grouped[item.tier].append(item)

        max_cols = max((len(grouped[t]) for t in tier_labels), default=0)
        cols     = min(max(max_cols, _MIN_COLS), _MAX_COLS)
        board_w  = _LABEL_W + cols * _CELL_W

        def tier_sub_rows(label: str) -> int:
            return max(1, math.ceil(len(grouped[label]) / cols))

        board_h = _HEADER_H + sum(
            tier_sub_rows(t) * _ROW_H + _ROW_GAP for t in tier_labels
        )

        image = Image.new("RGB", (board_w, board_h), color=_BG)
        draw  = ImageDraw.Draw(image)

        # ── header ────────────────────────────────────────────────────────────
        draw.rectangle([(0, 0), (board_w, _HEADER_H)], fill=_HEADER_BG)
        title_font = ImageFont.load_default(size=14)
        _center_text(draw, tier_list.name, title_font, 0, 0, board_w, _HEADER_H, _WHITE)

        # ── tier rows ─────────────────────────────────────────────────────────
        custom_idx = 0
        ry = _HEADER_H
        for tier_idx, tier_label in enumerate(tier_labels):
            color = _DEFAULT_TIER_COLORS.get(tier_label)
            if color is None:
                color = _CUSTOM_PALETTE[custom_idx % len(_CUSTOM_PALETTE)]
                custom_idx += 1

            n_sub_rows = tier_sub_rows(tier_label)
            tier_h = n_sub_rows * _ROW_H

            # content-area background
            draw.rectangle([(0, ry), (board_w, ry + tier_h)], fill=_ROW_BG)

            # 1 px divider above each tier (except the first)
            if tier_idx > 0:
                draw.line([(0, ry), (board_w, ry)], fill=_DIVIDER)

            # coloured label cell spanning full tier height
            draw.rectangle([(0, ry), (_LABEL_W, ry + tier_h)], fill=color)
            _draw_tier_label(draw, tier_label, 0, ry, _LABEL_W, tier_h, _LABEL_TEXT)

            # thumbnails — wrap every `cols` items onto a new sub-row
            thumb_size = _CELL_W - _THUMB_PAD * 2
            for idx, item in enumerate(grouped[tier_label]):
                sub_row = idx // cols
                sub_col = idx % cols
                ix = _LABEL_W + sub_col * _CELL_W
                iy = ry + sub_row * _ROW_H
                thumb = self._load_thumbnail(Path(item.image_path), thumb_size)
                image.paste(thumb, (ix + _THUMB_PAD, iy + _THUMB_PAD))
                if item.label:
                    tag_y = iy + _ROW_H - 20
                    draw.rectangle([(ix, tag_y), (ix + _CELL_W, iy + _ROW_H)], fill=_ITEM_TAG)
                    tag_font = ImageFont.load_default(size=11)
                    draw.text((ix + 4, tag_y + 3), item.label[:16], fill=_WHITE, font=tag_font)

            ry += tier_h + _ROW_GAP

        out_path = self.output_dir / f"render-{tier_list.id}.png"
        image.save(out_path, format="PNG", compress_level=1)
        return out_path

    def _load_thumbnail(self, path: Path, size: int) -> Image.Image:
        key = (str(path), size)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        try:
            img = Image.open(path).convert("RGB")
            img.thumbnail((size, size))
            canvas = Image.new("RGB", (size, size), color=_THUMB_BG)
            canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
            self._thumb_cache[key] = canvas
        except (FileNotFoundError, UnidentifiedImageError, OSError):
            placeholder = Image.new("RGB", (size, size), color=_THUMB_BG)
            draw = ImageDraw.Draw(placeholder)
            draw.line([(0, 0), (size, size)], fill=(70, 70, 70), width=2)
            draw.line([(size, 0), (0, size)], fill=(70, 70, 70), width=2)
            self._thumb_cache[key] = placeholder
        return self._thumb_cache[key]
