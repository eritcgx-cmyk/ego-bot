"""
Friend Group (FG) System for Ego Bot.
Features /fg start (pending), /fg invite, auto 4-member staff review ticket,
private suite provisioning (Category + 1 Text + 1 Voice), custom role creation,
FG Control Panel with interactive action buttons (Create Category, 1 Text, 1 Voice, Create Role, Rename, Kick Member, Disband),
and /fg panel deployment.
"""
import os
import json
import re
import asyncio
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import FriendGroup, GuildConfig
from utils.permissions import is_admin_or_has_role, is_guild_owner
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_EMERALD, COLOR_CRIMSON, COLOR_CYAN, COLOR_AMBER, COLOR_ROSE
)
from config import logger

class FGRenameModal(discord.ui.Modal, title="Rename Friend Group"):
    def __init__(self, fg_id: int):
        super().__init__()
        self.fg_id = fg_id

    new_name = discord.ui.TextInput(label="New FG Name", placeholder="e.g. Syndicate Elite", max_length=50, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == self.fg_id))
            fg = res.scalar_one_or_none()

            if not fg or fg.creator_id != user.id:
                return await interaction.response.send_message("Only the FG Leader can rename this Friend Group.", ephemeral=True)

            old_name = fg.name
            fg.name = self.new_name.value.strip()
            await session.commit()

            # Sync Discord Category, Role, and Channels
            if fg.category_id:
                cat = guild.get_channel(fg.category_id)
                if cat:
                    await cat.edit(name=f"👑 ︱ {fg.name}")
            if fg.role_id:
                role = guild.get_role(fg.role_id)
                if role:
                    await role.edit(name=f"👑 ︱ {fg.name}")

        await interaction.response.send_message(
            embed=success_embed("FG Renamed", f"Renamed FG from **{old_name}** to **{self.new_name.value.strip()}**."),
            ephemeral=True
        )


