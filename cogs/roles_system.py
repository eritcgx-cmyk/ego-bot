"""
Role Presets, Special FG Roles, Live Updating Roles Board, and Custom Role Descriptions Cog for Ego Bot.
Features auto-updating roles board (live member sync), custom role descriptions (/roles set_description),
special FG milestone roles (Com FG, Known FG, Huge FG, Giant FG), and role presets.
"""
import os
import json
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import RolePanel, RolePerk
from utils.permissions import is_admin_or_has_role, is_guild_owner
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_EMERALD, COLOR_CRIMSON, COLOR_CYAN, COLOR_AMBER, COLOR_ROSE
)
from config import logger

PRESETS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "role_presets.json")
CC_REQ_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cc_tier_requirements.json")
ROLE_DESC_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "custom_role_descriptions.json")
ROLE_BOARD_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "role_boards.json")

# Special FG Milestone Roles
FG_SPECIAL_ROLES = [
    {"name": "Com FG", "color": 0x3B82F6, "desc": "Competitive Friend Group Circle"},
    {"name": "Known FG", "color": 0x8B5CF6, "desc": "Recognized Community Friend Group"},
    {"name": "Huge FG", "color": 0xF59E0B, "desc": "Large Scale Active Friend Group"},
    {"name": "Giant FG", "color": 0xEF4444, "desc": "Apex Tier Giant Friend Group"}
]

