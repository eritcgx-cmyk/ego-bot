"""
Aesthetic & Humanized Embed Builder for Ego Bot.
Features modern typography, rich colors, and clean layout patterns.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import discord

# Curated Aesthetic Palette
COLOR_OBSIDIAN = 0x18181B   # Sleek Dark
COLOR_VIOLET   = 0x8B5CF6   # Electric Violet / Brand Primary
COLOR_EMERALD  = 0x10B981   # Clean Success Mint
COLOR_CRIMSON  = 0xF43F5E   # Rose / Alert Red
COLOR_AMBER    = 0xF59E0B   # Warm Warning
COLOR_CYAN     = 0x06B6D4   # Neon Cyan
COLOR_ROSE     = 0xFB7185   # Soft Aesthetic Pink
COLOR_INDIGO   = 0x6366F1   # Indigo Blue

def ego_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: int = COLOR_VIOLET,
    thumbnail_url: Optional[str] = None,
    image_url: Optional[str] = None,
    footer_text: Optional[str] = None,
    timestamp: bool = True
) -> discord.Embed:
    """Builds a sleek modern Discord embed with humanized branding."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    if timestamp:
        embed.timestamp = datetime.utcnow()
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    if image_url:
        embed.set_image(url=image_url)

    footer = footer_text or "ego • sovereign community engine"
    embed.set_footer(text=footer)
    return embed

def success_embed(title: str, description: str, **kwargs) -> discord.Embed:
    """Aesthetic emerald success notification."""
    return ego_embed(
        title=f"✦ {title}",
        description=f"> {description}",
        color=COLOR_EMERALD,
        **kwargs
    )

def error_embed(title: str, description: str, tip: Optional[str] = None, **kwargs) -> discord.Embed:
    """Aesthetic rose/crimson error notification with friendly tip."""
    desc = f"> {description}"
    if tip:
        desc += f"\n\n💡 **Tip:** *{tip}*"
    return ego_embed(
        title=f"✖ {title}",
        description=desc,
        color=COLOR_CRIMSON,
        **kwargs
    )

def warning_embed(title: str, description: str, **kwargs) -> discord.Embed:
    """Aesthetic amber warning notification."""
    return ego_embed(
        title=f"▲ {title}",
        description=f"> {description}",
        color=COLOR_AMBER,
        **kwargs
    )

def info_embed(title: str, description: str, **kwargs) -> discord.Embed:
    """Aesthetic violet/cyan informative notification."""
    return ego_embed(
        title=f"◆ {title}",
        description=description,
        color=COLOR_CYAN,
        **kwargs
    )

def card_embed(title: str, fields: List[tuple], color: int = COLOR_VIOLET, description: Optional[str] = None, **kwargs) -> discord.Embed:
    """Multi-field structured card with neat alignment."""
    embed = ego_embed(title=title, description=description, color=color, **kwargs)
    for name, val, inline in fields:
        embed.add_field(name=f"› {name}", value=val, inline=inline)
    return embed
