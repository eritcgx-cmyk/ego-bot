"""
Ego Discord Bot - Production Entrypoint
"""
import os
import sys
import asyncio
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from config import BOT_TOKEN, DEFAULT_PREFIX, EMBED_COLOR, logger
from database.engine import init_db, AsyncSessionLocal
from database.models import GuildConfig
from utils.permissions import is_guild_owner, is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed

INITIAL_COGS = [
    "cogs.giveaways",
    "cogs.welcome",
    "cogs.automod",
    "cogs.friend_groups",
    "cogs.roles_system",
    "cogs.content_creator",
    "cogs.invites",
    "cogs.identity_verify",
    "cogs.general",
    "cogs.rules",
    "cogs.onboarding",
    "cogs.applications"
]

class EgoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        intents.guilds = True

        super().__init__(
            command_prefix=DEFAULT_PREFIX,
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # 1. Initialize Database
        logger.info("Connecting to database and verifying schema...")
        await init_db()

        # 2. Load all 12 Cogs
        for ext in INITIAL_COGS:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}")

        # 3. Sync Slash Commands
        logger.info("Syncing application slash command tree with Discord...")
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} global slash commands.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Serving {len(self.guilds)} guilds.")
        activity = discord.Activity(type=discord.ActivityType.watching, name="/help • Ego Engine")
        await self.change_presence(status=discord.Status.online, activity=activity)

bot = EgoBot()

# Global Tree Error Handler
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        return await interaction.response.send_message(
            embed=error_embed("Cooldown", f"Command is on cooldown. Try again in `{round(error.retry_after, 1)}s`."),
            ephemeral=True
        )
    elif isinstance(error, app_commands.MissingPermissions):
        return await interaction.response.send_message(
            embed=error_embed("Missing Permissions", "You do not have the required Discord permissions to run this command."),
            ephemeral=True
        )
    elif isinstance(error, app_commands.CheckFailure):
        msg = str(error) or "You do not meet the permission requirements for this command."
        if interaction.response.is_done():
            return await interaction.followup.send(embed=error_embed("Permission Denied", msg), ephemeral=True)
        else:
            return await interaction.response.send_message(embed=error_embed("Permission Denied", msg), ephemeral=True)

    logger.error(f"Unhandled AppCommand error in /{interaction.command.name if interaction.command else 'unknown'}: {error}")
    err_text = f"An unexpected error occurred: `{error}`"
    if interaction.response.is_done():
        await interaction.followup.send(embed=error_embed("Error", err_text), ephemeral=True)
    else:
        await interaction.response.send_message(embed=error_embed("Error", err_text), ephemeral=True)

# Central Guild Configuration Slash Command Group
config_group = app_commands.Group(name="config", description="Configure core Ego Bot settings for this server")

@config_group.command(name="modlog", description="Set the central mod-log and audit channel")
@app_commands.describe(channel="Target logging channel")
@is_admin_or_has_role()
async def config_modlog(interaction: discord.Interaction, channel: discord.TextChannel):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id))
        cfg = res.scalar_one_or_none()

        if not cfg:
            cfg = GuildConfig(guild_id=interaction.guild_id, mod_log_channel_id=channel.id)
            session.add(cfg)
        else:
            cfg.mod_log_channel_id = channel.id

        await session.commit()

    await interaction.response.send_message(
        embed=success_embed("Mod-Log Configured", f"Audit logs will be dispatched to {channel.mention}.")
    )

@config_group.command(name="roles", description="Set server-wide Admin and Mod roles")
@app_commands.describe(
    admin_role="Role considered Administrator by Ego bot",
    mod_role="Role considered Moderator by Ego bot"
)
@is_guild_owner()
async def config_roles(
    interaction: discord.Interaction,
    admin_role: Optional[discord.Role] = None,
    mod_role: Optional[discord.Role] = None
):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id))
        cfg = res.scalar_one_or_none()

        if not cfg:
            cfg = GuildConfig(guild_id=interaction.guild_id)
            session.add(cfg)

        if admin_role:
            cfg.admin_role_id = admin_role.id
        if mod_role:
            cfg.mod_role_id = mod_role.id

        await session.commit()

    await interaction.response.send_message(
        embed=success_embed(
            "Management Roles Updated",
            f"• Admin Role: {admin_role.mention if admin_role else '*Unchanged*'}\n"
            f"• Mod Role: {mod_role.mention if mod_role else '*Unchanged*'}"
        )
    )

@config_group.command(name="status", description="View all central configuration settings")
@is_admin_or_has_role()
async def config_status(interaction: discord.Interaction):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id))
        cfg = res.scalar_one_or_none()

    embed = ego_embed(title=f"⚙️ Core Config: {interaction.guild.name}", color=EMBED_COLOR)
    modlog = f"<#{cfg.mod_log_channel_id}>" if (cfg and cfg.mod_log_channel_id) else "*Not set*"
    adminr = f"<@&{cfg.admin_role_id}>" if (cfg and cfg.admin_role_id) else "*None (Admin Perms)*"
    modr = f"<@&{cfg.mod_role_id}>" if (cfg and cfg.mod_role_id) else "*None (Manage Msg Perms)*"

    embed.add_field(name="Mod-Log Channel", value=modlog, inline=True)
    embed.add_field(name="Admin Role", value=adminr, inline=True)
    embed.add_field(name="Mod Role", value=modr, inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.tree.add_command(config_group)

import aiohttp.web

async def start_keepalive_server():
    """Lightweight health check server for Render hosting."""
    async def handle_ping(request):
        return aiohttp.web.Response(text="Ego Bot Online", status=200)

    app = aiohttp.web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    
    port = int(os.environ.get("PORT", 8080))
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Keepalive web server listening on port {port}")

async def run_bot_with_server():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is missing! Please set it in .env or your cloud environment.")
        sys.exit(1)
    
    # Start web server if PORT is set (Render environment)
    if "PORT" in os.environ:
        await start_keepalive_server()
    
    await bot.start(BOT_TOKEN)

def main():
    asyncio.run(run_bot_with_server())

if __name__ == "__main__":
    main()

