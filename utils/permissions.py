"""
Permission checkers and decorators for Ego Bot Slash Commands.
"""
from typing import Callable, Coroutine, Any
import discord
from discord import app_commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import GuildConfig

def is_guild_owner():
    """Check if the user is the owner of the guild."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        if interaction.user.id == interaction.guild.owner_id:
            return True
        raise app_commands.AppCommandError("You must be the server owner to use this command.")
    return app_commands.check(predicate)

def is_admin_or_has_role():
    """Check if member has administrator permission or guild admin role."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id:
            return True
        
        # Check database configured admin role
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild.id))
            cfg = res.scalar_one_or_none()
            if cfg and cfg.admin_role_id:
                if any(role.id == cfg.admin_role_id for role in interaction.user.roles):
                    return True
        
        raise app_commands.AppCommandError("You lack the required Administrator permissions or role.")
    return app_commands.check(predicate)

def is_mod_or_has_role():
    """Check if member has manage_messages/kick/ban permission or guild mod role."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        if (interaction.user.guild_permissions.manage_messages or 
            interaction.user.guild_permissions.kick_members or 
            interaction.user.guild_permissions.administrator or
            interaction.user.id == interaction.guild.owner_id):
            return True
        
        # Check database configured mod role or admin role
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild.id))
            cfg = res.scalar_one_or_none()
            if cfg:
                if cfg.mod_role_id and any(role.id == cfg.mod_role_id for role in interaction.user.roles):
                    return True
                if cfg.admin_role_id and any(role.id == cfg.admin_role_id for role in interaction.user.roles):
                    return True
        
        raise app_commands.AppCommandError("You lack the required Moderator permissions or role.")
    return app_commands.check(predicate)
