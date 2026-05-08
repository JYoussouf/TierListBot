from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


DEFAULT_TIERS: list[str] = ["S", "A", "B", "C", "D"]


@dataclass(slots=True)
class TierList:
    id: str
    guild_id: int
    channel_id: int
    owner_id: int
    name: str
    created_at: datetime
    updated_at: datetime
    message_id: str | None = None
    finished_at: datetime | None = None


@dataclass(slots=True)
class TierItem:
    id: str
    list_id: str
    label: str | None
    tier: str
    image_path: str
    created_by: int
    created_at: datetime
