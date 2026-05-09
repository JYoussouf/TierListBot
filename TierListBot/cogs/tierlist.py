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
                 btn_interaction: discord.Interaction, move_view: "MoveItemView"):
        super().__init__()
        self.cog = cog
        self.tier_list = tier_list
        self._items = items
        self._tier_labels = tier_labels
        self._item_display = item_display
        self.btn_interaction = btn_interaction
        self.move_view = move_view

        # Build reverse lookup: positional label (uppercase) → item_id
        self._label_to_id: dict[str, str] = {v.upper(): k for k, v in item_display.items()}

        # Pre-populate text with current layout, showing labels in parens for context
        by_tier: dict[str, list[str]] = {t: [] for t in tier_labels}
        for item in items:
            if item.tier in by_tier:
                lbl = item_display[item.id]
                token = f"{lbl} ({item.label})" if item.label else lbl
                by_tier[item.tier].append(token)
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
        await self.move_view._reload_view(self.btn_interaction)



class MoveItemView(discord.ui.View):
    """
    Row 0: item select   Row 1: tier select   Row 2: position select
    Row 3: Rearrange / Delete / Type / Mass-edit
    Row 4: ← ↑ ↓ → / Apply nudge  (fast, no board repost until Apply)
    """

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
        self._all_items = items          # full list used by nudge / mass-edit
        self._items = items[:25]         # first 25 for dropdowns
        self._tier_labels = tier_labels
        self.selected_item_id: str | None = None
        self.selected_tier: str | None = None
        self.selected_before_id: str | None = None

        # Positional labels for every item (S1, A2, …)
        tier_counter: dict[str, int] = {}
        self._item_display: dict[str, str] = {}
        for item in self._all_items:
            n = tier_counter[item.tier] = tier_counter.get(item.tier, 0) + 1
            self._item_display[item.id] = f"{item.tier}{n}"

        # In-memory working order for nudge (committed only on Apply)
        self._working_order: list[tuple[str, str]] = [
            (item.id, item.tier) for item in self._all_items
        ]

        # ── row 0: item select ────────────────────────────────────────────────
        item_opts: list[discord.SelectOption] = []
        for item in self._items:
            pos_lbl = self._item_display[item.id]
            label = (f"{pos_lbl} - {item.label}" if item.label else pos_lbl)[:100]
            item_opts.append(discord.SelectOption(
                label=label, value=item.id, description=f"Currently in {item.tier}"[:100]
            ))
        item_opts.sort(key=lambda o: o.label.lower())
        self.item_select = discord.ui.Select(
            placeholder="1. Pick an item…", options=item_opts, row=0
        )
        self.item_select.callback = self._on_item
        self.add_item(self.item_select)

        # ── row 1: tier select ────────────────────────────────────────────────
        self.tier_select = discord.ui.Select(
            placeholder="2. Pick destination tier…",
            options=[discord.SelectOption(label=t, value=t) for t in tier_labels[:25]],
            row=1,
        )
        self.tier_select.callback = self._on_tier
        self.add_item(self.tier_select)

        # ── row 2: position select ────────────────────────────────────────────
        self.pos_select = discord.ui.Select(
            placeholder="3. Pick position (default: end of tier)…",
            options=[discord.SelectOption(label="End of tier (default)", value="end")],
            disabled=True,
            row=2,
        )
        self.pos_select.callback = self._on_pos
        self.add_item(self.pos_select)

        # ── row 3: action buttons ─────────────────────────────────────────────
        self.move_btn = discord.ui.Button(
            label="Rearrange", style=discord.ButtonStyle.primary, disabled=True, row=3
        )
        self.move_btn.callback = self._on_move
        self.add_item(self.move_btn)

        self.delete_btn = discord.ui.Button(
            label="Delete", style=discord.ButtonStyle.danger, disabled=True, row=3
        )
        self.delete_btn.callback = self._on_delete
        self.add_item(self.delete_btn)

        self.mass_btn = discord.ui.Button(
            label="Mass edit…", style=discord.ButtonStyle.secondary, row=3
        )
        self.mass_btn.callback = self._on_mass
        self.add_item(self.mass_btn)

        self.done_btn = discord.ui.Button(
            label="Done", style=discord.ButtonStyle.secondary, row=3
        )
        self.done_btn.callback = self._on_done
        self.add_item(self.done_btn)

        # ── row 4: nudge buttons ──────────────────────────────────────────────
        self.left_btn  = discord.ui.Button(label="←", style=discord.ButtonStyle.secondary, disabled=True, row=4)
        self.up_btn    = discord.ui.Button(label="↑", style=discord.ButtonStyle.secondary, disabled=True, row=4)
        self.down_btn  = discord.ui.Button(label="↓", style=discord.ButtonStyle.secondary, disabled=True, row=4)
        self.right_btn = discord.ui.Button(label="→", style=discord.ButtonStyle.secondary, disabled=True, row=4)
        self.apply_btn = discord.ui.Button(label="Apply nudge", style=discord.ButtonStyle.success, disabled=True, row=4)
        self.left_btn.callback  = self._on_left
        self.up_btn.callback    = self._on_up
        self.down_btn.callback  = self._on_down
        self.right_btn.callback = self._on_right
        self.apply_btn.callback = self._on_apply_nudge
        for btn in (self.left_btn, self.up_btn, self.down_btn, self.right_btn, self.apply_btn):
            self.add_item(btn)

    # ── nudge helpers ─────────────────────────────────────────────────────────

    def _working_tier(self) -> str:
        return next(t for iid, t in self._working_order if iid == self.selected_item_id)

    def _tier_item_ids(self, tier: str) -> list[str]:
        return [iid for iid, t in self._working_order if t == tier]

    def _rebuild_working_order(self, by_tier: dict[str, list[str]]) -> None:
        self._working_order = [
            (iid, tier)
            for tier in self._tier_labels
            for iid in by_tier.get(tier, [])
        ]

    def _do_nudge(self, direction: str) -> None:
        if not self.selected_item_id:
            return
        by_tier = {t: self._tier_item_ids(t) for t in self._tier_labels}
        cur_tier = self._working_tier()
        pos = by_tier[cur_tier].index(self.selected_item_id)
        tier_idx = self._tier_labels.index(cur_tier)

        if direction == "left" and pos > 0:
            lst = by_tier[cur_tier]
            lst[pos], lst[pos - 1] = lst[pos - 1], lst[pos]
        elif direction == "right" and pos < len(by_tier[cur_tier]) - 1:
            lst = by_tier[cur_tier]
            lst[pos], lst[pos + 1] = lst[pos + 1], lst[pos]
        elif direction == "up" and tier_idx > 0:
            new_tier = self._tier_labels[tier_idx - 1]
            by_tier[cur_tier].remove(self.selected_item_id)
            by_tier[new_tier].insert(min(pos, len(by_tier[new_tier])), self.selected_item_id)
        elif direction == "down" and tier_idx < len(self._tier_labels) - 1:
            new_tier = self._tier_labels[tier_idx + 1]
            by_tier[cur_tier].remove(self.selected_item_id)
            by_tier[new_tier].insert(min(pos, len(by_tier[new_tier])), self.selected_item_id)
        self._rebuild_working_order(by_tier)

    def _update_arrow_states(self) -> None:
        if not self.selected_item_id:
            for btn in (self.left_btn, self.right_btn, self.up_btn, self.down_btn, self.apply_btn):
                btn.disabled = True
            return
        cur_tier   = self._working_tier()
        tier_items = self._tier_item_ids(cur_tier)
        pos        = tier_items.index(self.selected_item_id)
        tier_idx   = self._tier_labels.index(cur_tier)
        self.left_btn.disabled  = pos == 0
        self.right_btn.disabled = pos == len(tier_items) - 1
        self.up_btn.disabled    = tier_idx == 0
        self.down_btn.disabled  = tier_idx == len(self._tier_labels) - 1
        self.apply_btn.disabled = False

    def _status_content(self) -> str:
        if not self.selected_item_id:
            return (
                "Pick an item, then:\n"
                "- Use **tier / position selects** + **Rearrange** to move it\n"
                "- Use **← ↑ ↓ →** to nudge one step at a time, then **Apply nudge** to save"
            )
        cur_tier   = self._working_tier()
        tier_items = self._tier_item_ids(cur_tier)
        pos        = tier_items.index(self.selected_item_id) + 1
        total      = len(tier_items)
        disp       = self._item_display[self.selected_item_id]
        item       = next((i for i in self._all_items if i.id == self.selected_item_id), None)
        name_part  = f" ({item.label})" if item and item.label else ""
        return (
            f"**{disp}**{name_part} — tier **{cur_tier}**, position {pos}/{total}\n"
            "↑/↓ change tier · ←/→ reorder within tier · **Apply nudge** to save"
        )

    # ── nudge callbacks ───────────────────────────────────────────────────────

    async def _on_left(self, interaction: discord.Interaction) -> None:
        self._do_nudge("left");  self._update_arrow_states()
        await interaction.response.edit_message(content=self._status_content(), view=self)

    async def _on_right(self, interaction: discord.Interaction) -> None:
        self._do_nudge("right"); self._update_arrow_states()
        await interaction.response.edit_message(content=self._status_content(), view=self)

    async def _on_up(self, interaction: discord.Interaction) -> None:
        self._do_nudge("up");    self._update_arrow_states()
        await interaction.response.edit_message(content=self._status_content(), view=self)

    async def _on_down(self, interaction: discord.Interaction) -> None:
        self._do_nudge("down");  self._update_arrow_states()
        await interaction.response.edit_message(content=self._status_content(), view=self)

    async def _on_apply_nudge(self, interaction: discord.Interaction) -> None:
        try:
            self.cog.service.set_item_order(
                self.tier_list.id, interaction.user.id, self._working_order
            )
        except TierListError as exc:
            await interaction.response.edit_message(content=str(exc), view=self)
            return
        await interaction.response.defer()
        await self._refresh_board(interaction)
        await self._reload_view(interaction, keep_selected=self.selected_item_id)

    # ── modal / select helpers ────────────────────────────────────────────────

    async def _reload_view(
        self,
        edit_interaction: discord.Interaction,
        keep_selected: str | None = None,
    ) -> None:
        """Reload items from DB and rebuild the view in-place (no close)."""
        fresh_items = self.cog.service.list_items(self.tier_list.id)
        fresh_tiers = self.cog.service.get_tiers_ordered(self.tier_list.id)

        self._all_items   = fresh_items
        self._items       = fresh_items[:25]
        self._tier_labels = fresh_tiers

        tier_counter: dict[str, int] = {}
        self._item_display = {}
        for item in self._all_items:
            n = tier_counter[item.tier] = tier_counter.get(item.tier, 0) + 1
            self._item_display[item.id] = f"{item.tier}{n}"

        self._working_order = [(item.id, item.tier) for item in self._all_items]

        fresh_ids = {item.id for item in self._all_items}
        self.selected_item_id  = keep_selected if keep_selected in fresh_ids else None
        self.selected_before_id = None

        # Rebuild item select
        if not self._items:
            await edit_interaction.edit_original_response(
                content="No items left in this tier list.", view=None
            )
            return
        item_opts = []
        for item in self._items:
            pos_lbl = self._item_display[item.id]
            label = (f"{pos_lbl} - {item.label}" if item.label else pos_lbl)[:100]
            item_opts.append(discord.SelectOption(
                label=label,
                value=item.id,
                description=f"Currently in {item.tier}"[:100],
                default=(item.id == self.selected_item_id),
            ))
        item_opts.sort(key=lambda o: o.label.lower())
        self.item_select.options = item_opts

        # Rebuild tier select
        if self.selected_tier not in fresh_tiers:
            self.selected_tier = None
        self.tier_select.options = [
            discord.SelectOption(label=t, value=t, default=(t == self.selected_tier))
            for t in fresh_tiers[:25]
        ]

        # Rebuild pos select
        if self.selected_tier and self.selected_item_id:
            self.pos_select.options  = self._build_pos_opts(self.selected_tier)
            self.pos_select.disabled = False
        else:
            self.pos_select.options  = [discord.SelectOption(label="End of tier (default)", value="end")]
            self.pos_select.disabled = True

        self.move_btn.disabled   = not (self.selected_item_id and self.selected_tier)
        self.delete_btn.disabled = not self.selected_item_id
        self._update_arrow_states()

        await edit_interaction.edit_original_response(
            content=self._status_content(), view=self
        )

    async def _on_done(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="​", view=None)
        await interaction.delete_original_response()

    async def _on_mass(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            MassRearrangeModal(
                self.cog, self.tier_list, self._all_items, self._tier_labels,
                self._item_display, interaction, self,
            )
        )

    def _build_pos_opts(self, tier: str) -> list[discord.SelectOption]:
        opts = [discord.SelectOption(label="End of tier (default)", value="end", default=True)]
        for item in self._all_items:
            if item.tier == tier and item.id != self.selected_item_id:
                pos_lbl = self._item_display[item.id]
                label = (f"Before {pos_lbl} - {item.label}" if item.label else f"Before {pos_lbl}")[:100]
                opts.append(discord.SelectOption(label=label, value=item.id))
        return opts[:25]

    async def _on_item(self, interaction: discord.Interaction) -> None:
        self.selected_item_id = interaction.data["values"][0]  # type: ignore[index]
        for opt in self.item_select.options:
            opt.default = opt.value == self.selected_item_id
        if self.selected_tier:
            self.pos_select.options = self._build_pos_opts(self.selected_tier)
            self.pos_select.disabled = False
            self.selected_before_id = None
        self.move_btn.disabled  = not (self.selected_item_id and self.selected_tier)
        self.delete_btn.disabled = not self.selected_item_id
        self._update_arrow_states()
        await interaction.response.edit_message(content=self._status_content(), view=self)

    async def _on_tier(self, interaction: discord.Interaction) -> None:
        self.selected_tier = interaction.data["values"][0]  # type: ignore[index]
        for opt in self.tier_select.options:
            opt.default = opt.value == self.selected_tier
        self.selected_before_id = None
        self.pos_select.options = self._build_pos_opts(self.selected_tier)
        self.pos_select.disabled = False
        self.move_btn.disabled = not (self.selected_item_id and self.selected_tier)
        await interaction.response.edit_message(content=self._status_content(), view=self)

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
        moved_id = self.selected_item_id
        try:
            if self.selected_before_id:
                self.cog.service.reorder_item(
                    self.tier_list.id, moved_id, interaction.user.id, self.selected_before_id
                )
            else:
                self.cog.service.move_item(
                    self.tier_list.id, moved_id, interaction.user.id, self.selected_tier
                )
        except (NotFoundError, TierListError) as exc:
            await interaction.response.edit_message(content=str(exc), view=self)
            return
        await interaction.response.defer()
        await self._refresh_board(interaction)
        await self._reload_view(interaction, keep_selected=moved_id)

    async def _on_delete(self, interaction: discord.Interaction) -> None:
        assert self.selected_item_id
        try:
            self.cog.service.delete_item(
                self.tier_list.id, self.selected_item_id, interaction.user.id
            )
        except (NotFoundError, TierListError) as exc:
            await interaction.response.edit_message(content=str(exc), view=self)
            return
        await interaction.response.defer()
        await self._refresh_board(interaction)
        await self._reload_view(interaction, keep_selected=None)


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
            view._status_content(),
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