class FGKickMemberModal(discord.ui.Modal, title="Kick Member from FG"):
    def __init__(self, fg_id: int):
        super().__init__()
        self.fg_id = fg_id

    user_input = discord.ui.TextInput(
        label="Member ID or Mention",
        placeholder="e.g. 123456789012345678 or @username",
        required=True,
        max_length=64
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user

        raw = self.user_input.value.strip()
        match = re.search(r"(\d{15,22})", raw)
        if not match:
            return await interaction.response.send_message("❌ Invalid user ID or mention.", ephemeral=True)
        
        target_uid = int(match.group(1))
        if target_uid == user.id:
            return await interaction.response.send_message("❌ You cannot kick yourself as the FG Leader.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == self.fg_id))
            fg = res.scalar_one_or_none()

            if not fg or fg.creator_id != user.id:
                return await interaction.response.send_message("Only the FG Leader can kick members.", ephemeral=True)

            members = fg.members
            if target_uid not in members:
                return await interaction.response.send_message("This member is not in your Friend Group.", ephemeral=True)

            members.remove(target_uid)
            fg.members_json = json.dumps(members)
            await session.commit()

            # Revoke roles from kicked member
            target_member = guild.get_member(target_uid)
            if target_member:
                if fg.role_id:
                    p_role = guild.get_role(fg.role_id)
                    if p_role and p_role in target_member.roles:
                        try:
                            await target_member.remove_roles(p_role, reason="Kicked from Friend Group")
                        except Exception:
                            pass

                # Check if member is in any other FG before removing base FG role
                other_res = await session.execute(
                    select(FriendGroup).where(
                        FriendGroup.guild_id == guild.id,
                        FriendGroup.id != fg.id,
                        FriendGroup.status == "active"
                    )
                )
                other_fgs = other_res.scalars().all()
                in_other = any(target_uid in o_fg.members for o_fg in other_fgs)
                if not in_other:
                    base_fg = discord.utils.get(guild.roles, name="FG")
                    if base_fg and base_fg in target_member.roles:
                        try:
                            await target_member.remove_roles(base_fg, reason="Left all Friend Groups")
                        except Exception:
                            pass

                try:
                    await target_member.send(
                        embed=info_embed("Friend Group Update", f"You have been removed from Friend Group **{fg.name}**.")
                    )
                except Exception:
                    pass

        await interaction.response.send_message(
            embed=success_embed("Member Removed", f"Successfully removed <@{target_uid}> from **{fg.name}**."),
            ephemeral=True
        )


class FGControlPanelView(discord.ui.View):
    def __init__(self, fg_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.fg_id = fg_id

    def _extract_fg_id(self, message: discord.Message) -> Optional[int]:
        if not message or not message.embeds:
            return None
        embed = message.embeds[0]
        desc = embed.description or ""
        match = re.search(r"FG ID:\*\* `#(\d+)`", desc)
        if match:
            return int(match.group(1))
        return None

    @discord.ui.button(label="Setup Category", style=discord.ButtonStyle.primary, custom_id="fg_panel_category", row=0)
    async def create_category_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or fg.creator_id != interaction.user.id:
                return await interaction.response.send_message("Only the FG Leader can configure channels.", ephemeral=True)

            if fg.category_id and guild.get_channel(fg.category_id):
                return await interaction.response.send_message("Category is already configured for this FG.", ephemeral=True)

            # Resolve private role
            p_role = guild.get_role(fg.role_id) if fg.role_id else None
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, connect=True)
            }
            if p_role:
                overwrites[p_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True)
            for r in guild.roles:
                if r.permissions.manage_guild or r.permissions.administrator:
                    overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True)

            cat = await guild.create_category(name=f"👑 ︱ {fg.name}", overwrites=overwrites)
            fg.category_id = cat.id
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed("Category Created", f"Configured private category `{cat.name}`."),
            ephemeral=True
        )

    @discord.ui.button(label="Create Text Lounge (Max 1)", style=discord.ButtonStyle.primary, custom_id="fg_panel_text", row=0)
    async def create_text_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or fg.creator_id != interaction.user.id:
                return await interaction.response.send_message("Only the FG Leader can configure channels.", ephemeral=True)

            # Strict limit: Only 1 text channel
            if fg.text_channel_id and guild.get_channel(fg.text_channel_id):
                return await interaction.response.send_message("❌ Limit Reached: Only 1 text channel allowed per Friend Group.", ephemeral=True)

            cat = guild.get_channel(fg.category_id) if fg.category_id else None
            text_ch = await guild.create_text_channel(name="💬-lounge", category=cat, topic=f"Private FG lounge for {fg.name}")
            fg.text_channel_id = text_ch.id
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed("Text Lounge Ready", f"Created {text_ch.mention} (Limit: 1/1 text channels)."),
            ephemeral=True
        )

    @discord.ui.button(label="Create Voice Suite (Max 1)", style=discord.ButtonStyle.primary, custom_id="fg_panel_voice", row=0)
    async def create_voice_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or fg.creator_id != interaction.user.id:
                return await interaction.response.send_message("Only the FG Leader can configure channels.", ephemeral=True)

            # Strict limit: Only 1 voice channel
            if fg.voice_channel_id and guild.get_channel(fg.voice_channel_id):
                return await interaction.response.send_message("❌ Limit Reached: Only 1 voice channel allowed per Friend Group.", ephemeral=True)

            cat = guild.get_channel(fg.category_id) if fg.category_id else None
            voice_ch = await guild.create_voice_channel(name="🔊-voice", category=cat)
            fg.voice_channel_id = voice_ch.id
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed("Voice Suite Ready", f"Created {voice_ch.mention} (Limit: 1/1 voice channels)."),
            ephemeral=True
        )

    @discord.ui.button(label="Create Custom Role", style=discord.ButtonStyle.secondary, custom_id="fg_panel_role", row=1)
    async def create_role_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or fg.creator_id != interaction.user.id:
                return await interaction.response.send_message("Only the FG Leader can configure roles.", ephemeral=True)

            p_role = guild.get_role(fg.role_id) if fg.role_id else None
            if not p_role:
                p_role = discord.utils.find(lambda r: r.name.lower() == f"👑 ︱ {fg.name}".lower(), guild.roles)
                if not p_role:
                    p_role = await guild.create_role(
                        name=f"👑 ︱ {fg.name}",
                        color=discord.Color(0x8B5CF6),
                        mentionable=True,
                        reason="Ego FG Custom Role"
                    )
                fg.role_id = p_role.id
                await session.commit()

            # Auto-apply role to all members
            base_fg = discord.utils.find(lambda r: r.name.lower() == "fg", guild.roles)
            for uid in fg.members:
                m = guild.get_member(uid)
                if m:
                    roles_to_add = [r for r in (p_role, base_fg) if r and r not in m.roles]
                    if roles_to_add:
                        try:
                            await m.add_roles(*roles_to_add, reason="FG Custom Role Assignment")
                        except Exception:
                            pass

        await interaction.response.send_message(
            embed=success_embed("Role Configured", f"Created & applied {p_role.mention} to all FG members."),
            ephemeral=True
        )

    @discord.ui.button(label="Kick Member", style=discord.ButtonStyle.secondary, custom_id="fg_panel_kick", row=1)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or fg.creator_id != interaction.user.id:
                return await interaction.response.send_message("Only the FG Leader can kick members.", ephemeral=True)

        await interaction.response.send_modal(FGKickMemberModal(fg_id=fg_id))

    @discord.ui.button(label="Rename FG", style=discord.ButtonStyle.secondary, custom_id="fg_panel_rename", row=1)
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or fg.creator_id != interaction.user.id:
                return await interaction.response.send_message("Only the FG Leader can rename this FG.", ephemeral=True)

        await interaction.response.send_modal(FGRenameModal(fg_id=fg_id))

    @discord.ui.button(label="Roster & Stats", style=discord.ButtonStyle.secondary, custom_id="fg_panel_roster", row=2)
    async def roster_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg:
                return await interaction.response.send_message("FG record not found.", ephemeral=True)

            members_mentions = ", ".join(f"<@{m}>" for m in fg.members) if fg.members else "None"
            embed = ego_embed(
                title=f"FG Roster • {fg.name}",
                description=(
                    f"> **Leader:** <@{fg.creator_id}>\n"
                    f"> **Total Members:** `{len(fg.members)}`\n\n"
                    f"› **Active Members:**\n{members_mentions}\n"
                ),
                color=COLOR_CYAN
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Disband FG", style=discord.ButtonStyle.danger, custom_id="fg_panel_disband", row=2)
    async def disband_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        guild = interaction.guild
        user = interaction.user

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or (fg.creator_id != user.id and not user.guild_permissions.administrator):
                return await interaction.response.send_message("Only the FG Leader or an Admin can disband this FG.", ephemeral=True)

            # Purge Category, Channels, and Role
            if fg.category_id:
                cat = guild.get_channel(fg.category_id)
                if cat:
                    for ch in cat.channels:
                        await ch.delete()
                    await cat.delete()

            if fg.role_id:
                role = guild.get_role(fg.role_id)
                if role:
                    await role.delete(reason="Friend Group Disbanded")

            await session.delete(fg)
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed("FG Disbanded", "Friend Group disbanded and private suite purged."),
            ephemeral=True
        )


