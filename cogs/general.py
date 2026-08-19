"""
General and Utility System Cog for Ego Bot
"""
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import is_admin_or_has_role, is_mod_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import EMBED_COLOR, SUCCESS_COLOR, INFO_COLOR, logger

def parse_time_str(time_str: str) -> Optional[timedelta]:
    import re
    match = re.match(r"^(\d+)([smhd])$", time_str.strip().lower())
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    if unit == "s":
        return timedelta(seconds=val)
    elif unit == "m":
        return timedelta(minutes=val)
    elif unit == "h":
        return timedelta(hours=val)
    elif unit == "d":
        return timedelta(days=val)
    return None

class EmbedBuilderModal(discord.ui.Modal, title="Interactive Embed Builder"):
    def __init__(self, target_channel: discord.TextChannel):
        super().__init__()
        self.target_channel = target_channel

        self.title_input = discord.ui.TextInput(
            label="Embed Title",
            placeholder="Announcements / Server Update",
            required=True,
            max_length=256
        )
        self.desc_input = discord.ui.TextInput(
            label="Embed Description",
            placeholder="Type your markdown content here...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000
        )
        self.color_input = discord.ui.TextInput(
            label="Hex Color",
            placeholder="#5865F2",
            required=False,
            default="#5865F2",
            max_length=7
        )
        self.image_url_input = discord.ui.TextInput(
            label="Main Image URL",
            placeholder="https://example.com/banner.png",
            required=False,
            max_length=300
        )
        self.footer_input = discord.ui.TextInput(
            label="Footer Text",
            placeholder="Custom footer note",
            required=False,
            max_length=200
        )

        self.add_item(self.title_input)
        self.add_item(self.desc_input)
        self.add_item(self.color_input)
        self.add_item(self.image_url_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color_val = int(self.color_input.value.lstrip("#"), 16)
        except ValueError:
            color_val = EMBED_COLOR

        embed = discord.Embed(
            title=self.title_input.value,
            description=self.desc_input.value,
            color=color_val,
            timestamp=datetime.utcnow()
        )
        if self.image_url_input.value:
            embed.set_image(url=self.image_url_input.value.strip())
        if self.footer_input.value:
            embed.set_footer(text=self.footer_input.value.strip())
        else:
            embed.set_footer(text=f"Posted by {interaction.user.name}")

        await self.target_channel.send(embed=embed)
        await interaction.response.send_message(
            embed=success_embed("Embed Sent", f"Your embed has been posted in {self.target_channel.mention}."),
            ephemeral=True
        )

class GeneralCog(commands.Cog, name="General"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()

    @app_commands.command(name="announce", description="Post a server announcement")
    @app_commands.describe(
        channel="Channel to announce in",
        message="Announcement text",
        ping_role="Optional role to mention",
        use_embed="Send as formatted embed (True/False)"
    )
    @is_admin_or_has_role()
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str,
        ping_role: Optional[discord.Role] = None,
        use_embed: bool = True
    ):
        content = ping_role.mention if ping_role else None
        if use_embed:
            embed = ego_embed(
                title="📢 Server Announcement",
                description=message,
                color=EMBED_COLOR
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            await channel.send(content=content, embed=embed)
        else:
            full_msg = f"{content}\n\n{message}" if content else message
            await channel.send(full_msg)

        await interaction.response.send_message(
            embed=success_embed("Announcement Dispatched", f"Posted in {channel.mention}."),
            ephemeral=True
        )
        await log_action(
            interaction.guild,
            title="Announcement Sent",
            description=f"Channel: {channel.mention} | Ping: {ping_role.name if ping_role else 'None'}",
            moderator=interaction.user
        )

    @app_commands.command(name="say", description="Echo a message into a channel as the bot")
    @app_commands.describe(channel="Target channel", message="Message content")
    @is_admin_or_has_role()
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        await channel.send(message)
        await interaction.response.send_message(
            embed=success_embed("Sent", f"Message echoed in {channel.mention}."),
            ephemeral=True
        )

    @app_commands.command(name="purge", description="Purge messages from the current channel")
    @app_commands.describe(
        count="Number of messages to delete (1-100)",
        user="Only delete messages from this specific user",
        bot_only="Only delete messages sent by bots"
    )
    @is_mod_or_has_role()
    async def purge(
        self,
        interaction: discord.Interaction,
        count: int,
        user: Optional[discord.Member] = None,
        bot_only: bool = False
    ):
        if not (1 <= count <= 100):
            return await interaction.response.send_message(embed=error_embed("Invalid Count", "Count must be 1 to 100."), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        def check(m: discord.Message) -> bool:
            if user and m.author.id != user.id:
                return False
            if bot_only and not m.author.bot:
                return False
            return True

        deleted = await interaction.channel.purge(limit=count, check=check)
        await interaction.followup.send(
            embed=success_embed("Purged", f"Deleted `{len(deleted)}` message(s)."),
            ephemeral=True
        )
        await log_action(
            interaction.guild,
            title="Messages Purged",
            description=f"Deleted `{len(deleted)}` messages in {interaction.channel.mention}",
            moderator=interaction.user
        )

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000, 2)
        await interaction.response.send_message(
            embed=info_embed("🏓 Pong!", f"API Gateway Latency: `{latency_ms}ms`")
        )

    @app_commands.command(name="uptime", description="Check bot system uptime")
    async def uptime(self, interaction: discord.Interaction):
        delta = timedelta(seconds=int(time.time() - self.start_time))
        await interaction.response.send_message(
            embed=info_embed("⏱️ System Uptime", f"Ego has been online for: `{str(delta)}`")
        )

    @app_commands.command(name="botinfo", description="View bot technical and system information")
    async def botinfo(self, interaction: discord.Interaction):
        total_guilds = len(self.bot.guilds)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        delta = timedelta(seconds=int(time.time() - self.start_time))

        embed = ego_embed(
            title="🤖 Ego Bot • System Overview",
            description="High-performance modular Discord production management engine.",
            color=INFO_COLOR
        )
        embed.add_field(name="Servers", value=f"`{total_guilds}`", inline=True)
        embed.add_field(name="Users Managed", value=f"`{total_members:,}`", inline=True)
        embed.add_field(name="Latency", value=f"`{round(self.bot.latency * 1000, 2)}ms`", inline=True)
        embed.add_field(name="Uptime", value=f"`{str(delta)}`", inline=True)
        embed.add_field(name="Python & Library", value=f"`discord.py v{discord.__version__}`", inline=True)
        embed.add_field(name="Architecture", value="`Async SQLAlchemy + Cogs`", inline=True)

        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Display server statistics and information")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = ego_embed(title=f"🏰 Server Info: {guild.name}", color=INFO_COLOR)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="Members", value=f"`{guild.member_count:,}`", inline=True)
        embed.add_field(name="Roles", value=f"`{len(guild.roles)}`", inline=True)
        embed.add_field(name="Channels", value=f"`{len(guild.channels)}`", inline=True)
        embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Boost Level", value=f"Level `{guild.premium_tier}` (`{guild.premium_subscription_count}` boosts)", inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Display information for a member")
    @app_commands.describe(user="The member to view")
    async def userinfo(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        embed = ego_embed(title=f"👤 User Info: {target.display_name}", color=INFO_COLOR)
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(name="Username", value=f"`{target.name}`", inline=True)
        embed.add_field(name="ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="Account Created", value=f"<t:{int(target.created_at.timestamp())}:R>", inline=True)
        if isinstance(target, discord.Member) and target.joined_at:
            embed.add_field(name="Joined Server", value=f"<t:{int(target.joined_at.timestamp())}:R>", inline=True)
            roles = [r.mention for r in target.roles if not r.is_default()]
            embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:15]) if roles else "*None*", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="View member avatar")
    @app_commands.describe(user="The user to view")
    async def avatar(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        target = user or interaction.user
        embed = ego_embed(title=f"🖼️ Avatar: {target.name}", color=INFO_COLOR)
        embed.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="poll", description="Create an interactive poll")
    @app_commands.describe(
        question="Poll question",
        option1="First option",
        option2="Second option",
        option3="Third option (optional)",
        option4="Fourth option (optional)",
        duration="Duration e.g. 10m, 1h, 1d"
    )
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: Optional[str] = None,
        option4: Optional[str] = None,
        duration: Optional[str] = None
    ):
        options = [option1, option2]
        if option3:
            options.append(option3)
        if option4:
            options.append(option4)

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
        desc_lines = [f"{emojis[i]} **{opt}**" for i, opt in enumerate(options)]

        embed = ego_embed(
            title=f"📊 Poll: {question}",
            description="\n\n".join(desc_lines),
            color=INFO_COLOR
        )
        embed.set_footer(text=f"Poll created by {interaction.user.name}")

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        for i in range(len(options)):
            await msg.add_reaction(emojis[i])

    @app_commands.command(name="remind", description="Set a personal reminder DM")
    @app_commands.describe(duration="Time from now (e.g. 10m, 2h, 1d)", message="Reminder reminder note")
    async def remind(self, interaction: discord.Interaction, duration: str, message: str):
        td = parse_time_str(duration)
        if not td:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Duration", "Use formats like `10m`, `2h`, `1d`."),
                ephemeral=True
            )

        target_time = datetime.utcnow() + td
        await interaction.response.send_message(
            embed=success_embed(
                "Reminder Scheduled",
                f"I will DM you <t:{int(target_time.timestamp())}:R>: **{message}**"
            ),
            ephemeral=True
        )

        async def _reminder_task(delay: float, user_id: int, note: str):
            await asyncio.sleep(delay)
            user = self.bot.get_user(user_id)
            if user:
                try:
                    embed = ego_embed(title="⏰ Reminder!", description=note, color=INFO_COLOR)
                    await user.send(embed=embed)
                except Exception:
                    pass

        asyncio.create_task(_reminder_task(td.total_seconds(), interaction.user.id, message))

    embed_group = app_commands.Group(name="embed", description="Custom embed builder")

    @embed_group.command(name="builder", description="Launch the interactive modal embed builder")
    @app_commands.describe(channel="Channel to post the embed into")
    @is_admin_or_has_role()
    async def embed_builder(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_channel = channel or interaction.channel
        modal = EmbedBuilderModal(target_channel)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="help", description="Categorized list of all Ego Bot systems and slash commands")
    async def help_command(self, interaction: discord.Interaction):
        embed = ego_embed(
            title="📖 Ego Bot • Command Manual",
            description="Explore the complete suite of slash commands across all 12 production systems.",
            color=INFO_COLOR
        )
        categories = {
            "🎉 Giveaways": "`/giveaway start`, `/giveaway end`, `/giveaway reroll`, `/gwannounce`",
            "👋 Welcome": "`/welcome setup`, `/welcome preview`, `/welcome toggle`",
            "🛡️ Automod": "`/automod status`, `/automod toggle`, `/automod set_thresholds`, `/automod add_word`",
            "👥 Friend Groups": "`/fg config`, `/fg start`, `/fg invite`, `/fg rename`, `/fg kick`, `/fg disband`",
            "👑 Role System": "`/roles import_presets`, `/roles create_custom`, `/roles perks`, `/roles panel`",
            "🎥 Content Creator": "`/cc verify`, `/cc config_tier`, `/cc tiers`",
            "📈 Invites & Levels": "`/invites mystats`, `/invites leaderboard`, `/invites config_tier`, `/invites panel`",
            "✨ Identity & Gender": "`/verify_panel setup`",
            "📜 Rules Builder": "`/rules setup`, `/rules edit`, `/rules addrule`, `/rules removerule`, `/rules republish`",
            "🚀 Onboarding": "`/onboarding setup`, `/onboarding edit`, `/onboarding preview`, `/onboarding toggle`",
            "📝 Applications": "`/applications setup`, `/applications create`, `/applications list`, `/applications close`",
            "🛠️ Utility": "`/announce`, `/say`, `/purge`, `/poll`, `/remind`, `/embed builder`, `/ping`, `/uptime`, `/botinfo`, `/serverinfo`, `/userinfo`, `/avatar`"
        }

        for cat, cmds in categories.items():
            embed.add_field(name=cat, value=cmds, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCog(bot))
