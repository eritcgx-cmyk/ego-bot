"""
Comprehensive Face, Video & Identity Verification Engine for Ego Bot.
Features:
- Video & Selfie Proof verification with Server Vanity requirement
- Dedicated staff review queue with live approve/deny interactive buttons
- Automated role assignment and member DM notifications
- Persistent Verification Panel deployment
"""
import os
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import IdentityVerifyConfig
from utils.permissions import is_admin_or_has_role, is_guild_owner
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_EMERALD, COLOR_CRIMSON, COLOR_AMBER, COLOR_CYAN, get_eastern_time
)
from utils.logger import log_action
from config import SUCCESS_COLOR, INFO_COLOR, WARNING_COLOR, logger

VERIFY_CONFIGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "face_verify_config.json")

def load_face_configs() -> Dict[str, Any]:
    if not os.path.exists(VERIFY_CONFIGS_FILE):
        return {}
    try:
        with open(VERIFY_CONFIGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_face_configs(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(VERIFY_CONFIGS_FILE), exist_ok=True)
    with open(VERIFY_CONFIGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class FaceVerifySubmitModal(discord.ui.Modal, title="Face / Video Verification"):
    """Modal for submitting video proof showing user and server vanity."""
    def __init__(self, vanity_phrase: str):
        super().__init__()
        self.vanity_phrase = vanity_phrase

    video_url = discord.ui.TextInput(
        label="Video Proof Link (Required)",
        placeholder="https://streamable.com/... or Imgur / Discord CDN / YouTube / TikTok",
        required=True,
        max_length=512
    )
    social_handle = discord.ui.TextInput(
        label="Social Profile / Handle (Optional)",
        placeholder="Instagram / TikTok / Twitter handle...",
        required=False,
        max_length=100
    )
    notes = discord.ui.TextInput(
        label="Notes / Confirmation",
        placeholder="Confirmed video shows face & server vanity...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild
        if not guild:
            return

        cfg = load_face_configs().get(str(guild.id), {})
        review_ch_id = cfg.get("review_channel_id")
        if not review_ch_id:
            return await interaction.response.send_message(
                embed=error_embed("Review Channel Unset", "Staff review channel is not configured on this server."),
                ephemeral=True
            )

        review_ch = guild.get_channel(review_ch_id)
        if not review_ch or not isinstance(review_ch, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Review Channel Error", "Staff review channel is unavailable or deleted."),
                ephemeral=True
            )

        # Calculate account age
        account_age_days = (datetime.now(timezone.utc) - user.created_at).days
        min_age = cfg.get("min_account_age_days", 7)
        age_status = f"✅ `{account_age_days}` days old" if account_age_days >= min_age else f"⚠️ Account is `{account_age_days}` days old (Min: `{min_age}` days)"

        video_link_clean = self.video_url.value.strip()

        review_embed = ego_embed(
            title=f"📹 Face/Video Verification • {user.display_name}",
            description=(
                f"> **Applicant:** {user.mention} (`{user.id}`)\n"
                f"> **Account Age:** {age_status}\n"
                f"> **Joined Server:** <t:{int(user.joined_at.timestamp())}:R>\n"
                f"> **Required Vanity:** `{self.vanity_phrase}`\n\n"
                f"**✦ Submitted Proof:**\n"
                f"• **Video Link:** [Watch Submitted Video]({video_link_clean})\n"
                f"• **Raw URL:** `{video_link_clean}`\n"
                + (f"• **Social Profile:** `{self.social_handle.value.strip()}`\n" if self.social_handle.value else "")
                + (f"• **Applicant Notes:** *{self.notes.value.strip()}*\n" if self.notes.value else "")
                + f"\n*Staff: Review the video to ensure user shows face and matches the vanity requirement.*"
            ),
            color=COLOR_VIOLET
        )
        review_embed.set_thumbnail(url=user.display_avatar.url)
        review_embed.set_footer(text=f"Verification Ticket • {get_eastern_time()}")

        verified_role_id = cfg.get("verified_role_id")
        view = FaceVerifyReviewView(applicant_id=user.id, verified_role_id=verified_role_id)
        await review_ch.send(embed=review_embed, view=view)

        await interaction.response.send_message(
            embed=success_embed(
                "Verification Submitted",
                f"✅ Your video verification has been dispatched to staff for review in {review_ch.mention}!\n"
                f"You will receive a direct notification once reviewed."
            ),
            ephemeral=True
        )


class FaceVerifyDenyModal(discord.ui.Modal, title="Deny Verification"):
    def __init__(self, applicant_id: int, message: discord.Message):
        super().__init__()
        self.applicant_id = applicant_id
        self.msg = message

    reason = discord.ui.TextInput(
        label="Reason for Denial",
        placeholder="e.g. Video did not show server vanity, poor lighting, or unreadable note...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        applicant = guild.get_member(self.applicant_id) or await interaction.client.fetch_user(self.applicant_id)

        # Disable buttons on review card
        for item in self.msg.components:
            for child in item.children:
                child.disabled = True
        try:
            await self.msg.edit(view=None)
        except Exception:
            pass

        # Alert applicant
        if applicant:
            try:
                dm_embed = ego_embed(
                    title=f"Verification Update • {guild.name}",
                    description=(
                        f"❌ Your Face / Video verification request on **{guild.name}** was **Declined**.\n\n"
                        f"**Reason:** *{self.reason.value.strip()}*\n\n"
                        f"You may re-record your video with the correct vanity and re-submit in the verification channel."
                    ),
                    color=COLOR_CRIMSON
                )
                await applicant.send(embed=dm_embed)
            except Exception:
                pass

        await interaction.response.send_message(
            embed=error_embed("Verification Denied", f"Denied verification for <@{self.applicant_id}>.\nReason: *{self.reason.value.strip()}*")
        )


class FaceVerifyReviewView(discord.ui.View):
    """Staff review interactive buttons for Face/Video verification."""
    def __init__(self, applicant_id: int = 0, verified_role_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.verified_role_id = verified_role_id
        self.approve_btn.custom_id = f"face_approve:{applicant_id}"
        self.deny_btn.custom_id = f"face_deny:{applicant_id}"

    @discord.ui.button(label="Approve & Grant Role", style=discord.ButtonStyle.success, emoji="✅", custom_id="face_verify_approve")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not interaction.user.guild_permissions.manage_roles and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Staff permissions required.", ephemeral=True)

        applicant_id = self.applicant_id
        if not applicant_id and interaction.data and "custom_id" in interaction.data:
            cid = interaction.data["custom_id"]
            if ":" in cid:
                applicant_id = int(cid.split(":")[1])

        applicant = guild.get_member(applicant_id)
        cfg = load_face_configs().get(str(guild.id), {})
        role_id = self.verified_role_id or cfg.get("verified_role_id")
        role_granted_str = ""

        if applicant and role_id:
            role = guild.get_role(role_id)
            if role:
                try:
                    await applicant.add_roles(role, reason=f"Face/Video Verification approved by {interaction.user.name}")
                    role_granted_str = f" and assigned {role.mention}"
                except Exception as e:
                    logger.error(f"Failed to assign verified role: {e}")

        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        await interaction.response.send_message(
            embed=success_embed(
                "Verification Approved",
                f"✅ <@{applicant_id}> was **Approved** by {interaction.user.mention}{role_granted_str}."
            )
        )

        if applicant:
            try:
                dm_embed = ego_embed(
                    title=f"🎉 Verification Approved • {guild.name}",
                    description=f"Congratulations! Your Face/Video verification on **{guild.name}** has been **Approved**!{role_granted_str}",
                    color=COLOR_EMERALD
                )
                await applicant.send(embed=dm_embed)
            except Exception:
                pass

    @discord.ui.button(label="Deny Verification", style=discord.ButtonStyle.danger, emoji="❌", custom_id="face_verify_deny")
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Staff permissions required.", ephemeral=True)

        applicant_id = self.applicant_id
        if not applicant_id and interaction.data and "custom_id" in interaction.data:
            cid = interaction.data["custom_id"]
            if ":" in cid:
                applicant_id = int(cid.split(":")[1])

        modal = FaceVerifyDenyModal(applicant_id=applicant_id, message=interaction.message)
        await interaction.response.send_modal(modal)


class FaceVerificationLaunchView(discord.ui.View):
    """Persistent panel button deployed in #verify for members to start video verification."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Start Face / Video Verification",
        style=discord.ButtonStyle.primary,
        emoji="📹",
        custom_id="face_verify_launch_btn"
    )
    async def launch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            return

        cfg = load_face_configs().get(str(guild.id), {})
        vanity_phrase = cfg.get("vanity_phrase") or getattr(guild, "vanity_url_code", None) or f"discord.gg/{guild.name.lower().replace(' ', '')}"

        modal = FaceVerifySubmitModal(vanity_phrase=vanity_phrase)
        await interaction.response.send_modal(modal)


class IdentityVerifyCog(commands.Cog, name="IdentityVerify"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =========================================================================
    # PUBLIC VERIFICATION COMMAND (/verify)
    # =========================================================================
    verify_public_group = app_commands.Group(name="verify", description="Member verification and identity authentication")

    @verify_public_group.command(name="face", description="Submit Face / Video verification proof with server vanity")
    async def verify_face_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("❌ Must be in a server.", ephemeral=True)

        cfg = load_face_configs().get(str(guild.id), {})
        vanity_phrase = cfg.get("vanity_phrase") or getattr(guild, "vanity_url_code", None) or f"discord.gg/{guild.name.lower().replace(' ', '')}"

        modal = FaceVerifySubmitModal(vanity_phrase=vanity_phrase)
        await interaction.response.send_modal(modal)

    # =========================================================================
    # STAFF / ADMIN VERIFICATION GROUP (/verify_admin)
    # =========================================================================
    verify_admin_group = app_commands.Group(
        name="verify_admin",
        description="Staff administration controls for Face/Video Verification",
        default_permissions=discord.Permissions(administrator=True)
    )

    @verify_admin_group.command(name="setup", description="Configure Face/Video verification settings, role, and review channel")
    @app_commands.describe(
        verified_role="Role automatically granted upon approval",
        review_channel="Channel where submitted video proof is sent for staff review",
        vanity_phrase="Required vanity text (e.g. .gg/ego or server vanity)",
        min_account_age="Minimum account age in days (default: 7)"
    )
    @is_admin_or_has_role()
    async def verify_admin_setup(
        self,
        interaction: discord.Interaction,
        verified_role: discord.Role,
        review_channel: discord.TextChannel,
        vanity_phrase: Optional[str] = None,
        min_account_age: Optional[int] = 7
    ):
        guild = interaction.guild
        configs = load_face_configs()
        g_id = str(guild.id)

        phrase = vanity_phrase.strip() if vanity_phrase else getattr(guild, "vanity_url_code", None) or f"discord.gg/{guild.name.lower().replace(' ', '')}"

        configs[g_id] = {
            "verified_role_id": verified_role.id,
            "review_channel_id": review_channel.id,
            "vanity_phrase": phrase,
            "min_account_age_days": min_account_age or 7,
            "enabled": True
        }
        save_face_configs(configs)

        await interaction.response.send_message(
            embed=success_embed(
                "Face Verification Configured",
                f"✅ **Configuration Live:**\n"
                f"• **Verified Role:** {verified_role.mention}\n"
                f"• **Review Channel:** {review_channel.mention}\n"
                f"• **Required Vanity Phrase:** `{phrase}`\n"
                f"• **Min Account Age:** `{min_account_age or 7}` days\n\n"
                f"Run `/verify_admin post_panel` to drop the verification panel in your welcome/verify channel!"
            ),
            ephemeral=True
        )

    @verify_admin_group.command(name="post_panel", description="Deploy the aesthetic permanent Face Verification Panel to a channel")
    @app_commands.describe(channel="Channel to post verification panel in (defaults to current)")
    @is_admin_or_has_role()
    async def verify_admin_post_panel(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild
        if not guild or not target_ch:
            return await interaction.response.send_message("❌ Channel not found.", ephemeral=True)

        cfg = load_face_configs().get(str(guild.id), {})
        vanity_phrase = cfg.get("vanity_phrase") or getattr(guild, "vanity_url_code", None) or f"discord.gg/{guild.name.lower().replace(' ', '')}"
        role_id = cfg.get("verified_role_id")
        role_mention = f"<@&{role_id}>" if role_id else "@Verified"

        embed = ego_embed(
            title=f"📹 Face & Video Verification • {guild.name}",
            description=(
                f"> **Get Authenticated & Verified in {guild.name}**\n\n"
                f"✦ **Verification Requirements:**\n"
                f"1. Record a short video/selfie of yourself.\n"
                f"2. Hold a paper showing the server vanity: **`{vanity_phrase}`** along with your Discord username & today's date.\n"
                f"3. Upload to Streamable, Imgur, Discord, Drive, YouTube, or TikTok and submit your link below.\n\n"
                f"✦ **Reward:** Unlocks the **{role_mention}** role and access to all private server channels!\n\n"
                f"Click **Start Face / Video Verification** below to begin."
            ),
            color=COLOR_VIOLET
        )
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        elif guild.splash:
            embed.set_image(url=guild.splash.url)

        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.set_footer(text=f"Official Verification Gate • {guild.name}")

        view = FaceVerificationLaunchView()
        await target_ch.send(embed=embed, view=view)

        await interaction.response.send_message(
            embed=success_embed("Panel Deployed", f"Verification panel is active in {target_ch.mention}."),
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(IdentityVerifyCog(bot))
