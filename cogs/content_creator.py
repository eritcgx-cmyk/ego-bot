"""
Content Creator (CC) Verification & Custom Tier Requirements Cog for Ego Bot.
Features configurable follower/view/like thresholds per tier,
command to update requirements (/cc set_tier_req), clean verification tickets, and persistent storage.
"""
import os
import json
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

CC_REQ_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cc_tier_requirements.json")

DEFAULT_TIER_REQUIREMENTS = {
    "CC": {
        "followers": "1,000+",
        "views": "5,000+",
        "desc": "Entry level creator (1k+ Followers or 5k+ Views)"
    },
    "CC Tier 2": {
        "followers": "5,000+",
        "views": "20,000+",
        "desc": "Established creator (5k+ Followers or 20k+ Views)"
    },
    "CC Tier 3": {
        "followers": "20,000+",
        "views": "50,000+",
        "desc": "High performing creator (20k+ Followers or 50k+ Views)"
    },
    "Known": {
        "followers": "50,000+",
        "views": "150,000+",
        "desc": "Recognized influencer (50k+ Followers or 150k+ Views)"
    },
    "Famous": {
        "followers": "100,000+",
        "views": "300,000+",
        "desc": "Prominent creator (100k+ Followers or 300k+ Views)"
    },
    "Star": {
        "followers": "500,000+",
        "views": "1,000,000+",
        "desc": "Apex creator icon (500k+ Followers or 1M+ Views)"
    }
}