class FGTicketReviewView(discord.ui.View):
    def __init__(self, fg_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.fg_id = fg_id

    def _extract_fg_id(self, message: discord.Message) -> Optional[int]:
        if not message or not message.embeds:
            return None
        embed = message.embeds[0]
        desc = embed.description or ""
        match = re.search(r"FG ID:\*\* `#(\d+)`", desc)
        if match:
            return int(match.group(1))
        return None

    @discord.ui.button(label="Approve & Unlock FG", style=discord.ButtonStyle.success, custom_id="fg_ticket_approve")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID from this ticket.", ephemeral=True)

        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message("FG record not found in database.", ephemeral=True)

            if fg.status == "active":
                return await interaction.response.send_message("This Friend Group is already approved and active.", ephemeral=True)

            await interaction.response.defer(ephemeral=True)
            await provision_fg_suite(guild, fg)

        for item in self.children:
            item.disabled = True

        if interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = COLOR_EMERALD
            embed.title = f"Friend Group Approved - {fg.name}"
            embed.add_field(name="› Approved By", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=embed, view=self)

        await interaction.followup.send(f"Approved and provisioned private channels for **{fg.name}**.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="fg_ticket_decline")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        guild = interaction.guild

        async with AsyncSessionLocal() as session:
            if fg_id:
                res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
                fg = res.scalar_one_or_none()
                if fg:
                    creator = guild.get_member(fg.creator_id)
                    if creator:
                        try:
                            await creator.send(embed=error_embed("Friend Group Declined", f"Your application for FG **{fg.name}** was declined by staff."))
                        except Exception:
                            pass
                    await session.delete(fg)
                    await session.commit()

        for item in self.children:
            item.disabled = True

        if interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = COLOR_CRIMSON
            embed.title = "Friend Group Declined"
            embed.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=embed, view=self)

        await interaction.response.send_message("Declined FG application.", ephemeral=True)


class FGInviteView(discord.ui.View):
    def __init__(self, fg_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.fg_id = fg_id

    def _extract_fg_id(self, message: discord.Message) -> Optional[int]:
        if not message or not message.embeds:
            return None
        embed = message.embeds[0]
        desc = embed.description or ""
        match = re.search(r"FG ID:\*\* `#(\d+)`", desc)
        if match:
            return int(match.group(1))
        return None

    @discord.ui.button(label="Accept Invitation", style=discord.ButtonStyle.success, custom_id="fg_invite_accept")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self.fg_id or self._extract_fg_id(interaction.message)
        user = interaction.user

        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message("This Friend Group no longer exists.", ephemeral=True)

            members = fg.members
            if user.id not in members:
                members.append(user.id)
                fg.members_json = json.dumps(members)
                await session.commit()

            # If FG is already active, assign the private role and base FG role
            if fg.status == "active" and guild:
                roles_to_add = []
                if fg.role_id:
                    p_role = guild.get_role(fg.role_id)
                    if p_role and p_role not in user.roles:
                        roles_to_add.append(p_role)
                base_fg = discord.utils.get(guild.roles, name="FG")
                if base_fg and base_fg not in user.roles:
                    roles_to_add.append(base_fg)
                if roles_to_add:
                    try:
                        await user.add_roles(*roles_to_add, reason="Joined Active Friend Group")
                    except Exception:
                        pass

            for item in self.children:
                item.disabled = True

            await interaction.message.edit(view=self)
            await interaction.response.send_message(
                embed=success_embed("Invitation Accepted", f"You joined **{fg.name}**! ({len(members)} members in FG)"),
                ephemeral=True
            )

            # Check if FG reached 4 members while in pending status -> Create Staff Review Ticket!
            if len(members) >= 4 and fg.status == "pending" and not fg.ticket_channel_id and guild:
                fg.status = "under_review"
                await session.commit()
                await trigger_fg_staff_ticket(guild, fg)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="fg_invite_decline")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            embed=error_embed("Invitation Declined", "You declined the Friend Group invitation."),
            ephemeral=True
        )


