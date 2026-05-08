from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from TierListBot.models import TierItem, TierList

_DEFAULT_TIER_COLORS: dict[str, tuple[int, int, int]] = {
    "S": (254, 105, 106),
    "A": (255, 166, 89),
    "B": (255, 219, 102),
    "C": (156, 218, 120),
    "D": (120, 181, 255),
}

_CUSTOM_PALETTE: list[tuple[int, int, int]] = [
    (180, 120, 255),
    (255, 120, 200),
    (100, 220, 220),
    (255, 180, 50),
    (80, 200, 120),
    (200, 100, 80),
]


class BoardRenderer:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(self, tier_list: TierList, items: list[TierItem], tier_labels: list[str]) -> Path:
        grouped: dict[str, list[TierItem]] = defaultdict(list)
        for item in items:
            grouped[item.tier].append(item)

        row_height = 140
        tier_label_width = 90
        cell_width = 140
        margin = 16
        max_items_in_row = max((len(grouped[t]) for t in tier_labels), default=1)
        board_width = margin * 2 + tier_label_width + max_items_in_row * cell_width
        board_height = margin * 2 + len(tier_labels) * row_height + 40

        image = Image.new("RGB", (board_width, board_height), color=(242, 245, 247))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        draw.rectangle([(0, 0), (board_width, 40)], fill=(27, 39, 53))
        draw.text((margin, 12), tier_list.name, fill=(255, 255, 255), font=font)

        custom_color_idx = 0
        y = margin + 40
        for tier_label in tier_labels:
            color = _DEFAULT_TIER_COLORS.get(tier_label)
            if color is None:
                color = _CUSTOM_PALETTE[custom_color_idx % len(_CUSTOM_PALETTE)]
                custom_color_idx += 1

            draw.rectangle(
                [(margin, y), (board_width - margin, y + row_height - 8)],
                fill=(255, 255, 255),
                outline=(214, 220, 227),
                width=2,
            )
            draw.rectangle(
                [(margin, y), (margin + tier_label_width, y + row_height - 8)],
                fill=color,
            )
            draw.text((margin + 36, y + 50), tier_label[:4], fill=(20, 20, 20), font=font)

            x = margin + tier_label_width + 6
            for item in grouped[tier_label]:
                thumb = self._load_thumbnail(Path(item.image_path), size=120)
                image.paste(thumb, (x, y + 6))
                if item.label:
                    draw.rectangle(
                        [(x, y + 104), (x + 120, y + 126)], fill=(0, 0, 0)
                    )
                    draw.text((x + 4, y + 109), item.label[:18], fill=(255, 255, 255), font=font)
                x += cell_width

            y += row_height

        out_path = self.output_dir / f"render-{tier_list.id}.png"
        image.save(out_path, format="PNG")
        return out_path

    def _load_thumbnail(self, path: Path, size: int) -> Image.Image:
        try:
            img = Image.open(path).convert("RGB")
            img.thumbnail((size, size))
            canvas = Image.new("RGB", (size, size), color=(230, 232, 235))
            x = (size - img.width) // 2
            y = (size - img.height) // 2
            canvas.paste(img, (x, y))
            return canvas
        except (FileNotFoundError, UnidentifiedImageError, OSError):
            # Fallback placeholder if image can't be opened.
            placeholder = Image.new("RGB", (size, size), color=(222, 226, 230))
            draw = ImageDraw.Draw(placeholder)
            draw.line([(0, 0), (size, size)], fill=(150, 150, 150), width=3)
            draw.line([(size, 0), (0, size)], fill=(150, 150, 150), width=3)
            return placeholder
