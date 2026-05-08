from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS guilds (
    guild_id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tier_lists (
    id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    message_id TEXT,
    finished_at TEXT,
    FOREIGN KEY(guild_id) REFERENCES guilds(guild_id)
);

CREATE TABLE IF NOT EXISTS tiers (
    list_id TEXT NOT NULL,
    tier_label TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY(list_id, tier_label),
    FOREIGN KEY(list_id) REFERENCES tier_lists(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    list_id TEXT NOT NULL,
    label TEXT,
    tier TEXT NOT NULL,
    image_path TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(list_id) REFERENCES tier_lists(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS item_images (
    item_id TEXT PRIMARY KEY,
    original_filename TEXT,
    content_type TEXT,
    byte_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    list_id TEXT,
    actor_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            self._conn.commit()
            try:
                self._conn.execute("ALTER TABLE tier_lists ADD COLUMN message_id TEXT")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                self._conn.execute("ALTER TABLE tier_lists ADD COLUMN finished_at TEXT")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

    def get_active_list_by_channel(self, channel_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                """
                SELECT * FROM tier_lists
                WHERE channel_id = ? AND message_id IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (channel_id,),
            ).fetchone()

    def get_finished_lists(self, channel_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """
                SELECT * FROM tier_lists
                WHERE channel_id = ? AND finished_at IS NOT NULL
                ORDER BY finished_at DESC LIMIT ?
                """,
                (channel_id, limit),
            ).fetchall()

    def update_message_id(self, list_id: str, message_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tier_lists SET message_id = ? WHERE id = ?",
                (message_id, list_id),
            )
            self._conn.commit()

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
