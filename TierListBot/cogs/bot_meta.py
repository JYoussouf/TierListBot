from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)


class BotMetaCog(commands.Cog):
    meta = app_commands.Group(name="bot", description="Bot operational commands")

    def __init__(self, bot: commands.Bot, support_url: str):
        self.bot = bot
        self.support_url = support_url
        self._topgg = bot.deps.get("topgg_client")
        self.topgg_stats_loop.start()

    def cog_unload(self) -> None:
        self.topgg_stats_loop.cancel()

    @meta.command(name="status", description="Check bot health")
    async def status(self, interaction: discord.Interaction) -> None:
        guilds = len(self.bot.guilds)
        latency_ms = round(self.bot.latency * 1000, 1)
        topgg_enabled = "yes" if self._topgg else "no"
        await interaction.response.send_message(
            "\n".join(
                [
                    "TierListBot is online.",
                    f"Guilds: **{guilds}**",
                    f"Latency: **{latency_ms}ms**",
                    f"top.gg stats posting: **{topgg_enabled}**",
                    f"Support: {self.support_url}",
                ]
            ),
            ephemeral=True,
        )

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
    bot.tree.add_command(cog.meta)
    await bot.add_cog(cog)
