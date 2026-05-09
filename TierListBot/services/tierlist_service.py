from __future__ import annotations

import json
import textwrap
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from TierListBot.models import DEFAULT_TIERS, TierItem, TierList
from TierListBot.services.db import Database
from TierListBot.services.image_store import StoredImage


# Label rendering constraints - must match renderer.py constants
LABEL_WRAP_WIDTH = 18
LABEL_MAX_LINES  = 5
LABEL_MAX_CHARS  = LABEL_WRAP_WIDTH * LABEL_MAX_LINES  # 90


def tier_label_line_count(label: str) -> int:
    """Lines the label would occupy when word-wrapped for the board."""
    lines = textwrap.wrap(label, LABEL_WRAP_WIDTH, break_long_words=True)
    return len(lines) if lines else 1


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
                    (list_id, tier, idx),
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
            message_id=row["message_id"],
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )

    def list_items(self, list_id: str) -> list[TierItem]:
        with self.db.tx() as conn:
            rows = conn.execute(
                "SELECT * FROM items WHERE list_id = ? ORDER BY position ASC", (list_id,)
            ).fetchall()
        result: list[TierItem] = []
        for row in rows:
            result.append(
                TierItem(
                    id=row["id"],
                    list_id=row["list_id"],
                    label=row["label"],
                    tier=row["tier"],
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
        tier: str,
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

            max_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM items WHERE list_id = ?", (list_id,)
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO items(id, list_id, label, tier, image_path, created_by, created_at, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, list_id, label, tier, str(image.path), actor_id, now, max_pos + 1),
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
                {"item_id": item_id, "tier": tier, "label": label},
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
            tier=row["tier"],
            image_path=row["image_path"],
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def move_item(self, list_id: str, item_id: str, actor_id: int, tier: str) -> TierItem:
        now = self.db.utc_now()
        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT id FROM items WHERE id = ? AND list_id = ?", (item_id, list_id)
            ).fetchone()
            if not row:
                raise NotFoundError("Item not found in this tier list.")
            max_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM items WHERE list_id = ?", (list_id,)
            ).fetchone()[0]
            conn.execute(
                "UPDATE items SET tier = ?, position = ? WHERE id = ?",
                (tier, max_pos + 1, item_id),
            )
            conn.execute("UPDATE tier_lists SET updated_at = ? WHERE id = ?", (now, list_id))
            self._log(
                conn,
                list_obj.guild_id,
                list_id,
                actor_id,
                "tierlist.item.move",
                {"item_id": item_id, "tier": tier},
            )
        return self.get_item(item_id)

    def reorder_item(self, list_id: str, item_id: str, actor_id: int, before_item_id: str) -> TierItem:
        """Move item_id to appear just before before_item_id (possibly changing its tier)."""
        now = self.db.utc_now()
        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            if not conn.execute(
                "SELECT id FROM items WHERE id = ? AND list_id = ?", (item_id, list_id)
            ).fetchone():
                raise NotFoundError("Item not found in this tier list.")
            target = conn.execute(
                "SELECT position, tier FROM items WHERE id = ? AND list_id = ?",
                (before_item_id, list_id),
            ).fetchone()
            if not target:
                raise NotFoundError("Target item not found in this tier list.")
            target_pos = target["position"]
            target_tier = target["tier"]
            conn.execute(
                "UPDATE items SET position = position + 1 WHERE list_id = ? AND position >= ? AND id != ?",
                (list_id, target_pos, item_id),
            )
            conn.execute(
                "UPDATE items SET tier = ?, position = ? WHERE id = ?",
                (target_tier, target_pos, item_id),
            )
            conn.execute("UPDATE tier_lists SET updated_at = ? WHERE id = ?", (now, list_id))
            self._log(
                conn,
                list_obj.guild_id,
                list_id,
                actor_id,
                "tierlist.item.reorder",
                {"item_id": item_id, "before_item_id": before_item_id, "tier": target_tier},
            )
        return self.get_item(item_id)

    def delete_item(self, list_id: str, item_id: str, actor_id: int) -> None:
        now = self.db.utc_now()
        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT image_path FROM items WHERE id = ? AND list_id = ?", (item_id, list_id)
            ).fetchone()
            if not row:
                raise NotFoundError("Item not found in this tier list.")
            image_path = row["image_path"]
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            conn.execute("UPDATE tier_lists SET updated_at = ? WHERE id = ?", (now, list_id))
            self._log(
                conn,
                list_obj.guild_id,
                list_id,
                actor_id,
                "tierlist.item.delete",
                {"item_id": item_id},
            )
        path = Path(image_path)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

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

    def get_active_list(self, channel_id: int) -> TierList | None:
        row = self.db.get_active_list_by_channel(channel_id)
        if not row:
            return None
        return TierList(
            id=row["id"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            owner_id=row["owner_id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            message_id=row["message_id"],
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )

    def update_message_id(self, list_id: str, message_id: str) -> None:
        self.db.update_message_id(list_id, message_id)

    def finish_list(self, list_id: str, actor_id: int) -> TierList:
        list_obj = self.get_list(list_id)
        now = self.db.utc_now()
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE tier_lists SET message_id = NULL, finished_at = ? WHERE id = ?",
                (now, list_id),
            )
            self._log(conn, list_obj.guild_id, list_id, actor_id, "tierlist.finish", {})
        return self.get_list(list_id)

    def get_history(self, channel_id: int, limit: int = 10) -> list[TierList]:
        rows = self.db.get_finished_lists(channel_id, limit)
        return [
            TierList(
                id=row["id"],
                guild_id=row["guild_id"],
                channel_id=row["channel_id"],
                owner_id=row["owner_id"],
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                message_id=row["message_id"],
                finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            )
            for row in rows
        ]

    def get_tiers_ordered(self, list_id: str) -> list[str]:
        with self.db.tx() as conn:
            rows = conn.execute(
                "SELECT tier_label FROM tiers WHERE list_id = ? ORDER BY position ASC",
                (list_id,),
            ).fetchall()
        return [row["tier_label"] for row in rows]

    def add_tier(self, list_id: str, actor_id: int, tier_label: str) -> None:
        if tier_label_line_count(tier_label) > LABEL_MAX_LINES:
            raise LimitError(
                f"Tier label is too long ({len(tier_label)} chars). "
                f"Labels wrap at {LABEL_WRAP_WIDTH} characters per line with a max of "
                f"{LABEL_MAX_LINES} lines - keep it under {LABEL_MAX_CHARS} characters."
            )
        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            exists = conn.execute(
                "SELECT 1 FROM tiers WHERE list_id = ? AND tier_label = ?",
                (list_id, tier_label),
            ).fetchone()
            if exists:
                raise TierListError(f"Tier '{tier_label}' already exists.")
            max_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM tiers WHERE list_id = ?",
                (list_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO tiers(list_id, tier_label, position) VALUES (?, ?, ?)",
                (list_id, tier_label, max_pos + 1),
            )
            self._log(
                conn, list_obj.guild_id, list_id, actor_id,
                "tierlist.tier.add", {"tier_label": tier_label},
            )

    def set_tiers(self, list_id: str, actor_id: int, new_labels: list[str]) -> None:
        """Replace all tiers with new_labels (in order). Items in removed tiers move to the first new tier."""
        if not new_labels:
            raise TierListError("A tier list must have at least one tier.")
        seen: set[str] = set()
        for label in new_labels:
            if not label.strip():
                raise TierListError("Tier labels cannot be blank.")
            if label in seen:
                raise TierListError(f"Duplicate tier label: '{label}'.")
            if tier_label_line_count(label) > LABEL_MAX_LINES:
                raise LimitError(
                    f"'{label}' is too long ({len(label)} chars). "
                    f"Max {LABEL_MAX_CHARS} characters ({LABEL_MAX_LINES} lines × {LABEL_WRAP_WIDTH})."
                )
            seen.add(label)

        list_obj = self.get_list(list_id)
        with self.db.tx() as conn:
            old_labels = [
                row["tier_label"]
                for row in conn.execute(
                    "SELECT tier_label FROM tiers WHERE list_id = ? ORDER BY position",
                    (list_id,),
                ).fetchall()
            ]
            removed = set(old_labels) - set(new_labels)
            if removed:
                fallback = new_labels[0]
                for gone in removed:
                    conn.execute(
                        "UPDATE items SET tier = ? WHERE list_id = ? AND tier = ?",
                        (fallback, list_id, gone),
                    )
            conn.execute("DELETE FROM tiers WHERE list_id = ?", (list_id,))
            for idx, label in enumerate(new_labels):
                conn.execute(
                    "INSERT INTO tiers(list_id, tier_label, position) VALUES (?, ?, ?)",
                    (list_id, label, idx),
                )
            now = self.db.utc_now()
            conn.execute("UPDATE tier_lists SET updated_at = ? WHERE id = ?", (now, list_id))
            self._log(
                conn, list_obj.guild_id, list_id, actor_id,
                "tierlist.tiers.edit",
                {"added": list(set(new_labels) - set(old_labels)), "removed": list(removed), "order": new_labels},
            )

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
