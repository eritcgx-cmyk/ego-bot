"""
Content Creator (CC) Verification System Cog for Ego Bot
"""
from typing import Optional, List
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import ContentCreatorTier, ContentCreatorSubmission, GuildConfig
from utils.permissions import is_admin_or_has_role, is_mod_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, logger

PLATFORMS = ["YouTube", "Twitch", "TikTok", "Kick", "Twitter/X", "Instagram"]
DEFAULT_TIERS = [
    {"name": "Tier 1", "followers": 1000, "views": 5000},
    {"name": "Tier 2", "followers": 5000, "views": 25000},
    {"name": "Tier 3", "followers": 25000, "views": 100000},
    {"name": "Star", "followers": 100000, "views": 500000},
    {"name": "Famous", "followers": 500000, "views": 2000000}
]

class CCVerifyModal(discord.ui.Modal, title="Content Creator Verification"):
    def __init__(self, platform: str):
        super().__init__()
        self.platform = platform

        self.username_input = discord.ui.TextInput(
            label=f"{platform} Handle / URL",
            placeholder=f"e.g. @yourname or channel link",
            required=True,
            max_length=150
        )
        self.followers_input = discord.ui.TextInput(
            label="Follower / Subscriber Count",
            placeholder="e.g. 15000",
            required=True,
            max_length=20
        )
        self.views_input = discord.ui.TextInput(
            label="Average / Top Video Views",
            placeholder="e.g. 50000",
            required=False,
            max_length=20
        )
        self.proof_input = discord.ui.TextInput(
            label="Screenshot or Profile Verification Link",
            placeholder="Direct link to profile or analytics screenshot",
            required=False,
            max_length=300
        )

        self.add_item(self.username_input)
        self.add_item(self.followers_input)
        self.add_item(self.views_input)
        self.add_item(self.proof_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            followers_num = int("".join(c for c in self.followers_input.value if c.isdigit()) or "0")
            views_num = int("".join(c for c in self.views_input.value if c.isdigit()) or "0")
        except ValueError:
            return await interaction.response.send_message("❌ Please enter numeric values for stats.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            sub = ContentCreatorSubmission(
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                platform=self.platform,
                username=self.username_input.value.strip(),
                followers=followers_num,
                views=views_num,
                proof_url=self.proof_input.value.strip() if self.proof_input.value else None,
                status="pending"
            )
            session.add(sub)
            await session.commit()
            await session.refresh(sub)

            # Route to mod log or review channel
            res_g = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id))
            g_cfg = res_g.scalar_one_or_none()

            # Find matching tier suggestion
            res_tiers = await session.execute(
                select(ContentCreatorTier)
                .where(ContentCreatorTier.guild_id == interaction.guild_id)
                .order_by(ContentCreatorTier.required_followers.desc())
            )
            tiers = res_tiers.scalars().all()
            suggested_tier = None
            for t in tiers:
                if followers_num >= t.required_followers:
                    suggested_tier = t
                    break

            review_ch_id = g_cfg.mod_log_channel_id if g_cfg else None
            review_ch = interaction.guild.get_channel(review_ch_id) if review_ch_id else None

            if review_ch and isinstance(review_ch, discord.TextChannel):
                view = CCReviewView(sub.id, interaction.user.id, suggested_tier.role_id if suggested_tier else None)
                embed = ego_embed(
                    title=f"🎥 CC Verification Request #{sub.id}",
                    description=(
                        f"**Applicant:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                        f"**Platform:** `{self.platform}`\n"
                        f"**Handle:** `{self.username_input.value}`\n"
                        f"**Followers:** `{followers_num:,}` | **Views:** `{views_num:,}`\n"
                        + (f"**Proof Link:** [Click Here]({self.proof_input.value})\n" if self.proof_input.value else "")
                        + (f"**Suggested Tier:** `{suggested_tier.tier_name}` (<@&{suggested_tier.role_id}>)\n" if suggested_tier and suggested_tier.role_id else "")
                    ),
                    color=INFO_COLOR
                )
                await review_ch.send(embed=embed, view=view)

        await interaction.response.send_message(
            embed=success_embed(
                "Application Submitted",
                "Your content creator verification request has been submitted for moderator review!"
            ),
            ephemeral=True
        )

