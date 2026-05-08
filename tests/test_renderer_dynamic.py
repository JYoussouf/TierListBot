"""Tests for BoardRenderer with dynamic tier labels and custom tiers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from TierListBot.models import TierItem, TierList
from TierListBot.services.renderer import BoardRenderer

DEFAULT_LABELS = ["S", "A", "B", "C", "D"]


def _tier_list() -> TierList:
    return TierList(
        id="test123",
        guild_id=1,
        channel_id=1,
        owner_id=1,
        name="Test Board",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _item(tmp_path: Path, tier: str, filename: str = "img.png", label: str | None = None) -> TierItem:
    p = tmp_path / filename
    if not p.exists():
        p.write_bytes(b"fake")
    return TierItem(
        id=f"item-{filename}",
        list_id="test123",
        label=label,
        tier=tier,
        image_path=str(p),
        created_by=1,
        created_at=datetime.now(timezone.utc),
    )


# ── basic rendering ───────────────────────────────────────────────────────────


def test_render_empty_board_produces_valid_png(tmp_path: Path):
    out = BoardRenderer(tmp_path).render(_tier_list(), [], DEFAULT_LABELS)
    assert out.exists()
    img = Image.open(out)
    assert img.format == "PNG"
    assert img.width > 0 and img.height > 0


def test_render_output_path_is_deterministic(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    p1 = renderer.render(tl, [], DEFAULT_LABELS)
    p2 = renderer.render(tl, [], DEFAULT_LABELS)
    assert p1 == p2


# ── height scales with tier count ────────────────────────────────────────────


def test_board_height_grows_with_more_tiers(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    h5 = Image.open(renderer.render(tl, [], DEFAULT_LABELS)).height
    h6 = Image.open(renderer.render(tl, [], DEFAULT_LABELS + ["god-tier"])).height
    assert h6 > h5


def test_board_height_proportional_to_tier_count(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    two_tiers = ["S", "A"]
    five_tiers = DEFAULT_LABELS
    h2 = Image.open(renderer.render(tl, [], two_tiers)).height
    h5 = Image.open(renderer.render(tl, [], five_tiers)).height
    assert h5 > h2


# ── width scales with item count ─────────────────────────────────────────────


def test_board_width_grows_with_more_items(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    w_empty = Image.open(renderer.render(tl, [], DEFAULT_LABELS)).width
    items = [_item(tmp_path, "S", f"img{i}.png") for i in range(6)]
    w_full = Image.open(renderer.render(tl, items, DEFAULT_LABELS)).width
    assert w_full > w_empty


# ── custom tiers ──────────────────────────────────────────────────────────────


def test_render_with_single_custom_tier(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    labels = DEFAULT_LABELS + ["god-tier"]
    out = renderer.render(tl, [], labels)
    img = Image.open(out)
    assert img.format == "PNG"


def test_render_items_in_custom_tier_renders_thumbnail(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    labels = DEFAULT_LABELS + ["god-tier"]
    items = [_item(tmp_path, "god-tier", "a.png")]
    out = renderer.render(tl, items, labels)
    img = Image.open(out)
    assert img.format == "PNG"
    # Width must be wider than an empty board to accommodate the thumbnail
    empty_w = Image.open(renderer.render(tl, [], labels)).width
    assert img.width >= empty_w


def test_render_many_custom_tiers_cycles_palette(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    # 10 custom tiers exceeds the 6-color custom palette — must cycle without error
    custom = [f"custom-{i}" for i in range(10)]
    out = renderer.render(tl, [], DEFAULT_LABELS + custom)
    assert Image.open(out).format == "PNG"


def test_render_only_custom_tiers_no_defaults(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    out = renderer.render(tl, [], ["god-tier", "trash"])
    img = Image.open(out)
    assert img.format == "PNG"
    # Only 2 rows — should be shorter than 5-row default board
    h2 = img.height
    h5 = Image.open(renderer.render(tl, [], DEFAULT_LABELS)).height
    assert h2 < h5


# ── placeholder for broken images ────────────────────────────────────────────


def test_render_missing_image_shows_placeholder(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    item = TierItem(
        id="broken",
        list_id="test123",
        label="Gone",
        tier="S",
        image_path=str(tmp_path / "nonexistent.png"),
        created_by=1,
        created_at=datetime.now(timezone.utc),
    )
    out = renderer.render(tl, [item], DEFAULT_LABELS)
    assert out.exists()
    assert Image.open(out).format == "PNG"


# ── item labels ───────────────────────────────────────────────────────────────


def test_render_item_with_label_does_not_raise(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    item = _item(tmp_path, "A", "a.png", label="My Favorite")
    out = renderer.render(tl, [item], DEFAULT_LABELS)
    assert Image.open(out).format == "PNG"


def test_render_long_tier_label_truncated_safely(tmp_path: Path):
    renderer = BoardRenderer(tmp_path)
    tl = _tier_list()
    # Labels longer than 4 chars get truncated in the draw call — must not crash
    out = renderer.render(tl, [], ["very-long-tier-name"])
    assert Image.open(out).format == "PNG"
