from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    discord_token: str
    discord_application_id: int
    discord_guild_id: int | None
    topgg_api_token: str | None
    topgg_bot_id: str | None
    support_server_url: str
    base_data_dir: Path
    max_image_bytes: int
    max_items_per_list: int
    max_lists_per_guild: int
    log_level: str
    r2_endpoint_url: str | None
    r2_access_key_id: str | None
    r2_secret_access_key: str | None
    r2_bucket: str | None

    @property
    def db_path(self) -> Path:
        return self.base_data_dir / "tierlistbot.sqlite3"

    @property
    def images_dir(self) -> Path:
        return self.base_data_dir / "images"


def _opt_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(value)


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    app_id = os.getenv("DISCORD_APPLICATION_ID", "").strip()
    if not token:
        raise ValueError("DISCORD_TOKEN is required")
    if not app_id:
        raise ValueError("DISCORD_APPLICATION_ID is required")

    base_data_dir = Path(os.getenv("BASE_DATA_DIR", "./data")).resolve()
    base_data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        discord_token=token,
        discord_application_id=int(app_id),
        discord_guild_id=_opt_int(os.getenv("DISCORD_GUILD_ID")),
        topgg_api_token=os.getenv("TOPGG_API_TOKEN") or None,
        topgg_bot_id=os.getenv("TOPGG_BOT_ID") or None,
        support_server_url=os.getenv("SUPPORT_SERVER_URL", "https://discord.gg/support"),
        base_data_dir=base_data_dir,
        max_image_bytes=int(os.getenv("MAX_IMAGE_BYTES", str(5 * 1024 * 1024))),
        max_items_per_list=int(os.getenv("MAX_ITEMS_PER_LIST", "100")),
        max_lists_per_guild=int(os.getenv("MAX_LISTS_PER_GUILD", "50")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        r2_endpoint_url=os.getenv("CF_R2_ENDPOINT_URL") or None,
        r2_access_key_id=os.getenv("CF_R2_ACCESS_KEY_ID") or None,
        r2_secret_access_key=os.getenv("CF_R2_SECRET_ACCESS_KEY") or None,
        r2_bucket=os.getenv("CF_R2_BUCKET") or None,
    )
