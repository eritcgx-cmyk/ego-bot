"""
Automated Status & Game Activity Rotator Cog for Ego Bot (1-Minute Cycle & Custom Activities)
"""
import random
from typing import Optional, List, Dict
import discord
from discord import app_commands
from discord.ext import commands, tasks
from utils.permissions import is_guild_owner, is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from config import INFO_COLOR, SUCCESS_COLOR, logger

# 100+ Categorized Status Presets for 1-Minute Cycle
STATUS_PRESETS = [
    # Category 1: Gaming Activities & Rich Presets (25)
    ("game", "Roblox", "Grinding in Blox Fruits with the squad"),
    ("game", "Roblox", "Building in Developer Studio"),
    ("game", "Roblox", "Winning in Bedwars"),
    ("game", "Valorant", "Ranked Competitive • Radiant"),
    ("game", "Minecraft", "Surviving on Hardcore SMP"),
    ("game", "Grand Theft Auto VI", "Exploring Vice City"),
    ("game", "League of Legends", "Climbing to Challenger"),
    ("game", "Counter-Strike 2", "Premier Matchmaking"),
    ("game", "Fortnite", "Unranked to Unreal"),
    ("game", "Call of Duty: Warzone", "Securing the Victory Royale"),
    ("game", "Overwatch 2", "Grandmaster Support"),
    ("game", "Apex Legends", "Predator Ranked Grind"),
    ("game", "Cyberpunk 2077", "Roaming Night City"),
    ("game", "Rocket League", "Supersonic Legend 2v2"),
    ("game", "Elden Ring: Shadow of the Erdtree", "Defeating Consort Radahn"),
    ("game", "Rust", "Defending the Main Base"),
    ("game", "Rainbow Six Siege", "Ranked Champion 5-Stack"),
    ("game", "Garry's Mod", "DarkRP Mayor"),
    ("game", "Dead by Daylight", "Surviving the Entity"),
    ("game", "Phasmophobia", "Nightmare Hunt"),
    ("game", "Terraria", "Calamity Mod Infernum"),
    ("game", "Helldivers 2", "Spreading Managed Democracy"),
    ("game", "The Finals", "Tournament Finalists"),
    ("game", "Genshin Impact", "Spiral Abyss Floor 12"),
    ("game", "Osu!", "Clicking circles to the beat"),

    # Category 2: Advertisement Presets (25)
    ("playing", "👑 Join our VIP Hub • /help", ""),
    ("watching", "🎉 Active Giveaways • /giveaway", ""),
    ("playing", "💎 Unlock Custom Roles • /roles perks", ""),
    ("watching", "📈 Invite Leaderboards • /invites", ""),
    ("playing", "🚀 Verified Creator Ranks • /cc verify", ""),
    ("watching", "👥 Friend Groups • /fg start", ""),
    ("listening", "📜 Read Server Rules • /rules", ""),
    ("playing", "📝 Staff Applications Open • /applications", ""),
    ("watching", "🛡️ Protected by Ego Automod", ""),
    ("playing", "✨ Claim Your Roles in #verification", ""),
    ("watching", "🔥 Elite Nitro Booster Perks", ""),
    ("playing", "⚡ discord.gg/ecco • Join Now", ""),
    ("watching", "🎁 Massive Server Drops", ""),
    ("listening", "📢 Announcements in #announcements", ""),
    ("playing", "🌟 Level Up Your Invites", ""),
    ("watching", "💬 Community Chat & Voice", ""),
    ("playing", "🏆 Host Your Own Friend Group", ""),
    ("watching", "🎬 Content Creator Showcase", ""),
    ("playing", "🤖 Powered by Ego Production Engine", ""),
    ("watching", "💎 Diamond & Obsidian Status Tiers", ""),
    ("listening", "🎵 24/7 Music & Hangout", ""),
    ("playing", "🛡️ High-Security Community", ""),
    ("watching", "📊 Real-Time Server Analytics", ""),
    ("playing", "🎯 Join Giveaways Daily", ""),
    ("watching", "🚀 Explore 1200+ Role Presets", ""),

    # Category 3: Community & Scale Presets (25)
    ("watching", "{membercount} members across {guildcount} servers", ""),
    ("playing", "with {membercount} amazing members", ""),
    ("watching", "{guildcount} secure communities", ""),
    ("listening", "to {membercount} members chatting", ""),
    ("watching", "over {guildcount} active realms", ""),
    ("playing", "Ego v2.0 • Serving {membercount} users", ""),
    ("watching", "the member count grow ({membercount})", ""),
    ("listening", "to the community discussions", ""),
    ("playing", "in {guildcount} distinct server hubs", ""),
    ("watching", "new members joining every hour", ""),
    ("listening", "to voice channels & podcasts", ""),
    ("playing", "with {guildcount} guilds worldwide", ""),
    ("watching", "moderation logs & security filters", ""),
    ("playing", "managing {membercount} verified profiles", ""),
    ("watching", "friend groups collaborate in real time", ""),
    ("listening", "to staff updates & tickets", ""),
    ("playing", "24/7 Uptime • Ego Engine", ""),
    ("watching", "leaderboard rankings shift", ""),
    ("playing", "supporting {guildcount} partner hubs", ""),
    ("watching", "custom role panels refresh", ""),
    ("listening", "to verification requests", ""),
    ("playing", "active across {guildcount} Discord servers", ""),
    ("watching", "giveaways countdown to draw", ""),
    ("playing", "Ego Central Management", ""),
    ("watching", "server growth metrics", ""),

    # Category 4: Aesthetic & Flex Presets (25)
    ("playing", "⚡ Sovereign Authority", ""),
    ("watching", "💎 The Obsidian Syndicate", ""),
    ("playing", "🌙 Midnight Chroma Drift", ""),
    ("watching", "🔮 Ethereal Resonance", ""),
    ("playing", "🪐 Cosmic Horizon Phase", ""),
    ("watching", "👑 Apex Status Achieved", ""),
    ("playing", "✨ Neon Glitch Matrix", ""),
    ("watching", "🏆 Monarch Dynasty", ""),
    ("playing", "💠 Diamond Tier VIP", ""),
    ("watching", "🛡️ Sentinel Security Shield", ""),
    ("playing", "🌌 Astral Pulse Frequency", ""),
    ("watching", "⚡ High Voltage Infrastructure", ""),
    ("playing", "🔥 Infernal Sovereign", ""),
    ("watching", "❄️ Frost Radiant Aura", ""),
    ("playing", "🌀 Cyberpunk Synthwave Vibe", ""),
    ("watching", "⚜️ Imperial Council", ""),
    ("playing", "💎 Whale Status Lounge", ""),
    ("watching", "🎯 Zero Tolerance Automod", ""),
    ("playing", "🖤 Monochrome Aesthetic", ""),
    ("watching", "🌟 Star Creator Spotlight", ""),
    ("playing", "🚀 Quantum Execution Layer", ""),
    ("watching", "👑 Legendary Rank Prestige", ""),
    ("playing", "🔱 Celestial Authority", ""),
    ("watching", "💠 Platinum Standard", ""),
    ("playing", "⚡ Ego • Production Supreme", "")
]

