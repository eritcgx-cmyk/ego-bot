"""
Role Presets, Roster Panels, and Special Role Board Cog for Ego Bot.
Manages 1,200 role presets, live updating roster panels, and comprehensive special role boards with requirements.
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
        self.refresh_role_panels.start()

    def cog_unload(self):
        self.refresh_role_panels.cancel()

    def _load_presets(self) -> List[Dict[str, Any]]:
        if not os.path.exists(PRESETS_FILE):
            logger.warning(f"Presets file {PRESETS_FILE} not found.")
            return []
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"Loaded {len(data)} role presets.")
                return data
        except Exception as e:
            logger.error(f"Failed to load role presets: {e}")
            return []

    @tasks.loop(minutes=11)
    async def refresh_role_panels(self):
        """Automatically updates all active role roster panels across servers."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(RolePanel))
            panels = result.scalars().all()

            for panel in panels:
                guild = self.bot.get_guild(panel.guild_id)
                if not guild:
                    continue
                channel = guild.get_channel(panel.channel_id)
                if not channel or not isinstance(channel, discord.TextChannel):
                    continue

                try:
                    msg = await channel.fetch_message(panel.message_id)
                    embed = await self._generate_panel_embed(guild, panel)
                    await msg.edit(embed=embed)
                    panel.last_refreshed = datetime.utcnow()
                except discord.NotFound:
                    await session.delete(panel)
                except Exception as e:
                    logger.debug(f"Error refreshing panel {panel.id}: {e}")

            await session.commit()

    @refresh_role_panels.before_loop
    async def before_refresh_role_panels(self):
        await self.bot.wait_until_ready()

    async def _generate_panel_embed(self, guild: discord.Guild, panel: RolePanel) -> discord.Embed:
        """Helper to build role roster embed."""
        embed = ego_embed(
            title=f"Role Roster - Roles",
            description=f"> Active members holding **{panel.title}** roles in {guild.name}:\n",
            color=panel.color_hex
        )

        reqs = get_tier_requirements()

        for role_id in panel.role_ids:
            role = guild.get_role(role_id)
            if role:
                members = [m.mention for m in role.members[:20]]
                val = ", ".join(members) if members else "*No members*"
                if len(role.members) > 20:
                    val += f" *(+{len(role.members) - 20} more)*"
                
                # Check if role has special requirement info
                field_title = f"› {role.name} ({len(role.members)})"
                if role.name in reqs:
                    r_info = reqs[role.name]
                    field_title += f" • {r_info.get('followers', '')} Followers / {r_info.get('views', '')} Views"

                embed.add_field(name=field_title, value=val, inline=False)

        return embed

    roles_group = app_commands.Group(name="roles", description="Role library, presets, perks, and live panels")

    @roles_group.command(name="board", description="Deploy a comprehensive Special Roles Board with requirements and perks")
    @app_commands.describe(channel="Target channel for the Special Roles Board (defaults to current channel)")
    @is_admin_or_has_role()
    async def roles_board(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild
        reqs = get_tier_requirements()

        embed = ego_embed(
            title=f"Special Roles Directory • {guild.name}",
            description=(
                "> **Server Special Roles & Progression Guide**\n"
                "> Review the requirements below to unlock exclusive badges, perks, and media permissions.\n"
            ),
            color=COLOR_VIOLET
        )

        # 1. Content Creator Roles
        cc_roles = ["CC", "CC Tier 2", "CC Tier 3", "Known", "Famous", "Star"]
        cc_lines = []
        for r_name in cc_roles:
            r_obj = discord.utils.get(guild.roles, name=r_name)
            r_mention = r_obj.mention if r_obj else f"**@{r_name}**"
            r_data = reqs.get(r_name, {})
            f_req = r_data.get("followers", "Any")
            v_req = r_data.get("views", "Any")
            desc = r_data.get("desc", f"{f_req} Followers / {v_req} Views")
            cc_lines.append(f"› {r_mention} — `{f_req} Followers` or `{v_req} Views`\n  *{desc}*")

        if cc_lines:
            embed.add_field(
                name="✦ Content Creator Roles (/cc verify)",
                value="\n".join(cc_lines),
                inline=False
            )

        # 2. Server Booster & VIP Roles
        booster_roles = [r for r in guild.roles if r.is_premium_subscriber()]
        if booster_roles:
            embed.add_field(
                name="✦ Server Booster Perks",
                value=f"› {booster_roles[0].mention} — *Boost the server to unlock custom perks, image perms, and private lounges.*",
                inline=False
            )

        # 3. Friend Groups
        embed.add_field(
            name="✦ Friend Group Circles (/fg start)",
            value="› **Squad Leader** & **Squad Member** — *Form a 5-member circle to unlock dedicated private category + text & voice suites.*",
            inline=False
        )

        await target_ch.send(embed=embed)
        await interaction.response.send_message(
            embed=success_embed("Roles Board Deployed", f"Published Special Roles Board to {target_ch.mention}"),
            ephemeral=True
        )

    @roles_group.command(name="panel", description="Deploy an auto-updating Role Roster panel in a channel")
    @app_commands.describe(
        title="Title for the role panel (e.g. VIP Members, Creators)",
        roles_list="Space or comma-separated list of @roles or role names to display"
    )
    @is_admin_or_has_role()
    async def roles_panel(
        self,
        interaction: discord.Interaction,
        title: str,
        roles_list: str
    ):
        guild = interaction.guild
        raw_names = [r.strip().replace("<@&", "").replace(">", "").strip() for r in roles_list.replace(",", " ").split() if r.strip()]
        
        resolved_roles = []
        for name in raw_names:
            if name.isdigit():
                role = guild.get_role(int(name))
            else:
                role = discord.utils.get(guild.roles, name=name)
            if role and role not in resolved_roles:
                resolved_roles.append(role)

        if not resolved_roles:
            return await interaction.response.send_message(
                embed=error_embed("No Roles Found", "Could not find any matching roles. Ensure they exist in the server."),
                ephemeral=True
            )

        async with AsyncSessionLocal() as session:
            panel = RolePanel(
                guild_id=guild.id,
                channel_id=interaction.channel_id,
                message_id=0,
                category="custom",
                title=title.strip(),
                color_hex=COLOR_VIOLET,
                role_ids_json=json.dumps([r.id for r in resolved_roles])
            )
            session.add(panel)
            await session.commit()
            await session.refresh(panel)

            embed = await self._generate_panel_embed(guild, panel)
            msg = await interaction.channel.send(embed=embed)

            panel.message_id = msg.id
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed("Panel Initialized", f"Roster panel **{title}** is active and will auto-refresh every 11 minutes."),
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
