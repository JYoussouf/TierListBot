from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from TierListBot.models import Tier, TierItem, TierList
from TierListBot.services.renderer import BoardRenderer


def test_renderer_generates_png_with_placeholder(tmp_path: Path):
    missing_path = tmp_path / "missing.png"
    tier_list = TierList(
        id="abc123",
        guild_id=1,
        channel_id=1,
        owner_id=1,
        name="Test Board",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    items = [
        TierItem(
            id="item1",
            list_id=tier_list.id,
            label="Broken",
            tier=Tier.S,
            image_path=str(missing_path),
            created_by=1,
            created_at=datetime.now(timezone.utc),
        )
    ]

    renderer = BoardRenderer(tmp_path)
    output_path = renderer.render(tier_list, items, ["S", "A", "B", "C", "D"])
    assert output_path.exists()

    img = Image.open(output_path)
    assert img.format == "PNG"
    assert img.width > 100
    assert img.height > 100
