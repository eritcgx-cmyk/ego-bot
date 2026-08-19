"""
Permission checkers, role-based command access, and decorators for Ego Bot Slash Commands.
Supports custom role assignments per command via /command_access.
"""
import os
import json
from typing import Callable, Coroutine, Any, Optional, List, Dict
import discord
from discord import app_commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import GuildConfig

COMMAND_ACCESS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "command_access.json")

def load_command_access() -> Dict[str, Any]:
    os.makedirs(os.path.dirname(COMMAND_ACCESS_FILE), exist_ok=True)
    if not os.path.exists(COMMAND_ACCESS_FILE):
        return {}
    try:
        with open(COMMAND_ACCESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_command_access(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(COMMAND_ACCESS_FILE), exist_ok=True)
    with open(COMMAND_ACCESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def has_custom_command_access(guild_id: int, command_name: str, member: discord.Member) -> bool:
    access_data = load_command_access()
    guild_data = access_data.get(str(guild_id), {})
    # Match direct command name or subcommands (e.g. "giveaway" or "giveaway start")
    cmd_key = command_name.lower().strip()
    cmd_roles = guild_data.get(cmd_key, [])
    if not cmd_roles:
        # Also check base command name (e.g. "giveaway")
        base_cmd = cmd_key.split()[0]
        cmd_roles = guild_data.get(base_cmd, [])

    if not cmd_roles:
        return False

    user_role_ids = {r.id for r in member.roles}
    return any(role_id in user_role_ids for role_id in cmd_roles)

def is_guild_owner():
    """Check if the user is the owner of the guild."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        if interaction.user.id == interaction.guild.owner_id:
            return True
        raise app_commands.AppCommandError("You must be the server owner to use this command.")
    return app_commands.check(predicate)

def is_admin_or_has_role(command_name: Optional[str] = None):
    """Check if member has administrator, guild admin role, or custom role command access."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id:
            return True
        
        # Check custom role access for this command
        cmd = command_name or interaction.command.name
        if has_custom_command_access(interaction.guild.id, cmd, interaction.user):
            return True

        # Check database configured admin role
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild.id))
            cfg = res.scalar_one_or_none()
            if cfg and cfg.admin_role_id:
                if any(role.id == cfg.admin_role_id for role in interaction.user.roles):
                    return True
        
        raise app_commands.AppCommandError("You lack the required permissions or role for this command.")
    return app_commands.check(predicate)

def is_mod_or_has_role(command_name: Optional[str] = None):
    """Check if member has manage_messages/kick/ban, guild mod/admin role, or custom command access."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        if (interaction.user.guild_permissions.manage_messages or 
            interaction.user.guild_permissions.kick_members or 
            interaction.user.guild_permissions.administrator or
            interaction.user.id == interaction.guild.owner_id):
            return True
        
        # Check custom role access
        cmd = command_name or interaction.command.name
        if has_custom_command_access(interaction.guild.id, cmd, interaction.user):
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
        
        raise app_commands.AppCommandError("You lack the required permissions or role for this command.")
    return app_commands.check(predicate)
