"""
Content Creator (CC) Verification & Ticket Management Cog for Ego Bot.
Features simple creator tiers (CC, CC Tier 2, CC Tier 3, Known, Famous, Star),
profile & video proof submission, automated ticket/review creation with Accept/Decline actions.
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
    COLOR_VIOLET, COLOR_EMERALD, COLOR_CRIMSON, COLOR_CYAN, COLOR_AMBER, COLOR_ROSE
)
from config import logger

CC_TIERS_DEFAULT = [
    {"name": "CC", "color": 0x3B82F6, "desc": "Entry Content Creator"},
    {"name": "CC Tier 2", "color": 0x8B5CF6, "desc": "Established Creator"},
    {"name": "CC Tier 3", "color": 0xEC4899, "desc": "High Performing Creator"},
    {"name": "Known", "color": 0xF59E0B, "desc": "Recognized Community Influencer"},
    {"name": "Famous", "color": 0x10B981, "desc": "Prominent Creator"},
    {"name": "Star", "color": 0xF43F5E, "desc": "Apex Tier Creator Icon"}
]

class CCTicketReviewView(discord.ui.View):
    def __init__(self, applicant_id: int, platform: str, profile_url: str, video_url: str, requested_tier: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.platform = platform
        self.profile_url = profile_url
        self.video_url = video_url
        self.requested_tier = requested_tier

    @discord.ui.button(label="Accept & Assign Role", style=discord.ButtonStyle.success, emoji="✅", custom_id="cc_accept_btn")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = guild.get_member(self.applicant_id)

        target_role = discord.utils.get(guild.roles, name=self.requested_tier)
        if not target_role:
            # Create role if it doesn't exist
            try:
                target_role = await guild.create_role(name=self.requested_tier, color=discord.Color(0x8B5CF6), reason="Ego CC Tier")
            except Exception as e:
                return await interaction.response.send_message(f"❌ Failed to find or create role `{self.requested_tier}`: {e}", ephemeral=True)

        if member:
            try:
                await member.add_roles(target_role, reason="Ego Creator Verification Approved")
                try:
                    dm_embed = success_embed(
                        "Creator Verification Approved",
                        f"🎉 Congratulations! Your **{self.platform.title()}** Creator Application for **{guild.name}** has been approved.\n"
                        f"› **Assigned Role:** `{target_role.name}`"
                    )
                    await member.send(embed=dm_embed)
                except Exception:
                    pass
            except Exception as e:
                return await interaction.response.send_message(f"❌ Could not assign role to member (Hierarchy check): {e}", ephemeral=True)

        for item in self.children:
            item.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = COLOR_EMERALD
        embed.title = f"✅ Creator Verification Approved ({self.requested_tier})"
        embed.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"✅ Approved {member.mention if member else f'<@{self.applicant_id}>'} as **{self.requested_tier}**.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✖", custom_id="cc_decline_btn")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = guild.get_member(self.applicant_id)

        if member:
            try:
                dm_embed = error_embed(
                    "Creator Application Declined",
                    f"Your **{self.platform.title()}** verification request for **{guild.name}** was reviewed and declined at this time.\n"
                    f"You may re-apply once your content stats grow!",
                    tip="Make sure your profile and video links are public and active."
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

        for item in self.children:
            item.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = COLOR_CRIMSON
        embed.title = "✖ Creator Verification Declined"
        embed.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"✖ Declined application for <@{self.applicant_id}>.", ephemeral=True)

class CCVerificationModal(discord.ui.Modal, title="🚀 Content Creator Verification"):
    def __init__(self, platform: str, tier: str):
        super().__init__()
        self.platform = platform
        self.tier = tier

    profile_url = discord.ui.TextInput(
        label="Profile / Channel Link",
        placeholder="https://tiktok.com/@yourname or https://youtube.com/@yourname",
        max_length=300,
        required=True
    )
    video_url = discord.ui.TextInput(
        label="Recent Video / Proof Link",
        placeholder="https://tiktok.com/@yourname/video/... or Twitch VOD link",
        max_length=300,
        required=True
    )
    followers_count = discord.ui.TextInput(
        label="Follower / Subscriber Count (Optional)",
        placeholder="e.g. 5,000 (leave blank if preferred)",
        max_length=50,
        required=False
    )
    views_or_likes = discord.ui.TextInput(
        label="Avg Views / Likes (Optional)",
        placeholder="e.g. 10k views per video (leave blank if preferred)",
        max_length=100,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user

        # Create Private Staff Review Ticket Channel or post to review channel
        async with AsyncSessionLocal() as session:
            cfg_res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild.id))
            cfg = cfg_res.scalar_one_or_none()

        ticket_channel = None
        if cfg and cfg.mod_log_channel_id:
            ticket_channel = guild.get_channel(cfg.mod_log_channel_id)

        # Fallback: create an aesthetic review ticket channel in the server if no mod log channel is set
        if not ticket_channel:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            # Add mod roles to overwrites
            for role in guild.roles:
                if role.permissions.manage_guild or role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            try:
                ticket_channel = await guild.create_text_channel(
                    name=f"cc-{user.name[:15]}-{self.tier.lower().replace(' ', '-')}",
                    overwrites=overwrites,
                    topic=f"Creator Verification Ticket for {user.display_name} ({self.platform})"
                )
            except Exception:
                ticket_channel = interaction.channel

        review_embed = ego_embed(
            title=f"🚀 Creator Verification Request • {self.tier}",
            description=(
                f"> **Applicant:** {user.mention} (`{user.id}`)\n"
                f"> **Platform:** `{self.platform.upper()}`\n"
                f"> **Requested Tier:** `{self.tier}`\n\n"
                f"› **Profile URL:** [Click to View Profile]({self.profile_url.value})\n"
                f"› **Video / Proof URL:** [Click to View Video Proof]({self.video_url.value})\n"
                + (f"› **Followers:** `{self.followers_count.value}`\n" if self.followers_count.value else "› **Followers:** *Not specified*\n")
                + (f"› **Views / Likes:** `{self.views_or_likes.value}`\n" if self.views_or_likes.value else "› **Views / Likes:** *Not specified*\n")
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

        await ticket_channel.send(content=f"📢 **New Creator Submission from {user.mention}**", embed=review_embed, view=view)

        await interaction.response.send_message(
            embed=success_embed(
                "Application Submitted",
                f"Your **{self.platform.upper()}** verification request for **{self.tier}** was submitted!\n"
                f"Our staff team will review your links in {ticket_channel.mention}."
            ),
            ephemeral=True
        )

class ContentCreatorCog(commands.Cog, name="ContentCreator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    cc_group = app_commands.Group(name="cc", description="Content Creator verification & tier management")

    @cc_group.command(name="verify", description="Submit your profile link & video proof for Creator verification")
    @app_commands.describe(
        platform="Your primary content creation platform",
        tier="The creator tier you are applying for"
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
            app_commands.Choice(name="CC (Entry Creator)", value="CC"),
            app_commands.Choice(name="CC Tier 2 (Established)", value="CC Tier 2"),
            app_commands.Choice(name="CC Tier 3 (High Performing)", value="CC Tier 3"),
            app_commands.Choice(name="Known (Community Influencer)", value="Known"),
            app_commands.Choice(name="Famous (Prominent Creator)", value="Famous"),
            app_commands.Choice(name="Star (Apex Creator)", value="Star")
        ]
    )
    async def cc_verify(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        tier: app_commands.Choice[str]
    ):
        await interaction.response.send_modal(CCVerificationModal(platform=platform.value, tier=tier.value))

    @cc_group.command(name="tiers", description="View all available Content Creator tiers and perks")
    async def cc_tiers(self, interaction: discord.Interaction):
        embed = ego_embed(
            title="🚀 Content Creator Tiers",
            description=(
                "> Verified Creators receive exclusive role badges, promo permissions, and VIP perks.\n"
                "> Run `/cc verify` to submit your profile and video proof link!\n"
            ),
            color=COLOR_VIOLET
        )

        for t in CC_TIERS_DEFAULT:
            embed.add_field(
                name=f"› {t['name']}",
                value=f"• **Badge:** `{t['name']}`\n• **Description:** *{t['desc']}*",
                inline=True
            )

        await interaction.response.send_message(embed=embed)

    @cc_group.command(name="setup_roles", description="Auto-create all standard Creator roles (CC, CC Tier 2, CC Tier 3, Known, Famous, Star)")
    @is_guild_owner()
    async def cc_setup_roles(self, interaction: discord.Interaction):
        guild = interaction.guild
        created = []
        for t in CC_TIERS_DEFAULT:
            existing = discord.utils.get(guild.roles, name=t["name"])
            if not existing:
                try:
                    await guild.create_role(name=t["name"], color=discord.Color(t["color"]), reason="Ego CC Setup")
                    created.append(t["name"])
                except Exception as e:
                    logger.error(f"Error creating role {t['name']}: {e}")

        await interaction.response.send_message(
            embed=success_embed(
                "Creator Roles Ready",
                f"✅ Verified & configured all 6 Creator roles in the server!\n"
                f"› **Roles:** `CC`, `CC Tier 2`, `CC Tier 3`, `Known`, `Famous`, `Star`"
            ),
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(ContentCreatorCog(bot))
