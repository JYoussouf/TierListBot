from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from TierListBot.models import DEFAULT_TIERS, Tier
from TierListBot.services.image_store import ImageStore, ImageValidationError
from TierListBot.services.tierlist_service import LimitError, NotFoundError, TierListService

logger = logging.getLogger(__name__)


class RenameListModal(discord.ui.Modal, title="Rename Tier List"):
    new_name = discord.ui.TextInput(label="New name", min_length=1, max_length=80)

    def __init__(self, cog: "TierListCog", list_id: str):
        super().__init__()
        self.cog = cog
        self.list_id = list_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        if not await self.cog._can_edit(interaction, self.list_id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can edit this list.",
                ephemeral=True,
            )
            return

        updated = self.cog.service.rename_list(
            self.list_id,
            interaction.user.id,
            str(self.new_name),
        )
        await interaction.response.send_message(
            f"Renamed tier list `{updated.id}` to **{updated.name}**.", ephemeral=True
        )


class RelabelItemModal(discord.ui.Modal, title="Edit Item Label"):
    item_id = discord.ui.TextInput(label="Item ID", min_length=3, max_length=24)
    new_label = discord.ui.TextInput(label="New label", min_length=1, max_length=40)

    def __init__(self, cog: "TierListCog", list_id: str):
        super().__init__()
        self.cog = cog
        self.list_id = list_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        if not await self.cog._can_edit(interaction, self.list_id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can edit this list.",
                ephemeral=True,
            )
            return
        try:
            item = self.cog.service.relabel_item(
                self.list_id,
                str(self.item_id).strip(),
                interaction.user.id,
                str(self.new_label),
            )
            await interaction.response.send_message(
                f"Updated label for item `{item.id}` to **{self.new_label}**.",
                ephemeral=True,
            )
        except NotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class TierListManageView(discord.ui.View):
    def __init__(self, cog: "TierListCog", list_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.list_id = list_id

    @discord.ui.button(label="Rename List", style=discord.ButtonStyle.primary)
    async def rename_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(RenameListModal(self.cog, self.list_id))

    @discord.ui.button(label="Edit Item Label", style=discord.ButtonStyle.secondary)
    async def relabel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(RelabelItemModal(self.cog, self.list_id))

    @discord.ui.button(label="Save Board Image", style=discord.ButtonStyle.success)
    async def save_board_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.render_and_send(interaction, self.list_id, ephemeral=True)


class QuickMoveView(discord.ui.View):
    def __init__(self, cog: "TierListCog", list_id: str, item_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.list_id = list_id
        self.item_id = item_id

    async def _move(self, interaction: discord.Interaction, tier: Tier) -> None:
        if not await self.cog._can_edit(interaction, self.list_id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can edit this list.",
                ephemeral=True,
            )
            return
        try:
            item = self.cog.service.move_item(
                self.list_id, self.item_id, interaction.user.id, tier
            )
        except NotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Moved `{item.id}` to tier **{tier.value}**.", ephemeral=True
        )

    @discord.ui.button(label="S", style=discord.ButtonStyle.danger)
    async def s_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, Tier.S)

    @discord.ui.button(label="A", style=discord.ButtonStyle.secondary)
    async def a_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, Tier.A)

    @discord.ui.button(label="B", style=discord.ButtonStyle.secondary)
    async def b_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, Tier.B)

    @discord.ui.button(label="C", style=discord.ButtonStyle.secondary)
    async def c_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, Tier.C)

    @discord.ui.button(label="D", style=discord.ButtonStyle.secondary)
    async def d_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, Tier.D)


