from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)


class BotMetaCog(commands.Cog):
    def __init__(self, bot: commands.Bot, support_url: str):
        self.bot = bot
        self.support_url = support_url
        self._topgg = bot.deps.get("topgg_client")
        self.topgg_stats_loop.start()

    def cog_unload(self) -> None:
        self.topgg_stats_loop.cancel()

    @tasks.loop(minutes=30)
    async def topgg_stats_loop(self) -> None:
        if not self._topgg:
            return
        try:
            await self.bot.wait_until_ready()
            await self._topgg.post_stats(len(self.bot.guilds))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to post top.gg stats: %s", exc)

    @topgg_stats_loop.before_loop
    async def before_topgg_stats_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    support_url = bot.deps["settings"].support_server_url
    cog = BotMetaCog(bot, support_url=support_url)
    await bot.add_cog(cog)
