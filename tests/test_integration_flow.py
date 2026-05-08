from __future__ import annotations

from pathlib import Path

from TierListBot.services.db import Database
from TierListBot.services.image_store import StoredImage
from TierListBot.services.tierlist_service import TierListService


def test_command_like_flow_create_add_move_render_data(tmp_path: Path):
    db = Database(tmp_path / "integration.sqlite3")
    db.init_schema()
    service = TierListService(db, max_lists_per_guild=10, max_items_per_list=10)

    tier_list = service.create_list(guild_id=111, channel_id=222, owner_id=333, name="Anime")

    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"1234")
    item = service.add_item(
        list_id=tier_list.id,
        actor_id=333,
        label="Naruto",
        tier="D",
        image=StoredImage(
            path=image_path,
            sha256="hash",
            content_type="image/png",
            size=4,
        ),
        original_filename="a.png",
    )

    service.move_item(tier_list.id, item.id, actor_id=333, tier="A")

    reloaded = service.get_list(tier_list.id)
    assert reloaded.guild_id == 111
    assert reloaded.owner_id == 333
    items = service.list_items(tier_list.id)
    assert len(items) == 1
    assert items[0].tier == "A"
