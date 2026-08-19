"""
Friend Group (FG) System Cog for Ego Bot
"""
from typing import Optional, List
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func
from database.engine import AsyncSessionLocal
from database.models import FriendGroup, FriendGroupConfig, GuildConfig
from utils.permissions import is_guild_owner, is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, logger

class FGInviteView(discord.ui.View):
    def __init__(self, fg_id: int, user_id: int):
        super().__init__(timeout=86400) # 24 hours
        self.fg_id = fg_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This invitation is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept Invitation", style=discord.ButtonStyle.green, emoji="✅")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == self.fg_id))
            fg = res.scalar_one_or_none()

            if not fg or fg.status == "disbanded":
                return await interaction.response.send_message("❌ This Friend Group no longer exists.", ephemeral=True)

            members = list(fg.members)
            invited = list(fg.invited)

            if interaction.user.id in members:
                return await interaction.response.send_message("You are already a confirmed member of this Friend Group.", ephemeral=True)

            if interaction.user.id in invited:
                invited.remove(interaction.user.id)
            members.append(interaction.user.id)

            fg.members = members
            fg.invited = invited
            await session.commit()

            self.disable_all_items()
            await interaction.response.edit_message(content="✅ You accepted the Friend Group invitation!", view=self)

            # Check if threshold reached to provision channels
            if fg.status == "pending" and len(members) >= 4:
                cog = interaction.client.get_cog("FriendGroups")
                if cog:
                    guild = interaction.client.get_guild(fg.guild_id)
                    if guild:
                        await cog.provision_fg_channels(guild, fg)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, emoji="✖️")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroup).where(FriendGroup.id == self.fg_id))
            fg = res.scalar_one_or_none()

            if fg:
                invited = list(fg.invited)
                if interaction.user.id in invited:
                    invited.remove(interaction.user.id)
                    fg.invited = invited
                    await session.commit()

        self.disable_all_items()
        await interaction.response.edit_message(content="❌ You declined the Friend Group invitation.", view=self)

