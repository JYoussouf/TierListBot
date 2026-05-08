"""Tests for new live-tier-list service methods:
get_tiers_ordered, add_tier, get_active_list, update_message_id,
and the tier-as-str migration for add_item / move_item / list_items.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from TierListBot.models import Tier
from TierListBot.services.db import Database
from TierListBot.services.image_store import StoredImage
from TierListBot.services.tierlist_service import (
    LimitError,
    NotFoundError,
    TierListError,
    TierListService,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _svc(tmp_path: Path, name: str = "test.sqlite3", **kwargs) -> TierListService:
    db = Database(tmp_path / name)
    db.init_schema()
    return TierListService(db, max_lists_per_guild=50, max_items_per_list=100, **kwargs)


def _img(tmp_path: Path, name: str = "img.png") -> StoredImage:
    p = tmp_path / name
    p.write_bytes(b"fake")
    return StoredImage(path=p, sha256=name, content_type="image/png", size=4)


# ── get_tiers_ordered ─────────────────────────────────────────────────────────


def test_get_tiers_ordered_default(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    assert svc.get_tiers_ordered(tl.id) == ["S", "A", "B", "C", "D"]


# ── add_tier ──────────────────────────────────────────────────────────────────


def test_add_tier_appends_after_defaults(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    svc.add_tier(tl.id, 1, "god-tier")
    assert svc.get_tiers_ordered(tl.id) == ["S", "A", "B", "C", "D", "god-tier"]


def test_add_tier_multiple_preserve_insertion_order(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    svc.add_tier(tl.id, 1, "god-tier")
    svc.add_tier(tl.id, 1, "trash")
    assert svc.get_tiers_ordered(tl.id) == ["S", "A", "B", "C", "D", "god-tier", "trash"]


def test_add_tier_duplicate_label_raises(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    svc.add_tier(tl.id, 1, "god-tier")
    with pytest.raises(TierListError, match="already exists"):
        svc.add_tier(tl.id, 1, "god-tier")


def test_add_tier_duplicate_default_tier_raises(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    with pytest.raises(TierListError):
        svc.add_tier(tl.id, 1, "S")


def test_add_tier_list_not_found_raises(tmp_path: Path):
    svc = _svc(tmp_path)
    with pytest.raises(NotFoundError):
        svc.add_tier("doesnotexist", 1, "god-tier")


# ── update_message_id / get_active_list ───────────────────────────────────────


def test_get_active_list_returns_none_when_no_lists(tmp_path: Path):
    svc = _svc(tmp_path)
    assert svc.get_active_list(channel_id=99) is None


def test_get_active_list_returns_none_before_message_id_set(tmp_path: Path):
    svc = _svc(tmp_path)
    svc.create_list(1, 42, 1, "Test")
    assert svc.get_active_list(channel_id=42) is None


def test_update_message_id_visible_in_get_list(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    assert svc.get_list(tl.id).message_id is None
    svc.update_message_id(tl.id, "123456789")
    assert svc.get_list(tl.id).message_id == "123456789"


def test_get_active_list_returns_list_after_message_id_set(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 42, 1, "Test")
    svc.update_message_id(tl.id, "999")
    result = svc.get_active_list(channel_id=42)
    assert result is not None
    assert result.id == tl.id
    assert result.message_id == "999"


def test_get_active_list_returns_most_recent_with_message_id(tmp_path: Path):
    svc = _svc(tmp_path)
    old = svc.create_list(1, 42, 1, "Old")
    new = svc.create_list(1, 42, 1, "New")
    svc.update_message_id(old.id, "aaa")
    svc.update_message_id(new.id, "bbb")
    result = svc.get_active_list(channel_id=42)
    assert result is not None
    assert result.id == new.id


def test_get_active_list_only_considers_channel_with_message_id(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 42, 1, "Test")
    svc.update_message_id(tl.id, "msg1")
    # Different channel sees nothing
    assert svc.get_active_list(channel_id=99) is None


def test_get_active_list_skips_lists_without_message_id(tmp_path: Path):
    svc = _svc(tmp_path)
    without = svc.create_list(1, 42, 1, "No msg")
    with_msg = svc.create_list(1, 42, 1, "Has msg")
    svc.update_message_id(with_msg.id, "555")
    result = svc.get_active_list(channel_id=42)
    assert result is not None
    assert result.id == with_msg.id


# ── tier-as-str backward compatibility ───────────────────────────────────────


def test_tier_enum_values_equal_strings(tmp_path: Path):
    # Tier(str, Enum) means Tier.S == "S" — essential for backward compat
    assert Tier.S == "S"
    assert Tier.A == "A"
    assert Tier.B == "B"
    assert Tier.C == "C"
    assert Tier.D == "D"


def test_add_item_with_string_tier(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    item = svc.add_item(
        list_id=tl.id,
        actor_id=1,
        label="hello",
        tier="S",
        image=_img(tmp_path),
        original_filename="img.png",
    )
    assert item.tier == "S"


def test_add_item_with_tier_enum_still_works(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    item = svc.add_item(
        list_id=tl.id,
        actor_id=1,
        label=None,
        tier=Tier.D,
        image=_img(tmp_path),
        original_filename="img.png",
    )
    assert item.tier == "D"


def test_list_items_returns_string_tiers(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    svc.add_item(
        list_id=tl.id, actor_id=1, label=None, tier="A",
        image=_img(tmp_path), original_filename="img.png",
    )
    items = svc.list_items(tl.id)
    assert isinstance(items[0].tier, str)
    assert items[0].tier == "A"


def test_move_item_with_string_tier(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    item = svc.add_item(
        list_id=tl.id, actor_id=1, label=None, tier="D",
        image=_img(tmp_path), original_filename="img.png",
    )
    moved = svc.move_item(tl.id, item.id, actor_id=1, tier="S")
    assert moved.tier == "S"


# ── items in custom tiers ─────────────────────────────────────────────────────


def test_add_item_to_custom_tier(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    svc.add_tier(tl.id, 1, "god-tier")
    item = svc.add_item(
        list_id=tl.id, actor_id=1, label="Best ever", tier="god-tier",
        image=_img(tmp_path), original_filename="img.png",
    )
    items = svc.list_items(tl.id)
    assert len(items) == 1
    assert items[0].tier == "god-tier"
    assert items[0].id == item.id


def test_move_item_to_custom_tier(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    svc.add_tier(tl.id, 1, "god-tier")
    item = svc.add_item(
        list_id=tl.id, actor_id=1, label=None, tier="S",
        image=_img(tmp_path), original_filename="img.png",
    )
    moved = svc.move_item(tl.id, item.id, actor_id=1, tier="god-tier")
    assert moved.tier == "god-tier"
    assert svc.list_items(tl.id)[0].tier == "god-tier"


def test_custom_tier_items_survive_reload(tmp_path: Path):
    svc = _svc(tmp_path)
    tl = svc.create_list(1, 1, 1, "Test")
    svc.add_tier(tl.id, 1, "god-tier")
    svc.add_item(
        list_id=tl.id, actor_id=1, label=None, tier="god-tier",
        image=_img(tmp_path), original_filename="img.png",
    )
    # Re-instantiate service from same DB file
    db2 = Database(tmp_path / "test.sqlite3")
    db2.init_schema()
    svc2 = TierListService(db2, max_lists_per_guild=50, max_items_per_list=100)
    items = svc2.list_items(tl.id)
    assert len(items) == 1
    assert items[0].tier == "god-tier"