def load_tier_requirements() -> Dict[str, Any]:
    os.makedirs(os.path.dirname(CC_REQ_FILE), exist_ok=True)
    if not os.path.exists(CC_REQ_FILE):
        with open(CC_REQ_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_TIER_REQUIREMENTS, f, indent=2)
        return DEFAULT_TIER_REQUIREMENTS.copy()
    try:
        with open(CC_REQ_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_TIER_REQUIREMENTS.copy()

def save_tier_requirements(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(CC_REQ_FILE), exist_ok=True)
    with open(CC_REQ_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

import re

class CCTicketReviewView(discord.ui.View):
    def __init__(
        self,
        applicant_id: Optional[int] = None,
        platform: Optional[str] = None,
        profile_url: Optional[str] = None,
        video_url: Optional[str] = None,
        requested_tier: Optional[str] = None
    ):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.platform = platform
        self.profile_url = profile_url
        self.video_url = video_url
        self.requested_tier = requested_tier

    def _extract_info_from_message(self, message: discord.Message):
        """Extracts applicant ID, tier, and platform directly from the embed message on bot reboots."""
        if not message or not message.embeds:
            return
        embed = message.embeds[0]
        desc = embed.description or ""

        # Extract Applicant User ID
        id_match = re.search(r"`(\d{15,22})`", desc)
        if id_match:
            self.applicant_id = int(id_match.group(1))

        # Extract Platform
        plat_match = re.search(r"Platform:\*\* `([^`]+)`", desc, re.IGNORECASE)
        if plat_match:
            self.platform = plat_match.group(1)
        elif not self.platform:
            self.platform = "Creator"

        # Extract Tier
        tier_match = re.search(r"Requested Tier:\*\* `([^`]+)`", desc, re.IGNORECASE)
        if tier_match:
            self.requested_tier = tier_match.group(1)
        elif embed.title and " - " in embed.title:
            self.requested_tier = embed.title.split(" - ")[-1].strip()
        elif not self.requested_tier:
            self.requested_tier = "CC"

    @discord.ui.button(label="Accept & Assign Role", style=discord.ButtonStyle.success, custom_id="cc_accept_btn")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.applicant_id:
            self._extract_info_from_message(interaction.message)

        if not self.applicant_id:
            return await interaction.response.send_message("Could not resolve applicant ID from this ticket.", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.applicant_id)
        requested_tier = self.requested_tier or "CC"

        target_role = discord.utils.get(guild.roles, name=requested_tier)
        if not target_role:
            try:
                target_role = await guild.create_role(name=requested_tier, color=discord.Color(0x8B5CF6), reason="Ego CC Tier")
            except Exception as e:
                return await interaction.response.send_message(f"Failed to find or create role `{requested_tier}`: {e}", ephemeral=True)

        if member:
            try:
                await member.add_roles(target_role, reason="Ego Creator Verification Approved")
                try:
                    dm_embed = success_embed(
                        "Creator Verification Approved",
                        f"Your **{(self.platform or 'Creator').title()}** Creator Application for **{guild.name}** has been approved.\n"
                        f"› **Assigned Role:** `{target_role.name}`"
                    )
                    await member.send(embed=dm_embed)
                except Exception:
                    pass
            except Exception as e:
                return await interaction.response.send_message(f"Could not assign role to member (Hierarchy check): {e}", ephemeral=True)

        for item in self.children:
            item.disabled = True

        if interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = COLOR_EMERALD
            embed.title = f"Creator Verification Approved - {requested_tier}"
            embed.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=embed, view=self)

        await interaction.response.send_message(f"Approved {member.mention if member else f'<@{self.applicant_id}>'} as **{requested_tier}**.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="cc_decline_btn")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.applicant_id:
            self._extract_info_from_message(interaction.message)

        guild = interaction.guild
        member = guild.get_member(self.applicant_id) if self.applicant_id else None

        if member:
            try:
                dm_embed = error_embed(
                    "Creator Application Declined",
                    f"Your **{(self.platform or 'Creator').title()}** verification request for **{guild.name}** was reviewed and declined at this time.",
                    tip="Make sure your profile and video links are public and active."
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

        for item in self.children:
            item.disabled = True

        if interaction.message.embeds:
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

    @cc_group.command(name="tiers", description="View all Creator tiers and follower / view requirements")
    async def cc_tiers(self, interaction: discord.Interaction):
        reqs = load_tier_requirements()
        embed = ego_embed(
            title="Content Creator Tiers & Requirements",
            description=(
                "> Verified Creators receive exclusive role badges and media permissions.\n"
                "> Run `/cc verify` to submit your profile and video proof.\n"
            ),
            color=COLOR_VIOLET
        )

        for t_name in ["CC", "CC Tier 2", "CC Tier 3", "Known", "Famous", "Star"]:
            t_data = reqs.get(t_name, {})
            f_req = t_data.get("followers", "Any")
            v_req = t_data.get("views", "Any")
            desc = t_data.get("desc", f"Followers: {f_req} | Views: {v_req}")

            embed.add_field(
                name=f"› {t_name}",
                value=(
                    f"• **Followers:** `{f_req}`\n"
                    f"• **Views / Likes:** `{v_req}`\n"
                    f"• **Description:** *{desc}*"
                ),
                inline=True
            )

        await interaction.response.send_message(embed=embed)

    @cc_group.command(name="set_tier_req", description="[Admin/Mods] Change follower, like, or view requirements for a Creator tier")
    @app_commands.describe(
        tier="Creator tier to update",
        followers="Required follower count (e.g. 2,500+)",
        views_or_likes="Required views or likes (e.g. 15,000+)",
        description="Custom description for this tier (optional)"
    )
    @app_commands.choices(tier=[
        app_commands.Choice(name="CC", value="CC"),
        app_commands.Choice(name="CC Tier 2", value="CC Tier 2"),
        app_commands.Choice(name="CC Tier 3", value="CC Tier 3"),
        app_commands.Choice(name="Known", value="Known"),
        app_commands.Choice(name="Famous", value="Famous"),
        app_commands.Choice(name="Star", value="Star")
    ])
    @is_admin_or_has_role()
    async def cc_set_tier_req(
        self,
        interaction: discord.Interaction,
        tier: app_commands.Choice[str],
        followers: str,
        views_or_likes: str,
        description: Optional[str] = None
    ):
        reqs = load_tier_requirements()
        t_name = tier.value
        reqs[t_name] = {
            "followers": followers.strip(),
            "views": views_or_likes.strip(),
            "desc": description.strip() if description else f"{followers.strip()} Followers or {views_or_likes.strip()} Views"
        }
        save_tier_requirements(reqs)

        await interaction.response.send_message(
            embed=success_embed(
                "Tier Requirements Updated",
                f"Updated requirements for **{t_name}**:\n"
                f"› **Followers:** `{followers.strip()}`\n"
                f"› **Views / Likes:** `{views_or_likes.strip()}`\n"
                f"› **Description:** *{reqs[t_name]['desc']}*"
            ),
            ephemeral=True
        )

    @cc_group.command(name="setup_roles", description="Auto-create all 6 Creator roles in your server")
    @is_guild_owner()
    async def cc_setup_roles(self, interaction: discord.Interaction):
        guild = interaction.guild
        created = []
        for t in ["CC", "CC Tier 2", "CC Tier 3", "Known", "Famous", "Star"]:
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
