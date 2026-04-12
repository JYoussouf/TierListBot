from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import aiohttp

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
