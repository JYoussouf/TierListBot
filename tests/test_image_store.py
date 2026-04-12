from __future__ import annotations

from pathlib import Path

import pytest

from TierListBot.services.image_store import ImageStore, ImageValidationError


def test_validate_rejects_non_image(tmp_path: Path):
    store = ImageStore(tmp_path, max_image_bytes=10)
    with pytest.raises(ImageValidationError):
        store.validate("text/plain", 4)


def test_validate_rejects_oversize(tmp_path: Path):
    store = ImageStore(tmp_path, max_image_bytes=2)
    with pytest.raises(ImageValidationError):
        store.validate("image/png", 4)


def test_validate_accepts_valid(tmp_path: Path):
    store = ImageStore(tmp_path, max_image_bytes=10)
    store.validate("image/png", 4)
