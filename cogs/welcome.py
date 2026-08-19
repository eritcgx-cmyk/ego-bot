"""
Comprehensive Welcome & Leave (Goodbye) System Cog for Ego Bot with Server Banner & Presets.
Features:
- Dedicated preset templates for Welcome & Goodbye cards
- Embedded Server Banner (Defaults to official server banner)
- Dynamic inviter & invite count resolution ({inviter}, {invites_count})
- Preset selector & live test commands
"""
import os
import json
from typing import Optional, Tuple, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import WelcomeConfig, UserInviteStat
from utils.permissions import is_admin_or_has_role
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed,
    COLOR_VIOLET, COLOR_CRIMSON, COLOR_EMERALD, COLOR_AMBER, COLOR_CYAN, get_eastern_time
)
from utils.logger import log_action
from config import logger

# Official Server Banner URL
DEFAULT_BANNER_URL = "https://cdn.discordapp.com/banners/1539142640891732051/106d651a4f8b37b596c2c29a1a612239.webp?size=480"

WELCOME_PRESETS: Dict[str, Dict[str, Any]] = {
    "standard": {
        "title": "✦ Welcome to {server}!",
        "message": (
            "> Hey {mention}, welcome to **{server}**!\n"
            "> You were invited by **{inviter}**, who now has **`{invites_count}`** invites.\n"
            "> Server Member Count: **`#{membercount}`**"
        ),
        "color": 0x8B5CF6
    },
    "compact": {
        "title": "👋 Welcome {user}!",
        "message": "Welcome {mention} to **{server}**! Invited by **{inviter}** (`{invites_count}` invites). Member **#{membercount}**.",
        "color": 0x3B82F6
    },
    "aesthetic": {
        "title": "👑 Welcome to {server} • {user}",
        "message": (
            "╭✦ **New Member Arrival**\n"
            "┊ › **User:** {mention} (`{user}`)\n"
            "┊ › **Invited By:** {inviter} (`{invites_count}` total)\n"
            "┊ › **Server Roster:** `#{membercount}`\n"
            "╰✦ Make sure to verify in <#1539142640891732051>!"
        ),
        "color": 0xEC4899
    }
}

LEAVE_PRESETS: Dict[str, Dict[str, Any]] = {
    "standard": {
        "title": "✦ Member Left • {server}",
        "message": (
            "> **{user}** (`{mention}`) has left the server.\n"
            "> They were invited by **{inviter}** (now has **`{invites_count}`** invites).\n"
            "> Remaining Members: **`#{membercount}`**"
        ),
        "color": 0xEF4444
    },
    "compact": {
        "title": "👋 Goodbye {user}",
        "message": "**{user}** left **{server}**. Invited by **{inviter}** (now `{invites_count}`). `{membercount}` members remaining.",
        "color": 0xF97316
    },
    "aesthetic": {
        "title": "🥀 Member Departure • {server}",
        "message": (
            "╭✦ **Departure Log**\n"
            "┊ › **User:** `{user}`\n"
            "┊ › **Original Inviter:** {inviter} (`{invites_count}` left)\n"
            "╰✦ **Remaining Roster:** `{membercount}` members"
        ),
        "color": 0x991B1B
    }
}

def format_welcome_string(
    template: str,
    member: discord.Member,
    inviter: Optional[discord.Member | discord.User] = None,
    invites_count: int = 0
) -> str:
    """Format template with member, server, and dynamic inviter placeholders."""
    inviter_str = inviter.mention if inviter else "Direct / Vanity Invite"
    inviter_name = inviter.display_name if inviter else "Direct / Vanity"
    vanity_code = getattr(member.guild, "vanity_url_code", None) or "Direct"

    replacements = {
        "{user}": member.name,
        "{mention}": member.mention,
        "{membercount}": str(member.guild.member_count),
        "{server}": member.guild.name,
        "{server_id}": str(member.guild.id),
        "{inviter}": inviter_str,
        "{inviter_name}": inviter_name,
        "{invites_count}": str(invites_count),
        "{vanity}": vanity_code
    }
    result = template
    for key, val in replacements.items():
        result = result.replace(key, val)
    return result


