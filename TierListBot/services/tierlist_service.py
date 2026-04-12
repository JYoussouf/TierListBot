from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from TierListBot.models import DEFAULT_TIERS, Tier, TierItem, TierList
from TierListBot.services.db import Database
from TierListBot.services.image_store import StoredImage


class TierListError(RuntimeError):
    """Base tier list error."""


class NotFoundError(TierListError):
    """Raised when a list or item cannot be found."""


class PermissionError(TierListError):
    """Raised when a user is not allowed to edit."""


class LimitError(TierListError):
    """Raised when a configured limit is exceeded."""


class TierListService:
    def __init__(
        self,
        db: Database,
        max_lists_per_guild: int,
        max_items_per_list: int,
    ):
        self.db = db
        self.max_lists_per_guild = max_lists_per_guild
        self.max_items_per_list = max_items_per_list

    def create_list(self, guild_id: int, channel_id: int, owner_id: int, name: str) -> TierList:
        list_id = uuid4().hex[:10]
        now = self.db.utc_now()

        with self.db.tx() as conn:
            list_count = conn.execute(
                "SELECT COUNT(*) AS c FROM tier_lists WHERE guild_id = ?", (guild_id,)
            ).fetchone()["c"]
            if list_count >= self.max_lists_per_guild:
                raise LimitError(
                    f"Guild reached max tier lists ({self.max_lists_per_guild})."
                )

            conn.execute(
                "INSERT OR IGNORE INTO guilds(guild_id, created_at) VALUES (?, ?)",
                (guild_id, now),
            )
            conn.execute(
                """
                INSERT INTO tier_lists(id, guild_id, channel_id, owner_id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (list_id, guild_id, channel_id, owner_id, name, now, now),
            )
            for idx, tier in enumerate(DEFAULT_TIERS):
                conn.execute(
                    "INSERT INTO tiers(list_id, tier_label, position) VALUES (?, ?, ?)",
                    (list_id, tier.value, idx),
                )

            self._log(conn, guild_id, list_id, owner_id, "tierlist.create", {"name": name})

        return self.get_list(list_id)

    def get_list(self, list_id: str) -> TierList:
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM tier_lists WHERE id = ?", (list_id,)).fetchone()
        if not row:
            raise NotFoundError(f"Tier list not found: {list_id}")
        return TierList(
            id=row["id"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            owner_id=row["owner_id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_items(self, list_id: str) -> list[TierItem]:
        with self.db.tx() as conn:
            rows = conn.execute(
                "SELECT * FROM items WHERE list_id = ? ORDER BY created_at ASC", (list_id,)
            ).fetchall()
        result: list[TierItem] = []
        for row in rows:
            result.append(
                TierItem(
                    id=row["id"],
                    list_id=row["list_id"],
                    label=row["label"],
                    tier=Tier(row["tier"]),
                    image_path=row["image_path"],
                    created_by=row["created_by"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return result

    def add_item(
        self,
        list_id: str,
        actor_id: int,
        label: str | None,
        tier: Tier,
        image: StoredImage,
        original_filename: str | None,
    ) -> TierItem:
        item_id = uuid4().hex[:12]
        now = self.db.utc_now()
        list_obj = self.get_list(list_id)

        with self.db.tx() as conn:
            item_count = conn.execute(
                "SELECT COUNT(*) AS c FROM items WHERE list_id = ?", (list_id,)
            ).fetchone()["c"]
            if item_count >= self.max_items_per_list:
                raise LimitError(f"List reached max items ({self.max_items_per_list}).")

            conn.execute(
                """
                INSERT INTO items(id, list_id, label, tier, image_path, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, list_id, label, tier.value, str(image.path), actor_id, now),
            )
            conn.execute(
                """
                INSERT INTO item_images(item_id, original_filename, content_type, byte_size, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    original_filename,
                    image.content_type,
                    image.size,
                    image.sha256,
                    now,
                ),
            )
            conn.execute(
                "UPDATE tier_lists SET updated_at = ? WHERE id = ?", (now, list_id)
            )
            self._log(
                conn,
                list_obj.guild_id,
                list_id,
                actor_id,
                "tierlist.item.add",
                {"item_id": item_id, "tier": tier.value, "label": label},
            )

        return self.get_item(item_id)

    def get_item(self, item_id: str) -> TierItem:
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise NotFoundError(f"Item not found: {item_id}")
        return TierItem(
            id=row["id"],
            list_id=row["list_id"],
            label=row["label"],
            tier=Tier(row["tier"]),
            image_path=row["image_path"],
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def move_item(self, list_id: str, item_id: str, actor_id: int, tier: Tier) -> TierItem:
        now = self.db.utc_now()
        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT id FROM items WHERE id = ? AND list_id = ?", (item_id, list_id)
            ).fetchone()
            if not row:
                raise NotFoundError("Item not found in this tier list.")
            conn.execute("UPDATE items SET tier = ? WHERE id = ?", (tier.value, item_id))
            conn.execute("UPDATE tier_lists SET updated_at = ? WHERE id = ?", (now, list_id))
            self._log(
                conn,
                list_obj.guild_id,
                list_id,
                actor_id,
                "tierlist.item.move",
                {"item_id": item_id, "tier": tier.value},
            )
        return self.get_item(item_id)

    def rename_list(self, list_id: str, actor_id: int, new_name: str) -> TierList:
        now = self.db.utc_now()
        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE tier_lists SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now, list_id),
            )
            self._log(
                conn,
                list_obj.guild_id,
                list_id,
                actor_id,
                "tierlist.rename",
                {"name": new_name},
            )
        return self.get_list(list_id)

    def relabel_item(self, list_id: str, item_id: str, actor_id: int, label: str) -> TierItem:
        now = self.db.utc_now()
        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT id FROM items WHERE id = ? AND list_id = ?", (item_id, list_id)
            ).fetchone()
            if not row:
                raise NotFoundError("Item not found in this tier list.")
            conn.execute("UPDATE items SET label = ? WHERE id = ?", (label, item_id))
            conn.execute("UPDATE tier_lists SET updated_at = ? WHERE id = ?", (now, list_id))
            self._log(
                conn,
                list_obj.guild_id,
                list_id,
                actor_id,
                "tierlist.item.relabel",
                {"item_id": item_id, "label": label},
            )
        return self.get_item(item_id)

    def delete_list(self, list_id: str, actor_id: int) -> None:
        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            item_rows = conn.execute(
                "SELECT image_path FROM items WHERE list_id = ?", (list_id,)
            ).fetchall()
            conn.execute("DELETE FROM tier_lists WHERE id = ?", (list_id,))
            self._log(conn, list_obj.guild_id, list_id, actor_id, "tierlist.delete", {})

        for row in item_rows:
            path = Path(row["image_path"])
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    continue

    def _log(
        self,
        conn,
        guild_id: int,
        list_id: str | None,
        actor_id: int,
        event_type: str,
        payload: dict,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_events(guild_id, list_id, actor_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                list_id,
                actor_id,
                event_type,
                json.dumps(payload, separators=(",", ":")),
                self.db.utc_now(),
            ),
        )