class FriendGroupsCog(commands.Cog, name="FriendGroups"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def provision_fg_channels(self, guild: discord.Guild, fg: FriendGroup):
        """Auto-create category, text channel, and voice channel with scoped permissions."""
        try:
            async with AsyncSessionLocal() as session:
                # Fetch fresh FG
                res = await session.execute(select(FriendGroup).where(FriendGroup.id == fg.id))
                fg_db = res.scalar_one()

                # Get guild roles for admin/mod overrides
                res_cfg = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild.id))
                g_cfg = res_cfg.scalar_one_or_none()

                overrides = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, connect=True)
                }

                # Allow server admins/mods
                if g_cfg:
                    if g_cfg.admin_role_id:
                        r = guild.get_role(g_cfg.admin_role_id)
                        if r:
                            overrides[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True)
                    if g_cfg.mod_role_id:
                        r = guild.get_role(g_cfg.mod_role_id)
                        if r:
                            overrides[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True)

                # Allow FG creator and all members
                all_member_ids = set([fg_db.creator_id] + fg_db.members)
                for mid in all_member_ids:
                    member = guild.get_member(mid)
                    if member:
                        overrides[member] = discord.PermissionOverwrite(
                            read_messages=True,
                            send_messages=True,
                            connect=True,
                            speak=True,
                            attach_files=True,
                            embed_links=True
                        )

                # Create Category
                cat_name = f"FG • {fg_db.name}"
                category = await guild.create_category(name=cat_name, overwrites=overrides, reason=f"Friend Group #{fg_db.id} provisioning")

                # Create Text Channel
                text_name = f"{fg_db.name.lower().replace(' ', '-')}-chat"
                text_ch = await guild.create_text_channel(name=text_name, category=category, reason=f"Friend Group #{fg_db.id}")

                # Create Voice Channel
                voice_name = f"🔊 {fg_db.name}"
                voice_ch = await guild.create_voice_channel(name=voice_name, category=category, reason=f"Friend Group #{fg_db.id}")

                fg_db.category_id = category.id
                fg_db.text_channel_id = text_ch.id
                fg_db.voice_channel_id = voice_ch.id
                fg_db.status = "active"
                await session.commit()

                # Welcome embed in text channel
                members_mentions = ", ".join(f"<@{m}>" for m in all_member_ids)
                welcome_embed = ego_embed(
                    title=f"👑 Welcome to {fg_db.name}",
                    description=(
                        f"> **Private Friend Group Circle Initialized!**\n"
                        f"› **Leader:** <@{fg_db.creator_id}>\n"
                        f"› **Members:** {members_mentions}\n\n"
                        f"This category, text lounge, and voice suite are exclusively configured for your squad.\n"
                        f"Use `/fg invite` to add more friends, `/fg rename` to update branding, or `/fg kick` to manage roster."
                    ),
                    color=COLOR_VIOLET
                )
                await text_ch.send(content=f"<@{fg_db.creator_id}>", embed=welcome_embed)
                logger.info(f"Provisioned Friend Group channels for {fg_db.name} (Guild: {guild.id})")
        except Exception as e:
            logger.error(f"Failed to provision Friend Group channels: {e}")

    fg_group = app_commands.Group(name="fg", description="Friend Group (FG) Management")

    @fg_group.command(name="config", description="Configure server-wide Friend Group settings")
    @app_commands.describe(
        enabled="Enable or disable Friend Groups",
        max_per_user="Max FGs a single user can create",
        max_per_guild="Max total FGs in the server"
    )
    @is_guild_owner()
    async def fg_config(
        self,
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        max_per_user: Optional[int] = None,
        max_per_guild: Optional[int] = None
    ):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(FriendGroupConfig).where(FriendGroupConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = FriendGroupConfig(guild_id=interaction.guild_id)
                session.add(cfg)

            if enabled is not None:
                cfg.enabled = enabled
            if max_per_user is not None:
                cfg.max_fgs_per_user = max_per_user
            if max_per_guild is not None:
                cfg.max_fgs_per_guild = max_per_guild

            await session.commit()

        await interaction.response.send_message(
            embed=success_embed(
                "FG Configuration Saved",
                f"• Status: `{'Enabled' if cfg.enabled else 'Disabled'}`\n"
                f"• Max per User: `{cfg.max_fgs_per_user}`\n"
                f"• Max per Server: `{cfg.max_fgs_per_guild}`"
            )
        )

    @fg_group.command(name="start", description="Create a new Friend Group")
    @app_commands.describe(name="Name for your Friend Group")
    async def fg_start(self, interaction: discord.Interaction, name: str):
        guild = interaction.guild
        user = interaction.user

        async with AsyncSessionLocal() as session:
            # Check system enabled
            res_cfg = await session.execute(select(FriendGroupConfig).where(FriendGroupConfig.guild_id == guild.id))
            cfg = res_cfg.scalar_one_or_none()

            if not cfg or not cfg.enabled:
                return await interaction.response.send_message(
                    embed=error_embed("System Disabled", "Friend Groups are not enabled by the server owner."),
                    ephemeral=True
                )

            # Check user FG limit
            res_user = await session.execute(
                select(func.count(FriendGroup.id)).where(
                    FriendGroup.guild_id == guild.id,
                    FriendGroup.creator_id == user.id,
                    FriendGroup.status != "disbanded"
                )
            )
            user_fgs = res_user.scalar() or 0
            if user_fgs >= cfg.max_fgs_per_user:
                return await interaction.response.send_message(
                    embed=error_embed("Limit Reached", f"You have reached the limit of `{cfg.max_fgs_per_user}` Friend Group(s)."),
                    ephemeral=True
                )

            # Create pending FG
            fg = FriendGroup(
                guild_id=guild.id,
                name=name.strip(),
                creator_id=user.id,
                status="pending",
                members_json=f"[{user.id}]", # Creator is member 1
                invited_json="[]"
            )
            session.add(fg)
            await session.commit()
            await session.refresh(fg)

        embed = ego_embed(
            title=f"👥 Friend Group: {name} (Pending)",
            description=(
                f"Your Friend Group **{name}** has entered the pending creation phase!\n\n"
                f"📌 **Required:** You need at least **4 members** (including yourself) before your private category and channels are auto-created.\n\n"
                f"Invite friends using `/fg invite @member` (Group ID: `{fg.id}`)."
            ),
            color=INFO_COLOR
        )
        await interaction.response.send_message(embed=embed)

    @fg_group.command(name="invite", description="Invite a friend to your Friend Group")
    @app_commands.describe(user="The member to invite")
    async def fg_invite(self, interaction: discord.Interaction, user: discord.Member):
        if user.bot or user.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Target", "You cannot invite yourself or bots."),
                ephemeral=True
            )

        async with AsyncSessionLocal() as session:
            # Find FG where caller is creator
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == interaction.guild_id,
                    FriendGroup.creator_id == interaction.user.id,
                    FriendGroup.status != "disbanded"
                )
            )
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message(
                    embed=error_embed("Not Found", "You do not own an active or pending Friend Group."),
                    ephemeral=True
                )

            members = list(fg.members)
            invited = list(fg.invited)

            if user.id in members:
                return await interaction.response.send_message(
                    embed=error_embed("Already Member", f"{user.mention} is already in your Friend Group."),
                    ephemeral=True
                )

            if user.id not in invited:
                invited.append(user.id)
                fg.invited = invited
                await session.commit()

        # Send invite view
        view = FGInviteView(fg.id, user.id)
        embed = ego_embed(
            title=f"💌 Friend Group Invite: {fg.name}",
            description=(
                f"{interaction.user.mention} has invited you to join the **{fg.name}** Friend Group in **{interaction.guild.name}**!\n\n"
                f"Click below to accept or decline."
            ),
            color=INFO_COLOR
        )

        try:
            await user.send(embed=embed, view=view)
            await interaction.response.send_message(
                embed=success_embed("Invite Sent", f"Invitation sent to {user.mention} via Direct Message.")
            )
        except Exception:
            # Fallback ping in channel
            await interaction.response.send_message(
                content=user.mention,
                embed=embed,
                view=view
            )

    @fg_group.command(name="rename", description="Rename your Friend Group")
    @app_commands.describe(new_name="New name for the Friend Group")
    async def fg_rename(self, interaction: discord.Interaction, new_name: str):
        new_name = new_name.strip()
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == interaction.guild_id,
                    FriendGroup.creator_id == interaction.user.id,
                    FriendGroup.status != "disbanded"
                )
            )
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message(
                    embed=error_embed("Not Found", "You do not own an active Friend Group."),
                    ephemeral=True
                )

            fg.name = new_name
            await session.commit()

            # Update channels if provisioned
            if fg.category_id:
                cat = interaction.guild.get_channel(fg.category_id)
                if cat:
                    await cat.edit(name=f"FG • {new_name}")
            if fg.text_channel_id:
                tc = interaction.guild.get_channel(fg.text_channel_id)
                if tc:
                    await tc.edit(name=f"{new_name.lower().replace(' ', '-')}-chat")
            if fg.voice_channel_id:
                vc = interaction.guild.get_channel(fg.voice_channel_id)
                if vc:
                    await vc.edit(name=f"🔊 {new_name}")

        await interaction.response.send_message(embed=success_embed("Renamed", f"Your Friend Group was renamed to **{new_name}**."))

    @fg_group.command(name="kick", description="Remove a member from your Friend Group")
    @app_commands.describe(user="The member to remove")
    async def fg_kick(self, interaction: discord.Interaction, user: discord.Member):
        if user.id == interaction.user.id:
            return await interaction.response.send_message(embed=error_embed("Error", "You cannot kick yourself."), ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == interaction.guild_id,
                    FriendGroup.creator_id == interaction.user.id,
                    FriendGroup.status != "disbanded"
                )
            )
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message(embed=error_embed("Not Found", "You do not own an active Friend Group."), ephemeral=True)

            members = list(fg.members)
            if user.id in members:
                members.remove(user.id)
                fg.members = members
                await session.commit()

                # Revoke channel permissions
                if fg.category_id:
                    cat = interaction.guild.get_channel(fg.category_id)
                    if cat:
                        await cat.set_permissions(user, overwrite=None)

                await interaction.response.send_message(embed=success_embed("Member Removed", f"{user.mention} was removed from **{fg.name}**."))
            else:
                await interaction.response.send_message(embed=error_embed("Not Member", f"{user.mention} is not in your Friend Group."), ephemeral=True)

    @fg_group.command(name="disband", description="Disband and delete your Friend Group")
    async def fg_disband(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(FriendGroup).where(
                    FriendGroup.guild_id == interaction.guild_id,
                    FriendGroup.creator_id == interaction.user.id,
                    FriendGroup.status != "disbanded"
                )
            )
            fg = res.scalar_one_or_none()

            if not fg:
                return await interaction.response.send_message(embed=error_embed("Not Found", "You do not own an active Friend Group."), ephemeral=True)

            fg.status = "disbanded"
            await session.commit()

            # Delete channels if existing
            for cid in [fg.text_channel_id, fg.voice_channel_id, fg.category_id]:
                if cid:
                    ch = interaction.guild.get_channel(cid)
                    if ch:
                        try:
                            await ch.delete(reason=f"FG #{fg.id} disbanded by creator")
                        except Exception:
                            pass

        await interaction.response.send_message(embed=success_embed("Disbanded", f"Your Friend Group **{fg.name}** has been disbanded."))

async def setup(bot: commands.Bot):
    await bot.add_cog(FriendGroupsCog(bot))
