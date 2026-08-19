"""
Content Creator (CC) Verification, Tier Requirements, and Creator Video Publishing Cog for Ego Bot.
Features /post command for Creators (with review ticket flow for CC and CC Tier 2),
configurable follower/view/like thresholds per tier, and custom video broadcast channels.
"""
import os
import json
import re
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
CC_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cc_config.json")

ALL_CC_ROLES = ["CC", "CC Tier 2", "CC Tier 3", "Known", "Famous", "Star"]
LOW_TIER_ROLES = ["CC", "CC Tier 2"]

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

def load_cc_config() -> Dict[str, Any]:
    os.makedirs(os.path.dirname(CC_CONFIG_FILE), exist_ok=True)
    if not os.path.exists(CC_CONFIG_FILE):
        return {}
    try:
        with open(CC_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_cc_config(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(CC_CONFIG_FILE), exist_ok=True)
    with open(CC_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class CCPostReviewView(discord.ui.View):
    def __init__(self, creator_id: Optional[int] = None, video_url: Optional[str] = None, desc: Optional[str] = None):
        super().__init__(timeout=None)
        self.creator_id = creator_id
        self.video_url = video_url
        self.desc = desc

    def _extract_info(self, message: discord.Message):
        if not message or not message.embeds:
            return
        embed = message.embeds[0]
        desc_text = embed.description or ""
        
        id_m = re.search(r"`(\d{15,22})`", desc_text)
        if id_m:
            self.creator_id = int(id_m.group(1))
            
        url_m = re.search(r"\((https?://[^\)]+)\)", desc_text)
        if url_m:
            self.video_url = url_m.group(1)

    @discord.ui.button(label="Accept & Broadcast Video", style=discord.ButtonStyle.success, custom_id="cc_post_approve_btn")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.creator_id:
            self._extract_info(interaction.message)

        if not self.creator_id or not self.video_url:
            return await interaction.response.send_message("Could not parse creator or video link.", ephemeral=True)

        guild = interaction.guild
        cfg = load_cc_config()
        vid_ch_id = cfg.get(str(guild.id), {}).get("video_channel_id")
        
        target_ch = guild.get_channel(vid_ch_id) if vid_ch_id else None
        if not target_ch or not isinstance(target_ch, discord.TextChannel):
            # Fallback to current channel
            target_ch = interaction.channel

        creator = guild.get_member(self.creator_id)
        creator_name = creator.display_name if creator else f"Creator ({self.creator_id})"

        # Broadcast video embed
        broadcast_embed = ego_embed(
            title=f"🎬 Creator Spotlight • {creator_name}",
            description=(
                f"> **Creator:** <@{self.creator_id}>\n"
                + (f"> **Note:** *{self.desc}*\n\n" if self.desc else "\n")
                + f"› **Watch Video:** [Direct Link]({self.video_url})\n\n"
                f"{self.video_url}"
            ),
            color=COLOR_CYAN
        )
        if creator:
            broadcast_embed.set_author(name=creator.display_name, icon_url=creator.display_avatar.url)

        await target_ch.send(content=f"📢 **New Creator Video!** <@{self.creator_id}>\n{self.video_url}", embed=broadcast_embed)

        # Notify creator via DM
        if creator:
            try:
                await creator.send(
                    embed=success_embed(
                        "Video Approved & Published",
                        f"Your video has been approved by staff and published in {target_ch.mention}!\n> {self.video_url}"
                    )
                )
            except Exception:
                pass

        # Disable review buttons
        for item in self.children:
            item.disabled = True

        if interaction.message.embeds:
            emb = interaction.message.embeds[0]
            emb.color = COLOR_EMERALD
            emb.title = "Video Post Approved"
            emb.add_field(name="› Approved By", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=emb, view=self)

        await interaction.response.send_message(f"Approved and published video to {target_ch.mention}.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="cc_post_decline_btn")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.creator_id:
            self._extract_info(interaction.message)

        guild = interaction.guild
        creator = guild.get_member(self.creator_id) if self.creator_id else None

        if creator:
            try:
                await creator.send(
                    embed=error_embed(
                        "Video Post Declined",
                        f"Your video submission was declined by server staff.\n> {self.video_url or 'Link'}"
                    )
                )
            except Exception:
                pass

        for item in self.children:
            item.disabled = True

        if interaction.message.embeds:
            emb = interaction.message.embeds[0]
            emb.color = COLOR_CRIMSON
            emb.title = "Video Post Declined"
            emb.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=emb, view=self)

        await interaction.response.send_message("Declined video submission.", ephemeral=True)


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
        if not message or not message.embeds:
            return
        embed = message.embeds[0]
        desc = embed.description or ""

        id_match = re.search(r"`(\d{15,22})`", desc)
        if id_match:
            self.applicant_id = int(id_match.group(1))

        plat_match = re.search(r"Platform:\*\* `([^`]+)`", desc, re.IGNORECASE)
        if plat_match:
            self.platform = plat_match.group(1)
        elif not self.platform:
            self.platform = "Creator"

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
                await member.add_roles(target_role, reason=f"CC Application Approved: {requested_tier}")
                try:
                    await member.send(
                        embed=success_embed(
                            "Creator Verification Approved",
                            f"Congratulations! You have been verified as **{requested_tier}** in **{guild.name}** and assigned {target_role.mention}."
                        )
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Failed to assign CC role: {e}")

        for item in self.children:
            item.disabled = True

        if interaction.message.embeds:
            old_embed = interaction.message.embeds[0]
            old_embed.color = COLOR_EMERALD
            old_embed.title = f"Creator Approved - {requested_tier}"
            old_embed.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=old_embed, view=self)

        await interaction.response.send_message(
            embed=success_embed("Approved", f"Assigned {target_role.mention} to <@{self.applicant_id}>."),
            ephemeral=True
        )

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="cc_decline_btn")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.applicant_id:
            self._extract_info_from_message(interaction.message)

        guild = interaction.guild
        member = guild.get_member(self.applicant_id) if self.applicant_id else None

        if member:
            try:
                await member.send(
                    embed=error_embed(
                        "Creator Application Declined",
                        f"Your verification application for **{self.requested_tier or 'Creator'}** in **{guild.name}** was declined by staff."
                    )
                )
            except Exception:
                pass

        for item in self.children:
            item.disabled = True

        if interaction.message.embeds:
            old_embed = interaction.message.embeds[0]
            old_embed.color = COLOR_CRIMSON
            old_embed.title = f"Creator Declined - {self.requested_tier or 'CC'}"
            old_embed.add_field(name="› Reviewed By", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=old_embed, view=self)

        await interaction.response.send_message(
            embed=error_embed("Declined", f"Declined application for <@{self.applicant_id}>."),
            ephemeral=True
        )


class CCVerifyModal(discord.ui.Modal, title="Content Creator Verification"):
    def __init__(self, platform: str, tier: str):
        super().__init__()
        self.platform = platform
        self.tier = tier

    profile_link = discord.ui.TextInput(
        label="Profile / Channel URL",
        placeholder="https://tiktok.com/@username or youtube.com/...",
        required=True,
        max_length=256
    )
    video_proof = discord.ui.TextInput(
        label="Video Proof URL",
        placeholder="Link to video showing your account analytics / handle",
        required=True,
        max_length=256
    )
    follower_count = discord.ui.TextInput(
        label="Follower / Subscriber Count",
        placeholder="e.g. 25,000",
        required=False,
        max_length=32
    )
    avg_views = discord.ui.TextInput(
        label="Average Views per Video",
        placeholder="e.g. 50,000",
        required=False,
        max_length=32
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user

        await interaction.response.defer(ephemeral=True)

        # Create Private Staff Ticket Channel for Verification
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        for role in guild.roles:
            if role.permissions.manage_guild or role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel_name = f"cc-verify-{user.name[:12].lower().replace(' ', '-')}"
        ticket_ch = await guild.create_text_channel(
            name=ticket_channel_name,
            overwrites=overwrites,
            topic=f"CC Verification Ticket for {user.name} ({user.id}) - Tier: {self.tier}"
        )

        ticket_embed = ego_embed(
            title=f"Creator Verification - {self.tier}",
            description=(
                f"> **Applicant:** {user.mention} (`{user.id}`)\n"
                f"> **Platform:** `{self.platform}`\n"
                f"> **Requested Tier:** `{self.tier}`\n"
                f"> **Followers / Subs:** `{self.follower_count.value or 'Not provided'}`\n"
                f"> **Average Views:** `{self.avg_views.value or 'Not provided'}`\n\n"
                f"› **Profile Link:** [Open Profile]({self.profile_link.value.strip()})\n"
                f"› **Video Proof Link:** [Watch Proof]({self.video_proof.value.strip()})\n\n"
                f"Staff can review the submitted proof links and click below to approve or decline."
            ),
            color=COLOR_VIOLET
        )
        ticket_embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

        view = CCTicketReviewView(
            applicant_id=user.id,
            platform=self.platform,
            profile_url=self.profile_link.value.strip(),
            video_url=self.video_proof.value.strip(),
            requested_tier=self.tier
        )

        await ticket_ch.send(
            content=f"📢 **New Creator Application:** {user.mention}",
            embed=ticket_embed,
            view=view
        )

        await interaction.followup.send(
            embed=success_embed(
                "Verification Ticket Created",
                f"Your Creator application for **{self.tier}** has been submitted! Staff will review it in {ticket_ch.mention}."
            ),
            ephemeral=True
        )


class ContentCreatorCog(commands.Cog, name="ContentCreator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    cc_group = app_commands.Group(name="cc", description="Content creator applications, tiers, and video publishing")

    @cc_group.command(name="verify", description="Apply for Content Creator roles with profile and video proof")
    @app_commands.describe(
        platform="Platform where you create content",
        tier="Tier you are applying for"
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="TikTok", value="TikTok"),
        app_commands.Choice(name="YouTube", value="YouTube"),
        app_commands.Choice(name="Twitch", value="Twitch"),
        app_commands.Choice(name="Instagram / Kick / Other", value="Other")
    ])
    @app_commands.choices(tier=[
        app_commands.Choice(name="CC", value="CC"),
        app_commands.Choice(name="CC Tier 2", value="CC Tier 2"),
        app_commands.Choice(name="CC Tier 3", value="CC Tier 3"),
        app_commands.Choice(name="Known", value="Known"),
        app_commands.Choice(name="Famous", value="Famous"),
        app_commands.Choice(name="Star", value="Star")
    ])
    async def cc_verify(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        tier: app_commands.Choice[str]
    ):
        await interaction.response.send_modal(CCVerifyModal(platform=platform.value, tier=tier.value))

    @app_commands.command(name="post", description="Publish a video to the server video channel (CC / CC Tier 2 queued for staff review)")
    @app_commands.describe(
        video_link="Direct link to your video (TikTok, YouTube, Twitch, etc.)",
        description="Optional title or note for your video"
    )
    async def post_video(
        self,
        interaction: discord.Interaction,
        video_link: str,
        description: Optional[str] = None
    ):
        guild = interaction.guild
        user = interaction.user

        if not isinstance(user, discord.Member):
            return await interaction.response.send_message("❌ This command must be run in a server.", ephemeral=True)

        user_role_names = [r.name for r in user.roles]
        user_cc_roles = [r for r in user_role_names if r in ALL_CC_ROLES]

        if not user_cc_roles and not user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Creator Role Required",
                    "You must have a verified Creator role (`CC` to `Star`) to use `/post`.\nRun `/cc verify` to apply!"
                ),
                ephemeral=True
            )

        # Check if user only holds low-tier roles (CC or CC Tier 2) requiring staff ticket approval
        highest_tier = "Star" if "Star" in user_cc_roles else "Famous" if "Famous" in user_cc_roles else "Known" if "Known" in user_cc_roles else "CC Tier 3" if "CC Tier 3" in user_cc_roles else "CC Tier 2" if "CC Tier 2" in user_cc_roles else "CC"
        requires_approval = highest_tier in LOW_TIER_ROLES and not user.guild_permissions.administrator

        if requires_approval:
            await interaction.response.defer(ephemeral=True)
            # Create Private Review Ticket Channel for Staff
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            for role in guild.roles:
                if role.permissions.manage_guild or role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            ticket_ch = await guild.create_text_channel(
                name=f"vid-review-{user.name[:12].lower().replace(' ', '-')}",
                overwrites=overwrites,
                topic=f"Video Post Review Ticket for {user.name} ({user.id}) - Tier: {highest_tier}"
            )

            review_embed = ego_embed(
                title=f"Video Post Review • {highest_tier}",
                description=(
                    f"> **Creator:** {user.mention} (`{user.id}`)\n"
                    f"> **Tier:** `{highest_tier}`\n"
                    + (f"> **Note:** *{description.strip()}*\n" if description else "")
                    + f"\n› **Video URL:** [Watch Video]({video_link.strip()})\n\n"
                    f"{video_link.strip()}\n\n"
                    f"Staff can click **Accept & Broadcast Video** to post to the server video channel or **Decline**."
                ),
                color=COLOR_AMBER
            )
            review_embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

            view = CCPostReviewView(creator_id=user.id, video_url=video_link.strip(), desc=description.strip() if description else None)
            await ticket_ch.send(content=f"📢 **New Video Submission:** {user.mention}", embed=review_embed, view=view)

            await interaction.followup.send(
                embed=info_embed(
                    "Video Queued for Review",
                    f"Your video has been submitted for staff approval in {ticket_ch.mention}.\n"
                    f"You will receive a direct message when it is approved and published!"
                ),
                ephemeral=True
            )
        else:
            # High Tier (CC Tier 3, Known, Famous, Star) or Admin -> Instant Publish!
            cfg = load_cc_config()
            vid_ch_id = cfg.get(str(guild.id), {}).get("video_channel_id")
            target_ch = guild.get_channel(vid_ch_id) if vid_ch_id else interaction.channel

            if not target_ch or not isinstance(target_ch, discord.TextChannel):
                target_ch = interaction.channel

            broadcast_embed = ego_embed(
                title=f"🎬 Creator Spotlight • {user.display_name}",
                description=(
                    f"> **Creator:** {user.mention} (`{highest_tier}`)\n"
                    + (f"> **Note:** *{description.strip()}*\n\n" if description else "\n")
                    + f"› **Watch Video:** [Direct Link]({video_link.strip()})\n\n"
                    f"{video_link.strip()}"
                ),
                color=COLOR_CYAN
            )
            broadcast_embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

            await target_ch.send(content=f"📢 **New Creator Video!** {user.mention}\n{video_link.strip()}", embed=broadcast_embed)
            await interaction.response.send_message(
                embed=success_embed("Video Published", f"Your video has been broadcasted to {target_ch.mention}!"),
                ephemeral=True
            )

    @cc_group.command(name="set_video_channel", description="Set the channel where approved Creator videos are published")
    @app_commands.describe(channel="Target video showcase channel")
    @is_admin_or_has_role()
    async def cc_set_video_ch(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_cc_config()
        g_id = str(interaction.guild.id)
        if g_id not in cfg:
            cfg[g_id] = {}
        cfg[g_id]["video_channel_id"] = channel.id
        save_cc_config(cfg)

        await interaction.response.send_message(
            embed=success_embed("Video Channel Set", f"Creator videos will now be published in {channel.mention}."),
            ephemeral=True
        )

    @cc_group.command(name="tiers", description="View follower and view requirements for all Creator tiers")
    async def cc_tiers(self, interaction: discord.Interaction):
        reqs = load_tier_requirements()
        embed = ego_embed(
            title="Creator Tiers & Requirements",
            description="Requirements to obtain Creator tiers in this server:\n",
            color=COLOR_VIOLET
        )

        for t_name in ["CC", "CC Tier 2", "CC Tier 3", "Known", "Famous", "Star"]:
            t_data = reqs.get(t_name, DEFAULT_TIER_REQUIREMENTS.get(t_name, {}))
            f_req = t_data.get("followers", "N/A")
            v_req = t_data.get("views", "N/A")
            desc = t_data.get("desc", "N/A")
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

    @cc_group.command(name="set_tier_req", description="Change follower, like, or view requirements for a Creator tier")
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
            existing = discord.utils.find(lambda r: r.name.lower() == t.lower(), guild.roles)
            if not existing:
                try:
                    role = await guild.create_role(name=t, color=discord.Color(0x8B5CF6), reason="Ego CC Setup")
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
