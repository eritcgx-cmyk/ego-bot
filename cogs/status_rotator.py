"""
Dynamic Custom Status & Activity Manager for Ego Bot
Allows users/owners to type any custom status or game activity, auto-saves to a reusable list,
and supports instant loading, deletion, and 1-minute auto-rotation across saved statuses.
"""
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands, tasks
from utils.permissions import is_admin_or_has_role, is_guild_owner
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from config import INFO_COLOR, SUCCESS_COLOR, logger

STATUS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "saved_statuses.json")

class CustomStatusManager:
    @staticmethod
    def load_statuses() -> List[Dict[str, Any]]:
        from utils.kv_store import get_cached_kv
        cached = get_cached_kv("saved_statuses")
        if cached is not None and isinstance(cached, list) and len(cached) > 0:
            return cached

        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data:
                        return data
            except Exception as e:
                logger.error(f"Failed to load saved statuses: {e}")
        # Default starting list with user-customizable games
        defaults = [
            {"id": 1, "type": "playing", "text": "Roblox", "details": "Grinding with friends", "url": None, "author": "Default"},
            {"id": 2, "type": "playing", "text": "Grand Theft Auto VI", "details": "Exploring Vice City", "url": None, "author": "Default"},
            {"id": 3, "type": "watching", "text": "you keep /egoing me", "details": None, "url": None, "author": "Default"},
            {"id": 4, "type": "playing", "text": "Valorant", "details": "Ranked Radiant", "url": None, "author": "Default"},
            {"id": 5, "type": "streaming", "text": "Live Stream Highlights", "details": None, "url": "https://twitch.tv/discord", "author": "Default"}
        ]
        CustomStatusManager.save_statuses(defaults)
        return defaults

    @staticmethod
    def save_statuses(statuses: List[Dict[str, Any]]):
        from utils.kv_store import set_cached_kv_and_schedule_save
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        try:
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(statuses, f, indent=2)
        except Exception:
            pass
        set_cached_kv_and_schedule_save("saved_statuses", statuses)

class StatusSelectView(discord.ui.View):
    def __init__(self, statuses: List[Dict[str, Any]], cog: "CustomStatusCog"):
        super().__init__(timeout=120)
        self.cog = cog
        self.statuses = statuses

        options = []
        for s in statuses[:25]: # Discord select menu limit
            emoji = "🎮" if s["type"] == "playing" else "📺" if s["type"] == "streaming" else "👀" if s["type"] == "watching" else "🎧" if s["type"] == "listening" else "🏆"
            desc = s.get("details") or f"Type: {s['type'].title()}"
            options.append(discord.SelectOption(
                label=f"#{s['id']} {s['text'][:70]}",
                description=desc[:100],
                value=str(s["id"]),
                emoji=emoji
            ))

        if options:
            self.select_menu.options = options
        else:
            self.remove_item(self.select_menu)

    @discord.ui.select(placeholder="Choose a saved status to apply immediately...", min_values=1, max_values=1)
    async def select_menu(self, interaction: discord.Interaction, select_comp: discord.ui.Select):
        chosen_id = int(select_comp.values[0])
        status_entry = next((s for s in self.statuses if s["id"] == chosen_id), None)

        if not status_entry:
            return await interaction.response.send_message("❌ Status entry not found.", ephemeral=True)

        await self.cog.apply_status_entry(status_entry)
        await interaction.response.send_message(
            embed=success_embed(
                "Status Loaded",
                f"✅ Applied Saved Status #{chosen_id}:\n"
                f"• **Type:** `{status_entry['type'].title()}`\n"
                f"• **Text:** `{status_entry['text']}`\n"
                + (f"• **Details:** `{status_entry['details']}`\n" if status_entry.get('details') else "")
            ),
            ephemeral=True
        )

