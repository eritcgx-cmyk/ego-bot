"""
Standard Embed builders for consistent UI across Ego bot.
"""
from typing import Optional
from datetime import datetime
import discord
from config import EMBED_COLOR, SUCCESS_COLOR, ERROR_COLOR, WARNING_COLOR, INFO_COLOR

def ego_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: int = EMBED_COLOR,
    timestamp: bool = True
) -> discord.Embed:
    """Create a standard styled Ego embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    if timestamp:
        embed.timestamp = datetime.utcnow()
    embed.set_footer(text="Ego • Production System", icon_url=None)
    return embed

def success_embed(title: str, description: str) -> discord.Embed:
    """Create a green success embed."""
    return ego_embed(
        title=f"✅ {title}",
        description=description,
        color=SUCCESS_COLOR
    )

def error_embed(title: str, description: str) -> discord.Embed:
    """Create a red error embed."""
    return ego_embed(
        title=f"❌ {title}",
        description=description,
        color=ERROR_COLOR
    )

def warning_embed(title: str, description: str) -> discord.Embed:
    """Create a yellow warning embed."""
    return ego_embed(
        title=f"⚠️ {title}",
        description=description,
        color=WARNING_COLOR
    )

def info_embed(title: str, description: str) -> discord.Embed:
    """Create a blue info embed."""
    return ego_embed(
        title=f"ℹ️ {title}",
        description=description,
        color=INFO_COLOR
    )
