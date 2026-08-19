"""
Welcome System Cog for Ego Bot
"""
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import WelcomeConfig
from utils.permissions import is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import logger

def format_welcome_string(template: str, member: discord.Member) -> str:
    """Format template with member placeholders."""
    return template.format(
        user=member.name,
        mention=member.mention,
        membercount=member.guild.member_count,
        server=member.guild.name,
        server_id=member.guild.id
    )

class WelcomeCog(commands.Cog, name="Welcome"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == member.guild.id))
            cfg = res.scalar_one_or_none()

            if not cfg or not cfg.enabled:
                return

            # Guild Channel Message
            if cfg.channel_id:
                channel = member.guild.get_channel(cfg.channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        title = format_welcome_string(cfg.title or "Welcome to {server}!", member)
                        desc = format_welcome_string(cfg.message or "Welcome {user}!", member)
                        embed = ego_embed(title=title, description=desc, color=cfg.embed_color or 0x5865F2)
                        embed.set_thumbnail(url=member.display_avatar.url)
                        await channel.send(content=member.mention, embed=embed)
                    except Exception as e:
                        logger.error(f"Failed to send welcome message in guild {member.guild.id}: {e}")

            # Optional DM
            if cfg.dm_enabled and cfg.dm_message:
                try:
                    dm_text = format_welcome_string(cfg.dm_message, member)
                    dm_embed = ego_embed(
                        title=f"Welcome to {member.guild.name}!",
                        description=dm_text,
                        color=cfg.embed_color or 0x5865F2
                    )
                    if member.guild.icon:
                        dm_embed.set_thumbnail(url=member.guild.icon.url)
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    pass # User has DMs closed
                except Exception as e:
                    logger.debug(f"Could not send welcome DM to user {member.id}: {e}")

    welcome_group = app_commands.Group(
        name="welcome",
        description="Configure welcome messages and DMs",
        default_permissions=discord.Permissions(administrator=True)
    )

    @welcome_group.command(name="setup", description="Configure welcome channel and message template")
    @app_commands.describe(
        channel="Channel to send welcome messages in",
        title="Embed title ({user}, {server}, {membercount})",
        message="Embed message body ({user}, {mention}, {server}, {membercount})",
        color="Hex color (e.g. #5865F2)",
        dm_enabled="Send a welcome direct message to joining users",
        dm_message="Message content for DM"
    )
    @is_admin_or_has_role()
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: Optional[str] = "Welcome to {server}!",
        message: Optional[str] = "Hey {mention}, welcome! You are member #{membercount}.",
        color: Optional[str] = "#5865F2",
        dm_enabled: Optional[bool] = False,
        dm_message: Optional[str] = "Welcome to {server}! Make sure to read the rules."
    ):
        try:
            embed_color = int(color.lstrip("#"), 16) if color else 0x5865F2
        except ValueError:
            embed_color = 0x5865F2

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

        await interaction.response.send_message(
            embed=success_embed(
                "Welcome Setup Complete",
                f"✅ Welcome messages active in {channel.mention}.\n"
                f"DM Welcome: `{'Enabled' if dm_enabled else 'Disabled'}`\n\n"
                f"**Placeholders:** `{{user}}`, `{{mention}}`, `{{server}}`, `{{membercount}}`"
            )
        )
        await log_action(
            interaction.guild,
            title="Welcome System Configured",
            description=f"Channel: {channel.mention} | DM Enabled: {dm_enabled}",
            moderator=interaction.user
        )

    @welcome_group.command(name="preview", description="Preview the current welcome embed")
    @is_admin_or_has_role()
    async def welcome_preview(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                return await interaction.response.send_message(
                    embed=error_embed("Not Configured", "Welcome system is not configured yet. Run `/welcome setup`."),
                    ephemeral=True
                )

            member = interaction.user
            title = format_welcome_string(cfg.title or "Welcome to {server}!", member)
            desc = format_welcome_string(cfg.message or "Welcome {user}!", member)
            embed = ego_embed(title=f"👀 Preview: {title}", description=desc, color=cfg.embed_color or 0x5865F2)
            embed.set_thumbnail(url=member.display_avatar.url)

            await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="toggle", description="Enable or disable the welcome system")
    @app_commands.describe(enabled="Enable (True) or Disable (False)")
    @is_admin_or_has_role()
    async def welcome_toggle(self, interaction: discord.Interaction, enabled: bool):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = WelcomeConfig(guild_id=interaction.guild_id, enabled=enabled)
                session.add(cfg)
            else:
                cfg.enabled = enabled
            await session.commit()

        status_text = "Enabled" if enabled else "Disabled"
        await interaction.response.send_message(
            embed=success_embed("Welcome System Updated", f"Welcome system is now **{status_text}**.")
        )
        await log_action(
            interaction.guild,
            title=f"Welcome System {status_text}",
            description=f"Status set to {status_text}",
            moderator=interaction.user
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