class CustomStatusCog(commands.Cog, name="CustomStatus"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.statuses = CustomStatusManager.load_statuses()
        self.auto_rotate_enabled = True
        self.current_index = 0
        self.custom_override = None

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rotator_task.is_running():
            self.rotator_task.start()

    def cog_unload(self):
        if self.rotator_task.is_running():
            self.rotator_task.cancel()



    async def apply_status_entry(self, entry: Dict[str, Any]):
        """Apply a status dict to bot presence."""
        stype = entry.get("type", "playing").lower()
        text = entry.get("text", "Ego Bot")
        details = entry.get("details")
        url = entry.get("url")

        type_map = {
            "playing": discord.ActivityType.playing,
            "streaming": discord.ActivityType.streaming,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
            "custom": discord.ActivityType.custom
        }
        act_type = type_map.get(stype, discord.ActivityType.playing)

        if act_type == discord.ActivityType.streaming:
            activity = discord.Streaming(name=text, url=url or "https://twitch.tv/discord")
        elif act_type == discord.ActivityType.custom:
            activity = discord.CustomActivity(name=text)
        else:
            activity = discord.Activity(
                type=act_type,
                name=text,
                state=details
            )

        await self.bot.change_presence(status=discord.Status.online, activity=activity)
        self.custom_override = activity
        logger.info(f"Applied status: [{stype}] {text} (Details: {details})")

    @tasks.loop(minutes=1)
    async def rotator_task(self):
        """1-minute rotator cycling through user's saved statuses list."""
        if not self.auto_rotate_enabled or self.custom_override:
            return

        if not self.statuses:
            return

        try:
            entry = self.statuses[self.current_index % len(self.statuses)]
            self.current_index += 1
            await self.apply_status_entry(entry)
            self.custom_override = None # Keep in rotation mode
        except Exception as e:
            logger.debug(f"Rotator error: {e}")

    @rotator_task.before_loop
    async def before_rotator(self):
        await self.bot.wait_until_ready()

    status_group = app_commands.Group(
        name="status",
        description="Custom status & activity manager",
        default_permissions=discord.Permissions(administrator=True)
    )

    @status_group.command(name="set", description="Set a custom status or activity")
    @app_commands.describe(
        activity_type="Activity Type",
        text="Status text or game name",
        details="In-game state or details",
        stream_url="Stream link if activity is Streaming",
        save_to_list="Save to your reusable status library"
    )
    @app_commands.choices(activity_type=[
        app_commands.Choice(name="Playing", value="playing"),
        app_commands.Choice(name="Streaming", value="streaming"),
        app_commands.Choice(name="Watching", value="watching"),
        app_commands.Choice(name="Listening", value="listening"),
        app_commands.Choice(name="Competing", value="competing"),
        app_commands.Choice(name="Custom", value="custom")
    ])
    @is_admin_or_has_role()
    async def status_set(
        self,
        interaction: discord.Interaction,
        activity_type: app_commands.Choice[str],
        text: str,
        details: Optional[str] = None,
        stream_url: Optional[str] = None,
        save_to_list: bool = True
    ):

        stype = activity_type.value
        entry = {
            "type": stype,
            "text": text.strip(),
            "details": details.strip() if details else None,
            "url": stream_url.strip() if stream_url else None,
            "author": interaction.user.name,
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        }

        if save_to_list:
            next_id = max([s["id"] for s in self.statuses], default=0) + 1
            entry["id"] = next_id
            self.statuses.append(entry)
            CustomStatusManager.save_statuses(self.statuses)

        await self.apply_status_entry(entry)
        saved_msg = f" (Saved to list as `#{entry.get('id', 'N/A')}`)" if save_to_list else ""

        await interaction.response.send_message(
            embed=success_embed(
                "Status Updated",
                f"✅ **Active Presence Updated!**{saved_msg}\n\n"
                f"• **Type:** `{activity_type.name}`\n"
                f"• **Text / Game:** `{text}`\n"
                + (f"• **Details:** `{details}`\n" if details else "")
                + (f"• **Stream URL:** [Link]({stream_url})\n" if stream_url else "")
            )
        )

    @status_group.command(name="list", description="View all saved custom statuses and select one to apply")
    @is_admin_or_has_role()
    async def status_list(self, interaction: discord.Interaction):

        self.statuses = CustomStatusManager.load_statuses()
        if not self.statuses:
            return await interaction.response.send_message(
                embed=info_embed("Saved Statuses", "No saved statuses found. Run `/status set` to create one!"),
                ephemeral=True
            )

        embed = ego_embed(
            title=f"📋 Saved Statuses Library ({len(self.statuses)})",
            description="Select any status from the dropdown below to apply it immediately to the bot:\n",
            color=INFO_COLOR
        )

        for s in self.statuses[:15]:
            emoji = "🎮" if s["type"] == "playing" else "📺" if s["type"] == "streaming" else "👀" if s["type"] == "watching" else "🎧" if s["type"] == "listening" else "🏆"
            desc_line = f"• Details: `{s.get('details')}`" if s.get("details") else ""
            embed.add_field(
                name=f"{emoji} ID #{s['id']}: {s['text']} ({s['type'].title()})",
                value=f"{desc_line}\n*By: {s.get('author', 'Admin')}*",
                inline=False
            )

        view = StatusSelectView(self.statuses, self)
        await interaction.response.send_message(embed=embed, view=view)

    @status_group.command(name="load", description="Load and apply a saved status by ID")
    @app_commands.describe(status_id="The ID of the saved status")
    async def status_load(self, interaction: discord.Interaction, status_id: int):
        self.statuses = CustomStatusManager.load_statuses()
        entry = next((s for s in self.statuses if s["id"] == status_id), None)

        if not entry:
            return await interaction.response.send_message(
                embed=error_embed("Not Found", f"No saved status found with ID #{status_id}."),
                ephemeral=True
            )

        await self.apply_status_entry(entry)
        await interaction.response.send_message(
            embed=success_embed(
                "Status Loaded",
                f"✅ Applied Status #{status_id}: **[{entry['type'].title()}]** `{entry['text']}`"
            )
        )

    @status_group.command(name="delete", description="Delete a saved status from the library")
    @app_commands.describe(status_id="The ID of the status to remove")
    @is_admin_or_has_role()
    async def status_delete(self, interaction: discord.Interaction, status_id: int):
        self.statuses = CustomStatusManager.load_statuses()
        entry = next((s for s in self.statuses if s["id"] == status_id), None)

        if not entry:
            return await interaction.response.send_message(
                embed=error_embed("Not Found", f"No saved status found with ID #{status_id}."),
                ephemeral=True
            )

        self.statuses = [s for s in self.statuses if s["id"] != status_id]
        CustomStatusManager.save_statuses(self.statuses)

        await interaction.response.send_message(
            embed=success_embed("Status Deleted", f"Removed Status #{status_id} (`{entry['text']}`).")
        )

    @status_group.command(name="auto_rotate", description="Toggle 1-minute auto-rotation across your saved list")
    @app_commands.describe(enabled="Enable (True) or Disable (False)")
    @is_admin_or_has_role()
    async def status_auto_rotate(self, interaction: discord.Interaction, enabled: bool):
        self.auto_rotate_enabled = enabled
        self.custom_override = None if enabled else self.custom_override

        status_str = "Active (cycling every 1 minute across saved statuses)" if enabled else "Disabled (current status locked)"
        await interaction.response.send_message(
            embed=success_embed("Auto-Rotation Updated", f"1-Minute Status Rotator is now **{status_str}**.")
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(CustomStatusCog(bot))