class StatusRotatorCog(commands.Cog, name="StatusRotator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rotator_enabled = True
        self.custom_status_override: Optional[discord.Activity] = None
        self.current_index = 0
        self.status_rotation_task.start()

    def cog_unload(self):
        self.status_rotation_task.cancel()

    @tasks.loop(minutes=1)
    async def status_rotation_task(self):
        """Rotate bot activity status every 1 minute across 100+ presets."""
        if not self.rotator_enabled or self.custom_status_override:
            return

        try:
            total_members = sum(g.member_count or 0 for g in self.bot.guilds)
            total_guilds = len(self.bot.guilds)

            act_type_str, title_template, state_template = STATUS_PRESETS[self.current_index % len(STATUS_PRESETS)]
            self.current_index += 1

            title = title_template.format(membercount=f"{total_members:,}", guildcount=total_guilds)
            state = state_template.format(membercount=f"{total_members:,}", guildcount=total_guilds) if state_template else None

            if act_type_str == "game":
                # Rich Game Presence with details/state (e.g. Roblox, Minecraft)
                activity = discord.Activity(
                    type=discord.ActivityType.playing,
                    name=title,
                    state=state
                )
            elif act_type_str == "streaming":
                activity = discord.Streaming(name=title, url="https://twitch.tv/discord")
            elif act_type_str == "listening":
                activity = discord.Activity(type=discord.ActivityType.listening, name=title)
            elif act_type_str == "watching":
                activity = discord.Activity(type=discord.ActivityType.watching, name=title)
            else:
                activity = discord.Activity(type=discord.ActivityType.playing, name=title)

            await self.bot.change_presence(status=discord.Status.online, activity=activity)
            logger.info(f"Rotated 1-min status: [{act_type_str}] {title} ({state if state else ''})")
        except Exception as e:
            logger.debug(f"Error rotating status: {e}")

    @status_rotation_task.before_loop
    async def before_rotation(self):
        await self.bot.wait_until_ready()

    status_group = app_commands.Group(name="botstatus", description="Bot activity & 1-minute status rotator")

    @status_group.command(name="game", description="Set custom Game presence (e.g. Playing Roblox)")
    @app_commands.describe(
        game_name="Name of the game (e.g. Roblox, Valorant, GTA VI)",
        details="What you are doing in-game (e.g. Grinding Blox Fruits, Ranked)",
        state="Current in-game party/state",
        pause_rotator="Pause the 1-minute auto rotator"
    )
    @is_guild_owner()
    async def botstatus_game(
        self,
        interaction: discord.Interaction,
        game_name: str,
        details: Optional[str] = None,
        state: Optional[str] = None,
        pause_rotator: bool = True
    ):
        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name=game_name,
            state=details or state
        )
        await self.bot.change_presence(status=discord.Status.online, activity=activity)
        if pause_rotator:
            self.custom_status_override = activity
        else:
            self.custom_status_override = None

        await interaction.response.send_message(
            embed=success_embed(
                "Game Presence Set",
                f"🎮 **Now Playing:** `{game_name}`\n"
                f"• Details: `{details or 'None'}`\n"
                f"• Auto-Rotator: `{'Paused' if pause_rotator else 'Active (1-Min Cycle)'}`"
            ),
            ephemeral=True
        )

    @status_group.command(name="set", description="Set custom activity type and message")
    @app_commands.describe(
        activity_type="Activity Type",
        message="Status message text",
        pause_rotator="Pause the 1-minute auto rotator"
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
            self.custom_status_override = activity
        else:
            self.custom_status_override = None

        await interaction.response.send_message(
            embed=success_embed(
                "Status Updated",
                f"Bot activity set to **{activity_type.name}**: `{message}`\n"
                f"Auto-Rotator: `{'Paused' if pause_rotator else 'Active (1-Min Cycle)'}`"
            ),
            ephemeral=True
        )

    @status_group.command(name="resume_rotator", description="Resume the 1-minute status rotator with 100+ presets")
    @is_guild_owner()
    async def botstatus_resume(self, interaction: discord.Interaction):
        self.custom_status_override = None
        self.rotator_enabled = True
        await interaction.response.send_message(
            embed=success_embed("Rotator Resumed", "The 1-minute status rotator is now cycling across 100+ game & ad presets."),
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(StatusRotatorCog(bot))
