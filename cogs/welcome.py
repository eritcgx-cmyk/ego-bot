"""
100x Redesigned Ultra-Aesthetic Welcome & Leave (Goodbye) Engine for Ego Bot.
Features:
- Dynamic Inviter & Invite Count tracking on Join and Leave ({inviter}, {invites_count})
- Official Server Banner auto-embedding with fallback
- Auto-Role on join support (@Unverified / @Member)
- Built-in Curated Presets: Standard Ego, Framed Box Aesthetic, and Compact Minimal
- Live Testing commands (/welcome test join | leave) and Instant Previews (/welcome preview)
- Instant Master State Auto-Persistence & SQLite sync
"""
import os
import json
from datetime import datetime, timezone
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
            "> Welcome {mention} to **{server}**!\n"
            "> You were invited by **{inviter}**, who now has **`{invites_count}`** invites.\n"
            "> Server Member Count: **`#{membercount}`**"
        ),
        "color": 0x8B5CF6
    },
    "aesthetic": {
        "title": "👑 New Member Arrival • {server}",
        "message": (
            "╭✦ **Welcome to the Server**\n"
            "┊ › **User:** {mention} (`{user}`)\n"
            "┊ › **Invited By:** {inviter} (`{invites_count}` total)\n"
            "┊ › **Member Count:** `#{membercount}`\n"
            "╰✦ Make sure to complete verification in <#1539142640891732051>!"
        ),
        "color": 0xEC4899
    },
    "compact": {
        "title": "👋 Welcome {user}!",
        "message": "Welcome {mention} to **{server}**! Invited by **{inviter}** (`{invites_count}` invites). Member **#{membercount}**.",
        "color": 0x3B82F6
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
    "aesthetic": {
        "title": "🥀 Member Departure • {server}",
        "message": (
            "╭✦ **Departure Notice**\n"
            "┊ › **Member:** `{user}`\n"
            "┊ › **Original Inviter:** {inviter} (`{invites_count}` invites remaining)\n"
            "╰✦ **Remaining Roster:** `{membercount}` members"
        ),
        "color": 0x991B1B
    },
    "compact": {
        "title": "👋 Goodbye {user}",
        "message": "**{user}** left **{server}**. Invited by **{inviter}** (now `{invites_count}`). `{membercount}` members remaining.",
        "color": 0xF97316
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
            from utils.kv_store import get_cached_kv
            inv_map = get_cached_kv("member_inviters") or {}
            inv_id = inv_map.get(f"{guild.id}_{member.id}")
            if inv_id:
                inviter = guild.get_member(inv_id)
                if not inviter:
                    try:
                        inviter = await self.bot.fetch_user(inv_id)
                    except Exception:
                        inviter = None
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

        # Set Server Banner (Guild banner, splash, or official preset banner)
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

    def _get_target_welcome_channel(self, guild: discord.Guild, configured_id: Optional[int]) -> Optional[discord.TextChannel]:
        """Resolves the best welcome text channel with automatic name fallback."""
        if configured_id and configured_id != guild.id:
            ch = guild.get_channel(configured_id)
            if ch and isinstance(ch, discord.TextChannel):
                return ch

        for name in ["welc", "welcome", "joins", "arrivals", "gen", "general"]:
            found = discord.utils.find(lambda c: c.name.lower() == name and isinstance(c, discord.TextChannel), guild.channels)
            if found:
                return found

        if guild.system_channel:
            return guild.system_channel
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                return ch
        return None

    def _get_target_leave_channel(self, guild: discord.Guild, configured_id: Optional[int]) -> Optional[discord.TextChannel]:
        """Resolves the best leave/goodbye text channel with automatic name fallback."""
        if configured_id and configured_id != guild.id:
            ch = guild.get_channel(configured_id)
            if ch and isinstance(ch, discord.TextChannel):
                return ch

        for name in ["welc", "welcome", "leave", "goodbye", "gen", "general"]:
            found = discord.utils.find(lambda c: c.name.lower() == name and isinstance(c, discord.TextChannel), guild.channels)
            if found:
                return found

        if guild.system_channel:
            return guild.system_channel
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                return ch
        return None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == member.guild.id))
            cfg = res.scalar_one_or_none()

            if not cfg or not cfg.enabled:
                return

            # Auto-Role Assignment
            if cfg.auto_role_id:
                auto_r = member.guild.get_role(cfg.auto_role_id)
                if auto_r:
                    try:
                        await member.add_roles(auto_r, reason="Ego Welcome Auto-Role")
                    except Exception as e:
                        logger.debug(f"Could not assign auto-role: {e}")

            inviter, invites_count = await self._resolve_inviter_info(member)

            # Guild Channel Welcome Message
            target_ch = self._get_target_welcome_channel(member.guild, cfg.channel_id)
            if target_ch:
                try:
                    title_tmpl = cfg.title or WELCOME_PRESETS["standard"]["title"]
                    msg_tmpl = cfg.message or WELCOME_PRESETS["standard"]["message"]
                    color_val = cfg.embed_color or WELCOME_PRESETS["standard"]["color"]

                    embed = self._build_welcome_embed(member, title_tmpl, msg_tmpl, color_val, inviter, invites_count)
                    await target_ch.send(content=member.mention, embed=embed)
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
                except Exception:
                    pass

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
            target_ch = self._get_target_leave_channel(member.guild, leave_ch_id)
            if not target_ch:
                return

            inviter, invites_count = await self._resolve_inviter_info(member)
            title_tmpl = getattr(cfg, "leave_title", None) or LEAVE_PRESETS["standard"]["title"]
            msg_tmpl = getattr(cfg, "leave_message", None) or LEAVE_PRESETS["standard"]["message"]
            color_val = getattr(cfg, "leave_color", None) or LEAVE_PRESETS["standard"]["color"]

            try:
                embed = self._build_leave_embed(member, title_tmpl, msg_tmpl, color_val, inviter, invites_count)
                await target_ch.send(embed=embed)
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

    @welcome_group.command(name="setup", description="Configure welcome channel, message template, and auto-role")
    @app_commands.describe(
        channel="Channel to send welcome embeds in",
        title="Embed title ({user}, {server}, {membercount}, {inviter}, {invites_count})",
        message="Embed message body ({mention}, {server}, {membercount}, {inviter}, {invites_count})",
        color="Hex color (e.g. #8B5CF6)",
        auto_role="Optional role automatically given to new members",
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
        auto_role: Optional[discord.Role] = None,
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
            cfg.auto_role_id = auto_role.id if auto_role else None
            cfg.dm_enabled = dm_enabled or False
            cfg.dm_message = dm_message
            await session.commit()

        try:
            from utils.state_manager import update_guild_state_section
            update_guild_state_section(interaction.guild_id, "welcome", {
                "enabled": True,
                "channel_id": channel.id,
                "title": title,
                "message": message,
                "embed_color": embed_color,
                "auto_role_id": auto_role.id if auto_role else None,
                "dm_enabled": dm_enabled or False,
                "dm_message": dm_message,
                "leave_enabled": getattr(cfg, "leave_enabled", True),
                "leave_channel_id": getattr(cfg, "leave_channel_id", channel.id),
                "leave_title": getattr(cfg, "leave_title", None),
                "leave_message": getattr(cfg, "leave_message", None),
                "leave_color": getattr(cfg, "leave_color", 0xEF4444)
            })
        except Exception:
            pass

        sample_embed = self._build_welcome_embed(
            interaction.user,
            title or WELCOME_PRESETS["standard"]["title"],
            message or WELCOME_PRESETS["standard"]["message"],
            embed_color,
            inviter=interaction.user,
            invites_count=5
        )

        await interaction.response.send_message(
            content="✅ **Welcome System Configured & Saved!** Live preview with Server Banner:",
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

        try:
            from utils.state_manager import update_guild_state_section
            update_guild_state_section(interaction.guild_id, "welcome", {
                "enabled": getattr(cfg, "enabled", True),
                "channel_id": getattr(cfg, "channel_id", channel.id),
                "title": getattr(cfg, "title", None),
                "message": getattr(cfg, "message", None),
                "embed_color": getattr(cfg, "embed_color", 0x8B5CF6),
                "leave_enabled": enabled if enabled is not None else True,
                "leave_channel_id": channel.id,
                "leave_title": title or LEAVE_PRESETS["standard"]["title"],
                "leave_message": message or LEAVE_PRESETS["standard"]["message"],
                "leave_color": embed_color
            })
        except Exception:
            pass

        sample_embed = self._build_leave_embed(
            interaction.user,
            title or LEAVE_PRESETS["standard"]["title"],
            message or LEAVE_PRESETS["standard"]["message"],
            embed_color,
            inviter=interaction.user,
            invites_count=4
        )

        await interaction.response.send_message(
            content="✅ **Leave / Goodbye System Configured & Saved!** Live preview with Server Banner:",
            embed=sample_embed
        )

    @welcome_group.command(name="apply_preset", description="Apply an aesthetic built-in preset to Welcome and Leave cards")
    @app_commands.describe(preset="Preset style to apply (standard, aesthetic, compact)")
    @app_commands.choices(preset=[
        app_commands.Choice(name="Standard (Ego Dynamic Inviter + Banner)", value="standard"),
        app_commands.Choice(name="Aesthetic (Framed Box Style)", value="aesthetic"),
        app_commands.Choice(name="Compact (2-Line Minimal)", value="compact")
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

        try:
            from utils.state_manager import update_guild_state_section
            update_guild_state_section(interaction.guild_id, "welcome", {
                "title": w_preset["title"],
                "message": w_preset["message"],
                "embed_color": w_preset["color"],
                "leave_title": l_preset["title"],
                "leave_message": l_preset["message"],
                "leave_color": l_preset["color"]
            })
        except Exception:
            pass

        w_embed = self._build_welcome_embed(
            interaction.user,
            w_preset["title"],
            w_preset["message"],
            w_preset["color"],
            inviter=interaction.user,
            invites_count=5
        )

        await interaction.response.send_message(
            content=f"✅ Applied **{preset.name}** preset to Welcome & Leave cards!\nLive Welcome Preview:",
            embed=w_embed
        )

    @welcome_group.command(name="test", description="Send a live test welcome or leave card to the configured channel")
    @app_commands.describe(event_type="Select test card to dispatch (join or leave)")
    @app_commands.choices(event_type=[
        app_commands.Choice(name="Welcome Card (Member Join)", value="join"),
        app_commands.Choice(name="Goodbye Card (Member Leave)", value="leave")
    ])
    @is_admin_or_has_role()
    async def welcome_test(self, interaction: discord.Interaction, event_type: app_commands.Choice[str]):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

        if not cfg:
            return await interaction.response.send_message(
                embed=error_embed("Not Configured", "Please run `/welcome setup` before running test dispatches."),
                ephemeral=True
            )

        if event_type.value == "join":
            ch_id = cfg.channel_id
            if not ch_id:
                return await interaction.response.send_message("❌ Welcome channel is not set.", ephemeral=True)
            ch = interaction.guild.get_channel(ch_id)
            if not ch:
                return await interaction.response.send_message("❌ Welcome channel not found.", ephemeral=True)

            embed = self._build_welcome_embed(
                interaction.user,
                cfg.title or WELCOME_PRESETS["standard"]["title"],
                cfg.message or WELCOME_PRESETS["standard"]["message"],
                cfg.embed_color or 0x8B5CF6,
                inviter=interaction.user,
                invites_count=7
            )
            await ch.send(content=interaction.user.mention, embed=embed)
            await interaction.response.send_message(f"✅ Dispatched test Welcome Card to {ch.mention}!", ephemeral=True)

        elif event_type.value == "leave":
            ch_id = getattr(cfg, "leave_channel_id", None) or cfg.channel_id
            if not ch_id:
                return await interaction.response.send_message("❌ Leave channel is not set.", ephemeral=True)
            ch = interaction.guild.get_channel(ch_id)
            if not ch:
                return await interaction.response.send_message("❌ Leave channel not found.", ephemeral=True)

            embed = self._build_leave_embed(
                interaction.user,
                getattr(cfg, "leave_title", None) or LEAVE_PRESETS["standard"]["title"],
                getattr(cfg, "leave_message", None) or LEAVE_PRESETS["standard"]["message"],
                getattr(cfg, "leave_color", None) or COLOR_CRIMSON,
                inviter=interaction.user,
                invites_count=6
            )
            await ch.send(embed=embed)
            await interaction.response.send_message(f"✅ Dispatched test Leave Card to {ch.mention}!", ephemeral=True)

    @welcome_group.command(name="preview", description="Preview current welcome and leave embed designs")
    @is_admin_or_has_role()
    async def welcome_preview(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

        title_tmpl = (cfg.title if cfg else None) or WELCOME_PRESETS["standard"]["title"]
        msg_tmpl = (cfg.message if cfg else None) or WELCOME_PRESETS["standard"]["message"]
        color_val = (cfg.embed_color if cfg else None) or WELCOME_PRESETS["standard"]["color"]

        w_embed = self._build_welcome_embed(interaction.user, title_tmpl, msg_tmpl, color_val, inviter=interaction.user, invites_count=5)

        l_title = getattr(cfg, "leave_title", None) if cfg else None or LEAVE_PRESETS["standard"]["title"]
        l_msg = getattr(cfg, "leave_message", None) if cfg else None or LEAVE_PRESETS["standard"]["message"]
        l_color = getattr(cfg, "leave_color", None) if cfg else None or LEAVE_PRESETS["standard"]["color"]
        l_embed = self._build_leave_embed(interaction.user, l_title, l_msg, l_color, inviter=interaction.user, invites_count=4)

        await interaction.response.send_message(
            content="✦ **Welcome & Leave Live Previews:**",
            embeds=[w_embed, l_embed],
            ephemeral=True
        )

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

        try:
            from utils.state_manager import update_guild_state_section
            update_guild_state_section(interaction.guild_id, "welcome", {
                "enabled": cfg.enabled,
                "leave_enabled": cfg.leave_enabled
            })
        except Exception:
            pass

        await interaction.response.send_message(
            embed=success_embed(
                "Welcome/Leave Updated",
                f"• Welcome Messages: **{'Enabled' if cfg.enabled else 'Disabled'}**\n"
                f"• Leave Messages: **{'Enabled' if cfg.leave_enabled else 'Disabled'}**"
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
