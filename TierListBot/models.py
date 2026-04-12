from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Tier(str, Enum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


DEFAULT_TIERS = [Tier.S, Tier.A, Tier.B, Tier.C, Tier.D]


@dataclass(slots=True)
class TierList:
    id: str
    guild_id: int
    channel_id: int
    owner_id: int
    name: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class TierItem:
    id: str
    list_id: str
    label: str | None
    tier: Tier
    image_path: str
    created_by: int
    created_at: datetime
