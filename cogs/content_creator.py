"""
Content Creator (CC) Verification Cog for Ego Bot.
Clean, minimal creator tiers (CC, CC Tier 2, CC Tier 3, Known, Famous, Star) with direct review tickets.
"""
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import ContentCreatorTier, GuildConfig
from utils.permissions import is_admin_or_has_role, is_guild_owner
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_EMERALD, COLOR_CRIMSON, COLOR_CYAN, COLOR_AMBER
)
from config import logger

CC_TIERS = ["CC", "CC Tier 2", "CC Tier 3", "Known", "Famous", "Star"]

class CCTicketReviewView(discord.ui.View):
    def __init__(self, applicant_id: int, platform: str, profile_url: str, video_url: str, requested_tier: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.platform = platform
        self.profile_url = profile_url
        self.video_url = video_url
        self.requested_tier = requested_tier

    @discord.ui.button(label="Accept & Assign Role", style=discord.ButtonStyle.success, custom_id="cc_accept_btn")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = guild.get_member(self.applicant_id)

        target_role = discord.utils.get(guild.roles, name=self.requested_tier)
        if not target_role:
            try:
                target_role = await guild.create_role(name=self.requested_tier, color=discord.Color(0x8B5CF6), reason="Ego CC Tier")
            except Exception as e:
                return await interaction.response.send_message(f"Failed to find or create role `{self.requested_tier}`: {e}", ephemeral=True)

        if member:
            try:
                await member.add_roles(target_role, reason="Ego Creator Verification Approved")
                try:
                    dm_embed = success_embed(
                        "Creator Verification Approved",
                        f"Your **{self.platform.title()}** Creator Application for **{guild.name}** has been approved.\n"
                        f"› **Assigned Role:** `{target_role.name}`"
                    )
                    await member.send(embed=dm_embed)
                except Exception:
                    pass
            except Exception as e:
                return await interaction.response.send_message(f"Could not assign role to member (Hierarchy check): {e}", ephemeral=True)

        for item in self.children:
            item.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = COLOR_EMERALD
        embed.title = f"Creator Verification Approved - {self.requested_tier}"
        embed.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"Approved {member.mention if member else f'<@{self.applicant_id}>'} as **{self.requested_tier}**.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="cc_decline_btn")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = guild.get_member(self.applicant_id)

        if member:
            try:
                dm_embed = error_embed(
                    "Creator Application Declined",
                    f"Your **{self.platform.title()}** verification request for **{guild.name}** was reviewed and declined at this time.",
                    tip="Make sure your profile and video links are public and active."
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

        for item in self.children:
            item.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = COLOR_CRIMSON
        embed.title = "Creator Verification Declined"
        embed.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"Declined application for <@{self.applicant_id}>.", ephemeral=True)

class CCVerificationModal(discord.ui.Modal, title="Content Creator Verification"):
    def __init__(self, platform: str, tier: str):
        super().__init__()
        self.platform = platform
        self.tier = tier

    profile_url = discord.ui.TextInput(
        label="Profile Link",
        placeholder="https://tiktok.com/@name or https://youtube.com/@name",
        max_length=300,
        required=True
    )
    video_url = discord.ui.TextInput(
        label="Video / Proof Link",
        placeholder="https://tiktok.com/@name/video/... or stream link",
        max_length=300,
        required=True
    )
    followers_count = discord.ui.TextInput(
        label="Follower Count (Optional)",
        placeholder="e.g. 5,000",
        max_length=50,
        required=False
    )
    views_or_likes = discord.ui.TextInput(
        label="Views or Likes (Optional)",
        placeholder="e.g. 10k views",
        max_length=100,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user

        async with AsyncSessionLocal() as session:
            cfg_res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild.id))
            cfg = cfg_res.scalar_one_or_none()

        ticket_channel = None
        if cfg and cfg.mod_log_channel_id:
            ticket_channel = guild.get_channel(cfg.mod_log_channel_id)

        if not ticket_channel:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            for role in guild.roles:
                if role.permissions.manage_guild or role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            try:
                ticket_channel = await guild.create_text_channel(
                    name=f"cc-{user.name[:15]}-{self.tier.lower().replace(' ', '-')}",
                    overwrites=overwrites,
                    topic=f"Creator Verification Ticket for {user.display_name}"
                )
            except Exception:
                ticket_channel = interaction.channel

        review_embed = ego_embed(
            title=f"Creator Verification Request - {self.tier}",
            description=(
                f"> **Applicant:** {user.mention} (`{user.id}`)\n"
                f"> **Platform:** `{self.platform.upper()}`\n"
                f"> **Requested Tier:** `{self.tier}`\n\n"
                f"› **Profile URL:** [Click to View Profile]({self.profile_url.value})\n"
                f"› **Video Proof URL:** [Click to View Video Proof]({self.video_url.value})\n"
                + (f"› **Followers:** `{self.followers_count.value}`\n" if self.followers_count.value else "")
                + (f"› **Views / Likes:** `{self.views_or_likes.value}`\n" if self.views_or_likes.value else "")
            ),
            color=COLOR_VIOLET
        )
        review_embed.set_thumbnail(url=user.display_avatar.url)

        view = CCTicketReviewView(
            applicant_id=user.id,
            platform=self.platform,
            profile_url=self.profile_url.value,
            video_url=self.video_url.value,
            requested_tier=self.tier
        )

        await ticket_channel.send(content=f"New Creator Submission from {user.mention}", embed=review_embed, view=view)

        await interaction.response.send_message(
            embed=success_embed(
                "Application Submitted",
                f"Your **{self.platform.upper()}** verification request for **{self.tier}** was submitted.\n"
                f"Our staff team will review your links in {ticket_channel.mention}."
            ),
            ephemeral=True
        )

