"""Tests for TierShortcutsCog: /s /a /b /c /d and /add-tier commands.

Strategy: real Database + TierListService for business-logic correctness;
mock only Discord I/O (interactions, channels, partial messages) and
async file helpers (image_store.save_from_url, renderer.render).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from TierListBot.cogs.tier_shortcuts import TierShortcutsCog
from TierListBot.models import TierList
from TierListBot.services.db import Database
from TierListBot.services.image_store import ImageStore, ImageValidationError, StoredImage
from TierListBot.services.renderer import BoardRenderer
from TierListBot.services.tierlist_service import LimitError, TierListService


# ── test helpers ──────────────────────────────────────────────────────────────


def _svc(tmp_path: Path, name: str = "test.sqlite3", **kwargs) -> TierListService:
    db = Database(tmp_path / name)
    db.init_schema()
    return TierListService(db, max_lists_per_guild=50, max_items_per_list=100, **kwargs)


def _make_cog(tmp_path: Path, **svc_kwargs):
    service = _svc(tmp_path, **svc_kwargs)
    image_store = MagicMock(spec=ImageStore)
    renderer = MagicMock(spec=BoardRenderer)
    board_file = tmp_path / "board.png"
    board_file.write_bytes(b"fake_png")
    renderer.render.return_value = board_file
    cog = TierShortcutsCog(MagicMock(), service, image_store, renderer, http_session=None)
    return cog, service, image_store


def _stored_image(tmp_path: Path, name: str = "stored.png") -> StoredImage:
    p = tmp_path / name
    p.write_bytes(b"fake")
    return StoredImage(path=p, sha256=name, content_type="image/png", size=4)


def _channel() -> tuple[MagicMock, MagicMock]:
    """Returns (channel_mock, partial_message_mock).

    get_partial_message is synchronous in discord.py — channel must be
    MagicMock so calling it returns the partial directly, not a coroutine.
    """
    channel = MagicMock()
    partial = MagicMock()
    partial.edit = AsyncMock()
    channel.get_partial_message = MagicMock(return_value=partial)
    channel.send = AsyncMock(return_value=MagicMock(id=888888))
    return channel, partial


def _interaction(
    guild_id: int = 1,
    channel_id: int = 42,
    user_id: int = 100,
    channel: MagicMock | None = None,
) -> discord.Interaction:
    inter = MagicMock(spec=discord.Interaction)
    inter.guild = MagicMock()
    inter.guild.id = guild_id
    inter.channel_id = channel_id
    inter.user = MagicMock()
    inter.user.id = user_id
    inter.response = AsyncMock()
    inter.followup = AsyncMock()
    inter.channel = channel if channel is not None else _channel()[0]
    return inter


def _attachment(
    filename: str = "pic.png",
    content_type: str = "image/png",
    size: int = 100,
    url: str = "https://cdn.discordapp.com/pic.png",
) -> discord.Attachment:
    att = MagicMock(spec=discord.Attachment)
    att.filename = filename
    att.content_type = content_type
    att.size = size
    att.url = url
    return att


# ── _add_to_tier: guard clauses ───────────────────────────────────────────────


async def test_add_to_tier_no_guild_sends_ephemeral_error(tmp_path: Path):
    cog, *_ = _make_cog(tmp_path)
    inter = MagicMock(spec=discord.Interaction)
    inter.guild = None
    inter.channel_id = 42
    inter.response = AsyncMock()
    await cog._add_to_tier(inter, "S", _attachment())
    inter.response.send_message.assert_called_once()
    assert inter.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_to_tier_no_active_list_sends_error(tmp_path: Path):
    cog, *_ = _make_cog(tmp_path)
    inter = _interaction()
    await cog._add_to_tier(inter, "S", _attachment())
    inter.followup.send.assert_called_once()
    assert "No active tier list" in inter.followup.send.call_args.args[0]


async def test_add_to_tier_tier_not_in_list_sends_error(tmp_path: Path):
    cog, svc, _ = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")
    inter = _interaction()
    await cog._add_to_tier(inter, "Z", _attachment())
    inter.followup.send.assert_called_once()
    msg = inter.followup.send.call_args.args[0]
    assert "does not exist" in msg
    assert "Z" in msg


async def test_add_to_tier_image_validation_error_sends_error(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")
    image_store.save_from_url = AsyncMock(side_effect=ImageValidationError("File too large"))
    inter = _interaction()
    await cog._add_to_tier(inter, "S", _attachment())
    inter.followup.send.assert_called_once()
    assert "File too large" in inter.followup.send.call_args.args[0]


async def test_add_to_tier_item_limit_sends_error(tmp_path: Path):
    db = Database(tmp_path / "lim.sqlite3")
    db.init_schema()
    svc = TierListService(db, max_lists_per_guild=50, max_items_per_list=1)
    image_store = MagicMock(spec=ImageStore)
    renderer = MagicMock(spec=BoardRenderer)
    board_file = tmp_path / "board.png"
    board_file.write_bytes(b"fake")
    renderer.render.return_value = board_file
    cog = TierShortcutsCog(MagicMock(), svc, image_store, renderer, http_session=None)

    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")

    existing = _stored_image(tmp_path, "existing.png")
    svc.add_item(list_id=tl.id, actor_id=100, label=None, tier="S",
                 image=existing, original_filename="existing.png")

    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path, "new.png"))
    inter = _interaction()
    await cog._add_to_tier(inter, "S", _attachment())
    inter.followup.send.assert_called_once()
    assert "max items" in inter.followup.send.call_args.args[0].lower()


# ── _add_to_tier: happy path ──────────────────────────────────────────────────


async def test_add_to_tier_happy_path_edits_board_message(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "999888")

    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path))
    ch, partial = _channel()
    inter = _interaction(channel=ch)

    await cog._add_to_tier(inter, "S", _attachment())

    ch.get_partial_message.assert_called_once_with(999888)
    partial.edit.assert_called_once()
    inter.followup.send.assert_called_once()


async def test_add_to_tier_item_persisted_in_db(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")

    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path))
    ch, _ = _channel()
    inter = _interaction(channel=ch)

    await cog._add_to_tier(inter, "A", _attachment())

    items = svc.list_items(tl.id)
    assert len(items) == 1
    assert items[0].tier == "A"


async def test_add_to_tier_renderer_called_with_correct_args(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")

    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path))
    ch, _ = _channel()
    inter = _interaction(channel=ch)

    await cog._add_to_tier(inter, "B", _attachment())

    cog.renderer.render.assert_called_once()
    _, items_arg, labels_arg = cog.renderer.render.call_args.args
    assert any(i.tier == "B" for i in items_arg)
    assert labels_arg == ["S", "A", "B", "C", "D"]


async def test_add_to_tier_with_custom_tier(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.add_tier(tl.id, 100, "god-tier")
    svc.update_message_id(tl.id, "111")

    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path))
    ch, partial = _channel()
    inter = _interaction(channel=ch)

    await cog._add_to_tier(inter, "god-tier", _attachment())

    partial.edit.assert_called_once()
    items = svc.list_items(tl.id)
    assert items[0].tier == "god-tier"


# ── _add_to_tier: fallback on deleted message ─────────────────────────────────


async def test_add_to_tier_fallback_posts_new_message_on_http_exception(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "999")

    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path))
    ch, partial = _channel()
    partial.edit.side_effect = discord.HTTPException(MagicMock(), "Unknown Message")
    fallback_msg = MagicMock()
    fallback_msg.id = 777777
    ch.send = AsyncMock(return_value=fallback_msg)
    inter = _interaction(channel=ch)

    await cog._add_to_tier(inter, "S", _attachment())

    ch.send.assert_called_once()
    updated = svc.get_active_list(channel_id=42)
    assert updated is not None
    assert updated.message_id == "777777"


async def test_add_to_tier_fallback_still_sends_followup(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "999")

    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path))
    ch, partial = _channel()
    partial.edit.side_effect = discord.HTTPException(MagicMock(), "Unknown Message")
    fallback_msg = MagicMock()
    fallback_msg.id = 888
    ch.send = AsyncMock(return_value=fallback_msg)
    inter = _interaction(channel=ch)

    await cog._add_to_tier(inter, "D", _attachment())

    inter.followup.send.assert_called_once()


# ── shorthand command callbacks ───────────────────────────────────────────────


async def test_shorthand_s_command_adds_to_s_tier(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")
    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path))
    ch, _ = _channel()
    inter = _interaction(channel=ch)
    await cog.s.callback(cog, inter, image=_attachment())
    assert svc.list_items(tl.id)[0].tier == "S"


async def test_shorthand_d_command_adds_to_d_tier(tmp_path: Path):
    cog, svc, image_store = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")
    image_store.save_from_url = AsyncMock(return_value=_stored_image(tmp_path, "d.png"))
    ch, _ = _channel()
    inter = _interaction(channel=ch)
    await cog.d.callback(cog, inter, image=_attachment())
    assert svc.list_items(tl.id)[0].tier == "D"


# ── add_tier command ──────────────────────────────────────────────────────────


async def test_add_tier_cmd_no_guild_sends_error(tmp_path: Path):
    cog, *_ = _make_cog(tmp_path)
    inter = MagicMock(spec=discord.Interaction)
    inter.guild = None
    inter.channel_id = 42
    inter.response = AsyncMock()
    await cog._add_tier_to_list(inter, name="god-tier")
    inter.response.send_message.assert_called_once()
    assert inter.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_tier_cmd_no_active_list_sends_error(tmp_path: Path):
    cog, *_ = _make_cog(tmp_path)
    inter = _interaction()
    await cog._add_tier_to_list(inter, name="god-tier")
    inter.response.send_message.assert_called_once()
    assert "No active tier list" in inter.response.send_message.call_args.args[0]


async def test_add_tier_cmd_duplicate_sends_error(tmp_path: Path):
    cog, svc, _ = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")

    # First call succeeds
    ch, _ = _channel()
    inter1 = _interaction(channel=ch)
    await cog._add_tier_to_list(inter1, name="god-tier")

    # Second call is a duplicate
    ch2, _ = _channel()
    inter2 = _interaction(channel=ch2)
    await cog._add_tier_to_list(inter2, name="god-tier")
    inter2.response.send_message.assert_called_once()
    assert "already exists" in inter2.response.send_message.call_args.args[0]


async def test_add_tier_cmd_happy_path_persists_tier(tmp_path: Path):
    cog, svc, _ = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")
    ch, partial = _channel()
    inter = _interaction(channel=ch)
    await cog._add_tier_to_list(inter, name="god-tier")
    assert "god-tier" in svc.get_tiers_ordered(tl.id)


async def test_add_tier_cmd_happy_path_edits_board(tmp_path: Path):
    cog, svc, _ = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")
    ch, partial = _channel()
    inter = _interaction(channel=ch)
    await cog._add_tier_to_list(inter, name="god-tier")
    ch.get_partial_message.assert_called_once_with(111)
    partial.edit.assert_called_once()


async def test_add_tier_cmd_renderer_includes_new_tier(tmp_path: Path):
    cog, svc, _ = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")
    ch, _ = _channel()
    inter = _interaction(channel=ch)
    await cog._add_tier_to_list(inter, name="god-tier")
    _, _, labels_arg = cog.renderer.render.call_args.args
    assert "god-tier" in labels_arg


async def test_add_tier_cmd_sends_ephemeral_confirmation(tmp_path: Path):
    cog, svc, _ = _make_cog(tmp_path)
    tl = svc.create_list(1, 42, 100, "Test")
    svc.update_message_id(tl.id, "111")
    ch, _ = _channel()
    inter = _interaction(channel=ch)
    await cog._add_tier_to_list(inter, name="god-tier")
    inter.followup.send.assert_called_once()
