from __future__ import annotations

import hashlib
import io
import textwrap
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

VALID_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


class ImageValidationError(ValueError):
    """Raised for invalid image uploads."""


@dataclass(slots=True)
class StoredImage:
    path: Path
    sha256: str
    content_type: str | None
    size: int


class ImageStore:
    def __init__(self, base_dir: Path, max_image_bytes: int):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.max_image_bytes = max_image_bytes

    def validate(self, content_type: str | None, size: int) -> None:
        if size <= 0:
            raise ImageValidationError("Image file cannot be empty.")
        if size > self.max_image_bytes:
            raise ImageValidationError(
                f"Image is too large ({size} bytes). Max is {self.max_image_bytes} bytes."
            )
        if content_type and content_type.lower() not in VALID_IMAGE_TYPES:
            raise ImageValidationError(
                f"Unsupported image content type: {content_type}."
            )

    async def save_from_url(
        self,
        session: aiohttp.ClientSession,
        url: str,
        suggested_ext: str,
        content_type: str | None,
        size: int,
    ) -> StoredImage:
        self.validate(content_type, size)

        async with session.get(url, timeout=30) as response:
            response.raise_for_status()
            raw = await response.read()

        if len(raw) != size and size > 0:
            self.validate(content_type, len(raw))
        else:
            self.validate(content_type, size)

        digest = hashlib.sha256(raw).hexdigest()
        ext = suggested_ext.lower() if suggested_ext else "png"
        if ext.startswith("."):
            ext = ext[1:]
        if not ext:
            ext = "png"

        out_path = self.base_dir / f"{digest}.{ext}"
        if not out_path.exists():
            out_path.write_bytes(raw)

        return StoredImage(path=out_path, sha256=digest, content_type=content_type, size=len(raw))

    def save_text_image(self, text: str) -> StoredImage:
        size = 200
        img = Image.new("RGB", (size, size), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)

        for font_size in (32, 24, 18, 14, 11):
            font = ImageFont.load_default(size=font_size)
            lines = textwrap.wrap(text, width=max(1, size // (font_size // 2)), break_long_words=True)
            lines = lines[:8]
            bb = draw.textbbox((0, 0), "Ag", font=font)
            line_h = bb[3] - bb[1] + 2
            total_h = line_h * len(lines)
            if total_h <= size - 16:
                break

        start_y = (size - total_h) // 2
        for i, line in enumerate(lines):
            bb = draw.textbbox((0, 0), line, font=font)
            x = (size - (bb[2] - bb[0])) // 2
            draw.text((x, start_y + i * line_h), line, fill=(255, 255, 255), font=font)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()

        digest = hashlib.sha256(raw).hexdigest()
        out_path = self.base_dir / f"{digest}.png"
        if not out_path.exists():
            out_path.write_bytes(raw)

        return StoredImage(path=out_path, sha256=digest, content_type="image/png", size=len(raw))