async def trigger_fg_staff_ticket(guild: discord.Guild, fg_record: FriendGroup):
    """Automatically generates a private staff review ticket when an FG hits 4 members."""
    try:
        creator = guild.get_member(fg_record.creator_id)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        if creator:
            overwrites[creator] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        for role in guild.roles:
            if role.permissions.manage_guild or role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_ch = await guild.create_text_channel(
            name=f"fg-review-{fg_record.name[:12].lower().replace(' ', '-')}",
            overwrites=overwrites,
            topic=f"Staff Review Ticket for Friend Group {fg_record.name} (FG ID: #{fg_record.id})"
        )

        members_mentions = ", ".join(f"<@{m}>" for m in fg_record.members)
        review_embed = ego_embed(
            title=f"Friend Group Application • {fg_record.name}",
            description=(
                f"> **FG ID:** `#{fg_record.id}`\n"
                f"> **Leader:** <@{fg_record.creator_id}>\n"
                f"> **Members ({len(fg_record.members)}/4+ ready):**\n{members_mentions}\n\n"
                f"› **Status:** Ready for Staff Review\n"
                f"Click **Approve & Unlock FG** to create the dedicated private suite, FG roles, and private channels, or **Decline** to reject."
            ),
            color=COLOR_VIOLET
        )

        view = FGTicketReviewView(fg_id=fg_record.id)
        await ticket_ch.send(content=f"📢 **New FG Review:** <@{fg_record.creator_id}>", embed=review_embed, view=view)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_record.id))
            fg = res.scalar_one_or_none()
            if fg:
                fg.ticket_channel_id = ticket_ch.id
                await session.commit()

        if creator:
            try:
                await creator.send(
                    embed=info_embed(
                        "Review Ticket Opened",
                        f"Your FG **{fg_record.name}** reached 4 members! A staff review ticket has opened in {ticket_ch.mention}."
                    )
                )
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to create FG staff ticket: {e}")