class ContentCreatorCog(commands.Cog, name="ContentCreator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    cc_group = app_commands.Group(name="cc", description="Content Creator verification and tier management")

    @cc_group.command(name="verify", description="Submit your profile link and video proof for Creator verification")
    @app_commands.describe(
        platform="Content creation platform",
        tier="Creator tier"
    )
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="TikTok", value="tiktok"),
            app_commands.Choice(name="YouTube", value="youtube"),
            app_commands.Choice(name="Twitch", value="twitch"),
            app_commands.Choice(name="Instagram", value="instagram"),
            app_commands.Choice(name="Kick", value="kick"),
            app_commands.Choice(name="Twitter / X", value="twitter")
        ],
        tier=[
            app_commands.Choice(name="CC", value="CC"),
            app_commands.Choice(name="CC Tier 2", value="CC Tier 2"),
            app_commands.Choice(name="CC Tier 3", value="CC Tier 3"),
            app_commands.Choice(name="Known", value="Known"),
            app_commands.Choice(name="Famous", value="Famous"),
            app_commands.Choice(name="Star", value="Star")
        ]
    )
    async def cc_verify(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        tier: app_commands.Choice[str]
    ):
        await interaction.response.send_modal(CCVerificationModal(platform=platform.value, tier=tier.value))

    @cc_group.command(name="tiers", description="View all available Content Creator tiers")
    async def cc_tiers(self, interaction: discord.Interaction):
        embed = ego_embed(
            title="Content Creator Tiers",
            description=(
                "> Verified Creators receive role badges and media permissions.\n"
                "> Run `/cc verify` to submit your profile and video proof.\n"
            ),
            color=COLOR_VIOLET
        )

        for t in CC_TIERS:
            embed.add_field(
                name=f"› {t}",
                value=f"• **Role:** `{t}`",
                inline=True
            )

        await interaction.response.send_message(embed=embed)

    @cc_group.command(name="setup_roles", description="Auto-create all 6 Creator roles in your server")
    @is_guild_owner()
    async def cc_setup_roles(self, interaction: discord.Interaction):
        guild = interaction.guild
        created = []
        for t in CC_TIERS:
            existing = discord.utils.get(guild.roles, name=t)
            if not existing:
                try:
                    await guild.create_role(name=t, color=discord.Color(0x8B5CF6), reason="Ego CC Setup")
                    created.append(t)
                except Exception as e:
                    logger.error(f"Error creating role {t}: {e}")

        await interaction.response.send_message(
            embed=success_embed(
                "Creator Roles Ready",
                f"Configured all 6 Creator roles in the server:\n"
                f"› `CC`, `CC Tier 2`, `CC Tier 3`, `Known`, `Famous`, `Star`"
            ),
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(ContentCreatorCog(bot))
