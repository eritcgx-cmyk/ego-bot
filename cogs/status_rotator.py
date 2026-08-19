"""
Automated Status Rotator and Server/Role Whitelist Cog for Ego Bot
"""
import random
from typing import Optional, List, Dict
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import GuildConfig
from utils.permissions import is_guild_owner, is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import INFO_COLOR, logger

# 100+ Categorized Status Presets
STATUS_PRESETS = [
    # Category 1: Advertisement Presets (25)
    ("playing", "👑 Join our VIP Hub • /help"),
    ("watching", "🎉 Active Giveaways • /giveaway"),
    ("playing", "💎 Unlock Custom Roles • /roles perks"),
    ("watching", "📈 Invite Leaderboards • /invites"),
    ("playing", "🚀 Verified Creator Ranks • /cc verify"),
    ("watching", "👥 Friend Groups • /fg start"),
    ("listening", "📜 Read Server Rules • /rules"),
    ("playing", "📝 Staff Applications Open • /applications"),
    ("watching", "🛡️ Protected by Ego Automod"),
    ("playing", "✨ Claim Your Roles in #verification"),
    ("watching", "🔥 Elite Nitro Booster Perks"),
    ("playing", "⚡ discord.gg/ecco • Join Now"),
    ("watching", "🎁 Massive Server Drops"),
    ("listening", "📢 Announcements in #announcements"),
    ("playing", "🌟 Level Up Your Invites"),
    ("watching", "💬 Community Chat & Voice"),
    ("playing", "🏆 Host Your Own Friend Group"),
    ("watching", "🎬 Content Creator Showcase"),
    ("playing", "🤖 Powered by Ego Production Engine"),
    ("watching", "💎 Diamond & Obsidian Status Tiers"),
    ("listening", "🎵 24/7 Music & Hangout"),
    ("playing", "🛡️ High-Security Community"),
    ("watching", "📊 Real-Time Server Analytics"),
    ("playing", "🎯 Join Giveaways Daily"),
    ("watching", "🚀 Explore 1200+ Role Presets"),

    # Category 2: Community & Scale Presets (25)
    ("watching", "{membercount} members across {guildcount} servers"),
    ("playing", "with {membercount} amazing members"),
    ("watching", "{guildcount} secure communities"),
    ("listening", "to {membercount} members chatting"),
    ("watching", "over {guildcount} active realms"),
    ("playing", "Ego v2.0 • Serving {membercount} users"),
    ("watching", "the member count grow ({membercount})"),
    ("listening", "to the community discussions"),
    ("playing", "in {guildcount} distinct server hubs"),
    ("watching", "new members joining every hour"),
    ("listening", "to voice channels & podcasts"),
    ("playing", "with {guildcount} guilds worldwide"),
    ("watching", "moderation logs & security filters"),
    ("playing", "managing {membercount} verified profiles"),
    ("watching", "friend groups collaborate in real time"),
    ("listening", "to staff updates & tickets"),
    ("playing", "24/7 Uptime • Ego Engine"),
    ("watching", "leaderboard rankings shift"),
    ("playing", "supporting {guildcount} partner hubs"),
    ("watching", "custom role panels refresh"),
    ("listening", "to verification requests"),
    ("playing", "active across {guildcount} Discord servers"),
    ("watching", "giveaways countdown to draw"),
    ("playing", "Ego Central Management"),
    ("watching", "server growth metrics"),

    # Category 3: Aesthetic & Flex Presets (25)
    ("playing", "⚡ Sovereign Authority"),
    ("watching", "💎 The Obsidian Syndicate"),
    ("playing", "🌙 Midnight Chroma Drift"),
    ("watching", "🔮 Ethereal Resonance"),
    ("playing", "🪐 Cosmic Horizon Phase"),
    ("watching", "👑 Apex Status Achieved"),
    ("playing", "✨ Neon Glitch Matrix"),
    ("watching", "🏆 Monarch Dynasty"),
    ("playing", "💠 Diamond Tier VIP"),
    ("watching", "🛡️ Sentinel Security Shield"),
    ("playing", "🌌 Astral Pulse Frequency"),
    ("watching", "⚡ High Voltage Infrastructure"),
    ("playing", "🔥 Infernal Sovereign"),
    ("watching", "❄️ Frost Radiant Aura"),
    ("playing", "🌀 Cyberpunk Synthwave Vibe"),
    ("watching", "⚜️ Imperial Council"),
    ("playing", "💎 Whale Status Lounge"),
    ("watching", "🎯 Zero Tolerance Automod"),
    ("playing", "🖤 Monochrome Aesthetic"),
    ("watching", "🌟 Star Creator Spotlight"),
    ("playing", "🚀 Quantum Execution Layer"),
    ("watching", "👑 Legendary Rank Prestige"),
    ("playing", "🔱 Celestial Authority"),
    ("watching", "💠 Platinum Standard"),
    ("playing", "⚡ Ego • Production Supreme"),

    # Category 4: Gaming & Media Presets (25)
    ("streaming", "🔴 Live Stream Highlights"),
    ("playing", "Valorant • Ranked Competitive"),
    ("playing", "Minecraft • Community SMP"),
    ("playing", "Roblox • Developer Studio"),
    ("watching", "Twitch Partner Streams"),
    ("watching", "YouTube Viral Uploads"),
    ("watching", "TikTok Trending Clips"),
    ("playing", "Grand Theft Auto VI"),
    ("playing", "League of Legends • Challenger"),
    ("watching", "Esports Championship Arena"),
    ("playing", "Overwatch 2 • Grandmaster"),
    ("watching", "Anime & Movie Night"),
    ("playing", "Counter-Strike 2 • Premier"),
    ("watching", "Speedrun World Records"),
    ("playing", "Fortnite • Champion Division"),
    ("watching", "Podcasts & Interviews"),
    ("playing", "Apex Legends • Predator Tier"),
    ("watching", "Community Clip Showcase"),
    ("playing", "Call of Duty • Warzone"),
    ("watching", "Kick Streamers Live"),
    ("playing", "Cyberpunk 2077 • Phantom Liberty"),
    ("watching", "Creator Highlights in #clips"),
    ("playing", "Rocket League • Supersonic Legend"),
    ("watching", "Music Festival Stream"),
    ("playing", "Ego Arcade • Winner Takes All")
]