async def provision_fg_suite(guild: discord.Guild, fg_record: FriendGroup):
    """Creates private role, base FG role, category, text lounge with Control Panel, and voice lounge."""
    try:
        # 1. Base FG Role
        base_fg_role = discord.utils.find(lambda r: r.name.lower() == "fg", guild.roles)
        if not base_fg_role:
            base_fg_role = await guild.create_role(
                name="FG",
                color=discord.Color(0x3B82F6),
                mentionable=True,
                reason="Ego Base Friend Group Role"
            )

        # 2. Create Private Role for FG
        private_role = discord.utils.find(lambda r: r.name.lower() == f"👑 ︱ {fg_record.name}".lower(), guild.roles)
        if not private_role:
            private_role = await guild.create_role(
                name=f"👑 ︱ {fg_record.name}",
                color=discord.Color(0x8B5CF6),
                mentionable=True,
                reason="Ego Friend Group Private Role"
            )

        # Assign Private Role and Base FG Role to all members
        for uid in fg_record.members:
            m = guild.get_member(uid)
            if m:
                try:
                    roles_to_add = [r for r in (private_role, base_fg_role) if r and r not in m.roles]
                    if roles_to_add:
                        await m.add_roles(*roles_to_add, reason="Joined Friend Group")
                except Exception:
                    pass

        # 3. Overwrites scoped exclusively to private role + staff
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
            private_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, connect=True)
        }
        for r in guild.roles:
            if r.permissions.manage_guild or r.permissions.administrator:
                overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True)

        # 4. Create Category, Text Lounge (1 text max), and Voice Suite (1 voice max)
        cat = await guild.create_category(name=f"👑 ︱ {fg_record.name}", overwrites=overwrites)
        text_ch = await guild.create_text_channel(name="💬-lounge", category=cat, topic=f"Private FG lounge for {fg_record.name}")
        voice_ch = await guild.create_voice_channel(name="🔊-voice", category=cat)

        # 5. Save IDs to DB
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_record.id))
            fg = res.scalar_one_or_none()
            if fg:
                fg.category_id = cat.id
                fg.text_channel_id = text_ch.id
                fg.voice_channel_id = voice_ch.id
                fg.role_id = private_role.id
                fg.status = "active"
                await session.commit()

        # 6. Post Dedicated Interactive Control Panel
        members_mentions = ", ".join(f"<@{m}>" for m in fg_record.members)
        panel_embed = ego_embed(
            title=f"👑 FG Control Panel • {fg_record.name}",
            description=(
                f"> **FG ID:** `#{fg_record.id}`\n"
                f"> **Leader:** <@{fg_record.creator_id}>\n"
                f"> **Private Role:** {private_role.mention}\n"
                f"> **Roster ({len(fg_record.members)}):** {members_mentions}\n\n"
                f"› **Exclusive Suite:** Limit 1 text channel (`#💬-lounge`) and 1 voice channel (`#🔊-voice`).\n"
                f"Use the buttons below to manage your Friend Group suite:"
            ),
            color=COLOR_VIOLET
        )

        panel_view = FGControlPanelView(fg_id=fg_record.id)
        await text_ch.send(content=f"<@{fg_record.creator_id}>", embed=panel_embed, view=panel_view)

    except Exception as e:
        logger.error(f"Failed to provision FG suite: {e}")