class WelcomeCog(commands.Cog, name="Welcome"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _resolve_inviter_info(self, member: discord.Member) -> Tuple[Optional[discord.User | discord.Member], int]:
        """Resolves the inviter and their current total invite count for a member."""
        guild = member.guild
        inviter = None
        invites_count = 0

        try:
            inviters_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "member_inviters.json")
            if os.path.exists(inviters_file):
                with open(inviters_file, "r", encoding="utf-8") as f:
                    inv_map = json.load(f)
                inv_id = inv_map.get(f"{guild.id}_{member.id}")
                if inv_id:
                    inviter = guild.get_member(inv_id) or await self.bot.fetch_user(inv_id)
        except Exception:
            pass

        if inviter:
            try:
                async with AsyncSessionLocal() as session:
                    res = await session.execute(
                        select(UserInviteStat).where(
                            UserInviteStat.guild_id == guild.id,
                            UserInviteStat.user_id == inviter.id
                        )
                    )
                    stat = res.scalar_one_or_none()
                    if stat:
                        invites_count = stat.total
            except Exception:
                pass

        return inviter, invites_count

    def _build_welcome_embed(
        self,
        member: discord.Member,
        title_tmpl: str,
        msg_tmpl: str,
        color_val: int,
        inviter: Optional[discord.Member | discord.User] = None,
        invites_count: int = 0
    ) -> discord.Embed:
        """Constructs an aesthetic welcome embed featuring the official server banner and avatar."""
        title = format_welcome_string(title_tmpl, member, inviter, invites_count)
        description = format_welcome_string(msg_tmpl, member, inviter, invites_count)

        embed = ego_embed(
            title=title,
            description=description,
            color=color_val or COLOR_VIOLET
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        # Set Server Banner (Guild banner, splash, or fallback official banner)
        guild = member.guild
        banner_url = (guild.banner.url if guild.banner else None) or (guild.splash.url if guild.splash else None) or DEFAULT_BANNER_URL
        embed.set_image(url=banner_url)

        embed.set_footer(
            text=f"{guild.name} • Member #{guild.member_count} • {get_eastern_time()}",
            icon_url=guild.icon.url if guild.icon else None
        )
        return embed

    def _build_leave_embed(
        self,
        member: discord.Member,
        title_tmpl: str,
        msg_tmpl: str,
        color_val: int,
        inviter: Optional[discord.Member | discord.User] = None,
        invites_count: int = 0
    ) -> discord.Embed:
        """Constructs an aesthetic leave/goodbye embed with banner."""
        title = format_welcome_string(title_tmpl, member, inviter, invites_count)
        description = format_welcome_string(msg_tmpl, member, inviter, invites_count)

        embed = ego_embed(
            title=title,
            description=description,
            color=color_val or COLOR_CRIMSON
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        guild = member.guild
        banner_url = (guild.banner.url if guild.banner else None) or (guild.splash.url if guild.splash else None) or DEFAULT_BANNER_URL
        embed.set_image(url=banner_url)

        embed.set_footer(
            text=f"{guild.name} • {guild.member_count} Members Remaining • {get_eastern_time()}",
            icon_url=guild.icon.url if guild.icon else None
        )
        return embed

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == member.guild.id))
            cfg = res.scalar_one_or_none()

            if not cfg or not cfg.enabled:
                return

            inviter, invites_count = await self._resolve_inviter_info(member)

            # Guild Channel Welcome Message
            if cfg.channel_id:
                channel = member.guild.get_channel(cfg.channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        title_tmpl = cfg.title or WELCOME_PRESETS["standard"]["title"]
                        msg_tmpl = cfg.message or WELCOME_PRESETS["standard"]["message"]
                        color_val = cfg.embed_color or WELCOME_PRESETS["standard"]["color"]

                        embed = self._build_welcome_embed(member, title_tmpl, msg_tmpl, color_val, inviter, invites_count)
                        await channel.send(content=member.mention, embed=embed)
                    except Exception as e:
                        logger.error(f"Failed to send welcome message in guild {member.guild.id}: {e}")

            # Optional Welcome Direct Message
            if cfg.dm_enabled and cfg.dm_message:
                try:
                    dm_text = format_welcome_string(cfg.dm_message, member, inviter, invites_count)
                    dm_embed = ego_embed(
                        title=f"Welcome to {member.guild.name}!",
                        description=dm_text,
                        color=cfg.embed_color or 0x8B5CF6
                    )
                    if member.guild.icon:
                        dm_embed.set_thumbnail(url=member.guild.icon.url)
                    dm_embed.set_image(url=DEFAULT_BANNER_URL)
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    pass
                except Exception as e:
                    logger.debug(f"Could not send welcome DM to user {member.id}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == member.guild.id))
            cfg = res.scalar_one_or_none()

            if not cfg or not getattr(cfg, "leave_enabled", False):
                return

            leave_ch_id = getattr(cfg, "leave_channel_id", None) or cfg.channel_id
            if not leave_ch_id:
                return

            channel = member.guild.get_channel(leave_ch_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            inviter, invites_count = await self._resolve_inviter_info(member)
            title_tmpl = getattr(cfg, "leave_title", None) or LEAVE_PRESETS["standard"]["title"]
            msg_tmpl = getattr(cfg, "leave_message", None) or LEAVE_PRESETS["standard"]["message"]
            color_val = getattr(cfg, "leave_color", None) or LEAVE_PRESETS["standard"]["color"]

            try:
                embed = self._build_leave_embed(member, title_tmpl, msg_tmpl, color_val, inviter, invites_count)
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send leave message in guild {member.guild.id}: {e}")

    # =========================================================================
    # WELCOME & GOODBYE ADMINISTRATIVE GROUP (/welcome)
    # =========================================================================
    welcome_group = app_commands.Group(
        name="welcome",
        description="Configure automated server welcome, leave cards, banners, and inviter tracking",
        default_permissions=discord.Permissions(administrator=True)
    )

    @welcome_group.command(name="setup", description="Configure welcome channel and message template")
    @app_commands.describe(
        channel="Channel to send welcome embeds in",
        title="Embed title ({user}, {server}, {membercount}, {inviter}, {invites_count})",
        message="Embed message body ({mention}, {server}, {membercount}, {inviter}, {invites_count})",
        color="Hex color (e.g. #8B5CF6)",
        dm_enabled="Send a welcome direct message to joining users",
        dm_message="Message content for direct message"
    )
    @is_admin_or_has_role()
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: Optional[str] = WELCOME_PRESETS["standard"]["title"],
        message: Optional[str] = WELCOME_PRESETS["standard"]["message"],
        color: Optional[str] = "#8B5CF6",
        dm_enabled: Optional[bool] = False,
        dm_message: Optional[str] = "Welcome to {server}! Be sure to review our rules and verify."
    ):
        try:
            embed_color = int(color.lstrip("#"), 16) if color else 0x8B5CF6
        except ValueError:
            embed_color = 0x8B5CF6

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = WelcomeConfig(guild_id=interaction.guild_id)
                session.add(cfg)

            cfg.enabled = True
            cfg.channel_id = channel.id
            cfg.title = title
            cfg.message = message
            cfg.embed_color = embed_color
            cfg.dm_enabled = dm_enabled or False
            cfg.dm_message = dm_message
            await session.commit()

        sample_embed = self._build_welcome_embed(
            interaction.user,
            title or WELCOME_PRESETS["standard"]["title"],
            message or WELCOME_PRESETS["standard"]["message"],
            embed_color,
            inviter=interaction.user,
            invites_count=5
        )

        await interaction.response.send_message(
            content="✅ **Welcome System Configured!** Live preview with Server Banner:",
            embed=sample_embed
        )

    @welcome_group.command(name="leave_setup", description="Configure leave / goodbye channel and message template")
    @app_commands.describe(
        channel="Channel to send leave/goodbye cards in",
        title="Leave embed title ({user}, {server}, {membercount})",
        message="Leave embed body ({user}, {mention}, {server}, {inviter}, {invites_count})",
        color="Hex color code (e.g. #EF4444)",
        enabled="Enable or disable leave messages"
    )
    @is_admin_or_has_role()
    async def welcome_leave_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: Optional[str] = LEAVE_PRESETS["standard"]["title"],
        message: Optional[str] = LEAVE_PRESETS["standard"]["message"],
        color: Optional[str] = "#EF4444",
        enabled: Optional[bool] = True
    ):
        try:
            embed_color = int(color.lstrip("#"), 16) if color else COLOR_CRIMSON
        except ValueError:
            embed_color = COLOR_CRIMSON

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = WelcomeConfig(guild_id=interaction.guild_id)
                session.add(cfg)

            cfg.leave_enabled = enabled if enabled is not None else True
            cfg.leave_channel_id = channel.id
            cfg.leave_title = title or LEAVE_PRESETS["standard"]["title"]
            cfg.leave_message = message or LEAVE_PRESETS["standard"]["message"]
            cfg.leave_color = embed_color
            await session.commit()

        sample_embed = self._build_leave_embed(
            interaction.user,
            title or LEAVE_PRESETS["standard"]["title"],
            message or LEAVE_PRESETS["standard"]["message"],
            embed_color,
            inviter=interaction.user,
            invites_count=4
        )

        await interaction.response.send_message(
            content="✅ **Leave / Goodbye System Configured!** Live preview with Server Banner:",
            embed=sample_embed
        )

    @welcome_group.command(name="apply_preset", description="Apply an aesthetic built-in preset to Welcome and Leave cards")
    @app_commands.describe(preset="Preset style to apply (standard, compact, aesthetic)")
    @app_commands.choices(preset=[
        app_commands.Choice(name="Standard (Ego Invite Tracker + Banner)", value="standard"),
        app_commands.Choice(name="Compact (2-Line Minimal)", value="compact"),
        app_commands.Choice(name="Aesthetic (Framed Box Style)", value="aesthetic")
    ])
    @is_admin_or_has_role()
    async def welcome_apply_preset(self, interaction: discord.Interaction, preset: app_commands.Choice[str]):
        p_name = preset.value
        w_preset = WELCOME_PRESETS.get(p_name, WELCOME_PRESETS["standard"])
        l_preset = LEAVE_PRESETS.get(p_name, LEAVE_PRESETS["standard"])

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = WelcomeConfig(guild_id=interaction.guild_id)
                session.add(cfg)

            cfg.title = w_preset["title"]
            cfg.message = w_preset["message"]
            cfg.embed_color = w_preset["color"]
            cfg.leave_title = l_preset["title"]
            cfg.leave_message = l_preset["message"]
            cfg.leave_color = l_preset["color"]
            await session.commit()

        w_embed = self._build_welcome_embed(interaction.user, w_preset["title"], w_preset["message"], w_preset["color"], inviter=interaction.user, invites_count=5)

        await interaction.response.send_message(
            content=f"✅ Applied **{preset.name}** preset to Welcome & Leave cards!\nLive Welcome Preview:",
            embed=w_embed
        )

    @welcome_group.command(name="preview", description="Preview current welcome and leave embed designs")
    @is_admin_or_has_role()
    async def welcome_preview(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

        if not cfg:
            return await interaction.response.send_message(
                embed=info_embed("Not Configured", "Welcome system is not configured yet. Run `/welcome setup`."),
                ephemeral=True
            )

        title_tmpl = cfg.title or WELCOME_PRESETS["standard"]["title"]
        msg_tmpl = cfg.message or WELCOME_PRESETS["standard"]["message"]
        color_val = cfg.embed_color or WELCOME_PRESETS["standard"]["color"]

        w_embed = self._build_welcome_embed(interaction.user, title_tmpl, msg_tmpl, color_val, inviter=interaction.user, invites_count=3)
        await interaction.response.send_message(embed=w_embed, ephemeral=True)

    @welcome_group.command(name="toggle", description="Enable or disable the welcome and leave systems")
    @app_commands.describe(welcome_enabled="Enable Welcome messages", leave_enabled="Enable Leave messages")
    @is_admin_or_has_role()
    async def welcome_toggle(self, interaction: discord.Interaction, welcome_enabled: Optional[bool] = None, leave_enabled: Optional[bool] = None):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                return await interaction.response.send_message(embed=error_embed("Not Configured", "Please run `/welcome setup` first."), ephemeral=True)

            if welcome_enabled is not None:
                cfg.enabled = welcome_enabled
            if leave_enabled is not None:
                cfg.leave_enabled = leave_enabled
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed(
                "Welcome/Leave Updated",
                f"• Welcome Messages: **{'Enabled' if cfg.enabled else 'Disabled'}**\n"
                f"• Leave Messages: **{'Enabled' if cfg.leave_enabled else 'Disabled'}**"
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