class StatusRotatorCog(commands.Cog, name="StatusRotator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rotator_enabled = True
        self.custom_status_override: Optional[str] = None
        self.current_index = 0
        self.whitelisted_guild_ids: List[int] = []
        self.whitelisted_owner_ids: List[int] = []
        self.status_rotation_task.start()

    def cog_unload(self):
        self.status_rotation_task.cancel()

    @tasks.loop(minutes=10)
    async def status_rotation_task(self):
        """Rotate bot activity status every 10 minutes across 100+ presets."""
        if not self.rotator_enabled or self.custom_status_override:
            return

        try:
            total_members = sum(g.member_count or 0 for g in self.bot.guilds)
            total_guilds = len(self.bot.guilds)

            act_type_str, template = STATUS_PRESETS[self.current_index % len(STATUS_PRESETS)]
            self.current_index += 1

            status_text = template.format(membercount=f"{total_members:,}", guildcount=total_guilds)

            act_type_map = {
                "playing": discord.ActivityType.playing,
                "watching": discord.ActivityType.watching,
                "listening": discord.ActivityType.listening,
                "streaming": discord.ActivityType.streaming,
                "competing": discord.ActivityType.competing
            }
            activity_type = act_type_map.get(act_type_str, discord.ActivityType.watching)

            if activity_type == discord.ActivityType.streaming:
                activity = discord.Streaming(name=status_text, url="https://twitch.tv/discord")
            else:
                activity = discord.Activity(type=activity_type, name=status_text)

            await self.bot.change_presence(status=discord.Status.online, activity=activity)
            logger.info(f"Rotated status to: [{act_type_str}] {status_text}")
        except Exception as e:
            logger.debug(f"Error updating status: {e}")

    @status_rotation_task.before_loop
    async def before_rotation(self):
        await self.bot.wait_until_ready()

    status_group = app_commands.Group(name="botstatus", description="Bot status management and rotator")

    @status_group.command(name="set", description="Set a custom bot status message")
    @app_commands.describe(
        activity_type="Type of activity",
        message="Status message text",
        pause_rotator="Pause the 10-minute automatic rotator"
    )
    @app_commands.choices(activity_type=[
        app_commands.Choice(name="Playing", value="playing"),
        app_commands.Choice(name="Watching", value="watching"),
        app_commands.Choice(name="Listening", value="listening"),
        app_commands.Choice(name="Streaming", value="streaming"),
        app_commands.Choice(name="Competing", value="competing")
    ])
    @is_guild_owner()
    async def botstatus_set(
        self,
        interaction: discord.Interaction,
        activity_type: app_commands.Choice[str],
        message: str,
        pause_rotator: bool = True
    ):
        act_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "streaming": discord.ActivityType.streaming,
            "competing": discord.ActivityType.competing
        }
        atype = act_map.get(activity_type.value, discord.ActivityType.playing)

        if atype == discord.ActivityType.streaming:
            activity = discord.Streaming(name=message, url="https://twitch.tv/discord")
        else:
            activity = discord.Activity(type=atype, name=message)

        await self.bot.change_presence(status=discord.Status.online, activity=activity)
        if pause_rotator:
            self.custom_status_override = message
        else:
            self.custom_status_override = None

        await interaction.response.send_message(
            embed=success_embed(
                "Status Updated",
                f"Bot activity set to **{activity_type.name}**: `{message}`\n"
                f"Auto-Rotator: `{'Paused' if pause_rotator else 'Active'}`"
            ),
            ephemeral=True
        )

    @status_group.command(name="resume_rotator", description="Resume the 10-minute status rotator with 100+ presets")
    @is_guild_owner()
    async def botstatus_resume(self, interaction: discord.Interaction):
        self.custom_status_override = None
        self.rotator_enabled = True
        await interaction.response.send_message(
            embed=success_embed("Rotator Resumed", "The 10-minute status rotator is now active across 100+ presets."),
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(StatusRotatorCog(bot))
