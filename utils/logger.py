"""
Central Logging dispatcher for all administrative and automated actions.
"""
from typing import Optional
import discord
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import GuildConfig
from utils.embeds import ego_embed
from config import INFO_COLOR, WARNING_COLOR, ERROR_COLOR, logger

async def log_action(
    guild: discord.Guild,
    title: str,
    description: str,
    color: int = INFO_COLOR,
    fields: Optional[dict] = None,
    moderator: Optional[discord.Member | discord.User] = None
) -> None:
    """Dispatches an audit log embed to the configured mod-log channel."""
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild.id))
            cfg = res.scalar_one_or_none()

            if not cfg or not cfg.mod_log_channel_id:
                return

            channel = guild.get_channel(cfg.mod_log_channel_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            embed = ego_embed(title=f"📋 Audit Log: {title}", description=description, color=color)
            if moderator:
                embed.add_field(name="Actor", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)

            if fields:
                for k, v in fields.items():
                    embed.add_field(name=k, value=str(v), inline=True)

            await channel.send(embed=embed)
    except Exception as e:
        logger.error(f"Failed to log action to mod-log channel for guild {guild.id}: {e}")
