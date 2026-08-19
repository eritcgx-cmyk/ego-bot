"""
Identity and Gender Verification System Cog for Ego Bot (Non-Photo)
"""
from datetime import datetime, timezone
from typing import Optional, Dict
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import IdentityVerifyConfig
from utils.permissions import is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import SUCCESS_COLOR, INFO_COLOR, WARNING_COLOR, logger

class IdentityVerificationView(discord.ui.View):
    def __init__(self, guild_id: int, roles_map: Dict[str, int]):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.roles_map = roles_map

        # Dynamically build buttons from roles_map
        for label, role_id in roles_map.items():
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"id_role:{guild_id}:{role_id}"
            )
            btn.callback = self._create_callback(role_id, label)
            self.add_item(btn)

        # Add manual verification button
        req_btn = discord.ui.Button(
            label="Request Mod Verification",
            style=discord.ButtonStyle.primary,
            emoji="🛡️",
            custom_id=f"id_manual_req:{guild_id}"
        )
        req_btn.callback = self._manual_request_callback
        self.add_item(req_btn)

    def _create_callback(self, role_id: int, label: str):
        async def callback(interaction: discord.Interaction):
            member = interaction.user
            if not isinstance(member, discord.Member):
                return

            role = interaction.guild.get_role(role_id)
            if not role:
                return await interaction.response.send_message("❌ This role no longer exists.", ephemeral=True)

            if role in member.roles:
                await member.remove_roles(role, reason="Identity self-selection toggle")
                await interaction.response.send_message(f"🗑️ Removed role **{role.name}**.", ephemeral=True)
            else:
                await member.add_roles(role, reason="Identity self-selection toggle")
                await interaction.response.send_message(f"✅ Added role **{role.name}**!", ephemeral=True)

        return callback

    async def _manual_request_callback(self, interaction: discord.Interaction):
        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(IdentityVerifyConfig).where(IdentityVerifyConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg or not cfg.review_channel_id:
                return await interaction.response.send_message("❌ Manual mod review channel is not configured on this server.", ephemeral=True)

            # Account Age Calculation
            created_at = member.created_at
            now = datetime.now(timezone.utc)
            account_age_days = (now - created_at).days

            review_channel = interaction.guild.get_channel(cfg.review_channel_id)
            if not review_channel or not isinstance(review_channel, discord.TextChannel):
                return await interaction.response.send_message("❌ Review channel unavailable.", ephemeral=True)

            age_status = f"✅ `{account_age_days}` days old" if account_age_days >= cfg.min_account_age_days else f"⚠️ Account is only `{account_age_days}` days old (Min: `{cfg.min_account_age_days}` days)"

            embed = ego_embed(
                title="🛡️ Manual Identity Verification Request",
                description=(
                    f"**User:** {member.mention} (`{member.id}`)\n"
                    f"**Account Age:** {age_status}\n"
                    f"**Joined Server:** <t:{int(member.joined_at.timestamp())}:R>\n\n"
                    f"*Staff may grant verified access or interview the user if needed.*"
                ),
                color=WARNING_COLOR if account_age_days < cfg.min_account_age_days else INFO_COLOR
            )
            embed.set_thumbnail(url=member.display_avatar.url)

            await review_channel.send(embed=embed)
            await interaction.response.send_message("✅ Your verification request has been dispatched to staff.", ephemeral=True)

class IdentityVerifyCog(commands.Cog, name="IdentityVerify"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def restore_verification_views(self):
        """Restore persistent buttons for verification panels."""
        try:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(IdentityVerifyConfig).where(IdentityVerifyConfig.enabled == True))
                configs = res.scalars().all()

                for cfg in configs:
                    if cfg.message_id and cfg.roles_map:
                        view = IdentityVerificationView(cfg.guild_id, cfg.roles_map)
                        self.bot.add_view(view, message_id=cfg.message_id)
        except Exception as e:
            logger.warning(f"Could not restore identity verification views: {e}")

    verify_group = app_commands.Group(
        name="verify_panel",
        description="Identity & Gender role verification panel",
        default_permissions=discord.Permissions(administrator=True)
    )

    @verify_group.command(name="setup", description="Deploy the identity & gender verification panel")
    @app_commands.describe(
        channel="Channel to post verification panel in",
        review_channel="Channel where manual verification alerts get sent",
        min_age_days="Minimum account age in days before flagging",
        role1="Role option 1 (e.g. He/Him)",
        role2="Role option 2 (e.g. She/Her)",
        role3="Role option 3 (e.g. They/Them)",
        role4="Role option 4 (e.g. Verified Member)"
    )
    @is_admin_or_has_role()
    async def verify_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        review_channel: Optional[discord.TextChannel] = None,
        min_age_days: int = 7,
        role1: Optional[discord.Role] = None,
        role2: Optional[discord.Role] = None,
        role3: Optional[discord.Role] = None,
        role4: Optional[discord.Role] = None
    ):
        roles_map = {}
        for r in [role1, role2, role3, role4]:
            if r:
                roles_map[r.name] = r.id

        if not roles_map:
            return await interaction.response.send_message(
                embed=error_embed("No Roles Specified", "Please provide at least 1 role option."),
                ephemeral=True
            )

        embed = ego_embed(
            title="✨ Identity & Role Verification",
            description=(
                "Select your identity, pronoun, or access roles below to customize your profile.\n\n"
                "🛡️ **Anti-Troll & Security:**\n"
                "If you need manual staff verification or access, click **Request Mod Verification**."
            ),
            color=INFO_COLOR
        )

        view = IdentityVerificationView(interaction.guild_id, roles_map)
        msg = await channel.send(embed=embed, view=view)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(IdentityVerifyConfig).where(IdentityVerifyConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = IdentityVerifyConfig(guild_id=interaction.guild_id)
                session.add(cfg)

            cfg.enabled = True
            cfg.channel_id = channel.id
            cfg.message_id = msg.id
            cfg.review_channel_id = review_channel.id if review_channel else None
            cfg.min_account_age_days = min_age_days
            cfg.roles_map = roles_map
            await session.commit()

        self.bot.add_view(view, message_id=msg.id)
        await interaction.response.send_message(
            embed=success_embed("Verification Panel Deployed", f"Active in {channel.mention} with `{len(roles_map)}` role buttons.")
        )

async def setup(bot: commands.Bot):
    cog = IdentityVerifyCog(bot)
    await bot.add_cog(cog)
    await cog.restore_verification_views()
