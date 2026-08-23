"""
Comprehensive Face, Video & Identity Verification Engine for Ego Bot with Gender-Aware Role Rewards.
Features:
- Video & Selfie Proof verification with Server Vanity requirement
- Gender-aware auto-assignment: Grants "Verified Boy" or "Verified Girl" based on Male/Female roles or Staff approval
- Dedicated staff review queue with [Approve Boy], [Approve Girl], [Auto-Approve], and [Deny] buttons
- Automated role assignment and member DM notifications
- Persistent Verification Panel deployment
"""
import os
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
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
    from utils.kv_store import get_cached_kv
    cached = get_cached_kv("face_verify_config")
    if cached is not None and isinstance(cached, dict):
        return cached

    if not os.path.exists(VERIFY_CONFIGS_FILE):
        return {}
    try:
        with open(VERIFY_CONFIGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_face_configs(data: Dict[str, Any]):
    from utils.kv_store import set_cached_kv_and_schedule_save
    os.makedirs(os.path.dirname(VERIFY_CONFIGS_FILE), exist_ok=True)
    try:
        with open(VERIFY_CONFIGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    set_cached_kv_and_schedule_save("face_verify_config", data)

def detect_member_gender(member: discord.Member, cfg: Dict[str, Any]) -> str:
    """Detects whether member has Male or Female roles configured on server."""
    male_role_id = cfg.get("male_role_id")
    female_role_id = cfg.get("female_role_id")

    user_role_ids = [r.id for r in member.roles]
    user_role_names = [r.name.lower() for r in member.roles]

    if female_role_id and female_role_id in user_role_ids:
        return "girl"
    if male_role_id and male_role_id in user_role_ids:
        return "boy"

    # Fallback to name pattern matching
    for name in user_role_names:
        if any(w in name for w in ["female", "girl", "she/her", "she", "woman", "lady"]):
            return "girl"
        if any(w in name for w in ["male", "boy", "he/him", "he", "man", "guy"]):
            return "boy"

    return "unknown"


class FaceVerifySubmitModal(discord.ui.Modal, title="Face & Vanity Video Verification"):
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
    gender_input = discord.ui.TextInput(
        label="Gender / Pronouns (Boy / Girl / He / She)",
        placeholder="Boy or Girl (helps assign Verified Boy / Verified Girl)",
        required=False,
        max_length=50
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
        if not guild or not isinstance(user, discord.Member):
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

        # Detect role gender and user input gender
        detected_gender = detect_member_gender(user, cfg)
        gender_claim = self.gender_input.value.strip() if self.gender_input.value else "Not specified"
        gender_display = f"`{detected_gender.upper()}` (detected from roles)" if detected_gender != "unknown" else f"`{gender_claim}` (claimed in modal)"

        # Calculate account age
        account_age_days = (datetime.now(timezone.utc) - user.created_at).days
        min_age = cfg.get("min_account_age_days", 7)
        age_status = f"✅ `{account_age_days}` days old" if account_age_days >= min_age else f"⚠️ Account is `{account_age_days}` days old (Min: `{min_age}` days)"

        video_link_clean = self.video_url.value.strip()

        review_embed = ego_embed(
            title=f"📹 Face/Video Verification • {user.display_name}",
            description=(
                f"> **Applicant:** {user.mention} (`{user.id}`)\n"
                f"> **Gender Target:** {gender_display}\n"
                f"> **Account Age:** {age_status}\n"
                f"> **Joined Server:** <t:{int(user.joined_at.timestamp())}:R>\n"
                f"> **Required Vanity:** `{self.vanity_phrase}`\n\n"
                f"**✦ Submitted Proof:**\n"
                f"• **Video Link:** [Watch Submitted Video]({video_link_clean})\n"
                f"• **Raw URL:** `{video_link_clean}`\n"
                + (f"• **Social Profile:** `{self.social_handle.value.strip()}`\n" if self.social_handle.value else "")
                + (f"• **Applicant Notes:** *{self.notes.value.strip()}*\n" if self.notes.value else "")
                + f"\n*Staff: Choose [Approve Boy], [Approve Girl], [Auto-Approve], or [Deny] below.*"
            ),
            color=COLOR_VIOLET
        )
        review_embed.set_thumbnail(url=user.display_avatar.url)
        review_embed.set_footer(text=f"Verification Ticket • {get_eastern_time()}")

        view = FaceVerifyReviewView(applicant_id=user.id, detected_gender=detected_gender)
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
    """Staff review interactive buttons for Face/Video verification with gender-aware role buttons."""
    def __init__(self, applicant_id: int = 0, detected_gender: str = "unknown"):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.detected_gender = detected_gender
        self.boy_btn.custom_id = f"face_app_boy:{applicant_id}"
        self.girl_btn.custom_id = f"face_app_girl:{applicant_id}"
        self.auto_btn.custom_id = f"face_app_auto:{applicant_id}"
        self.deny_btn.custom_id = f"face_deny:{applicant_id}"

    async def _execute_approval(self, interaction: discord.Interaction, target_gender: str):
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

        # Resolve roles to assign
        assigned_roles: List[discord.Role] = []

        # 1. Base Verified Role
        base_role_id = cfg.get("verified_role_id")
        if base_role_id:
            base_r = guild.get_role(base_role_id)
            if base_r:
                assigned_roles.append(base_r)

        # 2. Gender Verified Role
        if target_gender == "boy":
            boy_role_id = cfg.get("verified_boy_role_id")
            if boy_role_id:
                boy_r = guild.get_role(boy_role_id)
                if boy_r and boy_r not in assigned_roles:
                    assigned_roles.append(boy_r)
        elif target_gender == "girl":
            girl_role_id = cfg.get("verified_girl_role_id")
            if girl_role_id:
                girl_r = guild.get_role(girl_role_id)
                if girl_r and girl_r not in assigned_roles:
                    assigned_roles.append(girl_r)
        elif target_gender == "auto":
            # Auto-detect from applicant's current roles
            det = detect_member_gender(applicant, cfg) if applicant else "unknown"
            if det == "girl":
                girl_role_id = cfg.get("verified_girl_role_id")
                if girl_role_id:
                    girl_r = guild.get_role(girl_role_id)
                    if girl_r and girl_r not in assigned_roles:
                        assigned_roles.append(girl_r)
            elif det == "boy":
                boy_role_id = cfg.get("verified_boy_role_id")
                if boy_role_id:
                    boy_r = guild.get_role(boy_role_id)
                    if boy_r and boy_r not in assigned_roles:
                        assigned_roles.append(boy_r)

        if applicant and assigned_roles:
            try:
                await applicant.add_roles(*assigned_roles, reason=f"Face/Video Verification approved by {interaction.user.name}")
            except Exception as e:
                logger.error(f"Failed to assign verified roles: {e}")

        # Disable buttons
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        roles_str = ", ".join(r.mention for r in assigned_roles) if assigned_roles else "*None*"
        label_gender = "Verified Boy" if target_gender == "boy" else "Verified Girl" if target_gender == "girl" else "Auto-Verified"

        await interaction.response.send_message(
            embed=success_embed(
                f"Verification Approved ({label_gender})",
                f"✅ <@{applicant_id}> was approved by {interaction.user.mention} and assigned: {roles_str}."
            )
        )

        if applicant:
            try:
                dm_embed = ego_embed(
                    title=f"🎉 Verification Approved • {guild.name}",
                    description=f"Congratulations! Your Face/Video verification on **{guild.name}** has been **Approved**!\nYou have received: {roles_str}.",
                    color=COLOR_EMERALD
                )
                await applicant.send(embed=dm_embed)
            except Exception:
                pass

    @discord.ui.button(label="Approve Boy", style=discord.ButtonStyle.primary, emoji="👦", custom_id="face_app_boy")
    async def boy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_approval(interaction, target_gender="boy")

    @discord.ui.button(label="Approve Girl", style=discord.ButtonStyle.primary, emoji="👧", custom_id="face_app_girl")
    async def girl_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_approval(interaction, target_gender="girl")

    @discord.ui.button(label="Auto-Approve", style=discord.ButtonStyle.success, emoji="⚡", custom_id="face_app_auto")
    async def auto_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_approval(interaction, target_gender="auto")

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌", custom_id="face_deny")
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
        try:
            await interaction.response.send_modal(modal)
        except (discord.NotFound, discord.InteractionResponded):
            pass
        except Exception as e:
            logger.debug(f"Modal dispatch error: {e}")


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

    @verify_admin_group.command(name="setup", description="Configure Verified Boy/Girl roles, review channel, and vanity")
    @app_commands.describe(
        review_channel="Channel where submitted video proof is sent for staff review",
        verified_boy_role="Role given to verified boys / males (e.g. @Verified Boy)",
        verified_girl_role="Role given to verified girls / females (e.g. @Verified Girl)",
        base_verified_role="Optional base @Verified role granted to all approved applicants",
        male_role="Optional @Male role used for automatic gender detection",
        female_role="Optional @Female role used for automatic gender detection",
        vanity_phrase="Required vanity text (e.g. .gg/ego or server vanity)",
        min_account_age="Minimum account age in days (default: 7)"
    )
    @is_admin_or_has_role()
    async def verify_admin_setup(
        self,
        interaction: discord.Interaction,
        review_channel: discord.TextChannel,
        verified_boy_role: Optional[discord.Role] = None,
        verified_girl_role: Optional[discord.Role] = None,
        base_verified_role: Optional[discord.Role] = None,
        male_role: Optional[discord.Role] = None,
        female_role: Optional[discord.Role] = None,
        vanity_phrase: Optional[str] = None,
        min_account_age: Optional[int] = 7
    ):
        guild = interaction.guild
        configs = load_face_configs()
        g_id = str(guild.id)

        phrase = vanity_phrase.strip() if vanity_phrase else getattr(guild, "vanity_url_code", None) or f"discord.gg/{guild.name.lower().replace(' ', '')}"

        configs[g_id] = {
            "review_channel_id": review_channel.id,
            "verified_boy_role_id": verified_boy_role.id if verified_boy_role else None,
            "verified_girl_role_id": verified_girl_role.id if verified_girl_role else None,
            "verified_role_id": base_verified_role.id if base_verified_role else None,
            "male_role_id": male_role.id if male_role else None,
            "female_role_id": female_role.id if female_role else None,
            "vanity_phrase": phrase,
            "min_account_age_days": min_account_age or 7,
            "enabled": True
        }
        save_face_configs(configs)

        try:
            from utils.state_manager import update_guild_state_section
            update_guild_state_section(guild.id, "verify", configs[g_id])
        except Exception:
            pass

        boy_str = verified_boy_role.mention if verified_boy_role else "*Unset*"
        girl_str = verified_girl_role.mention if verified_girl_role else "*Unset*"
        base_str = base_verified_role.mention if base_verified_role else "*Unset*"

        await interaction.response.send_message(
            embed=success_embed(
                "Face & Gender Verification Configured",
                f"✅ **Configuration Live:**\n"
                f"• **Review Channel:** {review_channel.mention}\n"
                f"• **Verified Boy Role:** {boy_str}\n"
                f"• **Verified Girl Role:** {girl_str}\n"
                f"• **Base Verified Role:** {base_str}\n"
                f"• **Required Vanity Phrase:** `{phrase}`\n"
                f"• **Min Account Age:** `{min_account_age or 7}` days\n\n"
                f"Run `/verify_admin post_panel` to deploy the verification panel in your verify channel!"
            ),
            ephemeral=True
        )

    @verify_admin_group.command(name="setup_roles", description="Auto-create Verified Boy, Verified Girl, Verified, Male, Female roles")
    @is_guild_owner()
    async def verify_admin_auto_roles(self, interaction: discord.Interaction):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        role_specs = [
            ("Verified Boy", 0x3B82F6),
            ("Verified Girl", 0xEC4899),
            ("Verified", 0x10B981),
            ("Male", 0x60A5FA),
            ("Female", 0xF472B6)
        ]

        created = []
        found_map = {}
        for r_name, r_color in role_specs:
            existing = discord.utils.find(lambda r, n=r_name: r.name.lower() == n.lower(), guild.roles)
            if not existing:
                try:
                    new_r = await guild.create_role(name=r_name, color=discord.Color(r_color), reason="Ego Verification Role Setup")
                    created.append(r_name)
                    found_map[r_name] = new_r
                except Exception as e:
                    logger.error(f"Could not create role {r_name}: {e}")
            else:
                found_map[r_name] = existing

        # Update configs with detected/created roles
        configs = load_face_configs()
        g_id = str(guild.id)
        if g_id not in configs:
            configs[g_id] = {}

        if "Verified Boy" in found_map:
            configs[g_id]["verified_boy_role_id"] = found_map["Verified Boy"].id
        if "Verified Girl" in found_map:
            configs[g_id]["verified_girl_role_id"] = found_map["Verified Girl"].id
        if "Verified" in found_map:
            configs[g_id]["verified_role_id"] = found_map["Verified"].id
        if "Male" in found_map:
            configs[g_id]["male_role_id"] = found_map["Male"].id
        if "Female" in found_map:
            configs[g_id]["female_role_id"] = found_map["Female"].id

        save_face_configs(configs)

        await interaction.followup.send(
            embed=success_embed(
                "Verification Roles Ready",
                f"✅ Verified & bound roles for this server:\n"
                f"• **Verified Boy:** {found_map.get('Verified Boy', 'None').mention if 'Verified Boy' in found_map else 'None'}\n"
                f"• **Verified Girl:** {found_map.get('Verified Girl', 'None').mention if 'Verified Girl' in found_map else 'None'}\n"
                f"• **Verified (Base):** {found_map.get('Verified', 'None').mention if 'Verified' in found_map else 'None'}\n"
                f"• **Male:** {found_map.get('Male', 'None').mention if 'Male' in found_map else 'None'}\n"
                f"• **Female:** {found_map.get('Female', 'None').mention if 'Female' in found_map else 'None'}"
            )
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

        boy_r = f"<@&{cfg.get('verified_boy_role_id')}>" if cfg.get('verified_boy_role_id') else "`@Verified Boy`"
        girl_r = f"<@&{cfg.get('verified_girl_role_id')}>" if cfg.get('verified_girl_role_id') else "`@Verified Girl`"

        embed = ego_embed(
            title=f"📹 Face & Video Verification • {guild.name}",
            description=(
                f"> **Get Authenticated & Verified in {guild.name}**\n\n"
                f"✦ **Verification Requirements:**\n"
                f"1. Record a short video/selfie showing your face.\n"
                f"2. Hold a paper with the server vanity: **`{vanity_phrase}`** along with your Discord username & today's date.\n"
                f"3. Upload to Streamable, Imgur, Discord, Drive, YouTube, or TikTok and submit your link below.\n\n"
                f"✦ **Reward Roles:**\n"
                f"• Boys receive {boy_r}\n"
                f"• Girls receive {girl_r}\n\n"
                f"Click **Start Face / Video Verification** below to submit your proof!"
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
