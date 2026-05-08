from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from TierListBot.services.image_store import ImageStore, ImageValidationError
from TierListBot.services.renderer import BoardRenderer
from TierListBot.services.tierlist_service import LimitError, NotFoundError, TierListError, TierListService

logger = logging.getLogger(__name__)


class TierShortcutsCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        service: TierListService,
        image_store: ImageStore,
        renderer: BoardRenderer,
        http_session,
    ):
        self.bot = bot
        self.service = service
        self.image_store = image_store
        self.renderer = renderer
        self.http_session = http_session

    async def _add_to_tier(
        self,
        interaction: discord.Interaction,
        tier_label: str,
        attachment: discord.Attachment,
    ) -> None:
        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message(
                "This command only works in a server channel.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        tier_list = self.service.get_active_list(interaction.channel_id)
        if tier_list is None:
            await interaction.followup.send(
                "No active tier list in this channel. Use `/tierlist create` first.",
                ephemeral=True,
            )
            return

        tier_labels = self.service.get_tiers_ordered(tier_list.id)
        if tier_label not in tier_labels:
            await interaction.followup.send(
                f"Tier `{tier_label}` does not exist on this list. "
                f"Available: {', '.join(tier_labels)}",
                ephemeral=True,
            )
            return

        try:
            suffix = Path(attachment.filename).suffix.lstrip(".") or "png"
            stored = await self.image_store.save_from_url(
                self.http_session,
                attachment.url,
                suffix,
                attachment.content_type,
                attachment.size,
            )
        except ImageValidationError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        try:
            item = self.service.add_item(
                list_id=tier_list.id,
                actor_id=interaction.user.id,
                label=None,
                tier=tier_label,
                image=stored,
                original_filename=attachment.filename,
            )
        except (LimitError, NotFoundError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        items = self.service.list_items(tier_list.id)
        output_path = self.renderer.render(tier_list, items, tier_labels)

        assert interaction.channel is not None
        assert tier_list.message_id is not None
        partial_msg = interaction.channel.get_partial_message(int(tier_list.message_id))
        try:
            await partial_msg.edit(attachments=[discord.File(output_path, filename=f"{tier_list.id}.png")])
        except discord.HTTPException as exc:
            logger.warning("Failed to edit board message: %s", exc)
            fallback_msg = await interaction.channel.send(
                file=discord.File(output_path, filename=f"{tier_list.id}.png")
            )
            self.service.update_message_id(tier_list.id, str(fallback_msg.id))

        await interaction.followup.send(
            f"Added to **{tier_label}** tier! (`{item.id}`)", ephemeral=True
        )

    @app_commands.command(name="s", description="Add image to S tier of the active list")
    @app_commands.describe(image="Image to add")
    async def s(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._add_to_tier(interaction, "S", image)

    @app_commands.command(name="a", description="Add image to A tier of the active list")
    @app_commands.describe(image="Image to add")
    async def a(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._add_to_tier(interaction, "A", image)

    @app_commands.command(name="b", description="Add image to B tier of the active list")
    @app_commands.describe(image="Image to add")
    async def b(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._add_to_tier(interaction, "B", image)

    @app_commands.command(name="c", description="Add image to C tier of the active list")
    @app_commands.describe(image="Image to add")
    async def c(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._add_to_tier(interaction, "C", image)

    @app_commands.command(name="d", description="Add image to D tier of the active list")
    @app_commands.describe(image="Image to add")
    async def d(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._add_to_tier(interaction, "D", image)

    @app_commands.command(name="add-tier", description="Add a custom tier to the active list")
    @app_commands.describe(name="Tier label (e.g. god-tier)")
    async def add_tier(self, interaction: discord.Interaction, name: str) -> None:
        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message(
                "This command only works in a server channel.", ephemeral=True
            )
            return

        tier_list = self.service.get_active_list(interaction.channel_id)
        if tier_list is None:
            await interaction.response.send_message(
                "No active tier list in this channel. Use `/tierlist create` first.",
                ephemeral=True,
            )
            return

        try:
            self.service.add_tier(tier_list.id, interaction.user.id, name)
        except TierListError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        tier_labels = self.service.get_tiers_ordered(tier_list.id)
        items = self.service.list_items(tier_list.id)
        output_path = self.renderer.render(tier_list, items, tier_labels)

        assert interaction.channel is not None
        assert tier_list.message_id is not None
        partial_msg = interaction.channel.get_partial_message(int(tier_list.message_id))
        try:
            await partial_msg.edit(attachments=[discord.File(output_path, filename=f"{tier_list.id}.png")])
        except discord.HTTPException as exc:
            logger.warning("Failed to edit board message: %s", exc)

        await interaction.followup.send(f"Added tier **{name}** to the list.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    deps = bot.deps
    cog = TierShortcutsCog(
        bot,
        service=deps["tierlist_service"],
        image_store=deps["image_store"],
        renderer=deps["renderer"],
        http_session=deps["http_session"],
    )
    for cmd in [cog.s, cog.a, cog.b, cog.c, cog.d, cog.add_tier]:
        bot.tree.add_command(cmd)
    await bot.add_cog(cog)
