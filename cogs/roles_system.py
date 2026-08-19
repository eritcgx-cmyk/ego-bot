"""
Role Presets, Special FG Roles, Live Auto-Updating Roles Board, and Custom Role Descriptions Cog for Ego Bot.
Features comprehensive Roles Board listing ALL server roles with @mentions, descriptions & member lists,
instant auto-updating on member/role events, custom role descriptions (/roles set_description),
and special FG milestone roles.
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

    async def build_roles_board_embeds(self, guild: discord.Guild) -> List[discord.Embed]:
        """Constructs rich Roles Board embeds listing ALL server roles with @mentions, descriptions, and members."""
        reqs = get_tier_requirements()
        custom_descs = load_role_descriptions()

        # Get all roles sorted from highest hierarchy position to lowest
        valid_roles = [
            r for r in guild.roles
            if r.name != "@everyone" and not r.managed
        ]
        valid_roles.sort(key=lambda r: r.position, reverse=True)

        if not valid_roles:
            return [ego_embed(
                title="Roles",
                description=f"> No custom roles found in **{guild.name}**.\n> Create roles in Discord or use `/roles import_presets`!",
                color=COLOR_VIOLET
            )]

        embeds = []
        current_embed = ego_embed(
            title="Roles",
            description=f"> Complete directory of all **`{len(valid_roles)}`** server roles, descriptions, and members:\n",
            color=COLOR_VIOLET
        )

        field_count = 0
        for role in valid_roles:
            # 1. Resolve Description and Requirements
            desc_text = ""
            req_text = ""

            if str(role.id) in custom_descs:
                desc_text = custom_descs[str(role.id)].get("desc", "")
                req_text = custom_descs[str(role.id)].get("req", "")
            elif role.name in reqs:
                r_info = reqs[role.name]
                desc_text = r_info.get("desc", "")
                f_val = r_info.get("followers", "")
                v_val = r_info.get("views", "")
                req_text = f"{f_val} Followers / {v_val} Views" if f_val or v_val else ""
            else:
                for fg_r in FG_SPECIAL_ROLES:
                    if fg_r["name"] == role.name:
                        desc_text = fg_r["desc"]
                        break

            # 2. Resolve Member mentions
            members_list = [m.mention for m in role.members[:15]]
            members_str = ", ".join(members_list) if members_list else "*No members*"
            if len(role.members) > 15:
                members_str += f" *(+{len(role.members) - 15} more)*"

            # 3. Format Field Value with direct @mention
            val_lines = [f"• **Role:** {role.mention}"]
            if desc_text:
                val_lines.append(f"• **Description:** *{desc_text}*")
            if req_text:
                val_lines.append(f"• **Requirement:** `{req_text}`")
            val_lines.append(f"• **Members ({len(role.members)}):** {members_str}")

            field_val = "\n".join(val_lines)
            if len(field_val) > 1020:
                field_val = field_val[:1015] + "..."

            # Discord embeds allow max 25 fields
            if field_count >= 24:
                embeds.append(current_embed)
                current_embed = ego_embed(
                    title="Roles (Continued)",
                    color=COLOR_VIOLET
                )
                field_count = 0

            current_embed.add_field(
                name=f"› {role.name}",
                value=field_val,
                inline=False
            )
            field_count += 1

        embeds.append(current_embed)
        return embeds

    @tasks.loop(seconds=45)
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
                embeds = await self.build_roles_board_embeds(guild)
                await msg.edit(embed=embeds[0])
                updated_boards.append(b)
            except discord.NotFound:
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
        """Trigger instant board update when member roles change."""
        if before.roles != after.roles:
            await self._trigger_board_refresh_for_guild(after.guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._trigger_board_refresh_for_guild(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._trigger_board_refresh_for_guild(member.guild)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._trigger_board_refresh_for_guild(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._trigger_board_refresh_for_guild(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        await self._trigger_board_refresh_for_guild(after.guild)

    async def _trigger_board_refresh_for_guild(self, guild: discord.Guild):
        boards = load_board_states()
        for b in boards:
            if b.get("guild_id") == guild.id:
                ch = guild.get_channel(b.get("channel_id", 0))
                if ch and isinstance(ch, discord.TextChannel):
                    try:
                        msg = await ch.fetch_message(b.get("message_id", 0))
                        embeds = await self.build_roles_board_embeds(guild)
                        await msg.edit(embed=embeds[0])
                    except Exception:
                        pass

    roles_group = app_commands.Group(name="roles", description="Role library, presets, perks, and live panels")

    @roles_group.command(name="board", description="Deploy the live auto-updating Roles Board listing all server roles and members")
    @app_commands.describe(channel="Target channel for the Roles Board")
    @is_admin_or_has_role()
    async def roles_board(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild

        embeds = await self.build_roles_board_embeds(guild)
        msg = await target_ch.send(embed=embeds[0])

        boards = load_board_states()
        boards = [b for b in boards if b.get("channel_id") != target_ch.id]
        boards.append({
            "guild_id": guild.id,
            "channel_id": target_ch.id,
            "message_id": msg.id
        })
        save_board_states(boards)

        await interaction.response.send_message(
            embed=success_embed("Roles Board Deployed", f"Live auto-updating Roles Board is active in {target_ch.mention}."),
            ephemeral=True
        )

    @roles_group.command(name="set_description", description="Set custom description and requirements for any role on the board")
    @app_commands.describe(
        role="The role to describe",
        description="Description of perks or meaning",
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

        # Immediately update all deployed boards
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

        await self._trigger_board_refresh_for_guild(interaction.guild)

        await interaction.followup.send(
            embed=success_embed("Presets Imported", f"Created **{len(created_roles)}** roles for **{category.value}**.")
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(RolesSystemCog(bot))