class CCReviewView(discord.ui.View):
    def __init__(self, submission_id: int, applicant_id: int, suggested_role_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.submission_id = submission_id
        self.applicant_id = applicant_id
        self.suggested_role_id = suggested_role_id
        self.approve_btn.custom_id = f"cc_approve:{submission_id}"
        self.deny_btn.custom_id = f"cc_deny:{submission_id}"

    @discord.ui.button(label="Approve Verification", style=discord.ButtonStyle.green, emoji="✅")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ You lack permission to approve CC requests.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(ContentCreatorSubmission).where(ContentCreatorSubmission.id == self.submission_id))
            sub = res.scalar_one_or_none()

            if not sub or sub.status != "pending":
                return await interaction.response.send_message("❌ This submission is already processed.", ephemeral=True)

            sub.status = "approved"
            await session.commit()

        # Grant role
        applicant = interaction.guild.get_member(self.applicant_id)
        role_added_str = ""
        if applicant and self.suggested_role_id:
            role = interaction.guild.get_role(self.suggested_role_id)
            if role:
                try:
                    await applicant.add_roles(role, reason="CC Verification Approved")
                    role_added_str = f" and granted {role.mention}"
                except Exception:
                    pass

        self.disable_all_items()
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            embed=success_embed("Approved", f"Verification #{self.submission_id} approved by {interaction.user.mention}{role_added_str}.")
        )

        if applicant:
            try:
                await applicant.send(f"🎉 Your Content Creator verification on **{interaction.guild.name}** was **Approved**!")
            except Exception:
                pass

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, emoji="✖️")
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ You lack permission to deny CC requests.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(ContentCreatorSubmission).where(ContentCreatorSubmission.id == self.submission_id))
            sub = res.scalar_one_or_none()

            if not sub or sub.status != "pending":
                return await interaction.response.send_message("❌ This submission is already processed.", ephemeral=True)

            sub.status = "denied"
            await session.commit()

        self.disable_all_items()
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            embed=error_embed("Denied", f"Verification #{self.submission_id} denied by {interaction.user.mention}.")
        )

        applicant = interaction.guild.get_member(self.applicant_id)
        if applicant:
            try:
                await applicant.send(f"❌ Your Content Creator verification on **{interaction.guild.name}** was **Denied**.")
            except Exception:
                pass

class ContentCreatorCog(commands.Cog, name="ContentCreator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    cc_group = app_commands.Group(name="cc", description="Content Creator verification and tiers")

    @cc_group.command(name="verify", description="Submit your stats to verify for a Content Creator tier")
    @app_commands.describe(platform="Platform you create content on")
    @app_commands.choices(platform=[
        app_commands.Choice(name=p, value=p) for p in PLATFORMS
    ])
    async def cc_verify(self, interaction: discord.Interaction, platform: app_commands.Choice[str]):
        modal = CCVerifyModal(platform.value)
        await interaction.response.send_modal(modal)

    @cc_group.command(name="config_tier", description="Configure threshold and reward role for a CC tier")
    @app_commands.describe(
        tier_name="Tier Name (e.g. Tier 1, Star, Famous)",
        followers="Minimum followers required",
        views="Minimum average views required",
        role="Role to grant upon approval"
    )
    @is_admin_or_has_role()
    async def cc_config_tier(
        self,
        interaction: discord.Interaction,
        tier_name: str,
        followers: int,
        views: int,
        role: discord.Role
    ):
        tier_key = tier_name.strip().lower()
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(ContentCreatorTier).where(
                    ContentCreatorTier.guild_id == interaction.guild_id,
                    ContentCreatorTier.tier_name == tier_key
                )
            )
            tier = res.scalar_one_or_none()

            if not tier:
                tier = ContentCreatorTier(
                    guild_id=interaction.guild_id,
                    tier_name=tier_key,
                    required_followers=followers,
                    required_views=views,
                    role_id=role.id
                )
                session.add(tier)
            else:
                tier.required_followers = followers
                tier.required_views = views
                tier.role_id = role.id

            await session.commit()

        await interaction.response.send_message(
            embed=success_embed(
                "CC Tier Configured",
                f"Configured **{tier_name}**:\n"
                f"• Followers: `{followers:,}`\n"
                f"• Views: `{views:,}`\n"
                f"• Role: {role.mention}"
            )
        )

    @cc_group.command(name="tiers", description="List all configured Content Creator tiers")
    async def cc_tiers(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(ContentCreatorTier)
                .where(ContentCreatorTier.guild_id == interaction.guild_id)
                .order_by(ContentCreatorTier.required_followers.asc())
            )
            tiers = res.scalars().all()

        if not tiers:
            return await interaction.response.send_message(
                embed=info_embed("CC Tiers", "No CC tiers configured. Admins can run `/cc config_tier` to set up tiers."),
                ephemeral=True
            )

        embed = ego_embed(title="🎥 Content Creator Verification Tiers", color=INFO_COLOR)
        for t in tiers:
            role = interaction.guild.get_role(t.role_id) if t.role_id else None
            embed.add_field(
                name=f"⭐ {t.tier_name.title()}",
                value=f"• Followers: `{t.required_followers:,}`\n• Views: `{t.required_views:,}`\n• Role: {role.mention if role else '*Not set*'}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(ContentCreatorCog(bot))