def load_role_descriptions() -> Dict[str, Any]:
    os.makedirs(os.path.dirname(ROLE_DESC_FILE), exist_ok=True)
    if not os.path.exists(ROLE_DESC_FILE):
        return {}
    try:
        with open(ROLE_DESC_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_role_descriptions(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(ROLE_DESC_FILE), exist_ok=True)
    with open(ROLE_DESC_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_board_states() -> List[Dict[str, Any]]:
    os.makedirs(os.path.dirname(ROLE_BOARD_STATE_FILE), exist_ok=True)
    if not os.path.exists(ROLE_BOARD_STATE_FILE):
        return []
    try:
        with open(ROLE_BOARD_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_board_states(data: List[Dict[str, Any]]):
    os.makedirs(os.path.dirname(ROLE_BOARD_STATE_FILE), exist_ok=True)
    with open(ROLE_BOARD_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_tier_requirements() -> Dict[str, Any]:
    if os.path.exists(CC_REQ_FILE):
        try:
            with open(CC_REQ_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

class RolesSystemCog(commands.Cog, name="Roles"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.presets = self._load_presets()
        self.auto_refresh_boards.start()

    def cog_unload(self):
        self.auto_refresh_boards.cancel()

    def _load_presets(self) -> List[Dict[str, Any]]:
        if not os.path.exists(PRESETS_FILE):
            return []
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    async def build_roles_board_embed(self, guild: discord.Guild) -> discord.Embed:
        """Constructs the live Roles Board with descriptions, requirements, and user mentions."""
        reqs = get_tier_requirements()
        custom_descs = load_role_descriptions()

        embed = ego_embed(
            title=f"Role Roster - Roles",
            description=f"> Active roles, members, and descriptions in **{guild.name}**:\n",
            color=COLOR_VIOLET
        )

        # 1. Content Creator Roles
        cc_names = ["CC", "CC Tier 2", "CC Tier 3", "Known", "Famous", "Star"]
        cc_entries = []
        for name in cc_names:
            role = discord.utils.get(guild.roles, name=name)
            if role:
                members_list = [m.mention for m in role.members[:15]]
                members_str = ", ".join(members_list) if members_list else "*No members*"
                if len(role.members) > 15:
                    members_str += f" *(+{len(role.members) - 15} more)*"

                r_data = reqs.get(name, {})
                f_req = r_data.get("followers", "")
                v_req = r_data.get("views", "")
                desc_text = custom_descs.get(str(role.id), {}).get("desc", r_data.get("desc", ""))

                line = f"› {role.mention} `({len(role.members)})` — {members_str}"
                if f_req or v_req:
                    line += f"\n  *Req: {f_req} Followers / {v_req} Views*"
                if desc_text:
                    line += f"\n  *{desc_text}*"
                cc_entries.append(line)

        if cc_entries:
            embed.add_field(name="✦ Creator Roles (/cc verify)", value="\n\n".join(cc_entries), inline=False)

        # 2. Friend Group (FG) Roles
        fg_names = ["Giant FG", "Huge FG", "Known FG", "Com FG"]
        fg_entries = []
        for name in fg_names:
            role = discord.utils.get(guild.roles, name=name)
            if role:
                members_list = [m.mention for m in role.members[:15]]
                members_str = ", ".join(members_list) if members_list else "*No members*"
                if len(role.members) > 15:
                    members_str += f" *(+{len(role.members) - 15} more)*"

                desc_text = custom_descs.get(str(role.id), {}).get("desc", "")
                line = f"› {role.mention} `({len(role.members)})` — {members_str}"
                if desc_text:
                    line += f"\n  *{desc_text}*"
                fg_entries.append(line)

        # Also add dynamic private FG roles (prefixed with 👑 ︱)
        for role in guild.roles:
            if role.name.startswith("👑 ︱ "):
                members_list = [m.mention for m in role.members[:10]]
                members_str = ", ".join(members_list) if members_list else "*No members*"
                desc_text = custom_descs.get(str(role.id), {}).get("desc", "Private Friend Group Suite")
                fg_entries.append(f"› {role.mention} `({len(role.members)})` — {members_str}\n  *{desc_text}*")

        if fg_entries:
            embed.add_field(name="✦ Friend Group Roles (/fg start)", value="\n\n".join(fg_entries[:12]), inline=False)

        # 3. Custom Registered Roles (configured via /roles set_description)
        custom_entries = []
        for role_id_str, info in custom_descs.items():
            try:
                role = guild.get_role(int(role_id_str))
                if role and role.name not in cc_names and role.name not in fg_names and not role.name.startswith("👑 ︱ "):
                    members_list = [m.mention for m in role.members[:15]]
                    members_str = ", ".join(members_list) if members_list else "*No members*"
                    desc_text = info.get("desc", "")
                    req_text = info.get("req", "")

                    line = f"› {role.mention} `({len(role.members)})` — {members_str}"
                    if req_text:
                        line += f"\n  *Req: {req_text}*"
                    if desc_text:
                        line += f"\n  *{desc_text}*"
                    custom_entries.append(line)
            except Exception:
                pass

        if custom_entries:
            embed.add_field(name="✦ Featured Server Roles", value="\n\n".join(custom_entries[:10]), inline=False)

        return embed

    @tasks.loop(minutes=2)
    async def auto_refresh_boards(self):
        """Automatically keeps all deployed Role Boards updated across channels."""
        boards = load_board_states()
        updated_boards = []

        for b in boards:
            guild = self.bot.get_guild(b.get("guild_id", 0))
            if not guild:
                continue
            channel = guild.get_channel(b.get("channel_id", 0))
            if not channel or not isinstance(channel, discord.TextChannel):
                continue

            try:
                msg = await channel.fetch_message(b.get("message_id", 0))
                embed = await self.build_roles_board_embed(guild)
                await msg.edit(embed=embed)
                updated_boards.append(b)
            except discord.NotFound:
                # Message deleted, skip storing
                pass
            except Exception as e:
                logger.debug(f"Could not auto-refresh role board: {e}")
                updated_boards.append(b)

        if len(boards) != len(updated_boards):
            save_board_states(updated_boards)

    @auto_refresh_boards.before_loop
    async def before_auto_refresh(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Trigger instant update when member roles change."""
        if before.roles != after.roles:
            await self._trigger_board_refresh_for_guild(after.guild)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        """Trigger instant update when a role is modified."""
        await self._trigger_board_refresh_for_guild(after.guild)

    async def _trigger_board_refresh_for_guild(self, guild: discord.Guild):
        boards = load_board_states()
        for b in boards:
            if b.get("guild_id") == guild.id:
                ch = guild.get_channel(b.get("channel_id", 0))
                if ch and isinstance(ch, discord.TextChannel):
                    try:
                        msg = await ch.fetch_message(b.get("message_id", 0))
                        embed = await self.build_roles_board_embed(guild)
                        await msg.edit(embed=embed)
                    except Exception:
                        pass

    roles_group = app_commands.Group(name="roles", description="Role library, presets, perks, and live panels")

    @roles_group.command(name="board", description="Deploy the auto-updating Roles Board with live member roster")
    @app_commands.describe(channel="Target channel for the Roles Board")
    @is_admin_or_has_role()
    async def roles_board(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild

        embed = await self.build_roles_board_embed(guild)
        msg = await target_ch.send(embed=embed)

        # Save board state for auto-updates
        boards = load_board_states()
        # Remove any existing board in the same channel
        boards = [b for b in boards if b.get("channel_id") != target_ch.id]
        boards.append({
            "guild_id": guild.id,
            "channel_id": target_ch.id,
            "message_id": msg.id
        })
        save_board_states(boards)

        await interaction.response.send_message(
            embed=success_embed("Roles Board Deployed", f"Live auto-updating Roles Board published in {target_ch.mention}."),
            ephemeral=True
        )

    @roles_group.command(name="set_description", description="Set custom description and requirements for any role on the board")
    @app_commands.describe(
        role="The role to describe",
        description="Description of perks / meaning",
        requirements="Requirements to obtain this role (optional)"
    )
    @is_admin_or_has_role()
    async def roles_set_desc(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        description: str,
        requirements: Optional[str] = None
    ):
        custom_descs = load_role_descriptions()
        custom_descs[str(role.id)] = {
            "name": role.name,
            "desc": description.strip(),
            "req": requirements.strip() if requirements else ""
        }
        save_role_descriptions(custom_descs)

        # Immediately refresh boards
        await self._trigger_board_refresh_for_guild(interaction.guild)

        await interaction.response.send_message(
            embed=success_embed(
                "Role Description Saved",
                f"Updated description for {role.mention}:\n"
                f"› **Description:** *{description.strip()}*\n"
                + (f"› **Requirements:** `{requirements.strip()}`\n" if requirements else "")
                + "\n*The live Roles Board has been updated.*"
            ),
            ephemeral=True
        )

    @roles_group.command(name="setup_fg_roles", description="Auto-create special FG milestone roles (Com FG, Known FG, Huge FG, Giant FG)")
    @is_guild_owner()
    async def roles_setup_fg_roles(self, interaction: discord.Interaction):
        guild = interaction.guild
        created = []
        for r_data in FG_SPECIAL_ROLES:
            existing = discord.utils.get(guild.roles, name=r_data["name"])
            if not existing:
                try:
                    role = await guild.create_role(
                        name=r_data["name"],
                        color=discord.Color(r_data["color"]),
                        mentionable=True,
                        reason="Ego FG Special Role Setup"
                    )
                    created.append(role.name)
                except Exception as e:
                    logger.error(f"Error creating FG role {r_data['name']}: {e}")

        # Refresh board
        await self._trigger_board_refresh_for_guild(guild)

        await interaction.response.send_message(
            embed=success_embed(
                "FG Roles Ready",
                f"Configured all 4 special FG milestone roles in the server:\n"
                f"› `Com FG`, `Known FG`, `Huge FG`, `Giant FG`"
            ),
            ephemeral=True
        )

    @roles_group.command(name="import_presets", description="Bulk import preset roles from catalog into server")
    @app_commands.describe(
        category="Category to import",
        count="Number of roles to import (max 15)"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="Content Creator", value="Content Creator"),
        app_commands.Choice(name="Verified", value="Verified"),
        app_commands.Choice(name="Mod", value="Mod"),
        app_commands.Choice(name="Rich / Status", value="Rich/Status"),
        app_commands.Choice(name="Custom", value="Custom")
    ])
    @is_guild_owner()
    async def roles_import_presets(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        count: int = 5
    ):
        await interaction.response.defer(ephemeral=True)
        count = max(1, min(count, 15))

        filtered = [p for p in self.presets if p["category"] == category.value]
        if not filtered:
            return await interaction.followup.send(embed=error_embed("No Presets", "No presets found for this category."))

        created_roles = []
        for p in filtered[:count]:
            existing = discord.utils.get(interaction.guild.roles, name=p["name"])
            if not existing:
                try:
                    c = int(p["color_hex"].replace("#", ""), 16) if "color_hex" in p else 0x8B5CF6
                    role = await interaction.guild.create_role(name=p["name"], color=discord.Color(c), reason="Ego Presets Import")
                    created_roles.append(role.name)
                except Exception as e:
                    logger.error(f"Failed to create role {p['name']}: {e}")

        await interaction.followup.send(
            embed=success_embed("Presets Imported", f"Created **{len(created_roles)}** roles for **{category.value}**.")
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(RolesSystemCog(bot))
