"""
Friend Group (FG) System Cog for Ego Bot.
Features instant owner creation (/fg create), public invitation flow with DM Accept/Decline buttons (/fg start),
live group stats (/fg stats), and full channel provisioning (Category, Text Lounge, Voice Suite).
"""
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
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

class FGInviteDMView(discord.ui.View):
    def __init__(self, fg_id: int, guild_id: int, creator_id: int, fg_name: str):
        super().__init__(timeout=86400 * 2) # 48 hour invite expiration
        self.fg_id = fg_id
        self.guild_id = guild_id
        self.creator_id = creator_id
        self.fg_name = fg_name

    @discord.ui.button(label="Accept Invitation", style=discord.ButtonStyle.success, emoji="👑", custom_id="fg_accept_invite")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == self.fg_id))
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message("❌ This Friend Group no longer exists.", ephemeral=True)

            if fg.status == "active":
                return await interaction.response.send_message("✅ You are already in this active Friend Group!", ephemeral=True)

            members = fg.members
            if user.id not in members:
                members.append(user.id)
                fg.members_json = json.dumps(members)
                await session.commit()

            for item in self.children:
                item.disabled = True

            await interaction.message.edit(view=self)
            await interaction.response.send_message(
                embed=success_embed("Invitation Accepted", f"You joined **{self.fg_name}**! ({len(members)}/5 members ready)")
            )

            # Check if all required members accepted (Creator + 4 friends = 5)
            if len(members) >= 5 and fg.status == "pending":
                # Trigger channel provisioning
                bot = interaction.client
                guild = bot.get_guild(self.guild_id)
                if guild:
                    await provision_fg_channels(guild, fg)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✖", custom_id="fg_decline_invite")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            embed=error_embed("Invitation Declined", f"You declined the invitation to join **{self.fg_name}**.")
        )

async def provision_fg_channels(guild: discord.Guild, fg_record: FriendGroup):
    """Provisions private Category, Text Lounge, and Voice Suite for an approved FG."""
    try:
        members_list = [guild.get_member(uid) for uid in fg_record.members if guild.get_member(uid)]
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, connect=True)
        }

        # Add all members to overwrites
        for m in members_list:
            overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True)

        # Add mods to overwrites
        for r in guild.roles:
            if r.permissions.manage_guild or r.permissions.administrator:
                overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True)

        # Create Category & Channels
        cat = await guild.create_category(name=f"👑 ︱ {fg_record.name}", overwrites=overwrites)
        text_ch = await guild.create_text_channel(name=f"💬-lounge", category=cat, topic=f"Private squad lounge for {fg_record.name}")
        voice_ch = await guild.create_voice_channel(name=f"🔊-voice", category=cat)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg_record.id))
            fg = res.scalar_one_or_none()
            if fg:
                fg.category_id = cat.id
                fg.text_channel_id = text_ch.id
                fg.voice_channel_id = voice_ch.id
                fg.status = "active"
                await session.commit()

        # Send squad welcome card
        members_mentions = ", ".join(f"<@{m}>" for m in fg_record.members)
        welcome_embed = ego_embed(
            title=f"👑 Squad Unlocked • {fg_record.name}",
            description=(
                f"> **Private Friend Group Circle Initialized!**\n"
                f"› **Leader:** <@{fg_record.creator_id}>\n"
                f"› **Members:** {members_mentions}\n\n"
                f"This category, text lounge, and voice suite are exclusively scoped to your squad.\n"
                f"Use `/fg invite` to add more friends, `/fg rename` to update branding, or `/fg kick` to manage roster."
            ),
            color=COLOR_VIOLET
        )
        await text_ch.send(content=f"<@{fg_record.creator_id}>", embed=welcome_embed)
        logger.info(f"Provisioned channels for Friend Group {fg_record.name} in {guild.name}")
    except Exception as e:
        logger.error(f"Failed to provision FG channels: {e}")

