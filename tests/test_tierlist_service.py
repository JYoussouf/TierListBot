from __future__ import annotations

from pathlib import Path

from TierListBot.models import Tier
from TierListBot.services.db import Database
from TierListBot.services.image_store import StoredImage
from TierListBot.services.tierlist_service import LimitError, TierListService


def _service(tmp_path: Path, max_lists_per_guild: int = 50, max_items_per_list: int = 100):
    db = Database(tmp_path / "test.sqlite3")
    db.init_schema()
    return TierListService(db, max_lists_per_guild=max_lists_per_guild, max_items_per_list=max_items_per_list)


def test_create_add_move_and_persist(tmp_path: Path):
    service = _service(tmp_path)
    tier_list = service.create_list(1, 2, 10, "Games")

    image_path = tmp_path / "img.png"
    image_path.write_bytes(b"fake")
    item = service.add_item(
        list_id=tier_list.id,
        actor_id=10,
        label="Chess",
        tier=Tier.D,
        image=StoredImage(path=image_path, sha256="x", content_type="image/png", size=4),
        original_filename="img.png",
    )

    moved = service.move_item(tier_list.id, item.id, 10, Tier.S)
    assert moved.tier == Tier.S

    reloaded = service.get_list(tier_list.id)
    items = service.list_items(reloaded.id)
    assert len(items) == 1
    assert items[0].tier == Tier.S


def test_limits_enforced(tmp_path: Path):
    service = _service(tmp_path, max_lists_per_guild=1, max_items_per_list=1)
    first = service.create_list(22, 2, 10, "One")

    try:
        service.create_list(22, 2, 11, "Two")
        assert False, "expected LimitError"
    except LimitError:
        pass

    image_path = tmp_path / "img.png"
    image_path.write_bytes(b"fake")
    service.add_item(
        list_id=first.id,
        actor_id=10,
        label="Item1",
        tier=Tier.D,
        image=StoredImage(path=image_path, sha256="x", content_type="image/png", size=4),
        original_filename="img.png",
    )

    try:
        service.add_item(
            list_id=first.id,
            actor_id=10,
            label="Item2",
            tier=Tier.D,
            image=StoredImage(path=image_path, sha256="y", content_type="image/png", size=4),
            original_filename="img.png",
        )
        assert False, "expected LimitError"
    except LimitError:
        pass
