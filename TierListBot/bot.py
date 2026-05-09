from __future__ import annotations

import asyncio
import logging

import aiohttp
import discord
from discord.ext import commands

from TierListBot.config import Settings
from TierListBot.services.db import Database
from TierListBot.services.image_store import ImageStore
from TierListBot.services.renderer import BoardRenderer
from TierListBot.services.tierlist_service import TierListService
from TierListBot.services.topgg import TopGGClient

logger = logging.getLogger(__name__)


class TierListBotBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.none()
        intents.guilds = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            application_id=settings.discord_application_id,
        )
        self.settings = settings
        self.http_session: aiohttp.ClientSession | None = None
        self.db = Database(settings.db_path)
        self.db.init_schema()

        s3_client = None
        if settings.r2_bucket and settings.r2_endpoint_url:
            import boto3
            s3_client = boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
            )

        image_store = ImageStore(
            settings.images_dir,
            settings.max_image_bytes,
            s3_client=s3_client,
            bucket_name=settings.r2_bucket,
        )
        renderer = BoardRenderer(settings.base_data_dir / "renders")
        tierlist_service = TierListService(
            self.db,
            max_lists_per_guild=settings.max_lists_per_guild,
            max_items_per_list=settings.max_items_per_list,
        )

        self.deps = {
            "settings": settings,
            "image_store": image_store,
            "renderer": renderer,
            "tierlist_service": tierlist_service,
        }

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession()
        self.deps["http_session"] = self.http_session

        if self.settings.topgg_api_token and self.settings.topgg_bot_id:
            self.deps["topgg_client"] = TopGGClient(
                self.http_session,
                bot_id=self.settings.topgg_bot_id,
                token=self.settings.topgg_api_token,
            )
        else:
            self.deps["topgg_client"] = None

        await self.load_extension("TierListBot.cogs.tierlist")
        await self.load_extension("TierListBot.cogs.bot_meta")

        if self.settings.discord_guild_id:
            guild_obj = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info(
                "Synced %s guild commands to guild %s",
                len(synced),
                self.settings.discord_guild_id,
            )
        else:
            synced = await self.tree.sync()
            logger.info("Synced %s global commands", len(synced))

    async def close(self) -> None:
        logger.info("Shutting down TierListBot bot")
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        self.db.close()
        await super().close()


async def run_bot(settings: Settings) -> None:
    bot = TierListBotBot(settings)
    async with bot:
        await bot.start(settings.discord_token)
