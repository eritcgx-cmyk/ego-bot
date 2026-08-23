"""
Friend Group (FG) System for Ego Bot.
Features:
- /fg start (creates pending FG), /fg invite (dispatches DM & channel cards)
- Automatic 4-member staff review ticket creation & approval workflow
- Dedicated private suite auto-provisioning (Private Category + 1 Text Lounge + 1 Voice Suite)
- Custom role auto-creation (👑 ︱ <FG Name>) & base FG role assignment
- Persistent FG Control Panel with interactive action buttons (Roster, Invite, Lock/Unlock Voice, Sync Role, Rename, Kick Member, Disband)
- DM invitation acceptance & seamless cross-reboot persistence.
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
from utils.state_manager import update_guild_state_section
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

            if not fg or (fg.creator_id != user.id and not user.guild_permissions.administrator):
                return await interaction.response.send_message("Only the FG Leader or an Admin can rename this Friend Group.", ephemeral=True)

            old_name = fg.name
            fg.name = self.new_name.value.strip()
            await session.commit()

            # Sync Discord Category, Role, and Channels
            if guild:
                if fg.category_id:
                    cat = guild.get_channel(fg.category_id)
                    if cat:
                        try:
                            await cat.edit(name=f"👑 ︱ {fg.name}")
                        except Exception:
                            pass
                if fg.role_id:
                    role = guild.get_role(fg.role_id)
                    if role:
                        try:
                            await role.edit(name=f"👑 ︱ {fg.name}")
                        except Exception:
                            pass

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
            return await interaction.response.send_message("❌ You cannot kick yourself as the FG Leader. Use Disband to close the FG.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == self.fg_id))
            fg = res.scalar_one_or_none()

            if not fg or (fg.creator_id != user.id and not user.guild_permissions.administrator):
                return await interaction.response.send_message("Only the FG Leader or an Admin can kick members.", ephemeral=True)

            members = fg.members
            if target_uid not in members:
                return await interaction.response.send_message("This member is not in your Friend Group.", ephemeral=True)

            members.remove(target_uid)
            fg.members_json = json.dumps(members)
            await session.commit()

            # Revoke roles from kicked member
            if guild:
                target_member = guild.get_member(target_uid)
                if not target_member:
                    try:
                        target_member = await guild.fetch_member(target_uid)
                    except Exception:
                        target_member = None

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
                            embed=info_embed("Friend Group Update", f"You have been removed from Friend Group **{fg.name}** in **{guild.name}**.")
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

    def _extract_fg_id(self, interaction: discord.Interaction) -> Optional[int]:
        if self.fg_id:
            return self.fg_id

        # 1. From message embed
        msg = interaction.message
        if msg and msg.embeds:
            desc = msg.embeds[0].description or ""
            match = re.search(r"FG ID:\*\* `#(\d+)`", desc)
            if match:
                return int(match.group(1))

        # 2. From channel topic
        ch = interaction.channel
        if ch and getattr(ch, "topic", None):
            match = re.search(r"FG ID:\s*#?(\d+)", ch.topic)
            if match:
                return int(match.group(1))

        return None

    @discord.ui.button(label="Roster & Stats", style=discord.ButtonStyle.primary, emoji="📋", custom_id="fg_btn_roster", row=0)
    async def roster_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        if not fg_id:
            return await interaction.response.send_message("❌ Could not resolve Friend Group record.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg:
                return await interaction.response.send_message("❌ Friend Group record not found.", ephemeral=True)

            members_mentions = ", ".join(f"<@{m}>" for m in fg.members) if fg.members else "None"
            embed = ego_embed(
                title=f"👑 FG Roster • {fg.name}",
                description=(
                    f"> **FG ID:** `#{fg.id}`\n"
                    f"> **Leader:** <@{fg.creator_id}>\n"
                    f"> **Status:** `{fg.status.upper()}`\n"
                    f"> **Total Members:** `{len(fg.members)}`\n\n"
                    f"› **Roster Members:**\n{members_mentions}\n"
                ),
                color=COLOR_CYAN
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Invite Member", style=discord.ButtonStyle.success, emoji="👥", custom_id="fg_btn_invite", row=0)
    async def invite_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        await interaction.response.send_message(
            embed=info_embed(
                "Invite Friends",
                "To invite a friend to your Friend Group, run the slash command:\n"
                f"› `/fg invite member:@friend`"
            ),
            ephemeral=True
        )

    @discord.ui.button(label="Sync Roles", style=discord.ButtonStyle.secondary, emoji="👑", custom_id="fg_btn_role_sync", row=0)
    async def sync_role_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Server context missing.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or (fg.creator_id != interaction.user.id and not interaction.user.guild_permissions.administrator):
                return await interaction.followup.send("Only the FG Leader or an Admin can sync roles.", ephemeral=True)

            p_role = guild.get_role(fg.role_id) if fg.role_id else None
            if not p_role:
                p_role = discord.utils.find(lambda r: r.name.lower() == f"👑 ︱ {fg.name}".lower(), guild.roles)
                if not p_role:
                    p_role = await guild.create_role(
                        name=f"👑 ︱ {fg.name}",
                        color=discord.Color(0x8B5CF6),
                        mentionable=True,
                        reason="Ego FG Private Role"
                    )
                fg.role_id = p_role.id
                await session.commit()

            base_fg = discord.utils.find(lambda r: r.name.lower() == "fg", guild.roles)
            if not base_fg:
                base_fg = await guild.create_role(name="FG", color=discord.Color(0x3B82F6), mentionable=True, reason="Ego Base FG Role")

            synced_count = 0
            for uid in fg.members:
                m = guild.get_member(uid)
                if not m:
                    try:
                        m = await guild.fetch_member(uid)
                    except Exception:
                        m = None
                if m:
                    roles_to_add = [r for r in (p_role, base_fg) if r and r not in m.roles]
                    if roles_to_add:
                        try:
                            await m.add_roles(*roles_to_add, reason="FG Role Sync")
                            synced_count += 1
                        except Exception:
                            pass

        await interaction.followup.send(
            embed=success_embed("Roles Synced", f"Applied {p_role.mention} and {base_fg.mention} to all `{len(fg.members)}` members."),
            ephemeral=True
        )

    @discord.ui.button(label="Lock/Unlock Voice", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="fg_btn_toggle_voice", row=1)
    async def toggle_voice_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        guild = interaction.guild

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or (fg.creator_id != interaction.user.id and not interaction.user.guild_permissions.administrator):
                return await interaction.response.send_message("Only the FG Leader or an Admin can manage voice security.", ephemeral=True)

            if not fg.voice_channel_id:
                return await interaction.response.send_message("No voice channel found for this FG.", ephemeral=True)

            voice_ch = guild.get_channel(fg.voice_channel_id)
            if not voice_ch or not isinstance(voice_ch, discord.VoiceChannel):
                return await interaction.response.send_message("Voice channel not found.", ephemeral=True)

            current_ow = voice_ch.overwrites_for(guild.default_role)
            is_locked = current_ow.connect is False

            if is_locked:
                # Unlock (allow default role or private role)
                await voice_ch.set_permissions(guild.default_role, connect=None)
                status_msg = "🔓 **Unlocked** voice channel. Members with category access can connect."
            else:
                # Lock
                await voice_ch.set_permissions(guild.default_role, connect=False)
                status_msg = "🔒 **Locked** voice channel. Only verified FG members can connect."

        await interaction.response.send_message(embed=success_embed("Voice Security", status_msg), ephemeral=True)

    @discord.ui.button(label="Kick Member", style=discord.ButtonStyle.secondary, emoji="👢", custom_id="fg_btn_kick", row=1)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or (fg.creator_id != interaction.user.id and not interaction.user.guild_permissions.administrator):
                return await interaction.response.send_message("Only the FG Leader or an Admin can kick members.", ephemeral=True)

        await interaction.response.send_modal(FGKickMemberModal(fg_id=fg_id))

    @discord.ui.button(label="Rename FG", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="fg_btn_rename", row=1)
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or (fg.creator_id != interaction.user.id and not interaction.user.guild_permissions.administrator):
                return await interaction.response.send_message("Only the FG Leader or an Admin can rename this FG.", ephemeral=True)

        await interaction.response.send_modal(FGRenameModal(fg_id=fg_id))

    @discord.ui.button(label="Disband FG", style=discord.ButtonStyle.danger, emoji="💥", custom_id="fg_btn_disband", row=2)
    async def disband_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID.", ephemeral=True)

        guild = interaction.guild
        user = interaction.user

        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()
            if not fg or (fg.creator_id != user.id and not user.guild_permissions.administrator):
                return await interaction.followup.send("Only the FG Leader or an Admin can disband this FG.", ephemeral=True)

            fg_name = fg.name

            # Purge Category & Channels
            if guild and fg.category_id:
                cat = guild.get_channel(fg.category_id)
                if cat:
                    for ch in cat.channels:
                        try:
                            await ch.delete()
                        except Exception:
                            pass
                    try:
                        await cat.delete()
                    except Exception:
                        pass

            # Purge Role
            if guild and fg.role_id:
                role = guild.get_role(fg.role_id)
                if role:
                    try:
                        await role.delete(reason="Friend Group Disbanded")
                    except Exception:
                        pass

            await session.delete(fg)
            await session.commit()

        await interaction.followup.send(
            embed=success_embed("FG Disbanded", f"Friend Group **{fg_name}** has been disbanded and all channels/roles purged."),
            ephemeral=True
        )


class FGTicketReviewView(discord.ui.View):
    def __init__(self, fg_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.fg_id = fg_id

    def _extract_fg_id(self, interaction: discord.Interaction) -> Optional[int]:
        if self.fg_id:
            return self.fg_id

        msg = interaction.message
        if msg and msg.embeds:
            desc = msg.embeds[0].description or ""
            match = re.search(r"FG ID:\*\* `#(\d+)`", desc)
            if match:
                return int(match.group(1))

        ch = interaction.channel
        if ch and getattr(ch, "topic", None):
            match = re.search(r"FG ID:\s*#?(\d+)", ch.topic)
            if match:
                return int(match.group(1))

        return None

    @discord.ui.button(label="Approve & Unlock FG", style=discord.ButtonStyle.success, emoji="✅", custom_id="fg_ticket_approve")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        if not fg_id:
            return await interaction.response.send_message("Could not resolve FG ID from this ticket.", ephemeral=True)

        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Server context missing.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.followup.send("FG record not found in database.", ephemeral=True)

            if fg.status == "active":
                return await interaction.followup.send("This Friend Group is already approved and active.", ephemeral=True)

            await provision_fg_suite(guild, fg)

        for item in self.children:
            item.disabled = True

        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = COLOR_EMERALD
            embed.title = f"Friend Group Approved - {fg.name}"
            embed.add_field(name="› Approved By", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=embed, view=self)

        await interaction.followup.send(f"✅ Approved and provisioned private channels for **{fg.name}**.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✖", custom_id="fg_ticket_decline")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        guild = interaction.guild

        async with AsyncSessionLocal() as session:
            if fg_id:
                res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
                fg = res.scalar_one_or_none()
                if fg:
                    if guild:
                        creator = guild.get_member(fg.creator_id)
                        if creator:
                            try:
                                await creator.send(embed=error_embed("Friend Group Declined", f"Your application for FG **{fg.name}** in **{guild.name}** was declined by staff."))
                            except Exception:
                                pass
                    await session.delete(fg)
                    await session.commit()

        for item in self.children:
            item.disabled = True

        if interaction.message and interaction.message.embeds:
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

    def _extract_fg_id(self, interaction: discord.Interaction) -> Optional[int]:
        if self.fg_id:
            return self.fg_id

        msg = interaction.message
        if msg and msg.embeds:
            desc = msg.embeds[0].description or ""
            match = re.search(r"FG ID:\*\* `#(\d+)`", desc)
            if match:
                return int(match.group(1))

        return None

    @discord.ui.button(label="Accept Invitation", style=discord.ButtonStyle.success, emoji="✅", custom_id="fg_invite_accept")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        fg_id = self._extract_fg_id(interaction)
        user = interaction.user

        if not fg_id:
            return await interaction.response.send_message("❌ Could not resolve FG ID from this card.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_id))
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message("❌ This Friend Group no longer exists.", ephemeral=True)

            guild = interaction.guild or interaction.client.get_guild(fg.guild_id)
            if not guild:
                return await interaction.response.send_message("❌ Could not find the associated server.", ephemeral=True)

            members = fg.members
            if user.id not in members:
                members.append(user.id)
                fg.members_json = json.dumps(members)
                await session.commit()

            # If FG is already active, assign the private role and base FG role
            if fg.status == "active" and guild:
                member_obj = guild.get_member(user.id)
                if not member_obj:
                    try:
                        member_obj = await guild.fetch_member(user.id)
                    except Exception:
                        member_obj = None

                if member_obj:
                    roles_to_add = []
                    if fg.role_id:
                        p_role = guild.get_role(fg.role_id)
                        if p_role and p_role not in member_obj.roles:
                            roles_to_add.append(p_role)
                    base_fg = discord.utils.find(lambda r: r.name.lower() == "fg", guild.roles)
                    if base_fg and base_fg not in member_obj.roles:
                        roles_to_add.append(base_fg)
                    if roles_to_add:
                        try:
                            await member_obj.add_roles(*roles_to_add, reason="Joined Active Friend Group")
                        except Exception:
                            pass

            for item in self.children:
                item.disabled = True

            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

            await interaction.response.send_message(
                embed=success_embed("Invitation Accepted", f"You joined **{fg.name}**! ({len(members)} members in FG)"),
                ephemeral=True
            )

            # Check if FG reached 4 members while in pending status -> Create Staff Review Ticket!
            if len(members) >= 4 and fg.status == "pending" and not fg.ticket_channel_id and guild:
                fg.status = "under_review"
                await session.commit()
                await trigger_fg_staff_ticket(guild, fg)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✖", custom_id="fg_invite_decline")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.response.send_message(
            embed=error_embed("Invitation Declined", "You declined the Friend Group invitation."),
            ephemeral=True
        )


async def trigger_fg_staff_ticket(guild: discord.Guild, fg_record: FriendGroup):
    """Automatically generates a private staff review ticket when an FG hits 4 members."""
    try:
        creator = guild.get_member(fg_record.creator_id)
        if not creator:
            try:
                creator = await guild.fetch_member(fg_record.creator_id)
            except Exception:
                creator = None

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
            if not m:
                try:
                    m = await guild.fetch_member(uid)
                except Exception:
                    m = None
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

        # 4. Create Dedicated Category, Text Lounge, and Voice Suite
        cat = await guild.create_category(name=f"👑 ︱ {fg_record.name}", overwrites=overwrites)
        text_ch = await guild.create_text_channel(
            name="💬-lounge", 
            category=cat, 
            topic=f"Private FG lounge for {fg_record.name} (FG ID: #{fg_record.id})"
        )
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
                f"› **Exclusive Suite:** Private Category, Text Lounge, and Voice Suite.\n"
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
                    f"Click **Accept Invitation** below to join this Friend Group in **{guild.name}**!"
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
                    f"› **Suite Controls:** Roster, Invite, Lock/Unlock Voice, Sync Role, Rename, Kick Member, Disband:"
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
            user_fgs = [f for f in all_fgs if user.id in f.members or f.creator_id == user.id]

            if not user_fgs:
                return await interaction.response.send_message(
                    embed=info_embed("Friend Groups", "You do not belong to any Friend Groups in this server.\nRun `/fg start` to create one!"),
                    ephemeral=True
                )

            embed = ego_embed(title=f"Your Friend Groups • {user.display_name}", color=COLOR_CYAN)
            for fg in user_fgs:
                is_leader = "👑 Leader" if fg.creator_id == user.id else "Member"
                status_str = "🟢 Active" if fg.status == "active" else "🟡 Under Review" if fg.status == "under_review" else "⚪ Pending"
                p_role = guild.get_role(fg.role_id) if fg.role_id else None
                embed.add_field(
                    name=f"› {fg.name} (#{fg.id}) — {is_leader}",
                    value=(
                        f"• **Status:** {status_str}\n"
                        f"• **Members:** `{len(fg.members)}`\n"
                        f"• **Private Role:** {p_role.mention if p_role else 'None'}"
                    ),
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

    fg_admin_group = app_commands.Group(
        name="fg_admin",
        description="Admin management commands for Friend Groups",
        default_permissions=discord.Permissions(manage_guild=True)
    )

    @fg_admin_group.command(name="create", description="[Admin/Mods] Instantly create and provision an active Friend Group")
    @app_commands.describe(
        name="Name of the Friend Group",
        leader="Leader of the FG",
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
                f"Successfully deployed **{name}** with `{len(member_ids)}` members and provisioned dedicated category, text lounge, voice suite, and role."
            )
        )

    @fg_admin_group.command(name="overview", description="[Admin/Mods] Directory of all Friend Groups in the server")
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
