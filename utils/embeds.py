"""
Clean & Minimal Aesthetic Embed Builder for Ego Bot.
Features timezone-aware timestamps (EST / US Eastern Time) and sleek branding.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import zoneinfo
import discord

# Curated Palette
COLOR_OBSIDIAN = 0x18181B   # Sleek Dark
COLOR_VIOLET   = 0x8B5CF6   # Electric Violet / Brand Primary
COLOR_EMERALD  = 0x10B981   # Clean Success Mint
COLOR_CRIMSON  = 0xF43F5E   # Rose / Alert Red
COLOR_AMBER    = 0xF59E0B   # Warm Warning
COLOR_CYAN     = 0x06B6D4   # Neon Cyan
COLOR_ROSE     = 0xFB7185   # Soft Pink
COLOR_INDIGO   = 0x6366F1   # Indigo Blue

def get_eastern_time() -> datetime:
    """Returns the current Eastern Time (EST/EDT)."""
    try:
        return datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        return datetime.now(timezone.utc)

def ego_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: int = COLOR_VIOLET,
    thumbnail_url: Optional[str] = None,
    image_url: Optional[str] = None,
    footer_text: Optional[str] = None,
    timestamp: bool = True
) -> discord.Embed:
    """Builds a clean Discord embed with minimal branding and Eastern Time."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    if timestamp:
        # Timezone-aware UTC timestamp allows Discord to natively localize to user device (EST)
        embed.timestamp = datetime.now(timezone.utc)
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    if image_url:
        embed.set_image(url=image_url)

    est_now = get_eastern_time()
    est_str = est_now.strftime("%I:%M %p EST")
    
    if footer_text:
        footer = f"{footer_text} • {est_str}"
    else:
        footer = f"Ego • {est_str}"

    embed.set_footer(text=footer)
    return embed

def success_embed(title: str, description: str, **kwargs) -> discord.Embed:
    """Clean success notification."""
    return ego_embed(
        title=title,
        description=f"> {description}",
        color=COLOR_EMERALD,
        **kwargs
    )

def error_embed(title: str, description: str, tip: Optional[str] = None, **kwargs) -> discord.Embed:
    """Clean error notification."""
    desc = f"> {description}"
    if tip:
        desc += f"\n\n**Tip:** *{tip}*"
    return ego_embed(
        title=title,
        description=desc,
        color=COLOR_CRIMSON,
        **kwargs
    )

def warning_embed(title: str, description: str, **kwargs) -> discord.Embed:
    """Clean warning notification."""
    return ego_embed(
        title=title,
        description=f"> {description}",
        color=COLOR_AMBER,
        **kwargs
    )

def info_embed(title: str, description: str, **kwargs) -> discord.Embed:
    """Clean informative notification."""
    return ego_embed(
        title=title,
        description=description,
        color=COLOR_CYAN,
        **kwargs
    )

def card_embed(title: str, fields: List[tuple], color: int = COLOR_VIOLET, description: Optional[str] = None, **kwargs) -> discord.Embed:
    """Structured card with neat alignment."""
    embed = ego_embed(title=title, description=description, color=color, **kwargs)
    for name, val, inline in fields:
        embed.add_field(name=f"› {name}", value=val, inline=inline)
    return embed
