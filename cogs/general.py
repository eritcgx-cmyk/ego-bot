import re
import os
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import is_admin_or_has_role, is_guild_owner, load_command_access, save_command_access
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_CYAN, COLOR_AMBER, COLOR_EMERALD, COLOR_ROSE, get_eastern_time
)
from config import VERSION, DEFAULT_PREFIX, BOT_NAME

def parse_duration_seconds(time_str: str) -> Optional[int]:
    time_str = time_str.strip().lower()
    match = re.match(r"^(\d+)([smhd])$", time_str)
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    if unit == "s":
        return val
    elif unit == "m":
        return val * 60
    elif unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    return None


class EmbedBuilderModal(discord.ui.Modal, title="Embed Builder"):
    embed_title = discord.ui.TextInput(
        label="Embed Title",
        placeholder="Enter title...",
        required=True,
        max_length=256
    )
    embed_description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        placeholder="Markdown supported description...",
        required=True,
        max_length=4000
    )
    embed_color = discord.ui.TextInput(
        label="Hex Color Code",
        placeholder="#8B5CF6 (Leave blank for default violet)",
        required=False,
        max_length=7
    )
    image_url = discord.ui.TextInput(
        label="Image URL",
        placeholder="https://... (optional)",
        required=False,
        max_length=512
    )

    async def on_submit(self, interaction: discord.Interaction):
        color_val = COLOR_VIOLET
        if self.embed_color.value:
            try:
                hex_clean = self.embed_color.value.strip().replace("#", "")
                color_val = int(hex_clean, 16)
            except ValueError:
                color_val = COLOR_VIOLET

        embed = ego_embed(
            title=self.embed_title.value,
            description=self.embed_description.value,
            color=color_val
        )
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)

        embed.set_footer(text=f"Built by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)


class PollOptionModal(discord.ui.Modal, title="Create Community Poll"):
    poll_question = discord.ui.TextInput(
        label="Question",
        placeholder="What are we voting on?",
        required=True,
        max_length=256
    )
    options = discord.ui.TextInput(
        label="Options (1 per line, max 10)",
        style=discord.TextStyle.paragraph,
        placeholder="Option 1\nOption 2\nOption 3",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw_options = [opt.strip() for opt in self.options.value.split("\n") if opt.strip()]
        if len(raw_options) < 2:
            return await interaction.response.send_message("❌ Please provide at least 2 options.", ephemeral=True)
        if len(raw_options) > 10:
            return await interaction.response.send_message("❌ Maximum 10 options allowed.", ephemeral=True)

        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        desc_lines = [f"### ❓ {self.poll_question.value}\n"]
        for idx, opt in enumerate(raw_options):
            desc_lines.append(f"{number_emojis[idx]} **{opt}**")
        desc_lines.append("\n*React below with your vote!*")

        embed = ego_embed(
            title="Community Poll",
            description="\n".join(desc_lines),
            color=COLOR_CYAN
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        for idx in range(len(raw_options)):
            try:
                await msg.add_reaction(number_emojis[idx])
            except Exception:
                pass

class GeneralCog(commands.Cog, name="General"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = datetime.utcnow()

    @app_commands.command(name="commands", description="Command directory for members and community features")
    async def commands_cmd(self, interaction: discord.Interaction):
        embed = ego_embed(
            title="Community Commands",
            description=(
                "> **Ego Command Directory**\n"
                "> Public commands available to all server members (safe utilities):\n"
            ),
            color=COLOR_VIOLET
        )

        categories = [
            ("Friend Groups", "› `/fg start name:...` — Start a pending FG\n› `/fg invite member:...` — Invite friends to your FG\n› `/fg stats` — View your personal FG cards"),
            ("Creator Verification", "› `/cc verify` — Submit profile and video proof for Creator roles\n› `/cc tiers` — View follower and view requirements for all 6 tiers"),
            ("Invites & Stats", "› `/invites mystats` — Check your personal joins, leaves, and bonus invites\n› `/invites leaderboard` — Top server inviters"),
            ("Member Utilities", "› `/avatar` — Full resolution profile picture\n› `/userinfo` — Member join date, account age, and roles\n› `/serverinfo` — Server stats, channel totals, and boost level\n› `/remind duration:... message:...` — Set personal DM alert (e.g. `/remind 10m check stream`)\n› `/ping` — WebSocket heartbeat latency\n› `/uptime` — Bot continuous online duration timer\n› `/botinfo` — Bot system specs and metrics"),
        ]

        for cat_name, cat_desc in categories:
            embed.add_field(name=f"✦ {cat_name}", value=cat_desc, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="command_board", description="Deploy a permanent command board to a channel")
    @app_commands.describe(channel="Target channel to post command board")
    @is_admin_or_has_role()
    async def command_board(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild

        embed = ego_embed(
            title=f"Command Directory • {guild.name}",
            description=(
                "> **Server Command Board**\n"
                "> Public member commands across the server:\n"
            ),
            color=COLOR_VIOLET
        )

        categories = [
            ("Friend Groups", "› `/fg start` — Launch a pending FG\n› `/fg invite` — Invite members to FG\n› `/fg stats` — Inspect your personal FGs"),
            ("Content Creator", "› `/cc verify` — Apply for Creator roles (`CC`, `Known`, `Famous`, `Star`)\n› `/cc tiers` — Inspect follower and view requirements"),
            ("Invites & Community", "› `/invites mystats` — Check invite progress & role rewards\n› `/invites leaderboard` — Top server inviters"),
            ("Utilities", "› `/avatar` — Full resolution profile picture\n› `/userinfo` — Member stats & join dates\n› `/serverinfo` — Server stats & boost level\n› `/remind` — Set personal DM reminder\n› `/ping` — Live WebSocket latency\n› `/uptime` — Online duration"),
        ]

        for cat_name, cat_desc in categories:
            embed.add_field(name=f"✦ {cat_name}", value=cat_desc, inline=False)

        await target_ch.send(embed=embed)
        await interaction.response.send_message(
            embed=success_embed("Command Board Deployed", f"Posted Command Board to {target_ch.mention}"),
            ephemeral=True
        )

    @app_commands.command(name="commandboard", description="Deploy a permanent command board to a channel (alias)")
    @app_commands.describe(channel="Target channel to post command board")
    @is_admin_or_has_role()
    async def commandboard_alias(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await self.command_board(interaction, channel)


    # Command Access Management Group
    command_access_group = app_commands.Group(name="command_access", description="Manage role-based permissions for individual commands")

    @command_access_group.command(name="grant", description="Grant a role permission to use a specific command")
    @app_commands.describe(
        command="The command name to grant (e.g. poll, status, giveaway, announce)",
        role="The role to grant access to"
    )
    @is_guild_owner()
    async def access_grant(self, interaction: discord.Interaction, command: str, role: discord.Role):
        cmd_clean = command.strip().lower().replace("/", "")
        data = load_command_access()
        g_id = str(interaction.guild.id)
        if g_id not in data:
            data[g_id] = {}

        if cmd_clean not in data[g_id]:
            data[g_id][cmd_clean] = []

        if role.id not in data[g_id][cmd_clean]:
            data[g_id][cmd_clean].append(role.id)
            save_command_access(data)

        await interaction.response.send_message(
            embed=success_embed(
                "Command Access Granted",
                f"Members with {role.mention} can now execute `/{cmd_clean}`."
            ),
            ephemeral=True
        )

    @command_access_group.command(name="revoke", description="Revoke custom command access from a role")
    @app_commands.describe(
        command="The command name to revoke",
        role="The role to revoke access from"
    )
    @is_guild_owner()
    async def access_revoke(self, interaction: discord.Interaction, command: str, role: discord.Role):
        cmd_clean = command.strip().lower().replace("/", "")
        data = load_command_access()
        g_id = str(interaction.guild.id)

        if g_id in data and cmd_clean in data[g_id]:
            if role.id in data[g_id][cmd_clean]:
                data[g_id][cmd_clean].remove(role.id)
                save_command_access(data)
                return await interaction.response.send_message(
                    embed=success_embed(
                        "Command Access Revoked",
                        f"Revoked access to `/{cmd_clean}` for {role.mention}."
                    ),
                    ephemeral=True
                )

        await interaction.response.send_message(
            embed=error_embed("Not Found", f"No custom access rule found for `/{cmd_clean}` on {role.mention}."),
            ephemeral=True
        )

    @command_access_group.command(name="list", description="List all custom command access rules")
    @is_admin_or_has_role()
    async def access_list(self, interaction: discord.Interaction):
        data = load_command_access()
        g_id = str(interaction.guild.id)
        guild_rules = data.get(g_id, {})

        if not guild_rules:
            return await interaction.response.send_message(
                embed=info_embed("Command Access", "No custom command access rules defined for this server."),
                ephemeral=True
            )

        lines = []
        for cmd_name, role_ids in guild_rules.items():
            roles_formatted = [f"<@&{r_id}>" for r_id in role_ids]
            roles_str = ", ".join(roles_formatted) if roles_formatted else "*None*"
            lines.append(f"› `/{cmd_name}` — {roles_str}")

        embed = ego_embed(
            title="Command Access Rules",
            description="\n".join(lines),
            color=COLOR_VIOLET
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Check WebSocket latency and response time")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        embed = info_embed("Pong!", f"WebSocket Latency: **{latency_ms}ms**")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="uptime", description="Check how long Ego Bot has been continuously online")
    async def uptime(self, interaction: discord.Interaction):
        delta = datetime.utcnow() - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        embed = info_embed("System Uptime", f"Ego Bot has been online for: **{uptime_str}**")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botinfo", description="View technical bot infrastructure and statistics")
    async def botinfo(self, interaction: discord.Interaction):
        total_members = sum(g.member_count for g in self.bot.guilds)
        total_guilds = len(self.bot.guilds)
        total_channels = sum(len(g.channels) for g in self.bot.guilds)

        embed = card_embed(
            title=f"⚡ {BOT_NAME} System Specs",
            fields=[
                ("Version", f"`v{VERSION}`", True),
                ("Servers", f"`{total_guilds}`", True),
                ("Users Reached", f"`{total_members:,}`", True),
                ("Channels Managed", f"`{total_channels:,}`", True),
                ("Gateway Latency", f"`{round(self.bot.latency * 1000)}ms`", True),
                ("Python Version", "`3.12.0`", True),
                ("discord.py", f"`{discord.__version__}`", True),
                ("Database", "`SQLite / PostgreSQL Async`", True),
                ("Architecture", "`Modular Cogs + Microservices`", True),
            ],
            color=COLOR_VIOLET
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Get full-resolution user avatar")
    @app_commands.describe(user="The member to fetch avatar for (defaults to yourself)")
    async def avatar(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        avatar_url = target.display_avatar.url
        embed = ego_embed(title=f"{target.display_name}'s Avatar", color=COLOR_VIOLET)
        embed.set_image(url=avatar_url)
        embed.add_field(name="Direct Link", value=f"[Open in Browser]({avatar_url})")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Get user account information, roles, and join dates")
    @app_commands.describe(user="The member to inspect (defaults to yourself)")
    async def userinfo(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        created_ts = int(target.created_at.timestamp())
        joined_ts = int(target.joined_at.timestamp()) if hasattr(target, "joined_at") and target.joined_at else created_ts

        roles_list = [r.mention for r in target.roles if r.name != "@everyone"]
        roles_str = ", ".join(roles_list) if roles_list else "None"

        embed = card_embed(
            title=f"👤 {target.name}",
            fields=[
                ("User ID", f"`{target.id}`", True),
                ("Nickname", f"{target.nick or 'None'}", True),
                ("Bot Account", f"{'Yes' if target.bot else 'No'}", True),
                ("Account Created", f"<t:{created_ts}:R>", True),
                ("Joined Server", f"<t:{joined_ts}:R>", True),
                ("Highest Role", f"{target.top_role.mention if hasattr(target, 'top_role') else 'None'}", True),
                ("Roles", roles_str[:1024], False)
            ],
            color=COLOR_VIOLET,
            thumbnail_url=target.display_avatar.url
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="View server metrics, nitro boosts, and channel statistics")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("❌ This command must be run inside a server.", ephemeral=True)

        created_ts = int(guild.created_at.timestamp())
        text_count = len(guild.text_channels)
        voice_count = len(guild.voice_channels)
        role_count = len(guild.roles)
        boosts = guild.premium_subscription_count

        embed = card_embed(
            title=f"🏰 {guild.name}",
            fields=[
                ("Server ID", f"`{guild.id}`", True),
                ("Owner", f"{guild.owner.mention if guild.owner else 'Unknown'}", True),
                ("Created", f"<t:{created_ts}:R>", True),
                ("Members", f"`{guild.member_count:,}`", True),
                ("Channels", f"`{text_count}` Text • `{voice_count}` Voice", True),
                ("Roles", f"`{role_count}` Roles", True),
                ("Nitro Boosts", f"`{boosts}` Boosts (Level {guild.premium_tier})", True),
            ],
            color=COLOR_VIOLET,
            thumbnail_url=guild.icon.url if guild.icon else None
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="poll", description="Create a polished community poll with reaction voting")
    @is_admin_or_has_role()
    async def poll(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PollOptionModal())

    @app_commands.command(name="remind", description="Set a personal reminder DM")
    @app_commands.describe(duration="Time until reminder (e.g. 10m, 2h, 1d)", message="What should Ego remind you about?")
    async def remind(self, interaction: discord.Interaction, duration: str, message: str):
        sec = parse_duration_seconds(duration)
        if not sec or sec <= 0 or sec > 86400 * 30:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Duration", "Use formats like `10m`, `2h`, `1d` (Max 30 days)."),
                ephemeral=True
            )

        target_time = datetime.utcnow() + timedelta(seconds=sec)
        target_ts = int(target_time.timestamp())

        await interaction.response.send_message(
            embed=success_embed("Reminder Set", f"I will DM you <t:{target_ts}:R> about:\n> {message}"),
            ephemeral=True
        )

        async def _reminder_task(user_id: int, rem_msg: str, wait_time: int):
            await asyncio.sleep(wait_time)
            user = self.bot.get_user(user_id)
            if user:
                try:
                    embed = ego_embed(
                        title="Personal Reminder",
                        description=f"> {rem_msg}",
                        color=COLOR_AMBER
                    )
                    await user.send(embed=embed)
                except Exception:
                    pass

        asyncio.create_task(_reminder_task(interaction.user.id, message, sec))

    @app_commands.command(name="say", description="Broadcast a clean formatted message as the bot")
    @app_commands.describe(message="The message to send", channel="Target channel (optional)")
    @is_admin_or_has_role()
    async def say(self, interaction: discord.Interaction, message: str, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        await target_ch.send(message)
        await interaction.response.send_message(
            embed=success_embed("Message Sent", f"Broadcasted to {target_ch.mention}"),
            ephemeral=True
        )

    @app_commands.command(name="announce", description="Send an aesthetic announcement to a channel")
    @app_commands.describe(
        title="Announcement Title",
        message="Announcement Body",
        channel="Target Channel (optional)",
        role_ping="Optional role to ping"
    )
    @is_admin_or_has_role()
    async def announce(
        self,
        interaction: discord.Interaction,
        title: str,
        message: str,
        channel: Optional[discord.TextChannel] = None,
        role_ping: Optional[discord.Role] = None
    ):
        target_ch = channel or interaction.channel
        embed = ego_embed(
            title=f"📢 {title}",
            description=message,
            color=COLOR_VIOLET
        )
        embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        
        content = role_ping.mention if role_ping else None
        await target_ch.send(content=content, embed=embed)
        await interaction.response.send_message(
            embed=success_embed("Announcement Published", f"Posted to {target_ch.mention}"),
            ephemeral=True
        )

    @app_commands.command(name="embed_builder", description="Construct and send a custom rich embed via modal")
    @is_admin_or_has_role()
    async def embed_builder(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EmbedBuilderModal())

    @app_commands.command(name="purge", description="Bulk delete messages from the current channel")
    @app_commands.describe(amount="Number of messages to delete (1-100)", user_filter="Only delete messages from this user (optional)")
    @is_admin_or_has_role()
    async def purge(self, interaction: discord.Interaction, amount: int, user_filter: Optional[discord.Member] = None):
        if amount < 1 or amount > 100:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Amount", "Please specify a number between 1 and 100."),
                ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)

        def check(m):
            if user_filter:
                return m.author.id == user_filter.id
            return True

        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(
            embed=success_embed("Messages Purged", f"Successfully deleted `{len(deleted)}` messages."),
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCog(bot))
