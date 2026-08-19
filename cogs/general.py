"""
Humanized General & Utility Commands Cog for Ego Bot.
Includes announcement builder, giveaway broadcasts, poll creator, personal reminders, user/server info, and moderation shortcuts.
"""
import asyncio
import re
from typing import Optional, List
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import Giveaway
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_CYAN, COLOR_EMERALD, COLOR_ROSE, COLOR_AMBER
)
from utils.permissions import is_admin_or_has_role
from config import BOT_VERSION, logger

def parse_duration_seconds(duration_str: str) -> Optional[int]:
    """Parse string duration into seconds (e.g. 10m, 2h, 1d)."""
    match = re.match(r"^(\d+)([smhd])$", duration_str.strip().lower())
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return val * multipliers[unit]

class EmbedBuilderModal(discord.ui.Modal, title="🎨 Custom Embed Builder"):
    embed_title = discord.ui.TextInput(label="Embed Title", placeholder="e.g. Server Updates & Changelog", max_length=250, required=True)
    description = discord.ui.TextInput(label="Description / Body", style=discord.TextStyle.paragraph, placeholder="Type your message with markdown formatting...", max_length=4000, required=True)
    color_hex = discord.ui.TextInput(label="Hex Color (Optional, e.g. #8B5CF6)", placeholder="#8B5CF6", max_length=7, required=False)
    image_url = discord.ui.TextInput(label="Banner Image URL (Optional)", placeholder="https://...", max_length=500, required=False)
    thumbnail_url = discord.ui.TextInput(label="Thumbnail URL (Optional)", placeholder="https://...", max_length=500, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        color = COLOR_VIOLET
        if self.color_hex.value:
            try:
                hex_clean = self.color_hex.value.replace("#", "")
                color = int(hex_clean, 16)
            except Exception:
                color = COLOR_VIOLET

        embed = ego_embed(
            title=self.embed_title.value,
            description=self.description.value,
            color=color,
            image_url=self.image_url.value or None,
            thumbnail_url=self.thumbnail_url.value or None
        )
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            embed=success_embed("Embed Sent", "Custom embed has been posted to this channel."),
            ephemeral=True
        )