class FriendGroupsCog(commands.Cog, name="FriendGroups"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    fg_group = app_commands.Group(name="fg", description="Friend Group private squads & channel provisioning")

    @fg_group.command(name="create", description="[Owners/Admins] Instantly create and provision a Friend Group without waiting for invites")
    @app_commands.describe(
        name="Name of the Friend Group",
        member1="Squad Member 1",
        member2="Squad Member 2",
        member3="Squad Member 3",
        member4="Squad Member 4"
    )
    @is_admin_or_has_role()
    async def fg_create(
        self,
        interaction: discord.Interaction,
        name: str,
        member1: discord.Member,
        member2: discord.Member,
        member3: discord.Member,
        member4: discord.Member
    ):
        guild = interaction.guild
        members = list(set([interaction.user.id, member1.id, member2.id, member3.id, member4.id]))

        async with AsyncSessionLocal() as session:
            fg = FriendGroup(
                guild_id=guild.id,
                creator_id=interaction.user.id,
                name=name.strip(),
                status="pending",
                members_json=json.dumps(members)
            )
            session.add(fg)
            await session.commit()
            await session.refresh(fg)

            await interaction.response.send_message(
                embed=info_embed("Provisioning Squad...", f"Creating private category, text lounge, and voice suite for **{name}**..."),
                ephemeral=True
            )
            await provision_fg_channels(guild, fg)

            await interaction.followup.send(
                embed=success_embed("Squad Created", f"✅ **{name}** has been instantly created with 5 members!"),
                ephemeral=True
            )

    @fg_group.command(name="start", description="[Public] Start a Friend Group and send DM invites to 4 members")
    @app_commands.describe(
        name="Name of your squad",
        member1="Friend 1 to invite",
        member2="Friend 2 to invite",
        member3="Friend 3 to invite",
        member4="Friend 4 to invite"
    )
    async def fg_start(
        self,
        interaction: discord.Interaction,
        name: str,
        member1: discord.Member,
        member2: discord.Member,
        member3: discord.Member,
        member4: discord.Member
    ):
        guild = interaction.guild
        user = interaction.user
        invitees = [member1, member2, member3, member4]

        # Prevent duplicate users or self-invite
        if len(set([m.id for m in invitees])) < 4 or any(m.id == user.id for m in invitees):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Members", "Please select 4 unique server members (excluding yourself)."),
                ephemeral=True
            )

        async with AsyncSessionLocal() as session:
            fg = FriendGroup(
                guild_id=guild.id,
                creator_id=user.id,
                name=name.strip(),
                status="pending",
                members_json=json.dumps([user.id]) # Only creator accepted so far
            )
            session.add(fg)
            await session.commit()
            await session.refresh(fg)

        # Send DM Embeds with Accept/Decline Buttons to each invitee
        sent_count = 0
        for m in invitees:
            try:
                dm_embed = ego_embed(
                    title=f"👑 Squad Invitation • {name}",
                    description=(
                        f"> **{user.display_name}** has invited you to form a private Friend Group (**{name}**) in **{guild.name}**!\n\n"
                        f"› **Squad Leader:** {user.mention}\n"
                        f"› **Perks:** Dedicated private category, secret text lounge, and 24/7 private voice suite.\n\n"
                        f"*Click **Accept Invitation** below to join!*"
                    ),
                    color=COLOR_VIOLET
                )
                view = FGInviteDMView(fg_id=fg.id, guild_id=guild.id, creator_id=user.id, fg_name=name)
                await m.send(embed=dm_embed, view=view)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Could not DM {m.name}: {e}")

        await interaction.response.send_message(
            embed=success_embed(
                "Squad Pending Creation",
                f"✅ **{name}** has entered pending status!\n"
                f"› Dispatched **{sent_count}/4** DM invites with Accept/Decline buttons.\n"
                f"› Once all 4 members accept, private channels will automatically unlock!"
            )
        )

    @fg_group.command(name="stats", description="View all Friend Groups, pending invites, and active channel suites")
    async def fg_stats(self, interaction: discord.Interaction):
        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.guild_id == guild.id))
            all_fgs = res.scalars().all()

        if not all_fgs:
            return await interaction.response.send_message(
                embed=info_embed("Friend Groups", "No active or pending Friend Groups found in this server. Run `/fg start` to begin!"),
                ephemeral=True
            )

        embed = ego_embed(
            title=f"👑 Server Friend Groups ({len(all_fgs)})",
            description="Overview of all registered squads, status, and private channels:\n",
            color=COLOR_VIOLET
        )

        for fg in all_fgs[:15]:
            status_badge = "🟢 Active & Provisioned" if fg.status == "active" else "🟡 Pending Invites"
            ch_info = f"• Channels: <#{fg.text_channel_id}>" if fg.text_channel_id else "• Channels: *Pending*"
            embed.add_field(
                name=f"› {fg.name} ({status_badge})",
                value=(
                    f"• **Leader:** <@{fg.creator_id}>\n"
                    f"• **Members:** `{len(fg.members)}/5`\n"
                    f"{ch_info}"
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @fg_group.command(name="rename", description="Rename your Friend Group and sync channel names")
    @app_commands.describe(new_name="New squad name")
    async def fg_rename(self, interaction: discord.Interaction, new_name: str):
        guild = interaction.guild
        user = interaction.user

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.guild_id == guild.id, FriendGroup.creator_id == user.id, FriendGroup.status == "active"))
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message(embed=error_embed("Not Allowed", "You do not own an active Friend Group."), ephemeral=True)

            fg.name = new_name.strip()
            await session.commit()

            if fg.category_id:
                cat = guild.get_channel(fg.category_id)
                if cat:
                    await cat.edit(name=f"👑 ︱ {fg.name}")

        await interaction.response.send_message(
            embed=success_embed("Squad Renamed", f"Updated Friend Group name to **{new_name}**.")
        )

    @fg_group.command(name="disband", description="Disband your Friend Group and delete private category and channels")
    async def fg_disband(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.guild_id == guild.id, FriendGroup.creator_id == user.id))
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message(embed=error_embed("Not Allowed", "You do not own a Friend Group."), ephemeral=True)

            # Purge channels
            if fg.category_id:
                cat = guild.get_channel(fg.category_id)
                if cat:
                    for ch in cat.channels:
                        await ch.delete()
                    await cat.delete()

            await session.delete(fg)
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed("Squad Disbanded", f"Successfully deleted **{fg.name}** and purged private channels.")
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(FriendGroupsCog(bot))
