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
    "cogs.applications",
    "cogs.status_rotator"
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

        # 3. Register Persistent UI Views (So buttons and tickets work forever across restarts)
        try:
            from cogs.content_creator import CCTicketReviewView
            self.add_view(CCTicketReviewView())
            logger.info("Registered persistent CCTicketReviewView.")
        except Exception as e:
            logger.debug(f"Could not register CCTicketReviewView: {e}")

        try:
            from cogs.rules import RulesAgreeView
            self.add_view(RulesAgreeView())
            logger.info("Registered persistent RulesAgreeView.")
        except Exception as e:
            logger.debug(f"Could not register RulesAgreeView: {e}")

        # 4. Sync Slash Commands
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
        err_text = f"Command is on cooldown. Try again in `{round(error.retry_after, 1)}s`."
    elif isinstance(error, app_commands.MissingPermissions):
        err_text = "You do not have the required Discord permissions to run this command."
    elif isinstance(error, app_commands.CheckFailure):
        err_text = "You are not authorized to run this command."
    else:
        logger.error(f"Unhandled AppCommand error in /{interaction.command.name if interaction.command else 'unknown'}: {error}")
        err_text = "An unexpected error occurred while executing this command."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=error_embed("Error", err_text), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed("Error", err_text), ephemeral=True)
    except Exception:
        pass



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

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class KeepaliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Ego Bot Online & Healthy")

    def log_message(self, format, *args):
        pass # Suppress continuous health check logging

def start_threaded_keepalive():
    """Starts a robust background HTTP server on 0.0.0.0:$PORT for Render."""
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), KeepaliveHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info(f"Threaded keepalive server listening on 0.0.0.0:{port}")
    except Exception as e:
        logger.warning(f"Could not bind keepalive port {port}: {e}")

async def run_bot_with_server():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is missing! Please set it in .env or your cloud environment.")
        sys.exit(1)

    # 1. Start Threaded HTTP Server immediately (Answers Render healthcheck in <1ms)
    start_threaded_keepalive()

    # 2. Initialize Database Schema
    logger.info("Verifying database schema...")
    await init_db()

    # 3. Start Discord Bot Gateway Connection
    logger.info("Connecting to Discord Gateway...")
    await bot.start(BOT_TOKEN)

def main():
    asyncio.run(run_bot_with_server())

if __name__ == "__main__":
    main()