class PollOptionModal(discord.ui.Modal, title="📊 Create Interactive Poll"):
    question = discord.ui.TextInput(label="Poll Question", placeholder="e.g. Which event should we host this weekend?", max_length=200, required=True)
    options_text = discord.ui.TextInput(label="Options (one per line, up to 10)", style=discord.TextStyle.paragraph, placeholder="1. Gaming Tournament\n2. Movie Night\n3. Nitro Drop", max_length=1000, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        raw_options = [opt.strip() for opt in self.options_text.value.strip().split("\n") if opt.strip()]
        if len(raw_options) < 2:
            return await interaction.response.send_message(
                embed=error_embed("Too Few Options", "Please provide at least 2 distinct poll choices."),
                ephemeral=True
            )
        if len(raw_options) > 10:
            return await interaction.response.send_message(
                embed=error_embed("Too Many Options", "Maximum 10 poll choices allowed."),
                ephemeral=True
            )

        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        desc_lines = [f"**{self.question.value}**\n"]
        for idx, opt in enumerate(raw_options):
            desc_lines.append(f"{number_emojis[idx]} **{opt}**")
        desc_lines.append("\n*React below with your vote!*")

        embed = ego_embed(
            title="📊 Community Poll",
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

    @app_commands.command(name="commands", description="Public command board for members and community features")
    async def commands_cmd(self, interaction: discord.Interaction):
        embed = ego_embed(
            title="Command Board",
            description=(
                "> **Ego Community Commands**\n"
                "> Run any of the commands below to interact with community systems:\n"
            ),
            color=COLOR_VIOLET
        )

        categories = [
            ("Friend Groups", "`/fg start` — Form a 5-member circle with private text & voice lounges\n`/fg stats` — View your active squad cards\n`/fg rename` — Rename squad & sync channels"),
            ("Creator Verification", "`/cc verify` — Submit profile & video proof for Creator tiers\n`/cc tiers` — View follower & view thresholds for all 6 tiers"),
            ("Giveaways", "`/giveaway start` — Launch timed giveaway with button entry\n`/giveaway reroll` — Pick new winners\n`/giveaway end` — Conclude early"),
            ("Invites & Tracking", "`/invites mystats` — Check your joins, leaves, and bonus invites\n`/invites leaderboard` — Top server inviters"),
            ("Utilities & Custom Status", "`/poll` — Launch an interactive vote\n`/remind` — Set personal DM alert (`/remind 10m message`)\n`/avatar` — View full resolution profile image\n`/userinfo` — Member join date and roles\n`/serverinfo` — Server stats and metrics\n`/status set` — Set custom game activity (e.g. Roblox, GTA VI)"),
        ]

        for cat_name, cat_desc in categories:
            embed.add_field(name=f"✦ {cat_name}", value=cat_desc, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="command_board", description="Deploy a permanent public command board to a channel")
    @app_commands.describe(channel="Target channel to post command board (defaults to current channel)")
    @is_admin_or_has_role()
    async def command_board(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild

        embed = ego_embed(
            title=f"Command Directory • {guild.name}",
            description=(
                "> **Server Command Board**\n"
                "> Available slash commands for members across the server:\n"
            ),
            color=COLOR_VIOLET
        )

        categories = [
            ("Friend Groups", "› `/fg start` — Launch a private 5-member squad with secret lounge & voice\n› `/fg stats` — Inspect your squads\n› `/fg rename` — Update squad title"),
            ("Content Creator", "› `/cc verify` — Apply for Creator roles (`CC`, `Known`, `Famous`, `Star`)\n› `/cc tiers` — Inspect follower and view requirements"),
            ("Giveaways", "› `/giveaway start` — Enter button giveaways with auto-draw\n› `/gwannounce` — Spotlight active giveaways"),
            ("Invites & Community", "› `/invites mystats` — Check invite progress & role rewards\n› `/invites leaderboard` — Top server inviters"),
            ("Utilities", "› `/poll` — Create reaction poll\n› `/remind` — Set personal DM reminder\n› `/userinfo` — Member stats\n› `/avatar` — Full resolution profile picture\n› `/status list` — Select from saved custom game activities"),
        ]

        for cat_name, cat_desc in categories:
            embed.add_field(name=f"✦ {cat_name}", value=cat_desc, inline=False)

        await target_ch.send(embed=embed)
        await interaction.response.send_message(
            embed=success_embed("Command Board Deployed", f"Posted Command Board to {target_ch.mention}"),
            ephemeral=True
        )

    @app_commands.command(name="help", description="Explore all commands, systems, and features in Ego")
    async def help_cmd(self, interaction: discord.Interaction):

        embed = ego_embed(
            title="⚡ Ego Command Directory",
            description=(
                "> **Welcome to Ego** — a next-generation Discord community & utility engine.\n"
                "> Everything is built for speed, aesthetics, and reliability.\n"
            ),
            color=COLOR_VIOLET
        )

        categories = [
            ("🎉 Giveaways", "`/giveaway start`, `/giveaway reroll`, `/giveaway end`, `/gwannounce`\n*Reaction & button entries with auto-draws.*"),
            ("👥 Friend Groups", "`/fg start`, `/fg invite`, `/fg rename`, `/fg kick`, `/fg disband`\n*Create 4-member circles with private channels.*"),
            ("🚀 Creator Verification", "`/cc verify`, `/cc tiers`, `/cc config`\n*Submit platform stats for verified creator perks.*"),
            ("📈 Invites & Tracking", "`/invites mystats`, `/invites leaderboard`, `/invites panel`\n*Track joins, leaves, and bonus invites.*"),
            ("🎭 Role Presets", "`/roles import_presets`, `/roles perks`, `/roles panel`\n*Access over 1,200 curated aesthetic role themes.*"),
            ("📜 Server Rules", "`/rules setup`, `/rules addrule`, `/rules republish`\n*Deploy numbered rules with an 'I Agree' gate.*"),
            ("🎮 Custom Statuses", "`/status set`, `/status list`, `/status load`, `/status auto_rotate`\n*Custom game presence (Roblox, GTA VI) & 1-min rotation.*"),
            ("🛡️ Moderation & Automod", "`/automod set_thresholds`, `/purge`, `/say`, `/announce`, `/remind`\n*Zero-tolerance spam, invites, and profanity defense.*"),
            ("⚙️ Server Configuration", "`/config modlog`, `/config roles`, `/config status`\n*Bind mod-logs and customize server thresholds.*")
        ]

        for cat_name, cat_desc in categories:
            embed.add_field(name=f"✦ {cat_name}", value=cat_desc, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping", description="Check live gateway latency and API response time")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000, 1)
        status_badge = "🟢 Excellent" if latency_ms < 60 else "🟡 Good" if latency_ms < 150 else "🔴 High"
        embed = ego_embed(
            title="📶 Gateway Heartbeat",
            description=(
                f"> **WebSocket Latency:** `{latency_ms}ms` ({status_badge})\n"
                f"> **Shards Connected:** `1/1`\n"
                f"> **Status:** `Operational & Synced`"
            ),
            color=COLOR_EMERALD if latency_ms < 100 else COLOR_CYAN
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="uptime", description="Check how long Ego has been online")
    async def uptime(self, interaction: discord.Interaction):
        uptime_delta = datetime.utcnow() - self.start_time
        hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        embed = ego_embed(
            title="⏱️ Online Uptime",
            description=f"> Ego has been continuously active for **`{uptime_str}`**.",
            color=COLOR_CYAN
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botinfo", description="View cloud uptime, server statistics, and infrastructure details")
    async def botinfo(self, interaction: discord.Interaction):
        uptime_delta = datetime.utcnow() - self.start_time
        hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        total_guilds = len(self.bot.guilds)

        embed = card_embed(
            title="🤖 Ego Statistics",
            fields=[
                ("Uptime", f"`{uptime_str}`", True),
                ("Servers", f"`{total_guilds}`", True),
                ("Total Members", f"`{total_members:,}`", True),
                ("discord.py", f"`{discord.__version__}`", True),
                ("Version", f"`v{BOT_VERSION}`", True),
                ("Environment", "`Production Cloud`", True),
            ],
            color=COLOR_VIOLET,
            description="> Engineered with discord.py 2.4+ and asynchronous SQLAlchemy."
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="View a member's high-resolution avatar")
    @app_commands.describe(user="The member to view (defaults to yourself)")
    async def avatar(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        avatar_url = target.display_avatar.url

        embed = ego_embed(
            title=f"🖼️ {target.display_name}'s Avatar",
            description=f"> [Open Full Resolution in Browser]({avatar_url})",
            color=COLOR_ROSE
        )
        embed.set_image(url=avatar_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Look up user profile, join date, account age, and roles")
    @app_commands.describe(member="The member to inspect (defaults to yourself)")
    async def userinfo(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        created_ts = int(target.created_at.timestamp())
        joined_ts = int(target.joined_at.timestamp()) if isinstance(target, discord.Member) and target.joined_at else None

        roles = [r.mention for r in target.roles if r.name != "@everyone"] if isinstance(target, discord.Member) else []
        roles_str = ", ".join(roles[:12]) if roles else "None"
        if len(roles) > 12:
            roles_str += f" *(+{len(roles) - 12} more)*"

        fields = [
            ("User ID", f"`{target.id}`", True),
            ("Account Created", f"<t:{created_ts}:R>\n*(<t:{created_ts}:d>)*", True),
        ]
        if joined_ts:
            fields.append(("Joined Server", f"<t:{joined_ts}:R>\n*(<t:{joined_ts}:d>)*", True))
        
        fields.append(("Roles", roles_str, False))

        embed = card_embed(
            title=f"👤 {target.display_name}",
            fields=fields,
            color=COLOR_CYAN,
            thumbnail_url=target.display_avatar.url
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Inspect server statistics, roles, channels, and owner")
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
                        title="⏰ Personal Reminder",
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
