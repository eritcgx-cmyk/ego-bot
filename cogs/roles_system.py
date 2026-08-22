"""
Role Presets, Special FG Roles, Live Auto-Updating Roles Board, Custom Role Descriptions, and Clean Server for Ego Bot.
Features complete dynamic role rendering showing 100% of all server roles without limits or truncation,
instant real-time event updates, custom role descriptions (/roles set_description), and /clean_server duplicate role cleaner.
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

FG_SPECIAL_ROLES = ["Giant FG", "Huge FG", "Known FG", "Com FG", "FG"]
CC_ROLE_NAMES = ["Star", "Famous", "Known", "CC Tier 3", "CC Tier 2", "CC", "CC Partner"]

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
        """Constructs the comprehensive Roles Board listing ALL server roles without truncation."""
        try:
            if not guild.chunked:
                await guild.chunk()
        except Exception:
            pass

        reqs = get_tier_requirements()
        custom_descs = load_role_descriptions()

        # All server roles deduplicated, sorted by hierarchy position descending
        seen_ids = set()
        all_roles = []
        for r in guild.roles:
            if r.name != "@everyone" and r.id not in seen_ids:
                seen_ids.add(r.id)
                all_roles.append(r)

        all_roles.sort(key=lambda r: r.position, reverse=True)

        if not all_roles:
            return [ego_embed(
                title="Roles",
                description=f"> No custom roles found in **{guild.name}**.\n> Create roles in Discord or use `/roles import_presets`!",
                color=COLOR_VIOLET
            )]

        def format_role_line(role: discord.Role) -> str:
            # Members list (first 8 mentions)
            members = [m.mention for m in role.members[:8]]
            members_str = ", ".join(members) if members else "*None*"
            if len(role.members) > 8:
                members_str += f" *(+{len(role.members) - 8} more)*"

            # Resolve description or requirements
            desc_sub = ""
            if str(role.id) in custom_descs:
                d_info = custom_descs[str(role.id)]
                d_text = d_info.get("desc", "")
                r_text = d_info.get("req", "")
                if r_text and d_text:
                    desc_sub = f"  *Req: {r_text} | {d_text}*"
                elif r_text:
                    desc_sub = f"  *Req: {r_text}*"
                elif d_text:
                    desc_sub = f"  *{d_text}*"
            elif role.name in reqs:
                r_info = reqs[role.name]
                f_val = r_info.get("followers", "")
                v_val = r_info.get("views", "")
                d_val = r_info.get("desc", "")
                if f_val or v_val:
                    desc_sub = f"  *Req: {f_val} Followers / {v_val} | {d_val}*"
                else:
                    desc_sub = f"  *{d_val}*"
            elif role.name in ["Giant FG", "Huge FG", "Known FG", "Com FG"]:
                desc_sub = "  *Special FG Milestone Perk Role*"
            elif role.name.startswith("👑 ︱ "):
                desc_sub = "  *Private Friend Group Suite Role*"

            line = f"› {role.mention} `({len(role.members)})` — {members_str}"
            if desc_sub:
                line += f"\n{desc_sub}"
            return line

        # Split all roles into logical categories
        cc_roles = [r for r in all_roles if r.name in CC_ROLE_NAMES]
        fg_roles = [r for r in all_roles if r.name in FG_SPECIAL_ROLES or r.name.startswith("👑 ︱ ")]
        other_roles = [r for r in all_roles if r not in cc_roles and r not in fg_roles]

        categories_to_process = [
            ("✦ Content Creator Roles (/cc verify)", cc_roles),
            ("✦ Friend Group Roles (/fg start)", fg_roles),
            ("✦ Server Roles", other_roles)
        ]

        embeds: List[discord.Embed] = []
        current_embed = ego_embed(
            title="Roles",
            description=f"> Complete directory of all **`{len(all_roles)}`** roles and active members in **{guild.name}**:\n",
            color=COLOR_VIOLET
        )
        current_embed_char_count = len(current_embed.title or "") + len(current_embed.description or "")
        field_count = 0

        for cat_title, role_list in categories_to_process:
            if not role_list:
                continue

            # Build all lines for this entire category (NO SLICING!)
            formatted_lines = [format_role_line(r) for r in role_list]

            # Chunk lines into batches that strictly fit within 1,024 characters per field
            batches: List[str] = []
            curr_batch: List[str] = []
            curr_len = 0

            for line in formatted_lines:
                line_len = len(line) + 2  # newline buffer
                if curr_len + line_len > 1000 and curr_batch:
                    batches.append("\n\n".join(curr_batch))
                    curr_batch = [line]
                    curr_len = line_len
                else:
                    curr_batch.append(line)
                    curr_len += line_len

            if curr_batch:
                batches.append("\n\n".join(curr_batch))

            for i, batch_val in enumerate(batches):
                field_name = cat_title if len(batches) == 1 else f"{cat_title} (Part {i+1})"
                field_chars = len(field_name) + len(batch_val)

                # Check if current embed is full (max 20 fields or > 5000 chars)
                if field_count >= 20 or (current_embed_char_count + field_chars > 5000):
                    embeds.append(current_embed)
                    current_embed = ego_embed(
                        title="Roles (Continued)",
                        color=COLOR_VIOLET
                    )
                    current_embed_char_count = len(current_embed.title or "")
                    field_count = 0

                current_embed.add_field(name=field_name, value=batch_val, inline=False)
                field_count += 1
                current_embed_char_count += field_chars

        if field_count > 0:
            embeds.append(current_embed)

        return embeds

    @tasks.loop(seconds=30)
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
                await msg.edit(embeds=embeds)
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
        if not guild:
            return
        boards = load_board_states()
        for b in boards:
            if b.get("guild_id") == guild.id:
                ch = guild.get_channel(b.get("channel_id", 0))
                if ch and isinstance(ch, discord.TextChannel):
                    try:
                        msg = await ch.fetch_message(b.get("message_id", 0))
                        embeds = await self.build_roles_board_embeds(guild)
                        await msg.edit(embeds=embeds)
                    except Exception as e:
                        logger.error(f"Error editing board message in #{ch.name}: {e}")

    roles_group = app_commands.Group(
        name="roles",
        description="Role library, presets, perks, and live panels",
        default_permissions=discord.Permissions(manage_roles=True)
    )

    @roles_group.command(name="board", description="Deploy the live auto-updating Roles Board listing all server roles and members")
    @app_commands.describe(channel="Target channel for the Roles Board")
    @is_admin_or_has_role()
    async def roles_board(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild

        await interaction.response.defer(ephemeral=True)
        embeds = await self.build_roles_board_embeds(guild)
        msg = await target_ch.send(embeds=embeds)

        boards = load_board_states()
        boards = [b for b in boards if b.get("channel_id") != target_ch.id]
        boards.append({
            "guild_id": guild.id,
            "channel_id": target_ch.id,
            "message_id": msg.id
        })
        save_board_states(boards)

        await interaction.followup.send(
            embed=success_embed("Roles Board Deployed", f"Live auto-updating Roles Board is active in {target_ch.mention} (listing all `{len(guild.roles) - 1}` roles)."),
            ephemeral=True
        )

    @app_commands.command(name="roles_board", description="Deploy the live auto-updating Roles Board to a channel")
    @app_commands.describe(channel="Target channel for the Roles Board")
    @app_commands.default_permissions(manage_roles=True)
    @is_admin_or_has_role()
    async def roles_board_alias(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await self.roles_board(interaction, channel)

    @app_commands.command(name="roleboard", description="Deploy the live auto-updating Roles Board to a channel (alias)")
    @app_commands.describe(channel="Target channel for the Roles Board")
    @app_commands.default_permissions(manage_roles=True)
    @is_admin_or_has_role()
    async def roleboard_alias(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await self.roles_board(interaction, channel)

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
        fg_special = [
            {"name": "Com FG", "color": 0x3B82F6},
            {"name": "Known FG", "color": 0x8B5CF6},
            {"name": "Huge FG", "color": 0xF59E0B},
            {"name": "Giant FG", "color": 0xEF4444}
        ]
        created = []
        for r_data in fg_special:
            existing = discord.utils.find(lambda r: r.name.lower() == r_data["name"].lower(), guild.roles)
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
                f"Configured special FG milestone roles in the server:\n"
                f"› `Com FG`, `Known FG`, `Huge FG`, `Giant FG`"
            ),
            ephemeral=True
        )

    @app_commands.command(name="clean_server", description="Safely scan and remove duplicate unused roles from the server")
    @app_commands.default_permissions(administrator=True)
    @is_guild_owner()
    async def clean_server(self, interaction: discord.Interaction):

        """Scans for duplicate roles with identical names, safely merges members, and removes clones."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild.chunked:
            try:
                await guild.chunk()
            except Exception:
                pass

        groups: Dict[str, List[discord.Role]] = {}
        for r in guild.roles:
            if r.name == "@everyone" or r.managed:
                continue
            norm = r.name.strip().lower()
            groups.setdefault(norm, []).append(r)

        deleted = []
        for norm, roles_list in groups.items():
            if len(roles_list) > 1:
                roles_list.sort(key=lambda r: (len(r.members), r.position), reverse=True)
                primary = roles_list[0]
                dupes = roles_list[1:]

                for dup in dupes:
                    try:
                        for m in dup.members:
                            if primary not in m.roles:
                                try:
                                    await m.add_roles(primary, reason="Merging duplicate role")
                                except Exception:
                                    pass
                        await dup.delete(reason="Clean Server Duplicate Purge")
                        deleted.append(f"@{dup.name} (`{dup.id}`)")
                    except Exception as e:
                        logger.error(f"Error purging duplicate role {dup.name}: {e}")

        await self._trigger_board_refresh_for_guild(guild)

        if deleted:
            embed = success_embed(
                "Server Cleaned",
                f"Successfully deleted **`{len(deleted)}`** duplicate roles and merged member assignments:\n" +
                "\n".join(f"› {d}" for d in deleted[:30])
            )
        else:
            embed = info_embed("Server Clean", "No duplicate roles detected in this server.")

        await interaction.followup.send(embed=embed)

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
            existing = discord.utils.find(lambda r: r.name.lower() == p["name"].lower(), interaction.guild.roles)
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
