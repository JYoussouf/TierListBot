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


class EditTiersModal(discord.ui.Modal, title="Edit Tier List"):
    name_input = discord.ui.TextInput(
        label="Title",
        min_length=1,
        max_length=80,
    )
    tiers_input = discord.ui.TextInput(
        label="Tiers - one per line, add/remove/reorder",
        style=discord.TextStyle.long,
        min_length=1,
        max_length=500,
        placeholder="S\nA\nB\nC\nD",
    )

    def __init__(self, cog: "TierListCog", tier_list: TierList, current_labels: list[str]):
        super().__init__()
        self.cog = cog
        self.tier_list = tier_list
        self.name_input.default = tier_list.name
        self.tiers_input.default = "\n".join(current_labels)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        new_name = str(self.name_input).strip()
        raw = str(self.tiers_input)
        new_labels = [line.strip() for line in raw.splitlines() if line.strip()]

        try:
            if new_name != self.tier_list.name:
                self.cog.service.rename_list(self.tier_list.id, interaction.user.id, new_name)
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

        await interaction.delete_original_response()


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
        await interaction.delete_original_response()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Cancelled.", view=None)


class HistoryDeleteView(discord.ui.View):
    def __init__(self, cog: "TierListCog", list_id: str, name: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.list_id = list_id
        self.name = name

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            self.cog.service.delete_list(self.list_id, interaction.user.id)
        except NotFoundError:
            pass
        await interaction.response.edit_message(
            content=f"**{self.name}** deleted.", view=None
        )

    @discord.ui.button(label="Keep", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Kept.", view=None)


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
            placeholder="Pick a finished tier list…",
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        list_id = interaction.data["values"][0]  # type: ignore[index]
        try:
            list_obj    = self.cog.service.get_list(list_id)
            items       = self.cog.service.list_items(list_id)
            tier_labels = self.cog.service.get_tiers_ordered(list_id)
        except Exception as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        output_path = self.cog.renderer.render(list_obj, items, tier_labels)
        finished_str = list_obj.finished_at.strftime("%Y-%m-%d") if list_obj.finished_at else "?"
        await interaction.response.send_message(
            f"**{list_obj.name}** (finished {finished_str})",
            file=discord.File(output_path, filename=f"{list_obj.id}.png"),
        )
        await interaction.followup.send(
            f"Delete **{list_obj.name}** from history?",
            view=HistoryDeleteView(self.cog, list_id, list_obj.name),
            ephemeral=True,
        )


class TierSelectView(discord.ui.View):
    """Shown after /tl add - user picks a tier and the item is placed + board updated."""

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
            try:
                old = interaction.channel.get_partial_message(int(tier_list.message_id))
                await old.delete()
            except discord.HTTPException:
                pass

        new_msg = await interaction.channel.send(
            file=discord.File(output_path, filename=f"{tier_list.id}.png")
        )
        self.cog.service.update_message_id(self.tier_list.id, str(new_msg.id))

        await interaction.response.edit_message(content="​", view=None)
        await interaction.delete_original_response()


class MassRearrangeModal(discord.ui.Modal, title="Mass rearrange"):
    layout = discord.ui.TextInput(
        label="Edit layout (one tier per line)",
        style=discord.TextStyle.long,
        placeholder="S: S1, S2\nA: A1\nC: C1, C2",
        min_length=1,
        max_length=2000,
    )

    def __init__(self, cog: "TierListCog", tier_list: TierList, items: list[TierItem],
                 tier_labels: list[str], item_display: dict[str, str],
                 btn_interaction: discord.Interaction):
        super().__init__()
        self.cog = cog
        self.tier_list = tier_list
        self._items = items
        self._tier_labels = tier_labels
        self._item_display = item_display  # item_id → positional label e.g. "S1"
        self.btn_interaction = btn_interaction

        # Build reverse lookup: positional label (uppercase) → item_id
        self._label_to_id: dict[str, str] = {v.upper(): k for k, v in item_display.items()}

        # Pre-populate text with current layout
        by_tier: dict[str, list[str]] = {t: [] for t in tier_labels}
        for item in items:
            if item.tier in by_tier:
                by_tier[item.tier].append(item_display[item.id])
        lines = [f"{t}: {', '.join(by_tier[t])}" for t in tier_labels]
        self.layout.default = "\n".join(lines)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        tier_set = set(self._tier_labels)
        ordered: list[tuple[str, str]] = []  # (item_id, tier) in desired order
        seen: set[str] = set()
        errors: list[str] = []

        for raw_line in self.layout.value.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                errors.append(f"Bad line (missing ':'): {line!r}")
                continue
            tier, rest = line.split(":", 1)
            tier = tier.strip()
            if tier not in tier_set:
                errors.append(f"Unknown tier: {tier!r}")
                continue
            for token in rest.split(","):
                lbl = token.strip().split()[0].upper() if token.strip() else ""
                if not lbl:
                    continue
                item_id = self._label_to_id.get(lbl)
                if item_id is None:
                    errors.append(f"Unknown label: {lbl}")
                    continue
                if item_id in seen:
                    errors.append(f"Duplicate: {lbl}")
                    continue
                seen.add(item_id)
                ordered.append((item_id, tier))

        if errors:
            await interaction.response.send_message(
                "Could not apply - fix these issues:\n" + "\n".join(f"- {e}" for e in errors),
                ephemeral=True,
            )
            return

        # Append any items not mentioned, keeping their current tier
        for item in self._items:
            if item.id not in seen:
                ordered.append((item.id, item.tier))

        try:
            self.cog.service.set_item_order(self.tier_list.id, interaction.user.id, ordered)
        except TierListError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        tier_list   = self.cog.service.get_list(self.tier_list.id)
        items       = self.cog.service.list_items(self.tier_list.id)
        tier_labels = self.cog.service.get_tiers_ordered(self.tier_list.id)
        output_path = self.cog.renderer.render(tier_list, items, tier_labels)

        assert interaction.channel is not None
        if tier_list.message_id:
            try:
                await interaction.channel.get_partial_message(int(tier_list.message_id)).delete()
            except discord.HTTPException:
                pass
        new_msg = await interaction.channel.send(
            file=discord.File(output_path, filename=f"{tier_list.id}.png")
        )
        self.cog.service.update_message_id(self.tier_list.id, str(new_msg.id))

        await interaction.response.defer()
        await self.btn_interaction.edit_original_response(content="​", view=None)
        await self.btn_interaction.delete_original_response()


class TypePositionModal(discord.ui.Modal, title="Pick item by position"):
    position = discord.ui.TextInput(
        label="Position (e.g. S2, A1)",
        placeholder="S2",
        min_length=1,
        max_length=10,
    )

    def __init__(self, view: "MoveItemView", btn_interaction: discord.Interaction):
        super().__init__()
        self.move_view = view
        self.btn_interaction = btn_interaction

    async def on_submit(self, interaction: discord.Interaction) -> None:
        typed = self.position.value.strip().upper()
        match = next(
            (iid for iid, lbl in self.move_view._item_display.items() if lbl.upper() == typed),
            None,
        )
        if match is None:
            await interaction.response.send_message(
                f"No item at position **{typed}**. Use labels shown on the board, e.g. S1, A2.",
                ephemeral=True,
            )
            return

        self.move_view.selected_item_id = match
        for opt in self.move_view.item_select.options:
            opt.default = opt.value == match
        if self.move_view.selected_tier:
            self.move_view.pos_select.options = self.move_view._build_pos_opts(self.move_view.selected_tier)
            self.move_view.pos_select.disabled = False
            self.move_view.selected_before_id = None
        self.move_view.move_btn.disabled = not (match and self.move_view.selected_tier)
        self.move_view.delete_btn.disabled = False

        await interaction.response.defer()
        await self.btn_interaction.edit_original_response(view=self.move_view)


class MoveItemView(discord.ui.View):
    """Item select → tier select → optional position select → Rearrange/Delete."""

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
        self._items = items[:25]
        self._tier_labels = tier_labels
        self.selected_item_id: str | None = None
        self.selected_tier: str | None = None
        self.selected_before_id: str | None = None  # None = append to end

        # positional labels: S1, S2, A1, …
        tier_counter: dict[str, int] = {}
        self._item_display: dict[str, str] = {}
        for item in self._items:
            n = tier_counter[item.tier] = tier_counter.get(item.tier, 0) + 1
            self._item_display[item.id] = f"{item.tier}{n}"

        # ── item select ───────────────────────────────────────────────────────
        item_opts: list[discord.SelectOption] = []
        for item in self._items:
            positional = self._item_display[item.id]
            label = (f"{positional} - {item.label}" if item.label else positional)[:100]
            item_opts.append(
                discord.SelectOption(
                    label=label,
                    value=item.id,
                    description=f"Currently in {item.tier}"[:100],
                )
            )
        item_opts.sort(key=lambda o: o.label.lower())
        self.item_select = discord.ui.Select(
            placeholder="1. Pick an item…",
            options=item_opts,
        )
        self.item_select.callback = self._on_item
        self.add_item(self.item_select)

        # ── tier select ───────────────────────────────────────────────────────
        tier_opts = [discord.SelectOption(label=t, value=t) for t in tier_labels[:25]]
        self.tier_select = discord.ui.Select(
            placeholder="2. Pick destination tier…",
            options=tier_opts,
        )
        self.tier_select.callback = self._on_tier
        self.add_item(self.tier_select)

        # ── position select (populated after tier is chosen) ──────────────────
        self.pos_select = discord.ui.Select(
            placeholder="3. Pick position (default: end of tier)…",
            options=[discord.SelectOption(label="End of tier (default)", value="end")],
            disabled=True,
        )
        self.pos_select.callback = self._on_pos
        self.add_item(self.pos_select)

        # ── buttons ───────────────────────────────────────────────────────────
        self.move_btn = discord.ui.Button(
            label="Rearrange", style=discord.ButtonStyle.primary, disabled=True
        )
        self.move_btn.callback = self._on_move
        self.add_item(self.move_btn)

        self.delete_btn = discord.ui.Button(
            label="Delete Item", style=discord.ButtonStyle.danger, disabled=True
        )
        self.delete_btn.callback = self._on_delete
        self.add_item(self.delete_btn)

        self.type_btn = discord.ui.Button(
            label="Type position…", style=discord.ButtonStyle.secondary
        )
        self.type_btn.callback = self._on_type
        self.add_item(self.type_btn)

        self.mass_btn = discord.ui.Button(
            label="Mass edit…", style=discord.ButtonStyle.secondary
        )
        self.mass_btn.callback = self._on_mass
        self.add_item(self.mass_btn)

    async def _on_type(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TypePositionModal(self, interaction))

    async def _on_mass(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            MassRearrangeModal(
                self.cog, self.tier_list, self._items, self._tier_labels,
                self._item_display, interaction,
            )
        )

    def _build_pos_opts(self, tier: str) -> list[discord.SelectOption]:
        opts = [discord.SelectOption(label="End of tier (default)", value="end", default=True)]
        for item in self._items:
            if item.tier == tier and item.id != self.selected_item_id:
                positional = self._item_display[item.id]
                label = (f"Before {positional} - {item.label}" if item.label else f"Before {positional}")[:100]
                opts.append(discord.SelectOption(label=label, value=item.id))
        return opts[:25]

    async def _on_item(self, interaction: discord.Interaction) -> None:
        self.selected_item_id = interaction.data["values"][0]  # type: ignore[index]
        for opt in self.item_select.options:
            opt.default = opt.value == self.selected_item_id
        # Refresh position opts to exclude newly selected item
        if self.selected_tier:
            self.pos_select.options = self._build_pos_opts(self.selected_tier)
            self.pos_select.disabled = False
            self.selected_before_id = None
        self.move_btn.disabled = not (self.selected_item_id and self.selected_tier)
        self.delete_btn.disabled = not self.selected_item_id
        await interaction.response.edit_message(view=self)

    async def _on_tier(self, interaction: discord.Interaction) -> None:
        self.selected_tier = interaction.data["values"][0]  # type: ignore[index]
        for opt in self.tier_select.options:
            opt.default = opt.value == self.selected_tier
        self.selected_before_id = None
        self.pos_select.options = self._build_pos_opts(self.selected_tier)
        self.pos_select.disabled = False
        self.move_btn.disabled = not (self.selected_item_id and self.selected_tier)
        await interaction.response.edit_message(view=self)

    async def _on_pos(self, interaction: discord.Interaction) -> None:
        val = interaction.data["values"][0]  # type: ignore[index]
        self.selected_before_id = None if val == "end" else val
        for opt in self.pos_select.options:
            opt.default = opt.value == val
        await interaction.response.edit_message(view=self)

    async def _refresh_board(self, interaction: discord.Interaction) -> None:
        tier_list   = self.cog.service.get_list(self.tier_list.id)
        items       = self.cog.service.list_items(self.tier_list.id)
        tier_labels = self.cog.service.get_tiers_ordered(self.tier_list.id)
        output_path = self.cog.renderer.render(tier_list, items, tier_labels)
        assert interaction.channel is not None
        if tier_list.message_id:
            try:
                await interaction.channel.get_partial_message(int(tier_list.message_id)).delete()
            except discord.HTTPException:
                pass
        new_msg = await interaction.channel.send(
            file=discord.File(output_path, filename=f"{tier_list.id}.png")
        )
        self.cog.service.update_message_id(self.tier_list.id, str(new_msg.id))

    async def _on_move(self, interaction: discord.Interaction) -> None:
        assert self.selected_item_id and self.selected_tier
        try:
            if self.selected_before_id:
                self.cog.service.reorder_item(
                    self.tier_list.id, self.selected_item_id, interaction.user.id, self.selected_before_id
                )
            else:
                self.cog.service.move_item(
                    self.tier_list.id, self.selected_item_id, interaction.user.id, self.selected_tier
                )
        except (NotFoundError, TierListError) as exc:
            await interaction.response.edit_message(content=str(exc), view=None)
            return
        await interaction.response.edit_message(content="​", view=None)
        await self._refresh_board(interaction)
        await interaction.delete_original_response()

    async def _on_delete(self, interaction: discord.Interaction) -> None:
        assert self.selected_item_id
        try:
            self.cog.service.delete_item(
                self.tier_list.id, self.selected_item_id, interaction.user.id
            )
        except (NotFoundError, TierListError) as exc:
            await interaction.response.edit_message(content=str(exc), view=None)
            return
        positional = self._item_display.get(self.selected_item_id, self.selected_item_id)
        await interaction.response.edit_message(content=f"Deleted {positional}.", view=None)
        await self._refresh_board(interaction)
        await interaction.delete_original_response()


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

        await interaction.delete_original_response()

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

    @tierlist.command(name="show", description="Bring the board to the bottom of chat")
    async def show(self, interaction: discord.Interaction) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return

        await interaction.response.defer(ephemeral=True)

        tier_list   = self.service.get_list(tier_list.id)
        items       = self.service.list_items(tier_list.id)
        tier_labels = self.service.get_tiers_ordered(tier_list.id)
        output_path = self.renderer.render(tier_list, items, tier_labels)

        assert interaction.channel is not None
        if tier_list.message_id:
            try:
                old = interaction.channel.get_partial_message(int(tier_list.message_id))
                await old.delete()
            except discord.HTTPException:
                pass

        new_msg = await interaction.channel.send(
            file=discord.File(output_path, filename=f"{tier_list.id}.png")
        )
        self.service.update_message_id(tier_list.id, str(new_msg.id))
        await interaction.delete_original_response()

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
            lines.append(f"• **{tl.name}** - {len(items)} items - finished {finished_str}")

        embed = discord.Embed(description="\n".join(lines), color=0x1B2735)
        view = HistorySelectView(self, finished)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @tierlist.command(name="help", description="Show how to use TierListBot")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="TierListBot - How to use", color=0x1B2735)
        embed.add_field(
            name="Start & end",
            value=(
                "`/tl start name:<name>` - start a tier list and post the live board\n"
                "`/tl finish` - mark it complete and free the channel for a new one\n"
                "`/tl delete` - permanently delete the active list (owner or admin only)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Adding items",
            value=(
                "`/tl add` - upload an image and pick the tier from buttons\n"
                "`/tl add-text text:<text>` - add a text tile (white text on black square)\n"
                "The board edits in place every time."
            ),
            inline=False,
        )
        embed.add_field(
            name="Tiers",
            value="`/tl edit-tiers` - add, remove, or reorder all tiers at once",
            inline=False,
        )
        embed.add_field(
            name="Managing items",
            value=(
                "`/tl rearrange` - pick an item, then:\n"
                "- choose a **destination tier** (and optionally a position within it) to move or reorder\n"
                "- click **Delete Item** to remove it entirely"
            ),
            inline=False,
        )
        embed.add_field(
            name="Board",
            value=(
                "`/tl show` - delete the old board and re-post it at the bottom of chat\n"
                "`/tl history` - browse and re-render finished lists"
            ),
            inline=False,
        )
        embed.set_footer(text="/tl and /tierlist are interchangeable. One active list per channel.")
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

    @tl.command(name="add-text", description="Add a text entry to the active tier list")
    @app_commands.describe(text="Text to display on the tile")
    async def tl_add_text(self, interaction: discord.Interaction, text: str) -> None:
        tier_list = await self._require_active(interaction)
        if tier_list is None:
            return

        await interaction.response.defer(ephemeral=True)

        stored = self.image_store.save_text_image(text)
        tier_labels = self.service.get_tiers_ordered(tier_list.id)
        view = TierSelectView(
            self, tier_list, tier_labels, stored, None, text[:40], interaction.user.id
        )
        await interaction.followup.send("Which tier?", view=view, ephemeral=True)

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

    @tierlist.command(name="add-text", description="Add a text entry to the active tier list")
    @app_commands.describe(text="Text to display on the tile")
    async def tierlist_add_text(self, interaction: discord.Interaction, text: str) -> None:
        await self.tl_add_text.callback(self, interaction, text)

    @tierlist.command(name="edit-tiers", description="Edit, reorder, add, or remove tiers via a text editor")
    async def tierlist_edit_tiers(self, interaction: discord.Interaction) -> None:
        await self.tl_edit_tiers.callback(self, interaction)

    @tl.command(name="rearrange", description="Rearrange an item into a different tier")
    async def tl_move(self, interaction: discord.Interaction) -> None:
        await self.move.callback(self, interaction)

    @tl.command(name="show", description="Bring the board to the bottom of chat")
    async def tl_show(self, interaction: discord.Interaction) -> None:
        await self.show.callback(self, interaction)

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
