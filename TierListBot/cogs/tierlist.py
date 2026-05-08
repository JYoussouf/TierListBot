from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from TierListBot.models import TierItem, TierList
from TierListBot.services.image_store import ImageStore, ImageValidationError
from TierListBot.services.tierlist_service import LimitError, NotFoundError, TierListError, TierListService

logger = logging.getLogger(__name__)


# ── Modals ────────────────────────────────────────────────────────────────────


class EditTiersModal(discord.ui.Modal, title="Edit Tiers"):
    tiers_input = discord.ui.TextInput(
        label="One tier per line — add, remove, reorder",
        style=discord.TextStyle.long,
        min_length=1,
        max_length=500,
        placeholder="S\nA\nB\nC\nD",
    )

    def __init__(self, cog: "TierListCog", tier_list: TierList, current_labels: list[str]):
        super().__init__()
        self.cog = cog
        self.tier_list = tier_list
        self.tiers_input.default = "\n".join(current_labels)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.tiers_input)
        new_labels = [line.strip() for line in raw.splitlines() if line.strip()]

        try:
            self.cog.service.set_tiers(self.tier_list.id, interaction.user.id, new_labels)
        except (TierListError, LimitError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        tier_list  = self.cog.service.get_list(self.tier_list.id)
        items      = self.cog.service.list_items(tier_list.id)
        tier_labels = self.cog.service.get_tiers_ordered(tier_list.id)
        output_path = self.cog.renderer.render(tier_list, items, tier_labels)

        assert interaction.channel is not None
        if tier_list.message_id:
            partial = interaction.channel.get_partial_message(int(tier_list.message_id))
            try:
                await partial.edit(attachments=[discord.File(output_path, filename=f"{tier_list.id}.png")])
            except discord.HTTPException:
                new_msg = await interaction.channel.send(
                    file=discord.File(output_path, filename=f"{tier_list.id}.png")
                )
                self.cog.service.update_message_id(tier_list.id, str(new_msg.id))
        else:
            new_msg = await interaction.channel.send(
                file=discord.File(output_path, filename=f"{tier_list.id}.png")
            )
            self.cog.service.update_message_id(tier_list.id, str(new_msg.id))

        await interaction.followup.send("​", ephemeral=True)


# ── Views ─────────────────────────────────────────────────────────────────────


class DeleteConfirmView(discord.ui.View):
    def __init__(self, cog: "TierListCog", tier_list: TierList):
        super().__init__(timeout=60)
        self.cog = cog
        self.tier_list = tier_list

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            self.cog.service.delete_list(self.tier_list.id, interaction.user.id)
        except NotFoundError:
            pass
        await interaction.response.edit_message(content="​", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Cancelled.", view=None)


class HistorySelectView(discord.ui.View):
    def __init__(self, cog: "TierListCog", finished_lists):
        super().__init__(timeout=120)
        self.cog = cog

        options = []
        for tl in finished_lists[:25]:
            finished_str = tl.finished_at.strftime("%Y-%m-%d") if tl.finished_at else "?"
            options.append(
                discord.SelectOption(
                    label=tl.name[:100],
                    value=tl.id,
                    description=f"Finished {finished_str}",
                )
            )

        select = discord.ui.Select(
            placeholder="Pick a finished tier list to re-render…",
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        list_id = interaction.data["values"][0]  # type: ignore[index]
        await interaction.response.defer(ephemeral=True)
        try:
            list_obj    = self.cog.service.get_list(list_id)
            items       = self.cog.service.list_items(list_id)
            tier_labels = self.cog.service.get_tiers_ordered(list_id)
        except Exception as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        output_path = self.cog.renderer.render(list_obj, items, tier_labels)
        finished_str = list_obj.finished_at.strftime("%Y-%m-%d") if list_obj.finished_at else "?"
        await interaction.followup.send(
            f"**{list_obj.name}** (finished {finished_str})",
            file=discord.File(output_path, filename=f"{list_obj.id}.png"),
            ephemeral=True,
        )


class TierSelectView(discord.ui.View):
    """Shown after /tl add — user picks a tier and the item is placed + board updated."""

    def __init__(
        self,
        cog: "TierListCog",
        tier_list: TierList,
        tier_labels: list[str],
        stored_image,
        original_filename: str | None,
        label: str | None,
        actor_id: int,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.tier_list = tier_list
        self.stored_image = stored_image
        self.original_filename = original_filename
        self.label = label
        self.actor_id = actor_id

        for tier_label in tier_labels[:25]:
            btn = discord.ui.Button(label=tier_label[:80], style=discord.ButtonStyle.primary)
            btn.callback = self._make_callback(tier_label)
            self.add_item(btn)

    def _make_callback(self, tier_label: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self._place(interaction, tier_label)
        return callback

    async def _place(self, interaction: discord.Interaction, tier_label: str) -> None:
        try:
            item = self.cog.service.add_item(
                list_id=self.tier_list.id,
                actor_id=self.actor_id,
                label=self.label,
                tier=tier_label,
                image=self.stored_image,
                original_filename=self.original_filename,
            )
        except (LimitError, NotFoundError) as exc:
            await interaction.response.edit_message(content=str(exc), view=None)
            return

        tier_list   = self.cog.service.get_list(self.tier_list.id)
        items       = self.cog.service.list_items(self.tier_list.id)
        tier_labels = self.cog.service.get_tiers_ordered(self.tier_list.id)
        output_path = self.cog.renderer.render(tier_list, items, tier_labels)

        assert interaction.channel is not None
        if tier_list.message_id:
            partial = interaction.channel.get_partial_message(int(tier_list.message_id))
            try:
                await partial.edit(
                    attachments=[discord.File(output_path, filename=f"{tier_list.id}.png")]
                )
            except discord.HTTPException:
                new_msg = await interaction.channel.send(
                    file=discord.File(output_path, filename=f"{tier_list.id}.png")
                )
                self.cog.service.update_message_id(self.tier_list.id, str(new_msg.id))

        await interaction.response.edit_message(content="​", view=None)


class MoveItemView(discord.ui.View):
    """Two-select + Move button: pick item → pick tier → confirm."""

    def __init__(
        self,
        cog: "TierListCog",
        tier_list: TierList,
        items: list[TierItem],
        tier_labels: list[str],
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.tier_list = tier_list
        self.selected_item_id: str | None = None
        self.selected_tier: str | None = None

        # ── positional labels: S1, S2, A1, custom-tier1, … ───────────────────
        tier_counter: dict[str, int] = {}
        self._item_display: dict[str, str] = {}  # item_id → "S1" / "S1 — label"
        for item in items[:25]:
            n = tier_counter[item.tier] = tier_counter.get(item.tier, 0) + 1
            positional = f"{item.tier}{n}"
            self._item_display[item.id] = positional

        # ── item select ───────────────────────────────────────────────────────
        item_opts: list[discord.SelectOption] = []
        for item in items[:25]:
            positional = self._item_display[item.id]
            label = (f"{positional} — {item.label}" if item.label else positional)[:100]
            item_opts.append(
                discord.SelectOption(
                    label=label,
                    value=item.id,
                    description=f"Currently in {item.tier}"[:100],
                )
            )
        self.item_select = discord.ui.Select(
            placeholder="1. Pick an item to move…",
            options=item_opts,
        )
        self.item_select.callback = self._on_item
        self.add_item(self.item_select)

        # ── tier select ───────────────────────────────────────────────────────
        tier_opts = [discord.SelectOption(label=t, value=t) for t in tier_labels[:25]]
        self.tier_select = discord.ui.Select(
            placeholder="2. Pick the destination tier…",
            options=tier_opts,
        )
        self.tier_select.callback = self._on_tier
        self.add_item(self.tier_select)

        # ── confirm button (starts disabled) ──────────────────────────────────
        self.move_btn = discord.ui.Button(
            label="Rearrange", style=discord.ButtonStyle.primary, disabled=True
        )
        self.move_btn.callback = self._on_move
        self.add_item(self.move_btn)

    async def _on_item(self, interaction: discord.Interaction) -> None:
        self.selected_item_id = interaction.data["values"][0]  # type: ignore[index]
        for opt in self.item_select.options:
            opt.default = opt.value == self.selected_item_id
        self.move_btn.disabled = not (self.selected_item_id and self.selected_tier)
        await interaction.response.edit_message(view=self)

    async def _on_tier(self, interaction: discord.Interaction) -> None:
        self.selected_tier = interaction.data["values"][0]  # type: ignore[index]
        for opt in self.tier_select.options:
            opt.default = opt.value == self.selected_tier
        self.move_btn.disabled = not (self.selected_item_id and self.selected_tier)
        await interaction.response.edit_message(view=self)

    async def _on_move(self, interaction: discord.Interaction) -> None:
        assert self.selected_item_id and self.selected_tier
        try:
            item = self.cog.service.move_item(
                self.tier_list.id, self.selected_item_id, interaction.user.id, self.selected_tier
            )
        except (NotFoundError, TierListError) as exc:
            await interaction.response.edit_message(content=str(exc), view=None)
            return

        tier_list   = self.cog.service.get_list(self.tier_list.id)
        items       = self.cog.service.list_items(self.tier_list.id)
        tier_labels = self.cog.service.get_tiers_ordered(self.tier_list.id)
        output_path = self.cog.renderer.render(tier_list, items, tier_labels)

        assert interaction.channel is not None
        if tier_list.message_id:
            partial = interaction.channel.get_partial_message(int(tier_list.message_id))
            try:
                await partial.edit(
                    attachments=[discord.File(output_path, filename=f"{tier_list.id}.png")]
                )
            except discord.HTTPException:
                new_msg = await interaction.channel.send(
                    file=discord.File(output_path, filename=f"{tier_list.id}.png")
                )
                self.cog.service.update_message_id(self.tier_list.id, str(new_msg.id))

        # Recompute positional label from updated item list (tier has changed)
        tier_counter: dict[str, int] = {}
        new_positional = item.id
        for it in items:
            n = tier_counter[it.tier] = tier_counter.get(it.tier, 0) + 1
            if it.id == item.id:
                new_positional = f"{it.tier}{n}"
                break
        await interaction.response.edit_message(content="​", view=None)


# ── Cog ───────────────────────────────────────────────────────────────────────


class TierListCog(commands.Cog):
    tierlist = app_commands.Group(name="tierlist", description="Manage tier lists")
    tl       = app_commands.Group(name="tl",       description="Shortcut for /tierlist")

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

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _can_edit(self, interaction: discord.Interaction, list_id: str) -> bool:
        list_obj = self.service.get_list(list_id)
        if interaction.user.id == list_obj.owner_id:
            return True
        if isinstance(interaction.user, discord.Member):
            return interaction.user.guild_permissions.administrator
        return False

    def _no_active_list(self) -> str:
        return "No active tier list in this channel. Start one with `/tl start`."

    async def _require_active(
        self, interaction: discord.Interaction
    ) -> TierList | None:
        """Return the active list, or send an ephemeral error and return None."""
        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message(
                "This command only works in a server channel.", ephemeral=True
            )
            return None
        tier_list = self.service.get_active_list(interaction.channel_id)
        if tier_list is None:
            await interaction.response.send_message(self._no_active_list(), ephemeral=True)
            return None
        return tier_list

    async def render_and_send(
        self, interaction: discord.Interaction, list_id: str, ephemeral: bool
    ) -> None:
        try:
            list_obj    = self.service.get_list(list_id)
            items       = self.service.list_items(list_id)
            tier_labels = self.service.get_tiers_ordered(list_id)
        except NotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        output_path = self.renderer.render(list_obj, items, tier_labels)
        file = discord.File(output_path, filename=f"{list_obj.id}.png")
        if interaction.response.is_done():
            await interaction.followup.send(file=file, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(file=file, ephemeral=ephemeral)

    # ── commands ──────────────────────────────────────────────────────────────

    @tierlist.command(name="start", description="Start a new tier list in this channel")
    @app_commands.describe(name="Display name for this tier list")
    async def create(self, interaction: discord.Interaction, name: str) -> None:
        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message(
                "This command only works in a server channel.", ephemeral=True
            )
            return

        existing = self.service.get_active_list(interaction.channel_id)
        if existing:
            await interaction.response.send_message(
                f"**{existing.name}** is already active in this channel.\n"
                f"Use `/tierlist finish` (or `/tierlist delete`) to end it before starting a new one.",
                ephemeral=True,
            )
            return

        try:
            tier_list = self.service.create_list(
                interaction.guild.id, interaction.channel_id, interaction.user.id, name=name
            )
        except LimitError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        tier_labels = self.service.get_tiers_ordered(tier_list.id)
        output_path = self.renderer.render(tier_list, [], tier_labels)
        assert interaction.channel is not None
        board_msg = await interaction.channel.send(
            file=discord.File(output_path, filename=f"{tier_list.id}.png")
        )
        self.service.update_message_id(tier_list.id, str(board_msg.id))

        await interaction.followup.send("​", ephemeral=True)

    @tierlist.command(name="add", description="Add an image to the active tier list")
    @app_commands.describe(image="Image attachment", label="Optional label")
    async def add(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment,
        label: str | None = None,
    ) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return

        if not await self._can_edit(interaction, tier_list.id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can add items.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            suffix = Path(image.filename).suffix.lstrip(".") or "png"
            stored = await self.image_store.save_from_url(
                self.http_session, image.url, suffix, image.content_type, image.size
            )
        except ImageValidationError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        tier_labels = self.service.get_tiers_ordered(tier_list.id)
        view = TierSelectView(
            self, tier_list, tier_labels, stored, image.filename, label, interaction.user.id
        )
        await interaction.followup.send("Which tier?", view=view, ephemeral=True)

    @tierlist.command(name="rearrange", description="Rearrange an item into a different tier")
    async def move(self, interaction: discord.Interaction) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return

        if not await self._can_edit(interaction, tier_list.id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can move items.", ephemeral=True
            )
            return

        items = self.service.list_items(tier_list.id)
        if not items:
            await interaction.response.send_message(
                "No items in this tier list yet.", ephemeral=True
            )
            return

        tier_labels = self.service.get_tiers_ordered(tier_list.id)
        view = MoveItemView(self, tier_list, items, tier_labels)
        await interaction.response.send_message(
            "Pick an item and a destination tier, then click **Move**.",
            view=view,
            ephemeral=True,
        )

    @tierlist.command(name="show", description="Re-post the active tier list board for everyone")
    async def show(self, interaction: discord.Interaction) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return
        await self.render_and_send(interaction, tier_list.id, ephemeral=False)

    @tierlist.command(name="render", description="Re-post the active tier list board")
    async def render(self, interaction: discord.Interaction) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return
        await self.render_and_send(interaction, tier_list.id, ephemeral=False)

    @tierlist.command(name="finish", description="Mark the active tier list as complete and free the channel")
    async def finish(self, interaction: discord.Interaction) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return

        if not await self._can_edit(interaction, tier_list.id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can finish this list.", ephemeral=True
            )
            return

        self.service.finish_list(tier_list.id, interaction.user.id)
        await interaction.response.send_message(
            f"**{tier_list.name}** is finished! The board stays in chat as the final result.\n"
            f"Start a new one any time with `/tl start`."
        )

    @tierlist.command(name="delete", description="Delete the active tier list")
    async def delete(self, interaction: discord.Interaction) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return

        if not await self._can_edit(interaction, tier_list.id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can delete this list.", ephemeral=True
            )
            return

        view = DeleteConfirmView(self, tier_list)
        await interaction.response.send_message(
            f"Delete **{tier_list.name}**? This cannot be undone.", view=view, ephemeral=True
        )

    @tierlist.command(name="history", description="Browse finished tier lists in this channel")
    async def history(self, interaction: discord.Interaction) -> None:
        if interaction.channel_id is None:
            await interaction.response.send_message(
                "This command only works in a server channel.", ephemeral=True
            )
            return

        finished = self.service.get_history(interaction.channel_id, limit=10)
        if not finished:
            await interaction.response.send_message(
                "No finished tier lists in this channel yet.", ephemeral=True
            )
            return

        lines = ["**Finished tier lists in this channel:**"]
        for tl in finished:
            finished_str = tl.finished_at.strftime("%Y-%m-%d %H:%M UTC") if tl.finished_at else "?"
            items = self.service.list_items(tl.id)
            lines.append(f"• **{tl.name}** — {len(items)} items — finished {finished_str}")

        embed = discord.Embed(description="\n".join(lines), color=0x1B2735)
        view = HistorySelectView(self, finished)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @tierlist.command(name="help", description="Show how to use TierListBot")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="TierListBot — How to use", color=0x1B2735)
        embed.add_field(
            name="Start & end",
            value=(
                "`/tl start name:<name>` — start a tier list and post the live board\n"
                "`/tl finish` — mark it complete and free the channel for a new one\n"
                "`/tl delete` — permanently delete the active list (owner or admin only)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Adding images",
            value=(
                "`/s image:<file>` · `/tl s image:<file>` — add to **S** tier\n"
                "`/a image:<file>` · `/tl a image:<file>` — add to **A** tier\n"
                "`/b image:<file>` · `/tl b image:<file>` — add to **B** tier\n"
                "`/c image:<file>` · `/tl c image:<file>` — add to **C** tier\n"
                "`/d image:<file>` · `/tl d image:<file>` — add to **D** tier\n"
                "`/tl add image:<file>` — add image and pick the tier from buttons\n"
                "\nThe board updates in place every time."
            ),
            inline=False,
        )
        embed.add_field(
            name="Custom tiers",
            value=(
                "`/tl edit-tiers` — open a text editor to add, remove, or reorder all tiers at once\n"
                "`/tl add-tier name:<label>` — quickly add a single custom tier row"
            ),
            inline=False,
        )
        embed.add_field(
            name="Managing items",
            value=(
                "`/tl rearrange` — pick an item and destination tier from dropdowns\n"
                "`/tl show` — view all item IDs and access rename/relabel buttons\n"
                "`/tl render` — re-post the board as a fresh image"
            ),
            inline=False,
        )
        embed.add_field(
            name="History",
            value="`/tl history` — browse finished tier lists and re-render any past board",
            inline=False,
        )
        embed.set_footer(text="All /tierlist commands also work as /tl shortcuts. One active list per channel.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


    # ── /tl shortcuts (mirror every /tierlist subcommand) ────────────────────

    @tl.command(name="start", description="Start a new tier list in this channel")
    @app_commands.describe(name="Display name for this tier list")
    async def tl_create(self, interaction: discord.Interaction, name: str) -> None:
        await self.create.callback(self, interaction, name)

    @tl.command(name="add", description="Add an image to the active tier list")
    @app_commands.describe(image="Image attachment", label="Optional label")
    async def tl_add(
        self, interaction: discord.Interaction, image: discord.Attachment, label: str | None = None
    ) -> None:
        await self.add.callback(self, interaction, image, label)

    async def _tl_tier_shortcut(
        self, interaction: discord.Interaction, tier_label: str, image: discord.Attachment
    ) -> None:
        shortcuts: commands.Cog | None = self.bot.cogs.get("TierShortcutsCog")  # type: ignore[assignment]
        if shortcuts is None:
            await interaction.response.send_message("Internal error: shortcuts cog not loaded.", ephemeral=True)
            return
        await shortcuts._add_to_tier(interaction, tier_label, image)  # type: ignore[attr-defined]

    @tl.command(name="edit-tiers", description="Edit, reorder, add, or remove tiers via a text editor")
    async def tl_edit_tiers(self, interaction: discord.Interaction) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return
        if not await self._can_edit(interaction, tier_list.id):
            await interaction.response.send_message(
                "Only the list creator or a server admin can edit tiers.", ephemeral=True
            )
            return
        labels = self.service.get_tiers_ordered(tier_list.id)
        await interaction.response.send_modal(EditTiersModal(self, tier_list, labels))

    @tierlist.command(name="edit-tiers", description="Edit, reorder, add, or remove tiers via a text editor")
    async def tierlist_edit_tiers(self, interaction: discord.Interaction) -> None:
        await self.tl_edit_tiers.callback(self, interaction)

    @tl.command(name="add-tier", description="Add a custom tier to the active list")
    @app_commands.describe(name="Tier label (e.g. god-tier)")
    async def tl_add_tier(self, interaction: discord.Interaction, name: str) -> None:
        shortcuts: commands.Cog | None = self.bot.cogs.get("TierShortcutsCog")  # type: ignore[assignment]
        if shortcuts is None:
            await interaction.response.send_message("Internal error: shortcuts cog not loaded.", ephemeral=True)
            return
        await shortcuts._add_tier_to_list(interaction, name)  # type: ignore[attr-defined]

    @tierlist.command(name="add-tier", description="Add a custom tier to the active list")
    @app_commands.describe(name="Tier label (e.g. god-tier)")
    async def tierlist_add_tier(self, interaction: discord.Interaction, name: str) -> None:
        await self.tl_add_tier.callback(self, interaction, name)

    @tl.command(name="s", description="Add image to S tier")
    @app_commands.describe(image="Image to add")
    async def tl_s(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._tl_tier_shortcut(interaction, "S", image)

    @tl.command(name="a", description="Add image to A tier")
    @app_commands.describe(image="Image to add")
    async def tl_a(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._tl_tier_shortcut(interaction, "A", image)

    @tl.command(name="b", description="Add image to B tier")
    @app_commands.describe(image="Image to add")
    async def tl_b(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._tl_tier_shortcut(interaction, "B", image)

    @tl.command(name="c", description="Add image to C tier")
    @app_commands.describe(image="Image to add")
    async def tl_c(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._tl_tier_shortcut(interaction, "C", image)

    @tl.command(name="d", description="Add image to D tier")
    @app_commands.describe(image="Image to add")
    async def tl_d(self, interaction: discord.Interaction, image: discord.Attachment) -> None:
        await self._tl_tier_shortcut(interaction, "D", image)

    @tl.command(name="rearrange", description="Rearrange an item into a different tier")
    async def tl_move(self, interaction: discord.Interaction) -> None:
        await self.move.callback(self, interaction)

    @tl.command(name="show", description="Show items in the active tier list")
    async def tl_show(self, interaction: discord.Interaction) -> None:
        await self.show.callback(self, interaction)

    @tl.command(name="render", description="Re-post the active tier list board")
    async def tl_render(self, interaction: discord.Interaction) -> None:
        await self.render.callback(self, interaction)

    @tl.command(name="finish", description="Mark the active tier list as complete")
    async def tl_finish(self, interaction: discord.Interaction) -> None:
        await self.finish.callback(self, interaction)

    @tl.command(name="delete", description="Delete the active tier list")
    async def tl_delete(self, interaction: discord.Interaction) -> None:
        await self.delete.callback(self, interaction)

    @tl.command(name="history", description="Browse finished tier lists in this channel")
    async def tl_history(self, interaction: discord.Interaction) -> None:
        await self.history.callback(self, interaction)

    @tl.command(name="help", description="Show how to use TierListBot")
    async def tl_help(self, interaction: discord.Interaction) -> None:
        await self.help.callback(self, interaction)


async def setup(bot: commands.Bot) -> None:
    deps = bot.deps
    cog = TierListCog(
        bot,
        service=deps["tierlist_service"],
        image_store=deps["image_store"],
        renderer=deps["renderer"],
        http_session=deps["http_session"],
    )
    await bot.add_cog(cog)