class TierListCog(commands.Cog):
    tierlist = app_commands.Group(name="tierlist", description="Manage tier lists")

    def __init__(
        self,
        bot: commands.Bot,
        service: TierListService,
        image_store: ImageStore,
        renderer,
        http_session,
    ):
        self.bot = bot
        self.service = service
        self.image_store = image_store
        self.renderer = renderer
        self.http_session = http_session

    async def _can_edit(self, interaction: discord.Interaction, list_id: str) -> bool:
        list_obj = self.service.get_list(list_id)
        if interaction.user.id == list_obj.owner_id:
            return True
        if isinstance(interaction.user, discord.Member):
            return interaction.user.guild_permissions.administrator
        return False

    async def render_and_send(
        self, interaction: discord.Interaction, list_id: str, ephemeral: bool
    ) -> None:
        try:
            list_obj = self.service.get_list(list_id)
            items = self.service.list_items(list_id)
        except NotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        output_path = self.renderer.render(list_obj, items)
        file = discord.File(output_path, filename=f"{list_obj.id}.png")
        if interaction.response.is_done():
            await interaction.followup.send(file=file, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(file=file, ephemeral=ephemeral)

    @tierlist.command(name="create", description="Create a new tier list")
    @app_commands.describe(name="Display name for this tier list", template="Optional template")
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        template: str | None = None,
    ) -> None:
        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message(
                "This command only works in a server channel.", ephemeral=True
            )
            return

        template_name = template or "default"
        try:
            tier_list = self.service.create_list(
                interaction.guild.id,
                interaction.channel_id,
                interaction.user.id,
                name=f"{name} ({template_name})" if template else name,
            )
        except LimitError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_message(
            f"Created tier list **{tier_list.name}** with ID `{tier_list.id}`."
        )

    @tierlist.command(name="add", description="Add an image item to a tier list")
    @app_commands.describe(
        list_id="Tier list ID", image="Image attachment", label="Optional item label"
    )
    async def add(
        self,
        interaction: discord.Interaction,
        list_id: str,
        image: discord.Attachment,
        label: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return

        if not await self._can_edit(interaction, list_id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can edit this list.",
                ephemeral=True,
            )
            return

        try:
            suffix = Path(image.filename).suffix.lstrip(".") or "png"
            stored = await self.image_store.save_from_url(
                self.http_session,
                image.url,
                suffix,
                image.content_type,
                image.size,
            )
            item = self.service.add_item(
                list_id=list_id,
                actor_id=interaction.user.id,
                label=label,
                tier=Tier.D,
                image=stored,
                original_filename=image.filename,
            )
        except (ImageValidationError, LimitError, NotFoundError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        view = QuickMoveView(self, list_id, item.id)
        await interaction.response.send_message(
            f"Added item `{item.id}` to tier **D**. Use buttons for quick move.",
            view=view,
        )

    @tierlist.command(name="move", description="Move an item to another tier")
    @app_commands.describe(list_id="Tier list ID", item_id="Item ID", tier="Target tier")
    async def move(
        self,
        interaction: discord.Interaction,
        list_id: str,
        item_id: str,
        tier: Literal["S", "A", "B", "C", "D"],
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return

        if not await self._can_edit(interaction, list_id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can edit this list.",
                ephemeral=True,
            )
            return

        try:
            item = self.service.move_item(list_id, item_id, interaction.user.id, Tier(tier))
        except NotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_message(
            f"Moved item `{item.id}` to tier **{item.tier.value}**."
        )

    @tierlist.command(name="render", description="Render and post the tier board")
    @app_commands.describe(list_id="Tier list ID")
    async def render(self, interaction: discord.Interaction, list_id: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return
        await self.render_and_send(interaction, list_id, ephemeral=False)

    @tierlist.command(name="show", description="Show current tier list details")
    @app_commands.describe(list_id="Tier list ID")
    async def show(self, interaction: discord.Interaction, list_id: str) -> None:
        try:
            tier_list = self.service.get_list(list_id)
            items = self.service.list_items(list_id)
        except NotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        lines = [f"**{tier_list.name}** (`{tier_list.id}`)"]
        for tier in DEFAULT_TIERS:
            tier_items = [i for i in items if i.tier == tier]
            if not tier_items:
                lines.append(f"`{tier.value}`: (empty)")
                continue
            summary = ", ".join(
                f"`{item.id}`{f' {item.label}' if item.label else ''}" for item in tier_items[:8]
            )
            lines.append(f"`{tier.value}`: {summary}")

        view = TierListManageView(self, list_id)
        await interaction.response.send_message("\n".join(lines), view=view)

    @tierlist.command(name="delete", description="Delete a tier list")
    @app_commands.describe(list_id="Tier list ID")
    async def delete(self, interaction: discord.Interaction, list_id: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return

        if not await self._can_edit(interaction, list_id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can edit this list.",
                ephemeral=True,
            )
            return

        try:
            self.service.delete_list(list_id, interaction.user.id)
        except NotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_message(f"Deleted tier list `{list_id}`.")


async def setup(bot: commands.Bot) -> None:
    deps = bot.deps
    cog = TierListCog(
        bot,
        service=deps["tierlist_service"],
        image_store=deps["image_store"],
        renderer=deps["renderer"],
        http_session=deps["http_session"],
    )
    bot.tree.add_command(cog.tierlist)
    await bot.add_cog(cog)