class FriendGroupsCog(commands.Cog, name="FriendGroups"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    fg_group = app_commands.Group(name="fg", description="Friend Group private channels and control panels")

    @fg_group.command(name="start", description="Start a new Friend Group in pending status (Creator is Leader)")
    @app_commands.describe(name="Name of your Friend Group")
    async def fg_start(self, interaction: discord.Interaction, name: str):
        guild = interaction.guild
        user = interaction.user

        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            # Check if user already owns an active or pending FG in this server
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == guild.id,
                    FriendGroup.creator_id == user.id,
                    FriendGroup.status != "disbanded"
                )
            )
            existing = res.scalar_one_or_none()
            if existing:
                return await interaction.followup.send(
                    embed=error_embed("FG Already Exists", f"You already lead Friend Group **{existing.name}** (`#{existing.id}`).")
                )

            # Create FG in pending state
            new_fg = FriendGroup(
                guild_id=guild.id,
                name=name.strip(),
                creator_id=user.id,
                status="pending",
                members_json=json.dumps([user.id]),
                invited_json=json.dumps([])
            )
            session.add(new_fg)
            await session.commit()
            await session.refresh(new_fg)

            embed = ego_embed(
                title="Friend Group Started",
                description=(
                    f"> **FG Name:** `{new_fg.name}`\n"
                    f"> **FG ID:** `#{new_fg.id}`\n"
                    f"> **Leader:** {user.mention}\n"
                    f"> **Members (1/4):** {user.mention}\n\n"
                    f"› **Next Step:** Run `/fg invite member:@friend` to invite at least 3 friends.\n"
                    f"Once your FG reaches **4 members**, a staff review ticket will automatically open!"
                ),
                color=COLOR_VIOLET
            )
            await interaction.followup.send(embed=embed)

    @fg_group.command(name="invite", description="Invite a friend to your Friend Group")
    @app_commands.describe(member="Member to invite")
    async def fg_invite(self, interaction: discord.Interaction, member: discord.Member):
        guild = interaction.guild
        user = interaction.user

        if member.id == user.id:
            return await interaction.response.send_message("❌ You cannot invite yourself.", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("❌ You cannot invite bots to an FG.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == guild.id,
                    FriendGroup.creator_id == user.id,
                    FriendGroup.status != "disbanded"
                )
            )
            fg = res.scalar_one_or_none()
            if not fg:
                return await interaction.response.send_message(
                    embed=error_embed("No FG Found", "You do not lead an active Friend Group. Run `/fg start` first!"),
                    ephemeral=True
                )

            members = fg.members
            if member.id in members:
                return await interaction.response.send_message(f"❌ {member.mention} is already in your Friend Group.", ephemeral=True)

            # Send Invite Card
            invite_embed = ego_embed(
                title="Friend Group Invitation",
                description=(
                    f"> **FG Name:** `{fg.name}`\n"
                    f"> **FG ID:** `#{fg.id}`\n"
                    f"> **Invited By:** {user.mention}\n"
                    f"> **Current Members:** `{len(members)}`\n\n"
                    f"Click **Accept Invitation** below to join this Friend Group!"
                ),
                color=COLOR_CYAN
            )

            view = FGInviteView(fg_id=fg.id)

            # Try to send via DM, fallback to channel
            sent_dm = False
            try:
                await member.send(embed=invite_embed, view=view)
                sent_dm = True
            except Exception:
                pass

            if not sent_dm:
                await interaction.channel.send(content=f"📢 {member.mention}", embed=invite_embed, view=view)

            await interaction.response.send_message(
                embed=success_embed(
                    "Invitation Dispatched",
                    f"Sent invite card to {member.mention} for FG **{fg.name}**."
                ),
                ephemeral=True
            )

    @fg_group.command(name="panel", description="Deploy or resend the FG Control Panel to your lounge")
    async def fg_panel(self, interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == guild.id,
                    FriendGroup.creator_id == user.id,
                    FriendGroup.status == "active"
                )
            )
            fg = res.scalar_one_or_none()
            if not fg:
                return await interaction.response.send_message(
                    embed=error_embed("No Active FG", "You do not own an active approved Friend Group."),
                    ephemeral=True
                )

            p_role = guild.get_role(fg.role_id) if fg.role_id else None
            role_mention = p_role.mention if p_role else "None"
            members_mentions = ", ".join(f"<@{m}>" for m in fg.members)

            panel_embed = ego_embed(
                title=f"👑 FG Control Panel • {fg.name}",
                description=(
                    f"> **FG ID:** `#{fg.id}`\n"
                    f"> **Leader:** <@{fg.creator_id}>\n"
                    f"> **Private Role:** {role_mention}\n"
                    f"> **Roster ({len(fg.members)}):** {members_mentions}\n\n"
                    f"› **Suite Controls:** Setup Category, 1 Text, 1 Voice, Custom Role, Rename, or Kick Members:"
                ),
                color=COLOR_VIOLET
            )

            view = FGControlPanelView(fg_id=fg.id)
            await interaction.response.send_message(embed=panel_embed, view=view)

    @fg_group.command(name="stats", description="View status and details of the Friend Groups you belong to")
    async def fg_stats(self, interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == guild.id,
                    FriendGroup.status != "disbanded"
                )
            )
            all_fgs = res.scalars().all()
            user_fgs = [fg for fg in all_fgs if user.id in fg.members]

            if not user_fgs:
                return await interaction.response.send_message(
                    embed=info_embed("Friend Groups", "You are not currently in any Friend Group.\nRun `/fg start` to create one!"),
                    ephemeral=True
                )

            embed = ego_embed(
                title=f"My Friend Groups ({len(user_fgs)})",
                description=f"> Active Friend Groups for {user.mention}:\n",
                color=COLOR_VIOLET
            )

            for fg in user_fgs:
                members_mentions = ", ".join(f"<@{m}>" for m in fg.members)
                status_text = "🟢 Active Suite" if fg.status == "active" else "🟡 Under Staff Review" if fg.status == "under_review" else "⚪ Pending (Needs 4 members)"
                role_str = f"<@&{fg.role_id}>" if fg.role_id else "*None*"

                embed.add_field(
                    name=f"👑 {fg.name} (ID: #{fg.id})",
                    value=(
                        f"• **Status:** `{status_text}`\n"
                        f"• **Leader:** <@{fg.creator_id}>\n"
                        f"• **Private Role:** {role_str}\n"
                        f"• **Members ({len(fg.members)}):** {members_mentions}"
                    ),
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

    @fg_group.command(name="create", description="[Admin/Owner] Instantly create and approve an active Friend Group")
    @app_commands.describe(
        name="Name of the FG",
        leader="Member who will lead the FG",
        member2="Second member",
        member3="Third member",
        member4="Fourth member",
        member5="Fifth member"
    )
    @is_admin_or_has_role()
    async def fg_create(
        self,
        interaction: discord.Interaction,
        name: str,
        leader: discord.Member,
        member2: discord.Member,
        member3: discord.Member,
        member4: discord.Member,
        member5: discord.Member
    ):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        member_ids = list(dict.fromkeys([leader.id, member2.id, member3.id, member4.id, member5.id]))

        async with AsyncSessionLocal() as session:
            new_fg = FriendGroup(
                guild_id=guild.id,
                name=name.strip(),
                creator_id=leader.id,
                status="active",
                members_json=json.dumps(member_ids),
                invited_json=json.dumps([])
            )
            session.add(new_fg)
            await session.commit()
            await session.refresh(new_fg)

            await provision_fg_suite(guild, new_fg)

        await interaction.followup.send(
            embed=success_embed(
                "FG Created Instantly",
                f"Successfully deployed **{name}** with `{len(member_ids)}` members and provisioned private suite."
            )
        )

    @fg_group.command(name="overview", description="[Admin/Mods] Directory of all Friend Groups in the server")
    @is_admin_or_has_role()
    async def fg_overview(self, interaction: discord.Interaction):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == guild.id,
                    FriendGroup.status != "disbanded"
                )
            )
            fgs = res.scalars().all()

            if not fgs:
                return await interaction.followup.send(
                    embed=info_embed("FG Overview", "No active Friend Groups found in this server.")
                )

            embed = ego_embed(
                title=f"Friend Groups Directory • {guild.name}",
                description=f"> Total Registered FGs: **`{len(fgs)}`**\n",
                color=COLOR_VIOLET
            )

            for fg in fgs:
                status_str = "🟢 Active" if fg.status == "active" else "🟡 In Review" if fg.status == "under_review" else "⚪ Pending"
                embed.add_field(
                    name=f"› {fg.name} (#{fg.id}) — {status_str}",
                    value=(
                        f"• **Leader:** <@{fg.creator_id}>\n"
                        f"• **Members:** `{len(fg.members)}`\n"
                        f"• **Role:** {f'<@&{fg.role_id}>' if fg.role_id else 'None'}\n"
                        f"• **Category:** {f'<#{fg.category_id}>' if fg.category_id else 'None'}"
                    ),
                    inline=True
                )

            await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(FriendGroupsCog(bot))
